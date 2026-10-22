"""Adversarial Unicorn case set against lane M5A's lifter changes: compare fusion across joins and loop back-edges,
ccmp/adc readers after fused setters, NaN-payload fast paths (scalar and vector fadd/fsub/fmul/fdiv/fmla/fmls, by-element
forms, sNaN in each operand position, invalid operations) and the whole-vector integer, widening and narrowing paths at
lane edges. Run via: microtest.py cases_m5a_adv1."""
###############
# imports and constants
###############
from __future__ import annotations
import random

SEED = 0x5A5A
QNAN_S, SNAN_S, INF_S, NINF_S = 0x7FC0_1234, 0x7F80_0567, 0x7F80_0000, 0xFF80_0000   # single-precision bit patterns
QNAN_D, SNAN_D, INF_D = 0x7FF8_0000_0000_0ABC, 0xFFF0_0000_0000_0DEF, 0x7FF0_0000_0000_0000
ONE_S, ZERO_S, NZERO_S, TWO_S = 0x3F80_0000, 0, 0x8000_0000, 0x4000_0000
ONE_D, ZERO_D, TWO_D = 0x3FF0_0000_0000_0000, 0, 0x4000_0000_0000_0000
FUSE_JOIN = [
    ("join two setters", "cbz x2, 1f\ncmp x0, x1\nb 2f\n1:\ncmn x0, x1\n2:\ncset x3, eq\ncset x4, hi\ncset x5, lt\nret"),
    ("back-edge reader", "mov x3, #0\nmov x4, #0\ncmp x4, x0\n1:\nb.ge 2f\nadd x3, x3, x4\nadd x4, x4, #1\ncmp x4, x0\nb 1b\n2:\ncset x5, eq\nret"),
    ("reader then setter at join", "subs x3, x0, x1\nb.lo 1f\ntst x0, #1\n1:\ncsel x4, x0, x1, ne\ncset x5, mi\nret"),
    ("ccmp after fused cmp", "cmp x0, x1\nccmp x0, #5, #4, ne\ncset x3, eq\ncset x4, gt\nret"),
    ("adc after fused cmp", "cmp x0, x1\nadc x3, x0, x1\ncset x4, hs\nret"),
    ("fused cmp, branch, fall-through", "cmp w0, w1\nb.eq 1f\ncset x3, gt\n1:\ncset x4, le\nret"),
    ("setter clobbers source", "subs x0, x0, x1\ncset x3, hi\ncset x4, ge\nsubs w1, w1, w0\ncset x5, lo\nret"),
    ("negs then loop", "mov x3, #0\n1:\nnegs x4, x0\ncinc x3, x3, mi\nsub x0, x0, #1\ncmp x0, x1\nb.gt 1b\ncset x5, eq\nret"),
    ("fcmp join", "fcmp d0, d1\nb.vs 1f\nfcmp d1, d0\n1:\ncset x3, gt\ncset x4, vs\nfcsel d2, d0, d1, mi\nret")]
INT_PAIRS = [(0, 0), (5, 9), (9, 5), (2 ** 63, 1), (2 ** 64 - 1, 1), (7, 2 ** 64 - 7)]
LOOP_PAIRS = [(0, 0), (5, 9), (9, 5), (2 ** 64 - 1, 1), (7, 2 ** 64 - 7)]   # loops end within 20 turns (2^63 - 1 down to 1 would not)
FP_PAIRS = [(ONE_D, TWO_D), (TWO_D, ONE_D), (QNAN_D, ONE_D), (ONE_D, SNAN_D), (INF_D, INF_D)]
SCALAR_FP = ["fadd {r}2, {r}0, {r}1", "fsub {r}2, {r}0, {r}1", "fmul {r}2, {r}0, {r}1", "fdiv {r}2, {r}0, {r}1",
             "fmadd {r}2, {r}0, {r}1, {r}3", "fmsub {r}2, {r}0, {r}1, {r}3", "fnmadd {r}2, {r}0, {r}1, {r}3",
             "fadd {r}0, {r}0, {r}1", "fmul {r}1, {r}0, {r}1"]
