"""Lane M7B microtest case set: runs of 2+ consecutive vector FP ops (recompile.nan_groups: one NaN test per run, re-run from a
snapshot through the per-op exact path) and chained scalar FP ops (lift_scalar's out-of-line NaN paths) on sNaN/qNaN
payloads of both signs, infinities, zeros, denormals and invalid operations: chains, accumulators, by-element, 2s/4s/2d,
register aliasing, runs whose NaN intermediates are overwritten and runs that overwrite their own inputs. Unicorn is the oracle.
Run: sbtenv/bin/python sbt/microtest.py cases_m7b (run bare, this file prints its case count)."""
###############
# imports and constants
###############
from __future__ import annotations
import itertools

S = [0x7F800001, 0xFF800005, 0x7FC00002, 0xFFC12345, 0x7FA00000, 0, 0x80000000, 0x3F800000, 0x7F800000, 0xFF800000, 1,
     0x807FFFFF, 0x7F7FFFFF, 0x00800000, 0x40490FDB, 0xBF000000]
D = [0x7FF0000000000001, 0xFFF0000000000005, 0x7FF8000000000002, 0xFFF8123456789ABC, 0, 0x8000000000000000,
     0x3FF0000000000000, 0x7FF0000000000000, 0xFFF0000000000000, 1, 0x800FFFFFFFFFFFFF, 0x7FEFFFFFFFFFFFFF]
FINITE_S = [0x3F800000, 0x40000000, 0xBF000000, 0x40490FDB, 0x00800000, 0x807FFFFF, 0, 0x80000000]
GARBAGE = {i: (0x0101010101010101 * (i + 1) ^ 0xA5A5A5A5A5A5A5A5, 0xC3C3C3C3C3C3C3C3 ^ (i * 0x1111111111111111)) for i in range(32)}
RUNS = {
    "chain4": "fmul v4.4s, v0.4s, v1.4s\nfadd v5.4s, v5.4s, v4.4s\nfmul v4.4s, v2.4s, v3.4s\nfadd v6.4s, v6.4s, v4.4s",
    "dead_nan": "fmul v4.4s, v0.4s, v1.4s\nfadd v5.4s, v4.4s, v2.4s\nfmul v4.4s, v3.4s, v3.4s\nfsub v5.4s, v3.4s, v3.4s",
    "self_inputs": "fadd v0.4s, v0.4s, v1.4s\nfmul v1.4s, v0.4s, v2.4s\nfadd v0.4s, v1.4s, v0.4s\nfdiv v2.4s, v0.4s, v1.4s",
    "fma_acc": "fmla v5.4s, v0.4s, v1.4s\nfmla v5.4s, v2.4s, v3.4s\nfmls v6.4s, v5.4s, v0.4s",
    "by_elem": "fmul v4.4s, v0.4s, v1.s[2]\nfmla v5.4s, v4.4s, v2.s[0]\nfmls v4.4s, v3.4s, v5.s[3]",
    "half_2s": "fadd v4.2s, v0.2s, v1.2s\nfmul v5.2s, v4.2s, v2.2s\nfdiv v4.2s, v5.2s, v3.2s",
    "mixed_2d": "fadd v4.2d, v0.2d, v1.2d\nfmul v5.2d, v4.2d, v2.2d\nfsub v4.2d, v5.2d, v3.2d\nfdiv v6.2d, v4.2d, v0.2d",
    "alias_all": "fadd v1.4s, v1.4s, v1.4s\nfmul v1.4s, v1.4s, v1.4s\nfsub v1.4s, v1.4s, v1.4s",
    "mix_widths": "fadd v4.4s, v0.4s, v1.4s\nfadd v5.2d, v2.2d, v3.2d\nfmul v6.2s, v4.2s, v0.2s",
}
CROSS = [                                                              # a NaN written at one width, read at the other, then overwritten
    ("cross 4s->2d", "fmul v4.4s, v0.4s, v1.4s\nfmul v4.2d, v4.2d, v2.2d",
     {0: (0, 0), 1: (0x3F8000007F800000, 0x3F8000007F800000), 2: (0x4630000000000000, 0x4630000000000000)}),
    ("cross 2d->4s elem", "fmul v4.2d, v0.2d, v1.2d\nfmul v5.4s, v2.4s, v4.s[0]\nfsub v4.4s, v2.4s, v2.4s",
     {0: (0x7FF800003F800000, 0), 1: (0x7FF0000040000000, 0), 2: (0x3F8000003F800000, 0x3F8000003F800000)}),
    ("cross 2d->4s elem swapped", "fmul v4.2d, v1.2d, v0.2d\nfmul v5.4s, v2.4s, v4.s[0]\nfsub v4.4s, v2.4s, v2.4s",
     {0: (0x7FF800003F800000, 0), 1: (0x7FF0000040000000, 0), 2: (0x3F8000003F800000, 0x3F8000003F800000)}),
]

