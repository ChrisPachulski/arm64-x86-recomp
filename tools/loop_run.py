"""Run one executable N times (cwd = its own dir, per-run timeout) and print failures: exit code, stdout mismatch vs run 1, stderr tail.
Usage: loop_run.py <exe> <n> [timeout_s] [expected_stdout_file]"""
###############
# imports and constants
###############
from __future__ import annotations
import collections, os, subprocess, sys, time

EXE = os.path.abspath(sys.argv[1])
N = int(sys.argv[2])
TIMEOUT = float(sys.argv[3]) if len(sys.argv) > 3 else 300.0     # seconds per run
EXPECT_FILE = sys.argv[4] if len(sys.argv) > 4 else ""

###############
# functions
###############
def run_once(exe: str, timeout: float) -> tuple[int, str, str]:
    """One run: (exit, stdout, stderr); exit -999 on timeout."""
    try:
        r = subprocess.run([exe], cwd=os.path.dirname(exe), capture_output=True, text=True, errors="replace", timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -999, "", "TIMEOUT"

def expected(path: str) -> str | None:
    """Expected stdout from a saved runner file (between '--- stdout' and '--- stderr'), or None."""
    if not path: return None
    t = open(path).read()
    return t.split("--- stdout\n", 1)[1].split("--- stderr\n", 1)[0]

###############
# run
###############
want = expected(EXPECT_FILE)
t0 = time.time()
results = [run_once(EXE, TIMEOUT) for _ in range(N)]
ref = want if want is not None else results[0][1]
bad = [(i, r) for i, r in enumerate(results) if r[0] != 0 or r[1] != ref]
for i, r in bad:
    print("run %d: exit %d, stdout %s, stderr tail: %s" % (i, r[0], "same" if r[1] == ref else "DIFFERENT", r[2].strip()[-600:]))
print("exits: %s" % dict(collections.Counter(r[0] for r in results)))
print("%d/%d failed, %.0f s" % (len(bad), N, time.time() - t0))
