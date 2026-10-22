"""Lane M5A Unicorn-differential case set for compare fusion (recompile.flag_capture / fuse_reader): every compare-like
setter form followed by csets of all 14 conditions (x2..x15), branch readers, a setter overwriting its own source, and
fcmp with NaN / infinities / signed zeros; NZCV compared too. Run via: microtest.py cases_m5a_fuse"""
###############
# imports and constants
###############
from __future__ import annotations
import random, struct

SEED = 0x5A5A
CONDS = ["eq", "ne", "hs", "lo", "mi", "pl", "vs", "vc", "hi", "ls", "ge", "lt", "gt", "le"]
M64 = 2 ** 64 - 1
INT_PAIRS = [(0, 0), (1, 0), (0, 1), (5, 5), (M64, M64), (M64, 1), (1, M64), (2 ** 63, 1), (2 ** 63 - 1, M64),
             (2 ** 63, 2 ** 63 - 1), (0xDEADBEEF00000000 | 0x7FFFFFFF, 0x12345678FFFFFFFF), (0xAAAAAAAA80000000, 0x5555555500000001)]
INT_FORMS = ["cmp x0, x1", "cmp w0, w1", "cmp x0, #0", "cmp w0, #4095", "cmp x0, x1, lsl #3", "cmp x0, w1, sxtw",
             "cmn x0, x1", "cmn w0, w1", "cmn x0, #1", "tst x0, x1", "tst w0, #0xff", "tst x0, #0x8000000000000000",
             "subs x16, x0, x1", "subs w16, w0, w1", "adds x16, x0, x1", "ands x16, x0, x1", "negs x16, x1",
             "subs x0, x0, x1", "ands w1, w1, w0"]
FP_PAIRS = [(1.0, 2.0), (2.0, 1.0), (1.0, 1.0), (float("nan"), 1.0), (1.0, float("nan")), (float("inf"), float("inf")),
            (-0.0, 0.0), (float("-inf"), 1.0)]
FP_FORMS = ["fcmp d0, d1", "fcmpe d0, d1", "fcmp s0, s1", "fcmp d0, #0.0"]
BRANCH = "{s}\nb.{c} 1f\nmov x2, #7\n1:\nret"

###############
# cases
###############
def csets(setter: str) -> str:
    """The setter, then cset of every condition into x2..x15, then ret."""
    return "\n".join([setter] + ["cset x%d, %s" % (2 + k, c) for k, c in enumerate(CONDS)] + ["ret"])

def int_cases(rng: random.Random) -> list[dict]:
    """Every integer form over the edge pairs and a few random ones (flags compared)."""
    pairs = INT_PAIRS + [(rng.getrandbits(64), rng.getrandbits(64)) for _ in range(4)]
    return [{"name": "%s #%d" % (f, k), "asm": csets(f), "regs": {0: a, 1: b}, "flags": True}
            for f in INT_FORMS for k, (a, b) in enumerate(pairs)]

def fp_bits(x: float, single: bool) -> int:
    """IEEE bits of x as a 32- or 64-bit value."""
    return struct.unpack("<I", struct.pack("<f", x))[0] if single else struct.unpack("<Q", struct.pack("<d", x))[0]

def fp_cases() -> list[dict]:
    """fcmp forms over ordered, unordered, infinite and signed-zero pairs (flags compared)."""
    return [{"name": "%s #%d" % (f, k), "asm": csets(f), "regs": {}, "flags": True, "v": True,
             "vregs": {0: (fp_bits(a, " s0" in f), 0), 1: (fp_bits(b, " s0" in f), 0)}}
            for f in FP_FORMS for k, (a, b) in enumerate(FP_PAIRS)]

def branch_cases() -> list[dict]:
    """b.cond readers of cmp and fcmp (the taken branch skips the mov)."""
    ints = [{"name": "cmp+b.%s #%d" % (c, k), "asm": BRANCH.format(s="cmp x0, x1", c=c), "regs": {0: a, 1: b, 2: 0}, "flags": True}
            for c in CONDS for k, (a, b) in enumerate(INT_PAIRS[:6])]
    fps = [{"name": "fcmp+b.%s #%d" % (c, k), "asm": BRANCH.format(s="fcmp d0, d1", c=c), "regs": {2: 0}, "flags": True, "v": True,
            "vregs": {0: (fp_bits(a, False), 0), 1: (fp_bits(b, False), 0)}} for c in CONDS for k, (a, b) in enumerate(FP_PAIRS[:5])]
    return ints + fps

###############
# run
###############
CASES = int_cases(random.Random(SEED)) + fp_cases() + branch_cases()
print("cases_m5a_fuse: %d cases" % len(CASES))
