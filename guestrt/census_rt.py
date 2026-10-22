"""Stream each built arm64 runtime dylib (libunwind, libc++abi, libc++) through the sbt lifter one function at a
time and report functions, instructions, % lift-supported, unsupported mnemonics with
examples, decode gaps, and the LL/SC vs LSE atomic counts. Writes out/verify/census_<lib>.json.
Run bare: sbtenv/bin/python guestrt/census_rt.py"""
###############
# imports and constants
###############
from __future__ import annotations
import json, os, resource, sys, time

LANE = os.path.dirname(os.path.abspath(__file__))
SBT = os.path.join(os.path.dirname(LANE), "sbt")
sys.path.insert(0, SBT)
import recompile as R
import macho

LIBS = ["libunwind.1.dylib", "libc++abi.1.dylib", "libc++.1.dylib"]
LIB_DIR = os.path.join(LANE, "out", "lib")
OUT_DIR = os.path.join(LANE, "out", "verify")
EXAMPLES = 4
LLSC = {"ldxr", "ldaxr", "stxr", "stlxr", "ldxp", "ldaxp", "stxp", "stlxp", "ldxrb", "ldaxrb", "stxrb", "stlxrb",
        "ldxrh", "ldaxrh", "stxrh", "stlxrh"}
LSE_PREFIX = ("cas", "ldadd", "ldclr", "ldeor", "ldset", "ldsmax", "ldsmin", "ldumax", "ldumin", "swp")

###############
# census
###############
def census(path: str) -> dict:
    """Lift every function of one dylib, streaming; return counts and examples."""
    t0 = time.time()
    m = macho.load_macho(path)
    taddr, tbytes = m["text"]
    fstarts = set(a for a in m["fstarts"] if taddr <= a < taddr + len(tbytes))
    unsup = {}; gaps = []; kinds = {}; atom = {"llsc": 0, "lse": 0}; nfunc = ninsn = 0
    ordered = sorted(fstarts) + [taddr + len(tbytes)]
    nxt = dict(zip(ordered, ordered[1:]))
    for start, insns in macho.iter_functions(taddr, tbytes, m["fstarts"]):
        nfunc += 1; ninsn += len(insns)
        atom["llsc"] += sum(1 for i in insns if i.mnemonic in LLSC)
        atom["lse"] += sum(1 for i in insns if i.mnemonic.startswith(LSE_PREFIX))
        covered = (insns[-1].address + 4) if insns else start
        if covered < nxt[start]:
            off = covered - taddr
            gaps.append({"func": hex(start), "at": hex(covered), "word": tbytes[off:off + 4][::-1].hex(),
                         "undecoded_bytes": nxt[start] - covered})
        _, us, _, kind = R.lift_function(insns, fstarts, "f")
        kinds[kind] = kinds.get(kind, 0) + 1
        for addr, mn, why in us:
            e = unsup.setdefault(mn, {"count": 0, "examples": []})
            e["count"] += 1
            if len(e["examples"]) < EXAMPLES:
                ins = next(i for i in insns if i.address == addr)
                e["examples"].append("%#x  %s %s  [%s]" % (addr, ins.mnemonic, ins.op_str, why[:60]))
    return {"lib": os.path.basename(path), "functions": nfunc, "instructions": ninsn, "text_bytes": len(tbytes),
            "kinds": kinds, "atomics": atom, "unsupported_total": sum(v["count"] for v in unsup.values()),
            "unsupported": dict(sorted(unsup.items(), key=lambda kv: -kv[1]["count"])),
            "decode_gaps": len(gaps), "decode_gap_bytes": sum(g["undecoded_bytes"] for g in gaps),
            "gap_examples": gaps[:20], "imports": len(m["imports"]), "fixups": len(m["fixups"]),
            "seconds": round(time.time() - t0, 1)}

###############
# run
###############
os.makedirs(OUT_DIR, exist_ok=True)
for _lib in LIBS:
    _c = census(os.path.join(LIB_DIR, _lib))
    json.dump(_c, open(os.path.join(OUT_DIR, "census_%s.json" % _lib.split(".")[0]), "w"), indent=1)
    _ok = _c["instructions"] - _c["unsupported_total"]
    print("== %s: %d functions, %d instructions, %.3f%% lift-supported, %d decode gaps (%d bytes), %d imports, "
          "%d fixups, atomics %s, %.0fs" % (_c["lib"], _c["functions"], _c["instructions"], 100.0 * _ok / _c["instructions"],
                                           _c["decode_gaps"], _c["decode_gap_bytes"], _c["imports"], _c["fixups"],
                                           _c["atomics"], _c["seconds"]))
    print("   kinds:", _c["kinds"])
    for _mn, _e in _c["unsupported"].items():
        print("   unsupported %-10s x%-4d e.g. %s" % (_mn, _e["count"], " | ".join(_e["examples"][:2])))
    for _g in _c["gap_examples"][:5]:
        print("   gap:", _g)
print("peak RSS MB: %.0f" % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576))
