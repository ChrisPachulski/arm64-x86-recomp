"""Adversarial bed for gdyld: builds every tests/adv program for arm64 (guest) and x86_64 (oracle), records the
native stdout+exit as expected output, translates each arm64 build with sbt/gdyld.py and diffs its stdout+exit
against the oracle (MATCH), checks that unsupported cases stop loudly at link or run time (LOUD-OK), and probes the
shared Apple-arm64 varargs core (sbt/gvarargs.h, used by gdyld and, where present, the printf bridge of sbt/e2e_http.py).
"""

###############
# Imports and constants

from __future__ import annotations

import ast
import os
import shutil
import struct
import subprocess
import sys

ADV = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(ADV))
SBT = os.environ.get("ADV_SBT") or os.path.join(LANE, "sbt")         # ADV_SBT: another translator (a pre-fix baseline)
GDYLD = os.path.join(SBT, "gdyld.py")
E2E = os.path.join(SBT, "e2e_http.py")
GVARARGS = os.path.join(SBT, "gvarargs.h")
sys.path.insert(0, SBT)
import gdyld  # noqa: E402  (lane library under test)
BUILD = os.path.join(ADV, "build")
ARCHES = ("x86_64", "arm64")
RUN_TIMEOUT = 60                                                       # s per native run
DYLIB = ["-dynamiclib"]
EXE = ["-Wl,-rpath,@executable_path"]
ROUTINES = "@routines="                                                # pseudo-flag: arm64 gets LC_ROUTINES_64, x86_64 gets -init
HOST_LIBS = {                                                          # test -> [(install name, header, dylib)] served by the host
    "abi_shapes": [("@rpath/libabih.dylib", "abih.h", "libabih.dylib")],
    "ldp_loud": [("@rpath/libldp.dylib", "ldp.h", "libldp.dylib")],
    "hcb": [("@rpath/libhcb.dylib", "hcb.h", "libhcb.dylib")],
    "ldcb": [("@rpath/libldcb.dylib", "ldcb.h", "libldcb.dylib")],
    "ldcb_loud": [("@rpath/libldcb.dylib", "ldcb.h", "libldcb.dylib")],
    "empty": [("@rpath/libempty.dylib", "empty.h", "libempty.dylib")],
    "twolib": [("@rpath/libhla.dylib", "hl.h", "libhla.dylib"), ("@rpath/libhlb.dylib", "hl.h", "libhlb.dylib")],
    "weak_host": [("@rpath/libwh.dylib", "wh.h", "libwh.dylib")],
    "cxx_values": [("@rpath/libcxxv.dylib", "cxxv.h", "libcxxv.dylib")],
    "ldref_loud": [("@rpath/libldr.dylib", "ldr.h", "libldr.dylib")],
    "ldll_loud": [("@rpath/libldr.dylib", "ldr.h", "libldr.dylib")],
    "ldln_loud": [("@rpath/libldr.dylib", "ldr.h", "libldr.dylib")],
    "srec_get_loud": [("@rpath/libsrec.dylib", "srec.h", "libsrec.dylib")],
    "srec_set_loud": [("@rpath/libsrec.dylib", "srec.h", "libsrec.dylib")]}
LOUD = {                                                               # test -> text the loud stop must carry
    "loud_untyped": "untyped host code pointer",
    "loud_nullfn": "indirect branch to an unmapped target",
    "ldp_loud": "GDYLD_LINK_ERROR: host import passes long double through memory",
    "ldcb_loud": "GDYLD_LINK_ERROR: host import passes long double through memory",
    "loud_sigctx": "SA_SIGINFO handler changed the machine context",
    "suffix_loud": "x86-64 host has no symbol ['_read$GDYLDTEST']",
    "ldref_loud": "GDYLD_LINK_ERROR: host import passes long double through memory",
    "ldll_loud": "GDYLD_LINK_ERROR: host import passes long double through memory",
    "ldln_loud": "a C++ class holding a long double crosses the boundary",
    "srec_get_loud": "a record holding a SIMD vector",
    "srec_set_loud": "a record holding a SIMD vector"}
