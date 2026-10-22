"""ABI check for gobjc.hpp's objc_msgLookup thunks on this host: builds tests/m7b/msglookup_probe.m natively (x86_64), runs
it and prints its lines; exit 1 when any case differs from class_getMethodImplementation or the probe fails."""
###############
# imports and constants
###############
from __future__ import annotations
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "msglookup_probe.m")
EXE = os.path.join(HERE, "build", "msglookup_probe")

###############
# functions
###############
def build(sdk: str) -> str:
    """Error text of the native build, '' when it built."""
    os.makedirs(os.path.dirname(EXE), exist_ok=True)
    r = subprocess.run(["/usr/bin/clang", "-O2", "-fno-objc-arc", "-isysroot", sdk, "-arch", "x86_64", "-framework", "Foundation",
                        "-o", EXE, SRC], capture_output=True, text=True)
    return r.stderr[-1500:] if r.returncode else ""

def probe() -> tuple[int, str]:
    """(exit status, stdout + stderr) of the probe."""
    r = subprocess.run([EXE], capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr

###############
# run
###############
SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
ERR = build(SDK)
if ERR: print("BUILD FAIL\n" + ERR); sys.exit(1)
CODE, OUT = probe()
print(OUT.rstrip())
print("msglookup probe: %s" % ("PASS" if CODE == 0 and "differing 0" in OUT else "FAIL (exit %d)" % CODE))
sys.exit(0 if CODE == 0 and "differing 0" in OUT else 1)
