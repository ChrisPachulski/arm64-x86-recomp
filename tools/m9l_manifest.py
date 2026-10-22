"""Lane M9L: sha256 manifest of a gdyld build dir (sources, headers, bridges, objects, executable; symlinks by target),
written as JSON; with a second manifest, prints the names whose hashes differ (contents are never printed).
Run bare: sbtenv/bin/python tools/m9l_manifest.py <build_dir> <out.json> [<other.json>]"""
###############
# imports and constants
###############
from __future__ import annotations
import hashlib, json, os, sys

SKIP = {"compile_stats.json"}                                          # per-job timings and RSS: differ every run
EXE = "translated"
BLOCK = 1 << 22                                                        # bytes per read

###############
# functions
###############
def file_hash(path: str) -> str:
    """sha256 of one file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(BLOCK), b""): h.update(b)
    return h.hexdigest()

def entry(root: str, rel: str) -> str:
    """'link:<target>' for a symlink, else the file's sha256."""
    p = os.path.join(root, rel)
    return "link:" + os.readlink(p) if os.path.islink(p) else file_hash(p)

def rel_paths(root: str) -> list[str]:
    """Every file or symlink under root, relative, sorted, minus SKIP."""
    out = [os.path.relpath(os.path.join(d, n), root) for d, ds, fs in os.walk(root) for n in fs + [x for x in ds if os.path.islink(os.path.join(d, x))]]
    return sorted(r for r in out if os.path.basename(r) not in SKIP)

def manifest(root: str) -> dict[str, str]:
    """rel path -> entry for the whole build dir."""
    return {r: entry(root, r) for r in rel_paths(root)}

def groups(m: dict[str, str]) -> dict[str, int]:
    """File counts by kind: objects, executable, everything else (sources, headers, bridges, links)."""
    obj = sum(r.endswith(".o") for r in m)
    return {"objects": obj, "executable": int(EXE in m), "generated": len(m) - obj - int(EXE in m)}

def digest(m: dict[str, str], keep: object) -> str:
    """sha256 over the sorted (path, entry) rows that keep(path) selects."""
    return hashlib.sha256("".join("%s\t%s\n" % (r, m[r]) for r in sorted(m) if keep(r)).encode()).hexdigest()

def differences(a: dict[str, str], b: dict[str, str]) -> list[str]:
    """Paths only in one manifest or with different entries."""
    return sorted(r for r in set(a) | set(b) if a.get(r) != b.get(r))

###############
# run
###############
_root, _out = sys.argv[1], sys.argv[2]
_m = manifest(_root)
json.dump(_m, open(_out, "w"), indent=0, sort_keys=True)
print("manifest %s: %d entries %s" % (_out, len(_m), groups(_m)))
print("digest generated (no .o, no exe): %s" % digest(_m, lambda r: not r.endswith(".o") and r != EXE))
print("digest objects: %s" % digest(_m, lambda r: r.endswith(".o")))
print("executable sha256: %s" % _m.get(EXE, "missing"))
_other = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else None
_diff = differences(_m, _other) if _other is not None else []
if _other is not None: print("vs %s: %d differing paths %s" % (sys.argv[3], len(_diff), _diff[:40]))
