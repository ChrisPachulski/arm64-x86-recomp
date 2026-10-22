"""Translates one arm64 macOS executable, with the arm64 dylibs it loads, into a native x86-64 executable
(<out dir>/translated) and prints gdyld's build report. --ui-guard-off lets the translated program reach the window
server and the GPU; by default those calls stop it loudly. Exit 1 on a build error, an unsupported instruction or an
input or link error (printed as one line); any other option is refused.
Run bare: sbtenv/bin/python tools/translate.py <arm64 executable> <out dir> [--ui-guard-off]"""
###############
# imports and constants
###############
from __future__ import annotations
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sbt"))
import gdyld  # noqa: E402  (the translator library)

USAGE = "usage: translate.py <arm64 executable> <out dir> [--ui-guard-off]"
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
OPTS = [a for a in sys.argv[1:] if a.startswith("--")]

###############
# functions
###############
def translate(exe: str, out: str, sdk: str, ui_guard: bool) -> dict:
    """gdyld.translate; its input, link and address-space errors become a one-line exit."""
    try:
        return gdyld.translate(exe, out, sdk, ui_guard=ui_guard)
    except (ValueError, OSError, LookupError, MemoryError) as e:
        if isinstance(e, (KeyError, IndexError)): raise                # a translator bug: keep the traceback
        raise SystemExit("translate.py: %s: %s" % (type(e).__name__, str(e)[-2000:]))

###############
# run
###############
if len(ARGS) != 2 or set(OPTS) - {"--ui-guard-off"}: raise SystemExit(USAGE)
SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True, check=True).stdout.strip()
RES = translate(os.path.abspath(ARGS[0]), os.path.abspath(ARGS[1]), SDK, "--ui-guard-off" not in OPTS)
print("\n".join(RES["report"]))
print("executable: %s | unsupported instructions: %d | build error: %s" % (RES["exe"], len(RES["unsupported"]), RES["error"][-2000:] or "none"))
if RES["error"] or RES["unsupported"]: raise SystemExit(1)
