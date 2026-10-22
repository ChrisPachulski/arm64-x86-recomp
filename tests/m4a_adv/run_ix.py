"""Adversarial bed for lane M4a: interior entries (several callers, b / bl / b.cond / cbz / tbz / tbnz, a jump-table
target, a resume point and an interior subroutine of a setjmp function, callers in a later chunk), the sorted lookup
table (first, last, chunk edges, interior, between, below, data), cross-chunk declarations, and dlsym / function-pointer
calls into the main image from the program and from a guest dylib. Guest arm64 translated by the lane's gdyld, oracle
x86_64 native. Run bare: sbtenv/bin/python tests/m4a_adv/run_ix.py"""
###############
# imports and constants
###############
from __future__ import annotations
import os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
BUILD = os.path.join(HERE, "build", "ix")
os.environ["GDYLD_OBJCACHE"] = os.path.join(BUILD, "objcache")
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld
import recompile as R

SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
NFILL, REPS = 250, 60                                                   # filler functions x adds each: ~15k instructions, 3 chunks
GUEST, ORACLE = os.path.join(BUILD, "ix_arm64"), os.path.join(BUILD, "ix_x86_64")
RUN_TIMEOUT = 60                                                        # seconds per run
LOUD = "indirect branch to a non-function"                             # dispatch: m0_lookup found nothing
LOUD_STUB = "neither a function start, an entry point nor a stub"       # a direct branch to a non-function
LABELS = {"Lk_mid": ("_ka", 8), "Lj_c1": ("_fj", 40), "Lj_c2": ("_fj", 48), "Lj_c3": ("_fj", 56), "Lr_rs1": ("_fr", 28),
          "Lr_mid": ("_fr", 68)}                                      # interior labels: symbol + byte offset in ix_a.s
TAB_RE = re.compile(r"^const uint64_t m0_a(\d+)\[\] = \{([^}]*)\};$", re.M)

###############
# functions
###############
def run(cmd: list, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=RUN_TIMEOUT, env=env, cwd=BUILD)

def gen_filler() -> None:
    """build/ix_all.s (ix_a.s + filler + ix_b.s), fill.c (x86 oracle) and fill_decl.h."""
    fill_s = ["    .section __TEXT,__text,regular,pure_instructions"] + [
        "    .globl _fill_%d\n    .p2align 2\n_fill_%d:\n    .rept %d\n    add x0, x0, #%d\n    .endr\n    ret" % (i, i, REPS, i + 1) for i in range(NFILL)]
    parts = [open(os.path.join(HERE, "ix_a.s")).read(), "\n".join(fill_s) + "\n", open(os.path.join(HERE, "ix_b.s")).read()]
    with open(os.path.join(BUILD, "ix_all.s"), "w") as f: f.write("\n".join(parts))
    with open(os.path.join(BUILD, "fill.c"), "w") as f:
        f.write("".join("long fill_%d(long x) { return x + %d; }\n" % (i, REPS * (i + 1)) for i in range(NFILL)))
    with open(os.path.join(BUILD, "fill_decl.h"), "w") as f:
        f.write("".join("long fill_%d(long);\n" % i for i in range(NFILL)) + "#define FILL_N %d\n" % NFILL
                + "static const fn fills[] = {%s};\n" % ", ".join("fill_%d" % i for i in range(NFILL)))

def build() -> str:
    """libixd + ix for arm64 (guest) and x86_64 (oracle); '' or the compiler errors."""
    errs = []
    for arch, exe, extra in (("arm64", GUEST, [os.path.join(BUILD, "ix_all.s")]), ("x86_64", ORACLE, [os.path.join(BUILD, "fill.c")])):
        lib = os.path.join(BUILD, "libixd_%s.dylib" % arch)
        cc = ["clang", "-isysroot", SDK, "-arch", arch, "-O1"]
        a = run(cc + ["-dynamiclib", os.path.join(HERE, "ixd.c"), "-install_name", "@rpath/libixd_%s.dylib" % arch, "-o", lib])
        b = run(cc + extra + [os.path.join(HERE, "ix_main.c"), "-I", BUILD, lib, "-Wl,-rpath," + BUILD, "-o", exe])
        errs += [r.stderr for r in (a, b) if r.returncode]
    return "".join(errs)

def symbols(exe: str) -> dict[str, int]:
    """Defined text symbols -> address (nm symbol table, no disassembly)."""
    out = run(["nm", "-U", exe]).stdout                                  # cctools nm: -U = defined only
    return {p[2]: int(p[0], 16) for p in (ln.split() for ln in out.splitlines()) if len(p) == 3 and p[1] in "tT"}

def chunk_tables(out_dir: str) -> dict[int, list[int]]:
    """Image 0 chunk index -> its sorted lookup addresses, from the generated chunk sources."""
    tabs = {}
    for f in sorted(os.listdir(out_dir)):
        if re.fullmatch(r"image0_\d+\.c", f):
            for j, body in TAB_RE.findall(open(os.path.join(out_dir, f)).read()):
                tabs[int(j)] = [int(x, 16) for x in re.findall(r"0x([0-9a-f]+)ULL", body)]
    return tabs

def outcome(r: subprocess.CompletedProcess) -> str:
    """stdout, or LOUD (exit 70 at the lookup's stop), or the failure."""
    if r.returncode == 70 and LOUD in r.stderr: return "LOUD"
    if r.returncode == 70 and LOUD_STUB in r.stderr: return "LOUD(extern_stub)"
    return r.stdout.strip() if r.returncode == 0 else "exit %d %s | %s" % (r.returncode, r.stdout.strip()[-120:], r.stderr.strip()[-200:])

