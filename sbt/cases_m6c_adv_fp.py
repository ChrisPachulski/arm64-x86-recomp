"""Lane M6C adversarial microtest case set: vector fadd/fsub/fmul/fdiv/fmla/fmls (4s, 2s with NaN garbage in the unused
upper lanes, 2d, by-element, register aliasing) on sNaN/qNaN payloads of both signs, infinities, signed zeros, denormals
and invalid operations, so every NaN lane takes the lane's out-of-line n_fixv path. Unicorn is the oracle.
Run: sbtenv/bin/python sbt/microtest.py cases_m6c_adv_fp (run bare, this file prints its case count)."""
###############
# imports and constants
###############
from __future__ import annotations
import itertools

S = [0x7F800001, 0xFF800005, 0x7FC00002, 0xFFC12345, 0x7FA00000, 0, 0x80000000, 0x3F800000, 0x7F800000, 0xFF800000, 1,
     0x807FFFFF, 0x7F7FFFFF, 0x00800000, 0x40490FDB, 0xBF000000]
D = [0x7FF0000000000001, 0xFFF0000000000005, 0x7FF8000000000002, 0xFFF8123456789ABC, 0, 0x8000000000000000,
     0x3FF0000000000000, 0x7FF0000000000000, 0xFFF0000000000000, 1, 0x800FFFFFFFFFFFFF, 0x7FEFFFFFFFFFFFFF]
OPS = ["fadd", "fsub", "fmul", "fdiv", "fmla", "fmls"]
GARBAGE = {i: (0x0101010101010101 * (i + 1) ^ 0xA5A5A5A5A5A5A5A5, 0xC3C3C3C3C3C3C3C3 ^ (i * 0x1111111111111111)) for i in range(32)}
UPPER_SNAN = 0x7F8000097F80000A                                        # unused upper lanes of a 2s source: two sNaNs

###############
# functions
###############
def pack(vals: list[int], bits: int) -> tuple[int, int]:
    """Lane values (lane 0 first) -> (lo, hi) halves of a V register."""
    q = sum((v & ((1 << bits) - 1)) << (i * bits) for i, v in enumerate(vals))
    return q & (2 ** 64 - 1), q >> 64

def vstate(**regs: tuple[int, int]) -> dict:
    """Every V register garbage except the named ones (v0=..., v1=...)."""
    return {**GARBAGE, **{int(k[1:]): v for k, v in regs.items()}}

def lanes(vals: list[int], start: int, n: int) -> list[int]:
    """n consecutive values from a cyclic list."""
    return [vals[(start + j) % len(vals)] for j in range(n)]

def op_cases() -> list[dict]:
    """Every op x arrangement x a sweep of rotated input lanes."""
    out = []
    for op, k in itertools.product(OPS, range(0, len(S), 2)):
        a, b, d = lanes(S, k, 4), lanes(S, 3 * k + 1, 4), lanes(S, 5 * k + 2, 4)
        out.append({"name": "%s 4s r%d" % (op, k), "asm": "%s v2.4s, v0.4s, v1.4s\nret" % op, "v": True,
                    "vregs": vstate(v0=pack(a, 32), v1=pack(b, 32), v2=pack(d, 32))})
        lo = lambda v: (pack(v[:2], 32)[0], UPPER_SNAN)
        out.append({"name": "%s 2s r%d" % (op, k), "asm": "%s v2.2s, v0.2s, v1.2s\nret" % op, "v": True,
                    "vregs": vstate(v0=lo(a), v1=lo(b), v2=lo(d))})
        out.append({"name": "%s 4s[%d] r%d" % (op, k % 4, k), "asm": "%s v2.4s, v0.4s, v1.s[%d]\nret" % (op, k % 4) if op in ("fmul", "fmla", "fmls")
                    else "%s v2.4s, v0.4s, v0.4s\nret" % op, "v": True, "vregs": vstate(v0=pack(a, 32), v1=pack(b, 32), v2=pack(d, 32))})
    for op, k in itertools.product(OPS, range(0, len(D), 2)):
        a, b, d = lanes(D, k, 2), lanes(D, 3 * k + 1, 2), lanes(D, 5 * k + 2, 2)
        out.append({"name": "%s 2d r%d" % (op, k), "asm": "%s v2.2d, v0.2d, v1.2d\nret" % op, "v": True,
                    "vregs": vstate(v0=pack(a, 64), v1=pack(b, 64), v2=pack(d, 64))})
        out.append({"name": "%s 2d alias r%d" % (op, k), "asm": "%s v1.2d, v1.2d, v1.2d\nret" % op, "v": True,
                    "vregs": vstate(v1=pack(a, 64))})
    return out

###############
# cases
###############
CASES = op_cases()
print("cases_m6c_adv_fp: %d cases" % len(CASES))
