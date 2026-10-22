"""Prints a crash report (.ips) summary or a translated program's log with every frame name that carries a guest-address-like hex run
(8+ hex digits) replaced by <guest-named frame>, so traces can be read without naming translated guest functions.
Usage: safe_trace.py <file.ips | program log> [max frames per thread, default 16]"""
###############
# imports and constants
###############
from __future__ import annotations
import json, os, re, sys

HEXRUN = re.compile(r"[0-9a-fA-F]{8,}")
BT_LINE = re.compile(r"^(\d+\s+)(\S+)(\s+0x[0-9a-fA-F]+\s+)(.*)$")                    # backtrace_symbols_fd format
PATH = sys.argv[1]
FRAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 16

###############
# functions
###############
def safe_name(name: str) -> str:
    """The frame name, or a placeholder when it carries a hex run."""
    return "<guest-named frame>" if HEXRUN.search(name) else name

def safe_log_line(line: str) -> str:
    """A log line with the symbol part of a backtrace line made safe; other lines unchanged."""
    m = BT_LINE.match(line)
    return line if not m else m.group(1) + m.group(2) + m.group(3) + safe_name(m.group(4))

def ips_summary(path: str, frames: int) -> list[str]:
    """Summary lines of a .ips crash report: process, exception, termination, abort info, faulting thread frames."""
    head, body = open(path, errors="replace").read().split("\n", 1)
    h, b = json.loads(head), json.loads(body)
    imgs = b.get("usedImages", [])
    th = b["threads"][b.get("faultingThread", 0)]
    out = ["%s %s launch %s crash %s parent %s" % (h.get("app_name"), b.get("procPath"), b.get("procLaunch"), b.get("captureTime"), b.get("parentProc")),
           "exception %s" % b.get("exception"), "termination %s" % b.get("termination", {}).get("indicator"),
           "asi %s" % b.get("asi"), "faulting thread %s queue %s name %s" % (b.get("faultingThread"), th.get("queue"), th.get("name"))]
    for fr in th.get("frames", [])[:frames]:
        im = imgs[fr["imageIndex"]] if fr.get("imageIndex", -1) < len(imgs) else {}
        out.append("  %-28s %s" % (im.get("name") or os.path.basename(im.get("path", "?")), safe_name(fr.get("symbol", ""))))
    return out

###############
# run
###############
LINES = ips_summary(PATH, FRAMES) if PATH.endswith(".ips") else [safe_log_line(l.rstrip("\n")) for l in open(PATH, errors="replace")]
for _l in LINES: print(_l[:260])
