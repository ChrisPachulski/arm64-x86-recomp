"""Lane M4a step 7 guard proof: ui.m (arm64 only, never run natively) is translated by gdyld and run once per case; every
window-server / AppKit-UI / GPU case must stop loudly before its call (FATAL 'blocked window-server', exit 70, no REACHED
line), and the Foundation-only case must still run. Safety order: two benign AppKit pre-flight cases (NSColor) must stop
first, and the bridge table must route every guarded C import to the stop, before any real UI/GPU case runs.
Run bare: sbtenv/bin/python tests/uiguard/run_uiguard.py"""
###############
# imports and constants
###############
from __future__ import annotations
import os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld

SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
BUILD = os.path.join(HERE, "build")
GUEST = os.path.join(BUILD, "ui_arm64")
PROBES = ["probe_msg", "probe_alloc"]                                  # benign if the guard failed: NSColor only
CASES = ["mtl", "mtlall", "app", "appmain", "win", "gview", "layer", "cg", "cfalert",
         "r_imp", "r_method_imp", "r_invoke", "r_invoke_target", "r_perform_all", "r_nstimer", "r_thread", "r_observer",
         "r_dlsym", "r_dispatch", "r_cftimer", "r_cftimer_import",
         "r_inv_saved", "r_inv_perform", "r_inv_perform_all", "r_inv_timer"]   # r_*: host-side routes, benign targets (NSColor, NSBitsPerPixelFromDepth)
C_IMPORTS = ["_MTLCreateSystemDefaultDevice", "_MTLCopyAllDevices", "_NSApplicationMain", "_CGMainDisplayID", "_CFUserNotificationDisplayAlert"]
RUN_TIMEOUT = 60                                                        # seconds per translated run
MARK = "blocked window-server / AppKit-UI / GPU entry point"

###############
# functions
###############
def build() -> str:
    """The arm64 guest only (no x86_64 build: the native program must never run); '' or the compiler error."""
    os.makedirs(BUILD, exist_ok=True)
    r = subprocess.run(["clang", "-isysroot", SDK, "-arch", "arm64", "-O1", "-mmacosx-version-min=13.0", os.path.join(HERE, "ui.m"),
                        "-framework", "Foundation", "-framework", "AppKit", "-framework", "Metal", "-framework", "QuartzCore",
                        "-framework", "CoreGraphics", "-o", GUEST], capture_output=True, text=True)
    return r.stderr if r.returncode else ""

def run_case(exe: str, case: str) -> tuple[int, str, str]:
    """(exit, stdout, last stderr line) of the translated program on one case."""
    r = subprocess.run([exe, case], cwd=BUILD, capture_output=True, text=True, errors="replace", timeout=RUN_TIMEOUT)
    return r.returncode, r.stdout, (r.stderr.strip().splitlines() or [""])[-1]

def loud(exe: str, case: str) -> bool:
    """Run one case; True when it stopped at the guard before the call."""
    rc, out, last = run_case(exe, case)
    good = rc == 70 and MARK in last and "REACHED" not in out and out == "case %s: before\n" % case
    print("%-11s %s exit %d | %s" % (case, "LOUD-OK" if good else "FAIL", rc, last))
    return good

def table_routes(bridge: str, names: list) -> dict[str, str]:
    """Import name -> its bridge.hpp entry macro (GD_S(sp_ui_stop ...) / GD_UIU expected)."""
    return {n: next((m.group(0)[:40] for m in re.finditer(r"GD_\w+\([^\n]*\"%s\"\)" % re.escape(n), bridge)), "absent") for n in names}

###############
# run
###############
_err = build()
print("build: %s" % (_err or "ok"))
_res = gdyld.translate(GUEST, os.path.join(BUILD, "gdyld"), SDK)
print("translate: error %r; ui-guard imports %s; prototype+ui-check %s" % (
    _res["error"][-300:], sorted(_res["classes"].get("ui-guard", [])), sorted(_res["classes"].get("prototype+ui-check", []))))
_routes = table_routes(open(os.path.join(BUILD, "gdyld", "bridge.hpp")).read(), C_IMPORTS)
print("bridge routes: %s" % _routes)
_preflight = all(loud(_res["exe"], p) for p in PROBES) and all(r.startswith(("GD_S(sp_ui_stop", "GD_UIU(")) for r in _routes.values())
print("pre-flight (guard proven on benign NSColor + bridge routes): %s" % ("PASS" if _preflight else "FAIL: real UI/GPU cases not run"))
_ok = sum(loud(_res["exe"], c) for c in CASES) if _preflight else 0
_rc, _out, _last = run_case(_res["exe"], "ok")
print("ok          %s exit %d | stdout %r" % ("PASS" if _rc == 0 and "7-foundation ok" in _out else "FAIL", _rc, _out))
print("RESULT: %d/%d guarded cases stopped loudly before the call" % (_ok, len(CASES)))
