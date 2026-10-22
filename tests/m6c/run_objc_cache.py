"""Regression bed for the per-site ObjC send cache (a stale-entry bug): builds tests/m6c/src/o2_cache_stale.m for x86_64
(native oracle) and arm64, translates the arm64 build with gdyld, compares stdout + exit with native and requires the
translated run to have reused the disposed class's address. Exit 1 on any failure.
Run bare: sbtenv/bin/python tests/m6c/run_objc_cache.py [prefix]  (prefix: translate with an older sbt/ copied to prefix_m6c/sbt, to show the bed catches the bug)"""
###############
# imports and constants
###############
from __future__ import annotations
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
PREFIX = "prefix" in sys.argv[1:]
SBT = os.path.join(LANE, "prefix_m6c", "sbt") if PREFIX else os.path.join(LANE, "sbt")
os.environ.setdefault("GDYLD_GUESTRT", os.path.join(LANE, "guestrt", "lib"))
sys.path.insert(0, SBT)
import gdyld  # noqa: E402  (translator under test)

SRC = os.path.join(HERE, "src", "o2_cache_stale.m")
BUILD = os.path.join(HERE, "build", "objc_cache_prefix" if PREFIX else "objc_cache")
RUN_TIMEOUT = 60                                                       # s per run
REUSED = "address reused: 1"

###############
# functions
###############
def build(arch: str, sdk: str) -> str:
    """Executable of SRC for arch."""
    out = os.path.join(BUILD, arch, "o2_cache_stale")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = subprocess.run(["/usr/bin/clang", "-O1", "-fno-objc-arc", "-isysroot", sdk, "-arch", arch, "-framework", "Foundation",
                        "-o", out, SRC], capture_output=True, text=True)
    if r.returncode: raise RuntimeError("build %s: %s" % (arch, r.stderr[-800:]))
    return out

def run(exe: str) -> tuple[str, str]:
    """(stdout + exit line, stderr) of one run."""
    r = subprocess.run([exe], capture_output=True, text=True, errors="replace", timeout=RUN_TIMEOUT)
    return r.stdout + "EXIT %d\n" % r.returncode, r.stderr

###############
# run
###############
print("translator: %s" % SBT, flush=True)
SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
NATIVE, NATIVE_ERR = run(build("x86_64", SDK))
RES = gdyld.translate(build("arm64", SDK), os.path.join(BUILD, "gdyld"), SDK)
if RES["error"]: print("BUILD FAIL %s" % RES["error"][-800:], flush=True); sys.exit(1)
GOT, GOT_ERR = run(RES["exe"])
print("native:     %s| %s" % (NATIVE.replace("\n", " | "), NATIVE_ERR.strip()), flush=True)
print("translated: %s| %s" % (GOT.replace("\n", " | "), GOT_ERR.strip()[-400:]), flush=True)
OK = GOT == NATIVE and REUSED in GOT_ERR
print("o2_cache_stale: %s" % ("MATCH (address reused)" if OK else "MISMATCH" if GOT != NATIVE else "INCONCLUSIVE (no address reuse)"), flush=True)
sys.exit(0 if OK else 1)
