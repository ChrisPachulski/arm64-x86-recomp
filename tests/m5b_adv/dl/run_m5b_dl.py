"""Adversarial guest dlopen bed: dlmain.c + sub/libm1 (linked) + sub/libm2 (libm1's dependency) + libh (universal host image),
built x86_64 (native oracle, 3 runs) and arm64 (translated by gdyld). Both run with cwd = their own build dir, so relative paths
mean the same thing. Prints MATCH or the per-line diff; then the 'hostcall' case (direct call of a dlsym'd host function)."""
###############
# imports and constants
###############
from __future__ import annotations
import difflib, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld  # noqa: E402  (library under test)

SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
BUILD = os.path.join(HERE, "build")
RUN_TIMEOUT = 60                                               # seconds per run

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
    os.makedirs(os.path.join(d, "sub"), exist_ok=True)
    errs = [cc(["-arch", arch, "-dynamiclib", "-install_name", "@rpath/libm2.dylib", os.path.join(HERE, "m2.c"), "-o", "sub/libm2.dylib"], d),
            cc(["-arch", arch, "-dynamiclib", "-install_name", "@rpath/libm1.dylib", os.path.join(HERE, "m1.c"), "sub/libm2.dylib",
                "-Wl,-rpath,@loader_path", "-o", "sub/libm1.dylib"], d),
            cc(["-arch", "arm64", "-arch", "x86_64", "-dynamiclib", "-install_name", "@rpath/libh.dylib", os.path.join(HERE, "h.c"), "-o", "libh.dylib"], d),
            cc(["-arch", arch, os.path.join(HERE, "dlmain.c"), "sub/libm1.dylib", "-Wl,-rpath,@executable_path/sub", "-o", "dlmain"], d)]
    link = os.path.join(d, "link_m1.dylib")
    if not os.path.islink(link): os.symlink("sub/libm1.dylib", link)
    return os.path.join(d, "dlmain"), "".join(errs)

def run_exe(argv: list[str], cwd: str) -> tuple[int, str, str]:
    """(exit, stdout, stderr) of one bounded run; exit -999 on timeout."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=RUN_TIMEOUT, errors="replace", cwd=cwd)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -999, "", "TIMEOUT"

def verdict(native: str, translated: str, guest_dir: str, extra: list[str]) -> str:
    """MATCH / MISMATCH with the diff and the translated stderr tail."""
    oracle = [run_exe([native] + extra, os.path.dirname(native)) for _ in range(3)]
    if len({(r[0], r[1]) for r in oracle}) != 1: return "UNSTABLE-ORACLE exits %s" % [r[0] for r in oracle]
    got = run_exe([translated] + extra, guest_dir)
    if (got[0], got[1]) == (oracle[0][0], oracle[0][1]): return "MATCH (exit %d, %d lines)\n%s" % (got[0], len(got[1].splitlines()), got[1])
    diff = "".join(difflib.unified_diff(oracle[0][1].splitlines(True), got[1].splitlines(True), "native", "translated", n=0))
    return "MISMATCH exit native %d translated %d\n%s  translated stderr tail: %s" % (oracle[0][0], got[0], diff, got[2][-1500:])

###############
# run
###############
NATIVE, ERR_X = build("x86_64")
GUEST, ERR_A = build("arm64")
print("build: %s" % (ERR_X + ERR_A or "ok"))
RES = gdyld.translate(GUEST, os.path.join(BUILD, "gdyld"), SDK)
print("translate: error %r" % RES["error"][-500:])
print("dlmain: %s" % verdict(NATIVE, RES["exe"], os.path.dirname(GUEST), []))
print("dlmain hostcall: %s" % verdict(NATIVE, RES["exe"], os.path.dirname(GUEST), ["hostcall"]).split("\n  translated stderr tail: ")[-1][-400:])
