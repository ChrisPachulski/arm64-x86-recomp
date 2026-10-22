"""ABI-route bed: abi_main.c (SecureTransport cipher-suite arrays, whose element type is 2 bytes on arm64 macOS and 4 on
x86_64) built for x86_64 (native oracle) and arm64 (translated by gdyld). The translated run must MATCH the oracle plain
and under GDYLD_HEAP_GUARD=1-3072 (every small guest block guarded, so a host write past the guest's buffer stops loudly).
Prints one line per run and a summary. Run bare: sbtenv/bin/python tests/abi/run_abi.py"""
###############
# imports and constants
###############
from __future__ import annotations
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld  # noqa: E402  (library under test)

SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
BUILD = os.path.join(HERE, "build")
RUN_TIMEOUT = 60                                               # seconds per run
GUARD = {"GDYLD_HEAP_GUARD": "1-3072", "GDYLD_CRASH_TRACE": "1"}

###############
# functions
###############
def build(arch: str) -> tuple[str, str]:
    """(executable, clang errors) for one arch in BUILD/<arch>."""
    d = os.path.join(BUILD, arch)
    os.makedirs(d, exist_ok=True)
    exe = os.path.join(d, "abi_main")
    r = subprocess.run(["clang", "-isysroot", SDK, "-mmacosx-version-min=13", "-O1", "-w", "-arch", arch, os.path.join(HERE, "abi_main.c"),
                        "-framework", "Security", "-framework", "CoreFoundation", "-o", exe], capture_output=True, text=True, timeout=300)
    return exe, r.stderr[-1500:] if r.returncode else ""

def run_exe(argv: list[str], extra: dict[str, str]) -> tuple[int, str, str]:
    """(exit, stdout, stderr) of one bounded run with extra environment; exit -999 on timeout."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=RUN_TIMEOUT, errors="replace", env=dict(os.environ, **extra))
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -999, "", "TIMEOUT"

def match_line(name: str, want: tuple[int, str, str], got: tuple[int, str, str]) -> str:
    """'PASS|FAIL name ...' for a translated run against the native oracle."""
    ok = (got[0], got[1]) == (want[0], want[1])
    return "%s %s exit %d%s" % ("PASS" if ok else "FAIL", name, got[0], "" if ok else " | got %r | want %r | stderr %s" % (got[1], want[1], got[2][-900:]))

###############
# run
###############
NATIVE, ERR_X = build("x86_64")
GUEST, ERR_A = build("arm64")
print("build: %s" % (ERR_X + ERR_A or "ok"))
RES = gdyld.translate(GUEST, os.path.join(BUILD, "gdyld"), SDK)
print("translate: error %r" % RES["error"][-500:])
WANT = run_exe([NATIVE], {})
print("native: exit %d, %s" % (WANT[0], WANT[1].splitlines()[0] if WANT[1] else "(no output)"))
ROWS = [match_line("plain", WANT, run_exe([RES["exe"]], {})), match_line("guarded 1-3072", WANT, run_exe([RES["exe"]], GUARD))]
gdyld.ABI_ROUTE = {}                                           # negative control: the guarded run must stop at the overflow
OFF = gdyld.translate(GUEST, os.path.join(BUILD, "gdyld_noroute"), SDK)
GOT = run_exe([OFF["exe"]], GUARD)
CAUGHT = GOT[0] == 71 and "inaccessible page after the data page" in GOT[2]
ROWS.append("%s negative control (routes off, guarded): exit %d%s" % ("PASS" if CAUGHT else "FAIL", GOT[0],
            " | " + next((l for l in GOT[2].splitlines() if "GDYLD_HEAP_GUARD: the fault" in l), "")[:200]))
for _r in ROWS: print(_r)
print("summary: %d/%d PASS" % (sum(r.startswith("PASS") for r in ROWS), len(ROWS)))
