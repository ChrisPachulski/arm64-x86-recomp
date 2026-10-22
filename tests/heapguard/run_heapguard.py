"""GDYLD_HEAP_GUARD bed: hg_main.c built for x86_64 (native oracle) and arm64 (translated by gdyld). 'ok' must MATCH the
oracle with the guard off, on (128-144) and on for host allocations too (128-144,host); with it on, 'uaf' and 'overflow'
must stop at the write (exit 71, the block's report) and 'double' at the second free (exit 72); with ,host, 'uaf_host'
(a block the host allocated) must stop at the write. Profiler check: 'spin' under GDYLD_PROFILE with a library inserted
(as some launchers insert one) must report "translated guest code" and no guest-address name (no 8+ hex digit run).
Prints one line per case and a summary.
Run bare: sbtenv/bin/python tests/heapguard/run_heapguard.py"""
###############
# imports and constants
###############
from __future__ import annotations
import os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld  # noqa: E402  (library under test)

SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
BUILD = os.path.join(HERE, "build")
RUN_TIMEOUT = 60                                               # seconds per run
GUARD = {"GDYLD_HEAP_GUARD": "128-144", "GDYLD_CRASH_TRACE": "1"}
GUARD_HOST = {"GDYLD_HEAP_GUARD": "128-144,host", "GDYLD_CRASH_TRACE": "1"}
LOUD = [("uaf", GUARD, 71, "in the data page of guarded slot"), ("overflow", GUARD, 71, "in the inaccessible page after the data page"),
        ("double", GUARD, 72, "already freed"), ("uaf_host", GUARD_HOST, 71, "in the data page of guarded slot")]

###############
# functions
###############
def build(arch: str) -> tuple[str, str]:
    """(executable, clang errors) for one arch in BUILD/<arch>."""
    d = os.path.join(BUILD, arch)
    os.makedirs(d, exist_ok=True)
    exe = os.path.join(d, "hg_main")
    r = subprocess.run(["clang", "-isysroot", SDK, "-mmacosx-version-min=13", "-O1", "-w", "-arch", arch, os.path.join(HERE, "hg_main.c"),
                        "-o", exe], capture_output=True, text=True, timeout=300)
    return exe, r.stderr[-1500:] if r.returncode else ""

def run_exe(argv: list[str], extra: dict[str, str]) -> tuple[int, str, str]:
    """(exit, stdout, stderr) of one bounded run with extra environment; exit -999 on timeout."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=RUN_TIMEOUT, errors="replace", env=dict(os.environ, **extra))
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -999, "", "TIMEOUT"

def match_line(name: str, want: tuple[int, str, str], got: tuple[int, str, str]) -> str:
    """'PASS|FAIL name ...' for an ok-run against the native oracle."""
    ok = (got[0], got[1]) == (want[0], want[1])
    return "%s %s exit %d%s" % ("PASS" if ok else "FAIL", name, got[0], "" if ok else " | got %r | want %r | stderr %s" % (got[1], want[1], got[2][-600:]))

def loud_line(exe: str, mode: str, env: dict[str, str], code: int, text: str) -> str:
    """'PASS|FAIL mode ...' for a case that must stop loudly with the guard on."""
    got = run_exe([exe, mode], env)
    ok = got[0] == code and text in got[2] and "not caught" not in got[1]
    return "%s %s exit %d | %s" % ("PASS" if ok else "FAIL", mode, got[0], " / ".join(l for l in got[2].splitlines() if "GDYLD_HEAP_GUARD" in l)[:300])

###############
# run
###############
NATIVE, ERR_X = build("x86_64")
GUEST, ERR_A = build("arm64")
print("build: %s" % (ERR_X + ERR_A or "ok"))
RES = gdyld.translate(GUEST, os.path.join(BUILD, "gdyld"), SDK)
print("translate: error %r" % RES["error"][-500:])
WANT = run_exe([NATIVE, "ok"], {})
ROWS = [match_line("ok guard-off", WANT, run_exe([RES["exe"], "ok"], {})), match_line("ok guard-on", WANT, run_exe([RES["exe"], "ok"], GUARD)),
        match_line("ok guard-host", WANT, run_exe([RES["exe"], "ok"], GUARD_HOST))]
ROWS += [loud_line(RES["exe"], m, e, c, t) for m, e, c, t in LOUD]
PROF = os.path.join(BUILD, "profile.txt")
SPIN = run_exe([RES["exe"], "spin"], {"GDYLD_PROFILE": PROF + ",1000", "DYLD_INSERT_LIBRARIES": "/usr/lib/libz.1.dylib"})
REPORT = open(PROF).read() if os.path.exists(PROF) else ""
LEAKS = len(re.findall(r"[0-9a-fA-F]{8,}", REPORT))
ROWS.append("%s profiler redaction: exit %d, translated group %s, guest-address names %d" % (
    "PASS" if SPIN[0] == 0 and "translated guest code" in REPORT and not LEAKS else "FAIL", SPIN[0], "translated guest code" in REPORT, LEAKS))
for _r in ROWS: print(_r)
print("summary: %d/%d PASS" % (sum(r.startswith("PASS") for r in ROWS), len(ROWS)))
