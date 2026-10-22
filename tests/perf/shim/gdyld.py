"""Stand-in gdyld for tests/perf/check_ab_exit.py (passed to ab_perf.py as --base=tests/perf/shim): translate() fails
(AB_SHIM=fail, the default) or hands back /usr/bin/true as the translation (AB_SHIM=diff), whose output matches no benchmark."""
###############
# imports
###############
from __future__ import annotations
import os

###############
# functions
###############
def translate(exe: str, out: str, sdk: str) -> dict:
    """gdyld.translate's result dict: a forced error, or a program whose output differs from the benchmark's."""
    if os.environ.get("AB_SHIM") == "diff": return {"error": "", "exe": "/usr/bin/true", "lift_secs": 0.0, "build_secs": 0.0}
    return {"error": "shim: forced translation failure", "exe": "", "lift_secs": 0.0, "build_secs": 0.0}