LC_ROUTINES_64, ROUTINES_SIZE = 0x1A, 72
VA_CASES = [                                                           # (name, fmt, [(kind, C expr)]); kind d=double L=long double i=int p=ptr
    ("p12", "%d %u %ld %lld %c %f %e %g %s %x %hhd %zu",
     [("i", "-7"), ("i", "4000000000u"), ("i", "-5L"), ("i", "-123456789012LL"), ("i", "'Z'"), ("d", "1.25f"),
      ("d", "6.02e23"), ("d", "1e-5"), ("p", "\"str\""), ("i", "0xBEEF"), ("i", "300"), ("i", "(size_t)99")]),
    ("float_promo", "%f %.3f %a", [("d", "1.25f"), ("d", "0.1f"), ("d", "3.5f")]),
    ("pct_lit", "100%% %d%%", [("i", "5")]),
    ("pointer", "%p %p", [("p", "(void*)0"), ("p", "(void*)0x2000123f0")]),
    ("positional", "%2$d %1$d|%3$ld", [("i", "11"), ("i", "22"), ("i", "33L")]),
    ("star_width", "|%*d|", [("i", "6"), ("i", "42")]),
    ("long_double", "%Lf", [("L", "2.5")]),                           # guest long double is a double; native gets a real one
    ("percent_n", "ab%n", [("p", "(int*)&scratch")]),
]

###############
# Functions


