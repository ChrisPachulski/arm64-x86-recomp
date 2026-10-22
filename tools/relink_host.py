"""Recompile host.cpp and relink a gdyld build in place from its host_link_cmds.json (written by gdyld.compile_all), for a
change to the host runtime headers only (gbridge.hpp, gobjc.hpp, gswift.hpp ...): the lifted chunks are not touched.
Run bare: sbtenv/bin/python tools/relink_host.py <gdyld out dir>"""
###############
# imports and constants
###############
from __future__ import annotations
import json, os, subprocess, sys, time

OUT = os.path.abspath(sys.argv[1])

###############
# functions
###############
def step(cmd: list[str]) -> tuple[int, float, str]:
    """(exit, seconds, stderr tail) of one command."""
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, time.time() - t0, r.stderr[-2000:]

###############
# run
###############
_cmds = json.load(open(os.path.join(OUT, "host_link_cmds.json")))
for _name in ("host", "link"):
    _rc, _secs, _err = step(_cmds[_name])
    print("%s: exit %d after %.0f s%s" % (_name, _rc, _secs, "" if not _rc else "\n" + _err))
    if _rc: raise SystemExit(1)
print("executable: %s, %d bytes" % (_cmds["link"][-1], os.path.getsize(_cmds["link"][-1])))
