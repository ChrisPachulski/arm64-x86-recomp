"""Adversarial Objective-C / blocks bed: each tests/objc_adv/a*.m (or the names given) built x86_64 (oracle) and arm64, the arm64 build translated by gdyld; translated stdout + exit must equal the oracle's, OBJC_REPEAT=n reruns the translated exe n times."""
###############
# imports and constants
###############
from __future__ import annotations
import collections, difflib, glob, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld  # noqa: E402  (library under test)

SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
CC = ["clang", "-isysroot", SDK, "-O1", "-w", "-fobjc-arc", "-framework", "Foundation"]
RUN_TIMEOUT = 120                                              # seconds per run
REPEAT = int(os.environ.get("OBJC_REPEAT", "1"))               # translated runs per program
SRCS = sorted(glob.glob(os.path.join(HERE, "a*.m")) + glob.glob(os.path.join(HERE, "a*.mm")))
NAMES = sys.argv[1:] or [os.path.splitext(os.path.basename(p))[0] for p in SRCS]
CXX = ["-std=c++17", "-nostdinc++", "-isystem", os.path.join(SDK, "usr", "include", "c++", "v1"), "-lc++"]   # .mm sources

###############
# functions
###############
def build(name: str, arch: str, out: str) -> tuple[str, str]:
    """(executable, error text) for one arch."""
    d = os.path.join(out, arch)
    os.makedirs(d, exist_ok=True)
    exe = os.path.join(d, name)
    src = next(p for p in SRCS if os.path.splitext(os.path.basename(p))[0] == name)
    r = subprocess.run(CC + (CXX if src.endswith(".mm") else []) + ["-arch", arch, src, "-o", exe], capture_output=True, text=True)
    return exe, r.stderr[-1500:] if r.returncode else ""

def run_exe(exe: str) -> tuple[int, str, str]:
    """(exit, stdout, stderr); exit -999 on timeout."""
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=RUN_TIMEOUT, errors="replace", cwd=os.path.dirname(exe))
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -999, "", "TIMEOUT"

def save(out: str, tag: str, r: tuple[int, str, str]) -> None:
    """Write one run's outputs."""
    open(os.path.join(out, tag + ".txt"), "w").write("exit %d\n--- stdout\n%s--- stderr\n%s" % r)

def verdict(name: str) -> str:
    """One program's verdict line."""
    out = os.path.join(HERE, "build", name)
    x86, ex = build(name, "x86_64", out)
    arm, ea = build(name, "arm64", out)
    if ex or ea: return "BUILD-FAIL %s" % (ex + ea)
    oracle = [run_exe(x86) for _ in range(3)]
    for i, r in enumerate(oracle): save(out, "native_%d" % i, r)
    if len({(r[0], r[1]) for r in oracle}) != 1: return "UNSTABLE-ORACLE exits %s" % [r[0] for r in oracle]
    try:
        res = gdyld.translate(arm, os.path.join(out, "gdyld"), SDK)
    except Exception as e:
        return "TRANSLATE-FAIL %s: %s" % (type(e).__name__, str(e)[-2000:])
    if res["error"]: return "TRANSLATE-FAIL build error: %s" % res["error"][-2500:]
    runs = [run_exe(res["exe"]) for _ in range(REPEAT)]
    for i, r in enumerate(runs): save(out, "translated_%d" % i, r)
    bad = [r for r in runs if (r[0], r[1]) != (oracle[0][0], oracle[0][1])]
    info = "unsupported %d, exits %s" % (len(res["unsupported"]), dict(collections.Counter(r[0] for r in runs)))
    if not bad: return "MATCH (exit %d, %d lines, %d runs) | %s" % (oracle[0][0], len(oracle[0][1].splitlines()), REPEAT, info)
    got = bad[0]
    diff = "".join(difflib.unified_diff(oracle[0][1].splitlines(True), got[1].splitlines(True), "native", "translated"))
    return "MISMATCH %d/%d runs, native exit %d translated %d | %s\n%s\n  translated stderr tail: %s" % (
        len(bad), REPEAT, oracle[0][0], got[0], info, diff[-3000:], got[2].strip()[-1200:])

###############
# run
###############
results = {}
for n in NAMES:
    t = time.time()
    results[n] = verdict(n)
    print("== %s (%.0f s): %s" % (n, time.time() - t, results[n]), flush=True)
print("summary: %s" % {n: v.split()[0] for n, v in results.items()})
