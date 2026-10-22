"""Translate one arm64 executable with the gdyld.py of a given sbt/ directory (A/B driver: each translator runs in its own
process, so two copies of the sbt modules never share sys.modules). Usage: ab_translate.py <sbt dir> <arm64 exe> <out dir>.
Prints 'EXE <path>' and the lift/build seconds, or 'ERROR <text>' and exits 1."""
###############
# imports and constants
###############
from __future__ import annotations
import os, subprocess, sys

SBT, EXE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GDYLD_GUESTRT", os.path.join(ROOT, "guestrt", "lib"))              # read-only guest runtime of this repo
sys.path.insert(0, SBT)
import gdyld  # noqa: E402  (the translator under test)

###############
# functions
###############
def translated(exe: str, out: str) -> str:
    """'EXE <path> lift <s> build <s>' or 'ERROR <text>' for one translation."""
    sdk = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
    res = gdyld.translate(exe, out, sdk)
    return "ERROR " + res["error"][-600:] if res["error"] else "EXE %s lift %.1f build %.1f" % (res["exe"], res["lift_secs"], res["build_secs"])

###############
# run
###############
RESULT = translated(EXE, OUT)
print(RESULT)
sys.exit(1 if RESULT.startswith("ERROR") else 0)