VEC_FP = ["fadd v2.{a}, v0.{a}, v1.{a}", "fsub v2.{a}, v0.{a}, v1.{a}", "fmul v2.{a}, v0.{a}, v1.{a}", "fdiv v2.{a}, v0.{a}, v1.{a}",
          "fmla v3.{a}, v0.{a}, v1.{a}", "fmls v3.{a}, v0.{a}, v1.{a}", "fmla v3.{a}, v0.{a}, v1.{e}[1]", "fmul v2.{a}, v0.{a}, v1.{e}[0]",
          "fadd v0.{a}, v0.{a}, v0.{a}", "fmla v0.{a}, v0.{a}, v1.{a}"]
VEC_INT = ["shl v2.16b, v0.16b, #7", "ushr v2.8h, v0.8h, #16", "ushr v2.4s, v0.4s, #32", "ushr v2.2d, v0.2d, #64", "shl v2.2d, v0.2d, #63",
           "xtn v2.8b, v0.8h", "xtn2 v2.16b, v0.8h", "shrn v2.4h, v0.4s, #16", "rshrn v2.8b, v0.8h, #8", "rshrn2 v2.4s, v0.2d, #32",
           "smull v2.8h, v0.8b, v1.8b", "umull2 v2.4s, v0.8h, v1.8h", "smlal v3.2d, v0.2s, v1.2s", "smlsl2 v3.4s, v0.8h, v1.h[7]",
           "sshll v2.4s, v0.4h, #15", "ushll2 v2.2d, v0.4s, #0", "saddw2 v2.8h, v1.8h, v0.16b", "ssubl v2.2d, v0.2s, v1.2s",
           "mul v2.8h, v0.8h, v1.8h", "bic v2.16b, v0.16b, v1.16b", "orn v2.8b, v0.8b, v1.8b", "sub v2.2d, v0.2d, v1.2d"]

###############
# cases
###############
def fuse_cases() -> list[dict]:
    """Every join snippet over the integer pairs (x2 picks the path) or the double pairs (flags compared)."""
    out = []
    for name, asm in FUSE_JOIN:
        if "fcmp" in asm:
            out += [{"name": "%s #%d" % (name, k), "asm": asm, "regs": {}, "flags": True, "v": True, "vregs": {0: (a, 0), 1: (b, 0)}}
                    for k, (a, b) in enumerate(FP_PAIRS)]
        else:
            out += [{"name": "%s #%d.%d" % (name, k, p), "asm": asm, "regs": {0: a, 1: b, 2: p}, "flags": True}
                    for k, (a, b) in enumerate(LOOP_PAIRS if "loop" in name or "back-edge" in name else INT_PAIRS) for p in (0, 1)]
    return out

def scalar_fp_cases() -> list[dict]:
    """Scalar float/double arithmetic with NaN payloads, sNaN and invalid operations in each operand position."""
    singles = [(QNAN_S, ONE_S, TWO_S), (ONE_S, SNAN_S, TWO_S), (QNAN_S, SNAN_S, ONE_S), (INF_S, NINF_S, ONE_S), (ZERO_S, INF_S, QNAN_S),
               (ONE_S, TWO_S, SNAN_S), (NZERO_S, ZERO_S, NZERO_S)]
    doubles = [(QNAN_D, ONE_D, TWO_D), (ONE_D, SNAN_D, TWO_D), (QNAN_D, SNAN_D, ONE_D), (INF_D, INF_D | 2 ** 63, ONE_D),
               (ZERO_D, INF_D, QNAN_D), (ONE_D, TWO_D, SNAN_D)]
    out = []
    for f in SCALAR_FP:
        out += [{"name": "%s s#%d" % (f.split()[0], k), "asm": f.format(r="s") + "\nret", "regs": {}, "v": True,
                 "vregs": {0: (a, 0), 1: (b, 0), 3: (c, 0)}} for k, (a, b, c) in enumerate(singles)]
        out += [{"name": "%s d#%d" % (f.split()[0], k), "asm": f.format(r="d") + "\nret", "regs": {}, "v": True,
                 "vregs": {0: (a, 0), 1: (b, 0), 3: (c, 0)}} for k, (a, b, c) in enumerate(doubles)]
    return out

