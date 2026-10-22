"""NZCV placement bed for lane M6C: builds each flag program in tests/m6c/flags (<name>.s + <name>_main.c) for arm64,
runs its drivers on the arm64 code itself under Unicorn (the oracle: no arm64 host here), translates it with gdyld
(default NZCV mode), runs the translation and compares; prints gdyld's NZCV plan line per program, then a negative
control (the same programs with a plan that stores NZCV nowhere; each must build, run and differ). Exit 1 on any failure.
Run bare: sbtenv/bin/python tests/m6c/run_flags.py [prefix]  (prefix: translate with an older sbt/ copied to prefix_m6c/sbt, to show the bed catches the bug)"""
###############
# imports and constants
###############
from __future__ import annotations
import os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
PREFIX = "prefix" in sys.argv[1:]
SBT = os.path.join(LANE, "prefix_m6c", "sbt") if PREFIX else os.path.join(LANE, "sbt")
os.environ.setdefault("GDYLD_GUESTRT", os.path.join(LANE, "guestrt", "lib"))
sys.path.insert(0, SBT)
import gdyld, macho  # noqa: E402  (translator under test; macho reads the arm64 build for the oracle)
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE  # noqa: E402
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X30, UC_ARM64_REG_SP, UC_ARM64_REG_PC  # noqa: E402

SRC = os.path.join(HERE, "flags")
BUILD = os.path.join(HERE, "build", "flags_prefix" if PREFIX else "flags")
PROGRAMS = ["flagsx", "flagsy", "flagsz", "flagsw"]
PLACED = {"flagsx": True, "flagsy": False, "flagsz": True, "flagsw": True}   # flagsy needs flags across indirect calls: everywhere
RUN_TIMEOUT = 60                                                       # s per program run
PAGE = 0x4000
IMP_BASE, STACK, RET_ADDR = 0x6000000000, 0x7000000000, 0x6000008000   # oracle address space: imports, stack, return sentinel
HOST = {"_labs": lambda x: abs(x - (1 << 64) if x >> 63 else x) & (2 ** 64 - 1)}   # imports the drivers call, emulated