def run(cmd: list[str], cwd: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    """Run a command, capturing text output."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout)


def plan(root: str) -> dict[str, list[tuple[str, list[str], list[str]]]]:
    """Build steps per test: (output path, sources, extra flags); the executable is always <test>/run/<test>."""
    p = lambda test, *parts: os.path.join(root, test, *parts)
    lib = lambda test, name, sub="run": p(test, sub, "lib%s.dylib" % name)
    iname = lambda name: DYLIB + ["-install_name", "@rpath/lib%s.dylib" % name]
    exe = lambda test, srcs, flags=(): [(p(test, "run", test), srcs, EXE + list(flags))]
    rp = lambda *parts: p("rpath_ctx", "run", *parts)
    wc = lambda test, flags: [(lib(test, "wca"), ["wc_a.cpp"], iname("wca") + flags),
                              (lib(test, "wcb"), ["wc_b.cpp"], iname("wcb") + flags)] + exe(test, ["wc_main.cpp", lib(test, "wca"), lib(test, "wcb")], flags)
    return {
        "abi_host": exe("abi_host", ["abi_host.c"], ["-framework", "CoreGraphics"]),
        "abi_x": [(lib("abi_x", "abix"), ["abi_xlib.c"], iname("abix"))] + exe("abi_x", ["abi_xmain.c", lib("abi_x", "abix")]),
        "varargs": exe("varargs", ["varargs.c"]),
        "reenter": exe("reenter", ["reenter.c"]),
        "threads": exe("threads", ["threads.c"]),
        "exit_thread": exe("exit_thread", ["exit_thread.c"]),
        "recurse": exe("recurse", ["recurse.c"]),
        "init_order": [(lib("init_order", "inita"), ["init_a.c"], iname("inita")),
                       (lib("init_order", "initb"), ["init_b.c", lib("init_order", "inita")], iname("initb"))]
                      + exe("init_order", ["init_main.c", lib("init_order", "initb"), lib("init_order", "inita")]),
        "interpose": [(lib("interpose", "interp"), ["interp_lib.c"],
                       iname("interp") + ["-Wl,-flat_namespace", "-Wl,-undefined,dynamic_lookup"])]
                     + exe("interpose", ["interp_main.c", lib("interpose", "interp")]),
        "weak": [(lib("weak", "weak", "link"), ["weak_lib.c"], iname("weak") + ["-DWEAK_FULL"]),
                 (lib("weak", "gone", "link"), ["weak_gone.c"], iname("gone")),
                 (lib("weak", "weak"), ["weak_lib.c"], iname("weak"))]
                + exe("weak", ["weak_main.c", lib("weak", "weak", "link")], ["-Wl,-weak_library," + lib("weak", "gone", "link")]),
        "abi_shapes": [(lib("abi_shapes", "abih"), ["abih_lib.c"], iname("abih"))]
                      + exe("abi_shapes", ["abi_shapes.c", lib("abi_shapes", "abih")]),
        "fnptr": exe("fnptr", ["fnptr.c"], ["-framework", "CoreFoundation"]),
        "host_keeps": exe("host_keeps", ["host_keeps.c"]),
        "nside": exe("nside", ["nside.c"]),
        "weak_coalesce": wc("weak_coalesce", []),
        "weak_coalesce_classic": wc("weak_coalesce_classic", ["-Wl,-no_fixup_chains"]),
        "flat_order": [(lib("flat_order", "foc"), ["fo_libs.c"], DYLIB + ["-install_name", lib("flat_order", "foc"), "-DFO_C"]),
                       (lib("flat_order", "foa"), ["fo_libs.c"], iname("foa") + ["-DFO_A", "-Wl,-reexport_library," + lib("flat_order", "foc")]),
                       (lib("flat_order", "fob"), ["fo_libs.c"], iname("fob") + ["-DFO_B"]),
                       (lib("flat_order", "fod"), ["fo_libs.c"], iname("fod") + ["-DFO_D", "-Wl,-undefined,dynamic_lookup"])]
                      + exe("flat_order", ["fo_main.c", lib("flat_order", "foa"), lib("flat_order", "fob"), lib("flat_order", "fod")]),
        "rpath_ctx": [(rp("lib", "librpb.dylib"), ["rp_libs.c"], iname("rpb") + ["-DRP_B", '-DWHERE="app"']),
                      (rp("plugins", "lib", "librpb.dylib"), ["rp_libs.c"], iname("rpb") + ["-DRP_B", '-DWHERE="plugin"']),
                      (rp("plugins", "deps", "librpd.dylib"), ["rp_libs.c"], iname("rpd") + ["-DRP_D"]),
                      (rp("plugins", "deps", "librpc.dylib"), ["rp_libs.c", rp("plugins", "deps", "librpd.dylib")], iname("rpc") + ["-DRP_C"]),
                      (rp("plugins", "librpa.dylib"), ["rp_libs.c", rp("lib", "librpb.dylib"), rp("plugins", "deps", "librpc.dylib")],
                       DYLIB + ["-install_name", "@executable_path/plugins/librpa.dylib", "-DRP_A", "-Wl,-rpath,@loader_path/deps"]),
                      (rp("rpath_ctx"), ["rp_main.c", rp("plugins", "librpa.dylib")], ["-Wl,-rpath,@loader_path/lib"])],
        "interpose_chain": [(lib("interpose_chain", "ip1"), ["ip_lib.c"], iname("ip1") + ["-DIP=1"]),
                            (lib("interpose_chain", "ip2"), ["ip_lib.c"], iname("ip2") + ["-DIP=2"])]
                           + exe("interpose_chain", ["ip_main.c", lib("interpose_chain", "ip1"), lib("interpose_chain", "ip2")]),
        "nocancel": exe("nocancel", ["nocancel.c"], ["-D__DARWIN_NON_CANCELABLE=1"]),
        "upward": [(lib("upward", "upb"), ["up_libs.c"], iname("upb") + ["-DUP_B", "-Wl,-undefined,dynamic_lookup"]),
                   (lib("upward", "upa"), ["up_libs.c"], iname("upa") + ["-DUP_A", "-Wl,-upward_library," + lib("upward", "upb")])]
                  + exe("upward", ["up_main.c", lib("upward", "upa")]),
        "routines": [(lib("routines", "rt"), ["rt_lib.c"], iname("rt") + ["-Wl,-headerpad,0x400", ROUTINES + "_seed"])]
                    + exe("routines", ["rt_main.c", lib("routines", "rt")]),
        "ldbl": exe("ldbl", ["ldbl.c"], ["-fno-builtin"]),
        "loud_struct": exe("loud_struct", ["loud_struct.c"], ["-framework", "CoreFoundation"]),
        "loud_untyped": exe("loud_untyped", ["loud_untyped.c"]),
        "loud_nullfn": exe("loud_nullfn", ["loud_nullfn.c"]),
        "zone_slots": exe("zone_slots", ["zone_slots.c"]),
        "loud_block": exe("loud_block", ["loud_block.c"]),
        "loud_noescape": exe("loud_noescape", ["loud_noescape.c"]),
        "ldp_loud": [(lib("ldp_loud", "ldp"), ["ldp_lib.c"], iname("ldp"))] + exe("ldp_loud", ["ldp_main.c", lib("ldp_loud", "ldp")]),
        "suffix_loud": exe("suffix_loud", ["sfx.c"], ["-Wl,-undefined,dynamic_lookup"]),
        "hcb": [(lib("hcb", "hcb"), ["hcb_lib.c"], iname("hcb"))] + exe("hcb", ["hcb_main.c", lib("hcb", "hcb")]),
        "sigrereg": exe("sigrereg", ["sigrereg.c"]),
        "sigctx": exe("sigctx", ["sigctx.c"]),
        "sigpush": exe("sigpush", ["sigpush.c"]),
        "voucher": exe("voucher", ["voucher.c"]),
        "loud_sigctx": exe("loud_sigctx", ["loud_sigctx.c"]),
        "ldcb": [(lib("ldcb", "ldcb"), ["ldcb_lib.c"], iname("ldcb"))] + exe("ldcb", ["ldcb_main.c", lib("ldcb", "ldcb")], ["-fno-builtin"]),
        "ldcb_loud": [(lib("ldcb_loud", "ldcb"), ["ldcb_lib.c"], iname("ldcb"))] + exe("ldcb_loud", ["ldcb_loud.c", lib("ldcb_loud", "ldcb")]),
        "empty": [(lib("empty", "empty"), ["empty_lib.c"], iname("empty") + ["-Wno-gnu-empty-struct", "-Wno-c++-compat"])]
                 + exe("empty", ["empty_main.c", lib("empty", "empty")], ["-Wno-gnu-empty-struct", "-Wno-c++-compat"]),
        "twolib": [(lib("twolib", "hla"), ["hl_lib.c"], iname("hla") + ["-DHL=1"]), (lib("twolib", "hlb"), ["hl_lib.c"], iname("hlb") + ["-DHL=2"]),
                   (lib("twolib", "ga"), ["hg_lib.c", lib("twolib", "hla")], iname("ga") + ["-DG=ga"]),
                   (lib("twolib", "gb"), ["hg_lib.c", lib("twolib", "hlb")], iname("gb") + ["-DG=gb"])]
                  + exe("twolib", ["hl_main.c", lib("twolib", "ga"), lib("twolib", "gb")]),
        "dlsym_guest": [(lib("dlsym_guest", "dg"), ["dg_lib.c"], iname("dg"))] + exe("dlsym_guest", ["dg_main.c", lib("dlsym_guest", "dg")]),
        "weak_host": [(lib("weak_host", "wh", "link"), ["wh_lib.c"], iname("wh") + ["-DWH_FULL"]), (lib("weak_host", "wh"), ["wh_lib.c"], iname("wh"))]
                     + exe("weak_host", ["wh_main.c", lib("weak_host", "wh", "link")]),
        "locale_l": exe("locale_l", ["locale_l.c"]),
        "cxx_values": [(lib("cxx_values", "cxxv"), ["cxxv_lib.cpp"], iname("cxxv"))] + exe("cxx_values", ["cxxv_main.cpp", lib("cxx_values", "cxxv")]),
        **{n: [(lib(n, "ldr"), ["ldr_lib.cpp"], iname("ldr"))] + exe(n, ["ldr_main.cpp", lib(n, "ldr")], ["-DLDR_CASE=%d" % c])
           for n, c in (("ldref_loud", 1), ("ldll_loud", 2), ("ldln_loud", 3))},
        **{n: [(lib(n, "srec"), ["srec_lib.m"], iname("srec") + ["-framework", "Foundation"])]
              + exe(n, ["srec_main.m", lib(n, "srec")], ["-framework", "Foundation", "-DSREC_CASE=%d" % c])
           for n, c in (("srec_get_loud", 1), ("srec_set_loud", 2))},
        "many_closures": exe("many_closures", ["many_closures.c"]),
        "int128": exe("int128", ["int128.c"]),
        "objc_umbrella": exe("objc_umbrella", ["objc_umbrella.c"], ["-framework", "Foundation"]),
    }


def add_routines(path: str, symbol: str) -> str:
    """Insert an LC_ROUTINES_64 command (init_address = exported symbol) into an arm64 dylib's header padding; '' or why not. The patched file is only parsed (gdyld, ld), never executed natively, so its stale code signature is irrelevant."""
    data = bytearray(open(path, "rb").read())
    ncmds, sizeofcmds = struct.unpack_from("<II", data, 16)
    m = gdyld.parse_image(path)
    room = min(s[4] for s in m["sects"] if s[4]) - (32 + sizeofcmds)
    exp = gdyld.export_trie(m).get(symbol)
    if room < ROUTINES_SIZE or not exp: return "no header room (%d) or no export %s" % (room, symbol)
    struct.pack_into("<II8Q", data, 32 + sizeofcmds, LC_ROUTINES_64, ROUTINES_SIZE, m["vm_base"] + exp[1], 0, 0, 0, 0, 0, 0, 0)
    struct.pack_into("<II", data, 16, ncmds + 1, sizeofcmds + ROUTINES_SIZE)
    open(path, "wb").write(bytes(data))
    return ""


def build_test(steps: list[tuple[str, list[str], list[str]]], arch: str, sdk: str) -> list[str]:
    """Compile+link every step for one arch (C++ through clang++ and the SDK libc++ headers); return error lines."""
    errs = []
    for out, srcs, flags in steps:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        init = [f[len(ROUTINES):] for f in flags if f.startswith(ROUTINES)]
        flags = [f for f in flags if not f.startswith(ROUTINES)] + (["-Wl,-init," + init[0]] if init and arch == "x86_64" else [])
        cxx = any(src.endswith(".cpp") for src in srcs)
        cc = ["/usr/bin/clang++", "-std=c++17", "-nostdinc++", "-isystem", sdk + "/usr/include/c++/v1"] if cxx else ["/usr/bin/clang"]
        r = run(cc + ["-O1", "-isysroot", sdk, "-arch", arch, "-o", out] + flags + srcs, cwd=ADV)
        err = r.stderr.strip()[-400:] if r.returncode else ""
        err = err or (add_routines(out, init[0]) if init and arch == "arm64" else "")
        errs += ["%s: %s" % (os.path.basename(out), err)] if err else []
    return errs


def archs_of(path: str) -> str:
    """Architectures in a Mach-O, per lipo."""
    return run(["/usr/bin/lipo", "-archs", path]).stdout.strip() if os.path.exists(path) else "missing"


def native_run(exe: str) -> tuple[str, int]:
    """Run the x86_64 oracle in its run dir; stdout and exit code (-signal on a crash)."""
    try:
        r = run([exe], cwd=os.path.dirname(exe), timeout=RUN_TIMEOUT)
        return r.stdout, r.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT", 999


def oracle(tests: dict[str, list[tuple[str, list[str], list[str]]]], sdk: str) -> list[str]:
    """Build both arches, run native, write expected/<test>.txt; one summary line per test."""
    os.makedirs(os.path.join(BUILD, "expected"), exist_ok=True)
    lines = []
    for name in tests:
        errs = {a: build_test(plan(os.path.join(BUILD, a))[name], a, sdk) for a in ARCHES}
        exe = {a: os.path.join(BUILD, a, name, "run", name) for a in ARCHES}
        out, rc = native_run(exe["x86_64"]) if not errs["x86_64"] else ("", -1)
        with open(os.path.join(BUILD, "expected", name + ".txt"), "w") as fh:
            fh.write(out + "EXIT %d\n" % rc)
        side = translated(name, exe["arm64"], sdk, out + "EXIT %d\n" % rc) if not errs["arm64"] else ["translated BLOCKED: arm64 build failed"]
        lines.append("%-22s x86 build %s | arm64 build %s (%s) | native exit %d, %d stdout lines | %s" % (
            name, "ok" if not errs["x86_64"] else "FAIL", "ok" if not errs["arm64"] else "FAIL",
            archs_of(exe["arm64"]), rc, out.count("\n"), side[0]))
        lines += ["    " + e for e in errs["x86_64"] + errs["arm64"] + side[1:]]
    return lines


def first_diff(got: str, want: str) -> str:
    """First differing line pair, for a one-line DIFF summary."""
    g, w = got.splitlines(), want.splitlines()
    k = next((i for i in range(max(len(g), len(w))) if i >= len(g) or i >= len(w) or g[i] != w[i]), 0)
    return "line %d: got %r want %r" % (k + 1, (g[k] if k < len(g) else "<eof>")[:120], (w[k] if k < len(w) else "<eof>")[:120])


def host_extra(name: str) -> dict[str, tuple[str, str]]:
    """gdyld host_extra for a test whose libraries are served by the host: install name -> (header, x86_64 dylib)."""
    return {iname: (os.path.join(ADV, header), os.path.join(BUILD, "x86_64", name, "run", dylib)) for iname, header, dylib in HOST_LIBS.get(name, [])}


def loud_status(name: str, got: str, want: str, rc: int, err: str) -> str:
    """LOUD-OK when an expected-unsupported program stopped with the expected message and printed nothing wrong first."""
    prefix_ok = want.startswith(got[:got.rfind("EXIT")])
    ok = rc == 70 and LOUD[name] in err and prefix_ok
    return ("translated LOUD-OK (stopped at run time: %s)" % LOUD[name] if ok else
            "translated LOUD-MISSING exit %d, stdout prefix ok %s, stderr %r" % (rc, prefix_ok, err[-200:]))


def translated(name: str, exe: str, sdk: str, want: str) -> list[str]:
    """Translate one arm64 program with gdyld, run it in the guest's run dir, diff stdout+exit with the oracle; LOUD tests must instead be refused by gdyld or stop at run time with the expected message."""
    out_dir = os.path.join(BUILD, "gdyld", name)
    try:
        res = gdyld.translate(exe, out_dir, sdk, host_extra(name))
    except (OSError, ValueError, LookupError, NotImplementedError, RuntimeError) as e:
        if name in LOUD and LOUD[name] in str(e):
            return ["translated LOUD-OK (gdyld refused to link: %s)" % LOUD[name], "gdyld: %s: %s" % (type(e).__name__, str(e)[:300])]
        return ["translated BLOCKED: %s: %s" % (type(e).__name__, e)]
    info = ["gdyld: " + ln for ln in res["report"]] + [
        "gdyld: host imports %s | unsupported insns %d %s" % (
            {k: len(v) for k, v in res["classes"].items()}, len(res["unsupported"]), res["unsupported"][:4])]
    if res["error"]:
        return ["translated BUILD FAIL"] + info + ["build: " + ln for ln in res["error"].strip().splitlines()[:12]]
    try:
        r = subprocess.run([res["exe"]], cwd=os.path.dirname(exe), capture_output=True, text=True, errors="replace", timeout=RUN_TIMEOUT)
        got, err = r.stdout + "EXIT %d\n" % r.returncode, r.stderr.strip()
    except subprocess.TimeoutExpired:
        got, err = "TIMEOUT\n", "timeout after %d s" % RUN_TIMEOUT
    os.makedirs(os.path.join(BUILD, "translated"), exist_ok=True)
    with open(os.path.join(BUILD, "translated", name + ".txt"), "w") as fh:
        fh.write(got)
    rc = int(got.rsplit("EXIT ", 1)[1]) if "EXIT " in got else 999
    status = (loud_status(name, got, want, rc, err) if name in LOUD else
              "translated MATCH" if got == want else "translated DIFF " + first_diff(got, want))
    return [status] + info + (["stderr: " + err[-300:]] if err else [])


def e2e_consts(path: str) -> dict[str, object]:
    """Literal string/dict constants of e2e_http.py, read via ast without executing it."""
    tree = ast.parse(open(path).read())
    return {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ("HOST_RT", "SPECIAL")}


def slot(kind: str, expr: str) -> str:
    """C expression for one Apple-arm64 8-byte vararg slot."""
    return {"d": "D(%s)" % expr, "L": "D(%s)" % expr, "p": "(uint64_t)(uintptr_t)(%s)" % expr}.get(kind, "(uint64_t)(int64_t)(%s)" % expr)


def probe_c(gvarargs: str, printf_body: str) -> str:
    """C program running the shared varargs core and e2e's printf body on simulated guest slots vs native snprintf."""
    cases = []
    for name, fmt, args in VA_CASES:
        cases.append('  { uint64_t va[]={%s}; char got[512], want[512]; if(!setjmp(jb)){ gfmt(got,sizeof got,"%s",va);'
                     ' snprintf(want,sizeof want,"%s",%s); printf("CASE %s %%s got=[%%s] want=[%%s]\\n",'
                     ' strcmp(got,want)?"DIFF":"MATCH",got,want);} }' % (
                         ",".join(slot(k, e) for k, e in args), fmt, fmt, ",".join("(long double)(%s)" % e if k == "L" else e for k, e in args), name))
    return r"""#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <setjmp.h>
static jmp_buf jb; static int scratch;
typedef struct { uint64_t X[31]; uint64_t SP; } CPU;
static void die(const char*what,uint64_t a){ (void)a; printf("TRAP %s\n",what); longjmp(jb,1); }
static uint64_t D(double d){ uint64_t u; memcpy(&u,&d,8); return u; }
""" + gvarargs + r"""
int main(void){
""" + "\n".join(cases) + r"""
  { static char big[9001]; memset(big,'x',9000); big[9000]=0; uint64_t va[]={(uint64_t)(uintptr_t)big};
    CPU cc={0}, *c=&cc; c->X[0]=(uint64_t)(uintptr_t)"%s\n"; c->SP=(uint64_t)(uintptr_t)va;
    char*buf=0; size_t len=0; FILE*capf=open_memstream(&buf,&len);
#undef stdout
#define stdout capf
""" + printf_body + r"""
#undef stdout
#define stdout __stdoutp
    fclose(capf); printf("CASE printf_9001 %s bytes_written=%zu want=9001 returned=%llu\n",
      len==9001?"MATCH":"DIFF",len,(unsigned long long)c->X[0]); free(buf); }
  return 0;
}
"""


def gfmt_probe(sdk: str) -> list[str]:
    """Compile and run the varargs-bridge probe; return its CASE/TRAP lines."""
    if not os.path.exists(E2E):
        return ["probe SKIPPED: %s (it holds the printf bridge body under test) is not in this tree" % os.path.basename(E2E)]
    consts = e2e_consts(E2E)
    if '#include "gvarargs.h"' not in consts["HOST_RT"]:
        return ["probe FAIL: e2e_http.py HOST_RT no longer includes gvarargs.h, so this probe would test dead code"]
    gfmt = open(GVARARGS).read()
    src = os.path.join(BUILD, "gfmt_probe.c")
    exe = os.path.join(BUILD, "gfmt_probe")
    with open(src, "w") as fh:
        fh.write(probe_c(gfmt, consts["SPECIAL"]["_printf"]))
    r = run(["/usr/bin/clang", "-O1", "-w", "-isysroot", sdk, "-arch", "x86_64", "-o", exe, src])
    if r.returncode:
        return ["probe build FAIL: " + r.stderr.strip()[:600]]
    p = run([exe], timeout=RUN_TIMEOUT)
    return p.stdout.strip().splitlines() + ["probe exit %d" % p.returncode]


###############
# Run

SDK = run(["/usr/bin/xcrun", "--show-sdk-path"]).stdout.strip()
ALL = plan(os.path.join(BUILD, "x86_64"))
TESTS = {n: ALL[n] for n in sys.argv[1:]} or ALL                       # argv: run only the named tests
for t in ([""] if TESTS is ALL else [os.path.join(a, n) for a in ARCHES for n in TESTS]):
    shutil.rmtree(os.path.join(BUILD, t), ignore_errors=True)
print("lane gdyld runner present: %s" % os.path.exists(GDYLD))
print("\n".join(oracle(TESTS, SDK)))
print("--- shared varargs core (sbt/gvarargs.h, included by e2e_http.py HOST_RT) + e2e _printf body vs native snprintf")
print("\n".join(gfmt_probe(SDK)))
