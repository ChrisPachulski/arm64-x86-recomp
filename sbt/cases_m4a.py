"""Lane M4a Unicorn-differential case set: vector RBIT (.8b / .16b, distinct and aliased registers), the form the main
binary's GHASH code uses (rbit v8.16b, v8.16b at 0x101e09efc). Run via: microtest.py cases_m4a"""
###############
# imports and constants
###############
from __future__ import annotations
import random

SEED = 0x4A4A
EDGE = [(0, 0), (2 ** 64 - 1, 2 ** 64 - 1), (0x0102040810204080, 0x8040201008040201), (0x8000000000000001, 0x00FF00FF00FF00FF)]

###############
# cases
###############
def rbit_cases(rng: random.Random) -> list[dict]:
    """rbit for both arrangements over random and edge contents of v0..v2."""
    sets = [{r: (rng.getrandbits(64), rng.getrandbits(64)) for r in (0, 1, 2)} for _ in range(4)]
    sets += [{0: e, 1: EDGE[(k + 1) % len(EDGE)], 2: EDGE[(k + 2) % len(EDGE)]} for k, e in enumerate(EDGE)]
    forms = ["rbit v0.16b, v1.16b", "rbit v0.8b, v1.8b", "rbit v2.16b, v2.16b", "rbit v2.8b, v2.8b"]
    return [{"name": "%s #%d" % (f, k), "asm": f + "\nret", "vregs": vs, "regs": {}, "v": True} for f in forms for k, vs in enumerate(sets)]

###############
# run
###############
CASES = rbit_cases(random.Random(SEED))
print("cases_m4a: %d cases" % len(CASES))