###############
# functions
###############
def build(name: str, sdk: str) -> str:
    """arm64 executable of <name>.s + <name>_main.c."""
    out = os.path.join(BUILD, "arm64", name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = subprocess.run(["/usr/bin/clang", "-O1", "-isysroot", sdk, "-arch", "arm64", "-o", out,
                        os.path.join(SRC, name + ".s"), os.path.join(SRC, name + "_main.c")], capture_output=True, text=True)
    if r.returncode: raise RuntimeError("build %s: %s" % (name, r.stderr[-800:]))
    return out

def driver_plan(name: str) -> tuple[list[str], list[int], list[int]]:
    """(driver names in call order, A, B) from <name>_main.c."""
    src = open(os.path.join(SRC, name + "_main.c")).read()
    arr = lambda k: [int(v) for v in re.search(r"\b%s\[\] = \{([^}]*)\}" % k, src).group(1).split(",")]
    return re.findall(r"^\s*RUN\((\w+)\);", src, re.M), arr("A"), arr("B")

def symbols(exe: str) -> dict[str, int]:
    """Defined symbol -> address (BSD nm -U)."""
    out = subprocess.run(["/usr/bin/nm", "-U", exe], capture_output=True, text=True, check=True).stdout
    return {p[2]: int(p[0], 16) for p in (ln.split() for ln in out.splitlines()) if len(p) == 3}

def arm64_call(exe: str, fn: int, a: int, b: int) -> int:
    """x0 after fn(a, b) runs on the arm64 code of exe under Unicorn (imports from HOST, others stop with an error)."""
    m = macho.load_macho(exe)
    img = macho.build_image(m, m["base"], lambda o: IMP_BASE + 16 * o)
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    uc.mem_map(m["base"], (len(img) + PAGE - 1) // PAGE * PAGE)
    uc.mem_write(m["base"], img)
    uc.mem_map(IMP_BASE, 0x10000)
    uc.mem_map(STACK - 0x100000, 0x100000)
    names = m["imports"]
    def on_import(u: Uc, addr: int, _size: int, _data: object) -> None:
        if addr == RET_ADDR: u.emu_stop(); return
        name = names[(addr - IMP_BASE) // 16]
        if name not in HOST: raise RuntimeError("oracle: import %s is not emulated" % name)
        u.reg_write(UC_ARM64_REG_X0, HOST[name](u.reg_read(UC_ARM64_REG_X0)))
        u.reg_write(UC_ARM64_REG_PC, u.reg_read(UC_ARM64_REG_X30))
    uc.hook_add(UC_HOOK_CODE, on_import, begin=IMP_BASE, end=IMP_BASE + 0x10000 - 1)
    for reg, v in ((UC_ARM64_REG_X0, a & (2 ** 64 - 1)), (UC_ARM64_REG_X1, b & (2 ** 64 - 1)), (UC_ARM64_REG_X30, RET_ADDR), (UC_ARM64_REG_SP, STACK - 64)):
        uc.reg_write(reg, v)
    uc.emu_start(fn, RET_ADDR, count=1_000_000)
    if uc.reg_read(UC_ARM64_REG_PC) != RET_ADDR: raise RuntimeError("oracle: %x did not return" % fn)
    x0 = uc.reg_read(UC_ARM64_REG_X0)
    return x0 - (1 << 64) if x0 >> 63 else x0

def expected(name: str, exe: str) -> str:
    """What the arm64 program prints, from its drivers run under Unicorn."""
    drivers, a, b = driver_plan(name)
    syms = symbols(exe)
    return "".join("%-16s%s\n" % (d, "".join(" %d" % arm64_call(exe, syms["_" + d], x, y) for x, y in zip(a, b))) for d in drivers) + "EXIT 0\n"

def run_translated(exe: str, out_dir: str, sdk: str) -> tuple[str | None, str, str]:
    """(output + exit line or None, gdyld's NZCV plan line, build error) of one translated program."""
    res = gdyld.translate(exe, out_dir, sdk)
    if res["error"]: return None, "", res["error"][-600:]
    r = subprocess.run([res["exe"]], capture_output=True, text=True, errors="replace", timeout=RUN_TIMEOUT)
    plan = next((ln for ln in res["report"] if ln.startswith("NZCV stores")), "?")
    return r.stdout + "EXIT %d\n" % r.returncode, plan, ""

def verdict(got: str | None, want: str, err: str) -> str:
    """MATCH, BUILD FAIL, or DIFF with the differing lines."""
    if got is None: return "BUILD FAIL " + err
    if got == want: return "MATCH"
    return "DIFF " + "; ".join("%r != %r" % (g, w) for g, w in zip(got.splitlines(), want.splitlines()) if g != w)

def nowhere(rows: list, taken: list, extra: frozenset = frozenset(), mode: str = "", host: frozenset = frozenset()) -> tuple[bool, set, set, str]:
    """A flag plan that stores NZCV at no call and no return (negative control)."""
    return False, set(), set(), ""

###############
# run
###############
print("translator: %s | NZCV mode %s" % (SBT, gdyld.NZCV_MODE), flush=True)
SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
EXES = {n: build(n, SDK) for n in PROGRAMS}
WANT = {n: expected(n, e) for n, e in EXES.items()}
for _n in PROGRAMS: print("oracle  %-7s %s" % (_n, WANT[_n].replace("\n", " | ")), flush=True)
OK = 0
for _n, _exe in EXES.items():
    _got, _plan, _err = run_translated(_exe, os.path.join(BUILD, "gdyld", _n), SDK)
    _placed = "only into" in _plan
    _v = verdict(_got, WANT[_n], _err)
    OK += _v == "MATCH" and _placed == PLACED[_n]
    print("%-7s %s | plan: %s (%s, intended %s)" % (_n, _v, _plan, "placed" if _placed else "everywhere",
                                                   "placed" if PLACED[_n] else "everywhere"), flush=True)
REAL_PLAN = gdyld.flag_plan
gdyld.flag_plan = nowhere
BROKEN = 0
for _n, _exe in EXES.items():
    _got, _plan, _err = run_translated(_exe, os.path.join(BUILD, "gdyld_none", _n), SDK)
    _v = verdict(_got, WANT[_n], _err)
    BROKEN += _v.startswith("DIFF")
    print("control %-7s (no NZCV stores): %s" % (_n, _v), flush=True)
gdyld.flag_plan = REAL_PLAN
print("flags bed: %d/%d programs match the arm64 oracle with the intended plan; negative control broke %d/%d (built, ran, differed)"
      % (OK, len(EXES), BROKEN, len(EXES)), flush=True)
sys.exit(0 if OK == len(EXES) and BROKEN == len(EXES) else 1)
