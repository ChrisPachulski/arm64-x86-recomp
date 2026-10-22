"""Bridge class of every host import of a guest program, without lifting or building: gdyld's load, link and bridge-table
steps only. Prints the class counts and the 'dynamic' imports split into functions and data (dlsym in this x86-64 process
after loading the program's host libraries). Usage: import_classes.py <arm64 executable> [ObjC-only filter: objc]"""
###############
# imports and constants
###############
from __future__ import annotations
import ctypes, os, subprocess, sys

LANE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld  # noqa: E402

EXE = sys.argv[1]
SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
OBJC_HINTS = ("objc", "OBJC", "Block", "NSConcrete", "NSLog", "CFConstantString")

###############
# functions
###############
def bridge_classes(exe: str) -> tuple[dict, list]:
    """(class -> [import names], host library install names) as gdyld.translate would emit them."""
    images = gdyld.load_images(exe)
    host_files = images[0]["host_files"]
    _flats, host_binds, _report = gdyld.link(images)
    keys = gdyld.import_keys(host_binds)
    names = sorted(set(keys.values()))
    weak = {keys[n] for _a, n, _ad, w in host_binds if w}
    extra = {n: (None, p) for n, p in host_files.items()}
    hdrs, _flags = gdyld.framework_headers(SDK, gdyld.host_libs(images), extra)
    declared, usable = gdyld.declared_names(SDK, hdrs)
    allp = gdyld.c_prototypes(SDK, gdyld.BASE_HEADERS + [h for h in usable if h not in gdyld.BASE_HEADERS])
    noesc = {n: gdyld.TRAIL_ATTR_RE.sub("", t.replace(gdyld.NOESCAPE + " ", "")) for n, t in allp.items() if gdyld.NOESCAPE in t}
    v8 = gdyld.v8_libs(host_files)
    v8idx = {n: 0 for n in names for n in [n[1]] if v8 and n.startswith(("__ZN2v8", "__ZNK2v8", "__ZN12v8_inspector"))}   # class only
    _bridge, classes = gdyld.bridge_hpp(names, declared, {lib: p for lib, (_h, p) in extra.items()}, weak, v8idx or None, None, noesc)
    return classes, gdyld.host_libs(images) + sorted(host_files.values())

def load_libs(libs: list) -> list:
    """dlopen each host library (frameworks by install name); returns the ones that failed."""
    bad = []
    for lib in libs:
        try: ctypes.CDLL(lib)
        except OSError: bad.append(lib)
    return bad

###############
# run
###############
classes, libs = bridge_classes(EXE)
print("classes: %s" % {k: len(v) for k, v in sorted(classes.items())})
print("unloadable host libraries: %s" % load_libs(libs))
dyn = classes.get("dynamic", [])
proc = ctypes.CDLL(None)
print("dynamic %d, not ObjC class refs, resolvable here: %s" % (len(dyn), [n for n in dyn if not n.startswith("_OBJC_") and hasattr(proc, n[1:])]))
print("dynamic, unresolvable here: %s" % [n for n in dyn if not hasattr(proc, n[1:])])
print("special: %s" % sorted(n for n in classes.get("special", []) if any(h in n for h in OBJC_HINTS) or "printf" in n or "ulock" in n))
print("trap: %s" % classes.get("trap", []))
print("objc-related by class: %s" % {k: sorted(n for n in v if any(h in n for h in OBJC_HINTS)) for k, v in sorted(classes.items())})
