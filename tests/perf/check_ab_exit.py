"""Regression check: ab_translate.py and ab_perf.py must exit non-zero on a translation error and on an output mismatch (the
stand-in translator tests/perf/shim/gdyld.py forces both). --perf=<dir> checks the runners in another copy of tests/perf.
Prints PASS/FAIL per case and exits 1 if any case fails."""
###############
# imports and constants
###############
from __future__ import annotations
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OPTS = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
PERF = os.path.abspath(OPTS.get("perf", HERE))
SHIM = os.path.join(HERE, "shim")
CASES = [                                                              # (name, AB_SHIM, argv after the interpreter, text the output must hold)
    ("ab_translate error", "fail", [os.path.join(PERF, "ab_translate.py"), SHIM, "/usr/bin/true", tempfile.mkdtemp()], "ERROR "),
    ("ab_perf translate fail", "fail", [os.path.join(PERF, "ab_perf.py"), "--base=" + SHIM, "b01_int"], "TRANSLATE FAIL"),
    ("ab_perf output diff", "diff", [os.path.join(PERF, "ab_perf.py"), "--base=" + SHIM, "b01_int"], " DIFF "),
]

###############
# functions
###############
def verdict(name: str, shim: str, argv: list[str], want: str) -> bool:
    """Run one case; True when its output holds want and its exit status is non-zero."""
    r = subprocess.run([sys.executable] + argv, capture_output=True, text=True, env={**os.environ, "AB_SHIM": shim}, timeout=1800)
    ok = want in r.stdout and r.returncode != 0
    print("%-24s %s  exit %d, %r %s in the output" % (name, "PASS" if ok else "FAIL", r.returncode, want.strip(),
                                                      "found" if want in r.stdout else "NOT found"), flush=True)
    return ok

###############
# run
###############
print("runners in %s" % PERF)
OK = [verdict(*c) for c in CASES]
print("check_ab_exit: %d/%d PASS" % (sum(OK), len(OK)))
sys.exit(0 if all(OK) else 1)
