"""Guest dlopen bed: dl_main.c with libdla (linked), libdlb (libdla's dependency) and libdlc (linked by nothing), built for
x86_64 (native oracle, 3 runs) and arm64 (translated by gdyld); MATCH when stdout + exit agree. Then the translated-only case
'outside': dlopen of libdlc, an arm64 image outside the load graph, must return NULL with gdyld's dlerror message.
Run bare: sbtenv/bin/python tests/dl/run_dl.py"""
###############
# imports and constants
###############
from __future__ import annotations
import difflib, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld  # noqa: E402  (library under test)

SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
BUILD = os.path.join(HERE, "build")
RUN_TIMEOUT = 60                                               # seconds per run
LIBS = [("libdlb", "dlb.c", []), ("libdla", "dla.c", ["libdlb.dylib", "-Wl,-rpath,@loader_path"]), ("libdlc", "dlc.c", [])]

###############
# functions
###############
def cc(args: list[str], d: str) -> str:
    """clang with the SDK in directory d; '' or the error text."""
    r = subprocess.run(["clang", "-isysroot", SDK, "-mmacosx-version-min=13", "-O1", "-w"] + args, cwd=d, capture_output=True, text=True, timeout=300)
    return r.stderr[-1500:] if r.returncode else ""

def build(arch: str) -> tuple[str, str]:
    """(executable, errors) for one arch in BUILD/<arch>."""
    d = os.path.join(BUILD, arch)
    os.makedirs(d, exist_ok=True)
    errs = [cc(["-arch", arch, "-dynamiclib", "-install_name", "@rpath/%s.dylib" % n, os.path.join(HERE, src)] + extra + ["-o", n + ".dylib"], d)
            for n, src, extra in LIBS]
    errs.append(cc(["-arch", "arm64", "-arch", "x86_64", "-dynamiclib", "-install_name", "@rpath/libdlh.dylib", os.path.join(HERE, "dlh.c"),
                    "-o", "libdlh.dylib"], d))                 # universal: a host image to the translated program
    errs.append(cc(["-arch", arch, os.path.join(HERE, "dl_main.c"), "libdla.dylib", "-Wl,-rpath,@executable_path", "-o", "dl_main"], d))
    return os.path.join(d, "dl_main"), "".join(errs)

def run_exe(argv: list[str]) -> tuple[int, str, str]:
    """(exit, stdout, stderr) of one bounded run; exit -999 on timeout."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=RUN_TIMEOUT, errors="replace", cwd=os.path.dirname(argv[0]))
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -999, "", "TIMEOUT"

def verdict(native: str, translated: str) -> str:
    """MATCH / MISMATCH (stdout diff, translated stderr tail) / UNSTABLE-ORACLE."""
    oracle = [run_exe([native]) for _ in range(3)]
    if len({(r[0], r[1]) for r in oracle}) != 1: return "UNSTABLE-ORACLE exits %s" % [r[0] for r in oracle]
    got = run_exe([translated])
    if (got[0], got[1]) == (oracle[0][0], oracle[0][1]): return "MATCH (exit %d, %d lines)\n%s" % (got[0], len(got[1].splitlines()), got[1])
    diff = "".join(difflib.unified_diff(oracle[0][1].splitlines(True), got[1].splitlines(True), "native", "translated"))
    return "MISMATCH exit native %d translated %d\n%s\n  translated stderr tail: %s" % (oracle[0][0], got[0], diff, got[2][-1200:])

###############
# run
###############
NATIVE, ERR_X = build("x86_64")
GUEST, ERR_A = build("arm64")
print("build: %s" % (ERR_X + ERR_A or "ok"))
RES = gdyld.translate(GUEST, os.path.join(BUILD, "gdyld"), SDK)
print("translate: error %r; specials %s" % (RES["error"][-500:], sorted(n for n in RES["classes"].get("special", []) if "dl" in n)))
print("dl_main: %s" % verdict(NATIVE, RES["exe"]))
OUT = run_exe([RES["exe"], "outside"])
OK = OUT[0] == 0 and "outside: NULL | gdyld:" in OUT[1] and "not part of this translation" in OUT[1]
print("outside (translated only): %s exit %d | %s" % ("LOUD-OK" if OK else "FAIL", OUT[0], OUT[1].strip()))
