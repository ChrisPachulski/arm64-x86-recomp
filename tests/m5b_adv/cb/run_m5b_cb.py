"""Adversarial callback bed: each tests/m5b_adv/cb/c*.m / c*.mm (or the names given) built x86_64 (oracle, 3 runs) and arm64,
the arm64 build translated by gdyld; MATCH when stdout + exit equal the oracle's, else the diff and the translated stderr tail.
ARGV_CASES adds extra runs with an argument."""
###############
# imports and constants
###############
from __future__ import annotations
import difflib, glob, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld  # noqa: E402  (library under test)

SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
CC = ["clang", "-isysroot", SDK, "-mmacosx-version-min=13", "-O1", "-w", "-fobjc-arc", "-framework", "Foundation"]
CXX = ["-std=c++17", "-nostdinc++", "-isystem", os.path.join(SDK, "usr", "include", "c++", "v1"), "-lc++"]
EXTRA = {"c4_coretext": ["-framework", "CoreText"]}
ARGV_CASES = {"c3_exc": [["uncaught"]], "c5_fts": [["nocmp"]], "c6_exit_flush": [["fopen"], ["funopen"]]}
RUN_TIMEOUT = 120                                              # seconds per run
SRCS = sorted(glob.glob(os.path.join(HERE, "c*.m")) + glob.glob(os.path.join(HERE, "c*.mm")))
NAMES = sys.argv[1:] or [os.path.splitext(os.path.basename(p))[0] for p in SRCS]

###############
# functions
###############
def build(name: str, arch: str) -> tuple[str, str]:
    """(executable, error text) for one arch."""
    d = os.path.join(HERE, "build", name, arch)
    os.makedirs(d, exist_ok=True)
    src = next(p for p in SRCS if os.path.splitext(os.path.basename(p))[0] == name)
    exe = os.path.join(d, name)
    r = subprocess.run(CC + (CXX if src.endswith(".mm") else []) + EXTRA.get(name, []) + ["-arch", arch, src, "-o", exe],
                       capture_output=True, text=True, timeout=300)
    return exe, r.stderr[-1500:] if r.returncode else ""

def run_exe(argv: list[str]) -> tuple[int, str, str]:
    """(exit, stdout, stderr); exit -999 on timeout."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=RUN_TIMEOUT, errors="replace", cwd=os.path.dirname(argv[0]))
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -999, "", "TIMEOUT"

def compare(native: str, translated: str, extra: list[str]) -> str:
    """One verdict for one argument list."""
    oracle = [run_exe([native] + extra) for _ in range(3)]
    if len({(r[0], r[1]) for r in oracle}) != 1: return "UNSTABLE-ORACLE %s" % [(r[0], r[1][-200:]) for r in oracle]
    got = run_exe([translated] + extra)
    if (got[0], got[1]) == (oracle[0][0], oracle[0][1]): return "MATCH (exit %d, %d lines)" % (got[0], len(got[1].splitlines()))
    diff = "".join(difflib.unified_diff(oracle[0][1].splitlines(True), got[1].splitlines(True), "native", "translated", n=0))
    return "MISMATCH native exit %d translated %d\n%s  translated stderr tail: %s" % (oracle[0][0], got[0], diff[-3500:], got[2].strip()[-1500:])

def verdict(name: str) -> str:
    """All verdict lines of one program."""
    x86, ex = build(name, "x86_64")
    arm, ea = build(name, "arm64")
    if ex or ea: return "BUILD-FAIL %s" % (ex + ea)
    try:
        res = gdyld.translate(arm, os.path.join(HERE, "build", name, "gdyld"), SDK)
    except Exception as e:
        return "TRANSLATE-FAIL %s: %s" % (type(e).__name__, str(e)[-2000:])
    if res["error"]: return "TRANSLATE-FAIL build error: %s" % res["error"][-2500:]
    return "\n".join("%s%s" % ("" if not a else "[%s] " % " ".join(a), compare(x86, res["exe"], a)) for a in [[]] + ARGV_CASES.get(name, []))

###############
# run
###############
for n in NAMES:
    t = time.time()
    v = verdict(n)
    print("== %s (%.0f s): %s" % (n, time.time() - t, v), flush=True)