###############
# functions
###############
def pack(vals: list[int], bits: int) -> tuple[int, int]:
    """Lane values (lane 0 first) -> (lo, hi) halves of a V register."""
    q = sum((v & ((1 << bits) - 1)) << (i * bits) for i, v in enumerate(vals))
    return q & (2 ** 64 - 1), q >> 64

def lanes(vals: list[int], start: int, n: int) -> list[int]:
    """n consecutive values from a cyclic list."""
    return [vals[(start + j) % len(vals)] for j in range(n)]

def vregs(vals: list[int], bits: int, k: int) -> dict:
    """V0-V6 from a rotated sweep of vals (bits-wide lanes), every other V register garbage."""
    n = 128 // bits
    return {**GARBAGE, **{r: pack(lanes(vals, (2 * r + 1) * k + r, n), bits) for r in range(7)}}

def scalar_cases() -> list[dict]:
    """Scalar s/d FP arith cases over the special-value sweeps, each op twice so the first result feeds the second."""
    out = []
    two = ["fadd", "fsub", "fmul", "fdiv"]
    three = ["fmadd", "fmsub", "fnmadd", "fnmsub"]
    for (w, vals, bits), k in itertools.product((("s", S, 32), ("d", D, 64)), range(0, 16, 3)):
        for op in two:
            asm = "%s %s4, %s0, %s1\n%s %s4, %s4, %s2\nret" % (op, w, w, w, op, w, w, w)
            out.append({"name": "%s %s r%d" % (op, w, k), "asm": asm, "v": True, "vregs": vregs(vals, bits, k)})
        for op in three:
            asm = "%s %s4, %s0, %s1, %s2\n%s %s5, %s4, %s3, %s4\nret" % (op, w, w, w, w, op, w, w, w, w)
            out.append({"name": "%s %s r%d" % (op, w, k), "asm": asm, "v": True, "vregs": vregs(vals, bits, k)})
        for op in ("fsqrt", "frinta", "frintm", "frintp"):
            asm = "%s %s4, %s0\n%s %s5, %s1\n%s %s6, %s4\nret" % (op, w, w, op, w, w, op, w, w)
            out.append({"name": "%s %s r%d" % (op, w, k), "asm": asm, "v": True, "vregs": vregs(vals, bits, k)})
        other = "d" if w == "s" else "s"
        asm = "fcvt %s4, %s0\nfcvt %s5, %s1\nfcvt %s6, %s4\nret" % (other, w, other, w, w, other)
        out.append({"name": "fcvt %s<-%s r%d" % (other, w, k), "asm": asm, "v": True, "vregs": vregs(vals, bits, k)})
    return out

def run_cases() -> list[dict]:
    """Every run x a sweep of special-value inputs, plus all-finite inputs (the fast path only)."""
    out = []
    for (name, asm), k in itertools.product(RUNS.items(), range(0, 16, 3)):
        bits = 64 if "2d" in name else 32
        out.append({"name": "%s r%d" % (name, k), "asm": asm + "\nret", "v": True, "vregs": vregs(D if bits == 64 else S, bits, k)})
    for name, asm in RUNS.items():
        if "2d" not in name:
            out.append({"name": "%s finite" % name, "asm": asm + "\nret", "v": True, "vregs": vregs(FINITE_S, 32, 1)})
    return out + [{"name": name, "asm": asm + "\nret", "v": True, "vregs": {**GARBAGE, **v}} for name, asm, v in CROSS]

###############
# cases
###############
CASES = run_cases() + scalar_cases()
print("cases_m7b: %d cases" % len(CASES))