def compare(exe: str, args: list) -> tuple[bool, str]:
    """Translated vs native oracle on one argument list."""
    t, o = outcome(run([exe] + args)), outcome(run([ORACLE] + args))
    return t == o, "%-5s %-24s translated %r | native %r" % ("MATCH" if t == o else "DIFF", " ".join(args), t, o)

def expect(exe: str, args: list, want: str) -> tuple[bool, str]:
    """Translated only (the native arm64 program never runs here) against the expected outcome."""
    t = outcome(run([exe] + args))
    return t == want, "%-5s %-24s translated %r | expected %r" % ("OK" if t == want else "WRONG", " ".join(args), t, want)

###############
# run
###############
os.makedirs(BUILD, exist_ok=True)
gen_filler()
_err = build()
print("build: %s" % (_err[-1500:] or "ok"))
_sym = symbols(GUEST)
_img = gdyld.load_images(GUEST)[0]
_bounds = gdyld.function_bounds(_img)
_starts = [b[0] for b in _bounds]
_lab = {n: _sym[s] + o for n, (s, o) in LABELS.items()}
print("labels are not function starts: %s" % {n: a not in _starts for n, a in _lab.items()})
_ents = gdyld.interior_entries(_img, _bounds, gdyld.eh_resume_points(_img, _bounds), gdyld.setjmp_stubs(_img),
                               gdyld.interior_pointers(_img, set(_starts)))
_found = {a for es in _ents.values() for a in es}
_byaddr = {a: n for n, a in _lab.items()}
print("extra entries found: %s; expected labels missing: %s" % (sorted(_byaddr.get(a, hex(a)) for a in _found), sorted(n for n, a in _lab.items() if a not in _found)))
_fj = next(b for b in _bounds if b[0] == _sym["_fj"])
_md = gdyld.Cs(gdyld.CS_ARCH_ARM64, gdyld.CS_MODE_ARM); _md.detail = True
_d, _i = gdyld.vm_bytes(_img, _fj[0])
_fji = list(_md.disasm(_d[_i:_i + _fj[1] - _fj[0]], _fj[0]))
print("fj br decoding: %s" % {hex(a): (k, sorted(_byaddr.get(t, hex(t)) for t in ts)) for a, (k, ts) in
                              R.reach(_fji, [_fj[0]], lambda a, n: gdyld.read_vm(_img, a, n), True)[1].items()})
_res = gdyld.translate(GUEST, os.path.join(BUILD, "gdyld"), SDK)
print("translate: error %r; %s" % (_res["error"][-1500:], [ln for ln in _res["report"] if ln.startswith("lift ix")]))
_tabs = chunk_tables(os.path.join(BUILD, "gdyld"))
_name = {a: n for n, a in _sym.items()}
_where = {n: next((j for j, t in _tabs.items() if a in t), None) for n, a in list(_lab.items()) + [(s, _sym[s]) for s in ("_ka", "_fr", "_xb1", "_xb4", "_zz_last")]}
print("chunk of each: %s" % _where)
_xb4c = open(os.path.join(BUILD, "gdyld", "image0_%d.c" % _where["_xb4"])).read()
print("xb4's chunk declares func_%x (ka, address-only use): %s; declares Lk_mid entry: %s" % (
    _sym["_ka"], "func_%x(" % _sym["_ka"] in _xb4c, "func_%x(" % _lab["Lk_mid"] in _xb4c))
_ok = []
_r = compare(_res["exe"], []); _ok.append(_r[0]); print(_r[1])
_names = ["ka", "fq", "xb4", "zz_last", "fill_0", "fill_%d" % (NFILL - 1), "no_such_symbol"]
_names += sorted({_name[a][1:] for t in _tabs.values() for a in (t[0], t[-1]) if a in _name})   # chunk-edge functions
for _how in ("dl", "dlm", "dls", "dl0", "dlx"):
    for _n in _names[:4] + _names[6:7]: _r = compare(_res["exe"], [_how, _n]); _ok.append(_r[0]); print(_r[1])
for _how in ("default", "main", "self", "next", "null"):
    for _n in ("kb", "zz_last"): _r = compare(_res["exe"], ["lib", _how, _n]); _ok.append(_r[0]); print(_r[1])
for _n in _names[4:6] + _names[7:]: _r = compare(_res["exe"], ["dl", _n]); _ok.append(_r[0]); print(_r[1])
for _n in ("ixd_twice", "ka"): _r = compare(_res["exe"], ["dll", _n]); _ok.append(_r[0]); print(_r[1])
_ka = _sym["_ka"]
_offs = [(0, "off 0: 6"), (_lab["Lk_mid"] - _ka, "off %x: 32"), (4, "LOUD"), (_sym["_zz_last"] - _ka, "off %x: 5007"), (_sym["_zz_last"] - _ka + 4, "LOUD"),
         (_lab["Lr_mid"] - _ka, "off %x: 12")]                       # Lj_c* read x1: no fixed value through off
for _j, _t in sorted(_tabs.items()):
    _offs += [(_t[0] - _ka, "off %x: " + str(5 + REPS * (int(_name[_t[0]][6:]) + 1)) if _name.get(_t[0], "").startswith("_fill_") else None),
              (_t[0] - 4 - _ka, "LOUD" if _j else None), (_t[-1] + 4 - _ka, "LOUD")]
for _o, _w in _offs:
    if _w is None: continue
    _r = expect(_res["exe"], ["off", "%x" % _o], _w % _o if "%x" in _w else _w); _ok.append(_r[0]); print(_r[1])
for _a in ("hdr", "data"): _r = expect(_res["exe"], [_a], "LOUD"); _ok.append(_r[0]); print(_r[1])
print("RESULT: %d/%d as expected" % (sum(_ok), len(_ok)))