def lanes(vals: list[int], bits: int) -> tuple[int, int]:
    """(lo, hi) 64-bit halves of a 128-bit register holding vals in lanes of `bits`."""
    q = sum(v << (bits * i) for i, v in enumerate(vals))
    return q & (2 ** 64 - 1), q >> 64

def vec_fp_cases() -> list[dict]:
    """Vector FP fast paths: one NaN lane, all-number lanes, sNaN lanes, invalid lanes, 4s/2s/2d and by-element."""
    s_sets = [([ONE_S, TWO_S, ONE_S, TWO_S], [TWO_S, TWO_S, ONE_S, ONE_S], [ONE_S] * 4),
              ([QNAN_S, ONE_S, SNAN_S, INF_S], [ONE_S, SNAN_S, TWO_S, NINF_S], [TWO_S, QNAN_S, ONE_S, ONE_S]),
              ([ZERO_S, INF_S, ONE_S, NZERO_S], [INF_S, ZERO_S, ZERO_S, ZERO_S], [SNAN_S, ONE_S, QNAN_S, NZERO_S]),
              ([ONE_S, ONE_S, QNAN_S, SNAN_S], [ONE_S, ONE_S, ONE_S, ONE_S], [ONE_S, ONE_S, ONE_S, ONE_S])]
    d_sets = [([ONE_D, TWO_D], [TWO_D, ONE_D], [ONE_D, ONE_D]), ([QNAN_D, ONE_D], [ONE_D, SNAN_D], [TWO_D, QNAN_D]),
              ([INF_D, ZERO_D], [INF_D | 2 ** 63, INF_D], [ONE_D, SNAN_D])]
    out = []
    for f in VEC_FP:
        for arr, e, bits, sets in (("4s", "s", 32, s_sets), ("2s", "s", 32, s_sets), ("2d", "d", 64, d_sets)):
            out += [{"name": "%s %s #%d" % (f.split()[0], arr, k), "asm": f.format(a=arr, e=e) + "\nret", "regs": {}, "v": True,
                     "vregs": {0: lanes(a, bits), 1: lanes(b, bits), 3: lanes(c, bits), 2: (0xDEAD, 0xBEEF)}}
                    for k, (a, b, c) in enumerate(sets)]
    return out

def vec_int_cases(rng: random.Random) -> list[dict]:
    """Whole-vector integer, widening and narrowing forms over edge lanes and random registers."""
    edge = [(lanes([0xFFFF, 0x8000, 0x7FFF, 0x0080, 0xFF7F, 1, 0, 0x8080], 16), lanes([0x8000, 0xFFFF, 2, 0x7F, 0x80, 0xFFFE, 3, 0x7FFF], 16)),
            (lanes([0xFFFFFFFF, 0x80000000, 0x7FFFFFFF, 0x8000], 32), lanes([0x80000000, 0xFFFFFFFF, 0xFFFF, 2], 32))]
    rand = [((rng.getrandbits(64), rng.getrandbits(64)), (rng.getrandbits(64), rng.getrandbits(64))) for _ in range(3)]
    return [{"name": "%s #%d" % (f.split()[0], k), "asm": f + "\nret", "regs": {}, "v": True,
             "vregs": {0: a, 1: b, 2: (0x1111111111111111, 0x2222222222222222), 3: (0x3333333333333333, 0x4444444444444444)}}
            for f in VEC_INT for k, (a, b) in enumerate(edge + rand)]

###############
# run
###############
CASES = fuse_cases() + scalar_fp_cases() + vec_fp_cases() + vec_int_cases(random.Random(SEED))
print("cases_m5a_adv1: %d cases" % len(CASES))
