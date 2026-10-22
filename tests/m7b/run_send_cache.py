"""Send-cache semantics bed: builds tests/m6c/src/o1_send_cache.m (one call site under swizzling, method exchange, late
addMethod, replaceMethod, forwarding, KVO, nil and class receivers, typed guest and host returns, blocks, two threads) for
x86_64 (oracle) and arm64, translates the arm64 build with the lane's sbt/gdyld.py and compares stdout + exit.
Exit 1 on any difference."""
###############
# imports and constants
###############
from __future__ import annotations
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld  # noqa: E402  (translator under test)

SRC = os.path.join(LANE, "tests", "m6c", "src", "o1_send_cache.m")
BUILD = os.path.join(HERE, "build", "send_cache")
RUN_TIMEOUT = 120                                                      # s per run

###############
# functions
###############
def build(arch: str, sdk: str) -> str:
    """Executable of SRC for arch."""
    out = os.path.join(BUILD, arch, "o1_send_cache")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = subprocess.run(["/usr/bin/clang", "-O1", "-fno-objc-arc", "-isysroot", sdk, "-arch", arch, "-I", os.path.join(LANE, "tests", "perf"),
                        "-framework", "Foundation", "-o", out, SRC], capture_output=True, text=True)
    if r.returncode: raise RuntimeError("build %s: %s" % (arch, r.stderr[-800:]))
    return out

def run(exe: str) -> tuple[str, str]:
    """(stdout + exit line, stderr tail) of one run."""
    r = subprocess.run([exe], capture_output=True, text=True, errors="replace", timeout=RUN_TIMEOUT)
    return r.stdout + "EXIT %d\n" % r.returncode, r.stderr.strip()[-600:]

###############
# run
###############
SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
NATIVE, _NERR = run(build("x86_64", SDK))
RES = gdyld.translate(build("arm64", SDK), os.path.join(BUILD, "gdyld"), SDK)
if RES["error"]: print("BUILD FAIL %s" % RES["error"][-800:]); sys.exit(1)
GOT, GOT_ERR = run(RES["exe"])
print("native:\n" + NATIVE.rstrip())
print("translated:\n" + GOT.rstrip() + ("\nstderr: " + GOT_ERR if GOT != NATIVE else ""))
print("o1_send_cache: %s" % ("MATCH" if GOT == NATIVE and "EXIT 0" in NATIVE else "MISMATCH"))
sys.exit(0 if GOT == NATIVE and "EXIT 0" in NATIVE else 1)
