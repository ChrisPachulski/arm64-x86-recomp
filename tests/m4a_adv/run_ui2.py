"""Adversarial guard test for lane M4a (translated side only; ui2.m never runs natively): four more window-server / AppKit /
display entry points (NSScreen, NSCursor, CVDisplayLink, CGDisplayMoveCursorToPoint) from main, from a constructor and
from a guest +load under GDYLD_INIT_ONLY; plus three host-side routes into AppKit (a direct IMP call, NSInvocation,
makeObjectsPerformSelector:) probed with the benign NSBezierPath only. Real cases run only after the benign pre-flight
stops loudly and their C imports are routed to the stop. Run bare: sbtenv/bin/python tests/m4a_adv/run_ui2.py"""
###############
# imports and constants
###############
from __future__ import annotations
import os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
BUILD = os.path.join(HERE, "build", "ui2")
os.environ["GDYLD_OBJCACHE"] = os.path.join(BUILD, "objcache")
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld

SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
GUEST = os.path.join(BUILD, "ui2_arm64")
PREFLIGHT = ["bez_msg", "bez_alloc"]                                    # benign: the guard must stop these
ROUTES = ["bez_imp", "bez_inv", "bez_each"]                             # benign: host-side sends into AppKit
MSG_CASES, C_CASES = ["screen", "cursor"], ["cvlink", "cgmove"]
C_IMPORTS = {"cvlink": "_CVDisplayLinkCreateWithActiveCGDisplays", "cgmove": "_CGDisplayMoveCursorToPoint"}
RUN_TIMEOUT = 60                                                        # seconds per translated run
MARK = "blocked window-server / AppKit-UI / GPU entry point"

###############
# functions
###############
def build() -> str:
    """The arm64 guest only; '' or the compiler error."""
    os.makedirs(BUILD, exist_ok=True)
    r = subprocess.run(["clang", "-isysroot", SDK, "-arch", "arm64", "-O1", "-mmacosx-version-min=13.0", os.path.join(HERE, "ui2.m"),
                        "-framework", "Foundation", "-framework", "AppKit", "-framework", "CoreVideo", "-framework", "CoreGraphics",
                        "-o", GUEST], capture_output=True, text=True)
    return r.stderr if r.returncode else ""

def run_case(exe: str, case: str, where: str) -> tuple[int, str, str]:
    """(exit, stdout, last stderr line); where: 'main' (argv), 'ctor' (UI2_INIT) or 'load' (UI2_LOAD), the last two init-only."""
    env = dict(os.environ)
    if where != "main": env.update({"GDYLD_INIT_ONLY": "1", "UI2_INIT" if where == "ctor" else "UI2_LOAD": case})
    r = subprocess.run([exe] + ([case] if where == "main" else []), cwd=BUILD, capture_output=True, text=True, errors="replace",
                       timeout=RUN_TIMEOUT, env=env)
    return r.returncode, r.stdout, (r.stderr.strip().splitlines() or [""])[-1]

def verdict(exe: str, case: str, where: str) -> str:
    """LOUD-OK (stopped at the guard before the call), REACHED (the call ran) or FAIL, with the evidence."""
    rc, out, last = run_case(exe, case, where)
    v = "LOUD-OK" if rc == 70 and MARK in last and "REACHED" not in out else "REACHED" if "REACHED" in out else "FAIL"
    return "%-8s %-10s %-5s exit %d | stdout %r | %s" % (v, case, where, rc, out[-80:], last[-160:])

def routes(bridge: str, names: dict) -> dict[str, str]:
    """case -> its import's bridge.hpp entry macro (GD_S(sp_ui_stop ...) / GD_UIU expected)."""
    return {c: next((m.group(0)[:40] for m in re.finditer(r"GD_\w+\([^\n]*\"%s\"\)" % re.escape(n), bridge)), "absent") for c, n in names.items()}

###############
# run
###############
_err = build()
print("build: %s" % (_err or "ok"))
_res = gdyld.translate(GUEST, os.path.join(BUILD, "gdyld"), SDK)
print("translate: error %r; ui-guard %s; prototype+ui-check %s" % (_res["error"][-300:], sorted(_res["classes"].get("ui-guard", [])),
                                                                   sorted(_res["classes"].get("prototype+ui-check", []))))
_rt = routes(open(os.path.join(BUILD, "gdyld", "bridge.hpp")).read(), C_IMPORTS)
print("C import routes: %s" % _rt)
_pre = [verdict(_res["exe"], c, "main") for c in PREFLIGHT]
for _ln in _pre: print("pre-flight " + _ln)
_pre_ok = all(_ln.startswith("LOUD-OK") for _ln in _pre)
for _c in ROUTES: print("route      " + verdict(_res["exe"], _c, "main"))
_real = [c for c in MSG_CASES if _pre_ok] + [c for c in C_CASES if _rt[c].startswith(("GD_S(sp_ui_stop", "GD_UIU("))]
print("real cases allowed to run: %s" % _real)
_v = [verdict(_res["exe"], _c, _w) for _c in _real for _w in ("main", "ctor", "load")]
for _ln in _v: print("real       " + _ln)
_rc, _out, _last = run_case(_res["exe"], "ok", "main")
print("ok         %s exit %d | stdout %r" % ("PASS" if _rc == 0 and "7-foundation ok" in _out else "FAIL", _rc, _out))
_rc, _out, _last = run_case(_res["exe"], "none", "ctor")
print("init-only, no case: exit %d | %s" % (_rc, _last[-160:]))
print("RESULT: %d/%d real cases stopped loudly before the call" % (sum(_ln.startswith("LOUD-OK") for _ln in _v), len(_v)))
