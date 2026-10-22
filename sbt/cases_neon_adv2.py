"""Second independent adversarial differential case set (vs Unicorn) for lift_neon.py.
Run: sbtenv/bin/python sbt/microtest.py cases_neon_adv2. Every V register starts as distinct garbage so
missed upper-half zeroing, lane clobbering and aliasing show up; NaN payloads, signed zero, denormals,
ties, saturation, integer extremes, wzr/xzr, 32-bit GPR zeroing, post-index writeback and narrow widths."""
###############
# imports and constants
###############
from __future__ import annotations
import random, struct

DATA = 0x240000000
MEM = bytes((i * 29 + 7) & 0xFF for i in range(512))                  # load/store scratch pattern
GX = 0xFEEDFACECAFEBEEF                                                # garbage preload for GPR destinations
INF, NINF = float("inf"), float("-inf")
SNAN32, SNAN32B = 0x7FA12345, 0xFF800ABC                               # signalling, nonzero payloads
QNAN32, QNAN32B = 0xFFC0BEEF, 0x7FC0DEAD
SNAN64, QNAN64, QNAN64B = 0x7FF4000000001234, 0xFFF800000000ABCD, 0x7FF80000DEAD0000
DEN32, NDEN32, DEN32MAX, MIN32 = 0x00000001, 0x80000001, 0x007FFFFF, 0x00800000  # f32 bit patterns
DEN64 = 0x0000000000000001
SPECIAL32 = [0.0, -0.0, 1.0, -1.0, INF, NINF, SNAN32, SNAN32B, QNAN32, QNAN32B, DEN32, DEN32MAX, NDEN32, MIN32,
             3.4028234663852886e38, 0.5, -0.5, 1.5, 2.5, -2.5, 65504.0, 65520.0, 2.0 ** -24, 2.0 ** -25, 2.0 ** -14,
             3e9, -3e9, 4294967296.0, 2147483648.0, -2147483648.0, 1e-40, 16777217.0]
SPECIAL64 = [0.0, -0.0, 1.0, -1.0, INF, NINF, SNAN64, QNAN64, QNAN64B, DEN64, 0x000FFFFFFFFFFFFF, 0x0010000000000000,
             1.7976931348623157e308, 0.5, -2.5, 3.4028235677973366e38, 1e-45, 1.401298464324817e-45 / 2,
             9.223372036854775807e18, -9.223372036854775808e18, 1.8446744073709552e19, 1.0 + 2.0 ** -24, 4503599627370495.5]
SWEEP_FORMS = [(f"{op} v0.4s, v1.4s, v2.4s", "s", 2) for op in ("fadd", "fsub", "fmul", "fdiv", "fmaxnm", "fminnm", "fabd",
                                                                 "fmla", "fmls", "faddp", "fcmeq", "fcmge", "fcmgt")] + \
              [(f"{op} v0.2d, v1.2d, v2.2d", "d", 2) for op in ("fadd", "fsub", "fmul", "fdiv", "fmaxnm", "fminnm", "fabd",
                                                                 "fmla", "fmls", "faddp", "fcmgt")] + \
              [(f"{op} v0.4s, v1.4s", "s", 1) for op in ("fsqrt", "frinta", "frintm", "frintp", "frintz", "fcvtzs", "fcvtzu")] + \
              [(f"{op} v0.2d, v1.2d", "d", 1) for op in ("fsqrt", "frinta", "frintm", "frintp", "frintz", "fcvtzs", "fcvtzu")] + \
              [("fcvtzs v0.4s, v1.4s, #7", "s", 1), ("fcvtzu v0.2d, v1.2d, #40", "d", 1), ("fcvtn v0.4h, v1.4s", "s", 1),
               ("fcvtn2 v0.4s, v1.2d", "d", 1), ("fcvtl v0.2d, v1.2s", "s", 1), ("fmla v0.4s, v1.4s, v2.s[2]", "s", 2),
               ("fmls v0.2d, v1.2d, v2.d[1]", "d", 2), ("scvtf v0.4s, v1.4s", "i", 1), ("ucvtf v0.4s, v1.4s, #5", "i", 1),
               ("scvtf v0.2d, v1.2d, #12", "i", 1), ("ucvtf v0.2d, v1.2d", "i", 1), ("sdot v0.4s, v1.16b, v2.16b", "i", 2),
               ("rshrn v0.8b, v1.8h, #3", "i", 1), ("sshl v0.8h, v1.8h, v2.8h", "i", 2), ("ushl v0.2d, v1.2d, v2.2d", "i", 2),
               ("tbx v0.16b, {v1.16b, v2.16b}, v2.16b", "i", 2), ("smull2 v0.2d, v1.4s, v2.4s", "i", 2)]

###############
# packing helpers
###############
def lanes(vals: list[int], e: int) -> tuple[int, int]:
    """Pack e-bit lane values (lane 0 first) into a (lo, hi) Q register."""
    q = 0
    for k, v in enumerate(vals):
        q |= (v & ((1 << e) - 1)) << (k * e)
    return (q & 0xFFFFFFFFFFFFFFFF, q >> 64)

def f32(x: float | int) -> int:
    """f32 bit pattern; ints pass through as raw bits."""
    return x if isinstance(x, int) else struct.unpack("<I", struct.pack("<f", x))[0]

def f64(x: float | int) -> int:
    """f64 bit pattern; ints pass through as raw bits."""
    return x if isinstance(x, int) else struct.unpack("<Q", struct.pack("<d", x))[0]

def vf32(vals: list[float | int]) -> tuple[int, int]:
    return lanes([f32(v) for v in vals], 32)

def vf64(vals: list[float | int]) -> tuple[int, int]:
    return lanes([f64(v) for v in vals], 64)

def garbage() -> dict:
    """Distinct nonzero contents for all 32 V registers."""
    return {i: (0xDEADBEEFCAFEF00D ^ (i * 0x0101010101010101), 0x0123456789ABCDEF ^ (i << 56)) for i in range(32)}

def c(name: str, asm: str, vregs: dict | None = None, regs: dict | None = None, mem: bytes | None = None) -> dict:
    """One case: asm lines joined, ret appended, V state compared, garbage under the given vregs."""
    case = {"name": name, "asm": asm.replace(";", "\n") + "\nret", "vregs": {**garbage(), **(vregs or {})},
            "regs": regs or {}, "v": True}
    if mem is not None: case["mem"] = mem
    return case

def pick32(r: random.Random) -> int:
    """f32 bits: a special value, a value near the f16 range, or raw random bits."""
    k = r.random()
    if k < 0.45: return f32(r.choice(SPECIAL32))
    if k < 0.75: return (r.getrandbits(1) << 31) | (r.randint(98, 146) << 23) | r.getrandbits(23)
    return r.getrandbits(32)

def pick64(r: random.Random) -> int:
    """f64 bits: a special value, a value near the f32/int64 ranges, or raw random bits."""
    k = r.random()
    if k < 0.45: return f64(r.choice(SPECIAL64))
    if k < 0.75: return (r.getrandbits(1) << 63) | (r.choice([r.randint(870, 1152), r.randint(1050, 1090)]) << 52) | r.getrandbits(52)
    return r.getrandbits(64)

def sweep(seed: int, reps: int) -> list[dict]:
    """Seeded random lanes through every FP and conversion form, reps cases per form."""
    r = random.Random(seed)
    out = []
    for asm, kind, nsrc in SWEEP_FORMS:
        for k in range(reps):
            regs = {}
            for s in range(nsrc + 1):                                  # v0 (accumulator) + sources v1..
                if kind == "s": regs[s] = lanes([pick32(r) for _ in range(4)], 32)
                elif kind == "d": regs[s] = lanes([pick64(r) for _ in range(2)], 64)
                else: regs[s] = (r.getrandbits(64), r.getrandbits(64))
            out.append(c("sw %s #%d" % (asm.split(",")[0].replace(" v0.", "."), k), asm, regs))
    return out

B16 = lanes([0x80, 0x7F, 0xFF, 0x00, 0x01, 0xFE, 0x81, 0x40, 0x55, 0xAA, 0x0F, 0xF0, 0x7E, 0x02, 0x80, 0xC3], 8)
B16B = lanes([0x80, 0x80, 0x01, 0xFF, 0x00, 0x7F, 0x7F, 0x40, 0xAA, 0x55, 0xF0, 0x0F, 0x81, 0xFE, 0x7F, 0x3C], 8)
H8 = lanes([0x8000, 0x7FFF, 0xFFFF, 0, 1, 0x8001, 0x4000, 0xC000], 16)
H8B = lanes([0x8000, 0x8000, 0x0001, 0xFFFF, 0x7FFF, 0xFFFF, 0x4000, 0x4000], 16)
S4 = lanes([0x80000000, 0x7FFFFFFF, 0xFFFFFFFF, 0], 32)
S4B = lanes([0xFFFFFFFF, 0x80000000, 0x7FFFFFFF, 0x80000001], 32)
D2 = lanes([0x8000000000000000, 0xFFFFFFFFFFFFFFFF], 64)
D2B = lanes([0xFFFFFFFFFFFFFFFF, 0x7FFFFFFFFFFFFFFF], 64)
SH8 = lanes([0x07, 0xF9, 0x08, 0xF8, 0x80, 0x7F, 0x00, 0xFF, 0x01, 0x40, 0xC0, 0x3F, 0xFE, 0x09, 0xF7, 0x10], 8)
SH32 = lanes([31, 0xFFFFFFE0, 0x00000020, 0x12345680], 32)              # +31, -32, +32, low byte -128
SH64 = lanes([64, 0xC0], 64)                                           # +64, low byte -64

###############
# floating point
###############
FP = [
    c("fadd 4s nan order", "fadd v0.4s, v1.4s, v2.4s", {1: vf32([SNAN32, 1.0, QNAN32, -0.0]), 2: vf32([QNAN32B, SNAN32B, SNAN32B, -0.0])}),
    c("fadd 4s inf/denorm/ovf", "fadd v0.4s, v1.4s, v2.4s", {1: vf32([INF, DEN32, DEN32MAX, 3.4e38]), 2: vf32([NINF, DEN32, DEN32, 3.4e38])}),
    c("fsub 2d -0 and inf-inf", "fsub v0.2d, v1.2d, v2.2d", {1: vf64([-0.0, INF]), 2: vf64([0.0, INF])}),
    c("fsub 2d dest==src", "fsub v1.2d, v1.2d, v1.2d", {1: vf64([NINF, -0.0])}),
    c("fmul 2s 0*inf upper", "fmul v0.2s, v1.2s, v2.2s", {1: vf32([0.0, 1e-30]), 2: vf32([NINF, -1e-30])}),
    c("fmul 2d denorm", "fmul v0.2d, v1.2d, v2.2d", {1: vf64([DEN64, 1e-200]), 2: vf64([0.5, 1e-200])}),
    c("fdiv 4s zeros", "fdiv v0.4s, v1.4s, v2.4s", {1: vf32([1.0, -1.0, 0.0, SNAN32]), 2: vf32([-0.0, 0.0, -0.0, 1.0])}),
    c("fdiv 2d inf/inf", "fdiv v0.2d, v1.2d, v2.2d", {1: vf64([INF, QNAN64]), 2: vf64([NINF, SNAN64])}),
    c("fmaxnm 4s", "fmaxnm v0.4s, v1.4s, v2.4s", {1: vf32([QNAN32, SNAN32, 0.0, -0.0]), 2: vf32([1.0, 1.0, -0.0, 0.0])}),
    c("fminnm 4s", "fminnm v0.4s, v1.4s, v2.4s", {1: vf32([QNAN32, QNAN32B, 0.0, 1.0]), 2: vf32([QNAN32B, QNAN32, -0.0, SNAN32])}),
    c("fminnm 2d", "fminnm v0.2d, v1.2d, v2.2d", {1: vf64([QNAN64, -0.0]), 2: vf64([-2.0, 0.0])}),
    c("fmaxnm 2s upper", "fmaxnm v0.2s, v1.2s, v2.2s", {1: vf32([NINF, -0.0]), 2: vf32([QNAN32, -0.0])}),
    c("fabd 4s", "fabd v0.4s, v1.4s, v2.4s", {1: vf32([QNAN32, NINF, 1.0, -0.0]), 2: vf32([1.0, NINF, 3.0, 0.0])}),
    c("fabd 2d snan", "fabd v0.2d, v1.2d, v2.2d", {1: vf64([1.0, -1e308]), 2: vf64([SNAN64 | (1 << 63), 1e308])}),
    c("fmla 4s inf*0 nan addend", "fmla v0.4s, v1.4s, v2.4s",
      {0: vf32([QNAN32, SNAN32, 1.0, QNAN32]), 1: vf32([INF, INF, SNAN32B, 0.0]), 2: vf32([0.0, 0.0, 1.0, 1.0])}),
    c("fmla 4s fused rounding", "fmla v0.4s, v1.4s, v2.4s",
      {0: vf32([-1.0, 1.0, -0.0, 0.0]), 1: vf32([1.0000001, 3.0, 0.0, -1e-30]), 2: vf32([0.9999999, 1 / 3, -0.0, 1e-30])}),
    c("fmls 2d nan sign", "fmls v0.2d, v1.2d, v2.2d", {0: vf64([1.0, 2.0]), 1: vf64([QNAN64B, 1e308]), 2: vf64([1.0, 10.0])}),
    c("fmls 2s upper", "fmls v0.2s, v1.2s, v2.2s", {0: vf32([0.0, -0.0]), 1: vf32([0.0, 0.0]), 2: vf32([1.0, 1.0])}),
    c("fmla 4s by elem s[3]", "fmla v0.4s, v1.4s, v2.s[3]", {0: vf32([1.0, 2.0, 3.0, 4.0]), 1: vf32([1.0, -1.0, INF, 0.5]), 2: vf32([9.0, 9.0, 9.0, 0.0])}),
    c("fmla 2d by elem d[1]", "fmla v0.2d, v1.2d, v2.d[1]", {0: vf64([1.0, QNAN64]), 1: vf64([2.0, 3.0]), 2: vf64([7.0, -0.5])}),
    c("fmul 4s by elem alias", "fmul v1.4s, v1.4s, v1.s[0]", {1: vf32([-2.0, 3.0, DEN32, INF])}),
    c("fmul scalar by elem", "fmul s0, s1, v2.s[3]", {1: vf32([3.0, 7.0, 7.0, 7.0]), 2: vf32([1.0, 1.0, 1.0, -0.5])}),
    c("fmla scalar d by elem", "fmla d0, d1, v2.d[1]", {0: vf64([1.0, 5.0]), 1: vf64([2.0, 9.0]), 2: vf64([9.0, 4.0])}),
    c("fsqrt 4s", "fsqrt v0.4s, v1.4s", {1: vf32([-0.0, -1.0, SNAN32, DEN32])}),
    c("fsqrt 2d", "fsqrt v0.2d, v1.2d", {1: vf64([NINF, QNAN64])}),
    c("frinta 4s ties", "frinta v0.4s, v1.4s", {1: vf32([0.5, -0.5, 2.5, -2.5])}),
    c("frinta 4s near-half", "frinta v0.4s, v1.4s", {1: vf32([0.49999997, -1.4999999, 8388609.0, -0.0])}),
    c("frintm 4s", "frintm v0.4s, v1.4s", {1: vf32([-0.5, -0.0, 0.5, SNAN32])}),
    c("frintp 4s", "frintp v0.4s, v1.4s", {1: vf32([-0.5, -1.5, DEN32, INF])}),
    c("frintz 2d", "frintz v0.2d, v1.2d", {1: vf64([-0.7, 1e300])}),
    c("frinta 2d", "frinta v0.2d, v1.2d", {1: vf64([-0.5, 4503599627370495.5])}),
    c("frintm 2s upper", "frintm v0.2s, v1.2s", {1: vf32([NDEN32, 1.5])}),
    c("fcvtzs 4s sat", "fcvtzs v0.4s, v1.4s", {1: vf32([QNAN32, 3e9, -3e9, -0.9])}),
    c("fcvtzu 4s sat", "fcvtzu v0.4s, v1.4s", {1: vf32([-1.0, 5e9, 4294967040.0, INF])}),
    c("fcvtzs 2d sat", "fcvtzs v0.2d, v1.2d", {1: vf64([9.3e18, NINF])}),
    c("fcvtzs 2d edge", "fcvtzs v0.2d, v1.2d", {1: vf64([-9223372036854775808.0, 9223372036854774784.0])}),
    c("fcvtzu 2d sat", "fcvtzu v0.2d, v1.2d", {1: vf64([1.9e19, -0.0])}),
    c("fcvtzu 2d big", "fcvtzu v0.2d, v1.2d", {1: vf64([18446744073709549568.0, SNAN64])}),
    c("fcvtzs 4s fixed16", "fcvtzs v0.4s, v1.4s, #16", {1: vf32([32768.0, -32768.0, 1.5e-5, -0.00001])}),
    c("fcvtzs 4s fixed32", "fcvtzs v0.4s, v1.4s, #32", {1: vf32([0.5, -0.5, DEN32MAX, -1.0])}),
    c("fcvtzu 2d fixed64", "fcvtzu v0.2d, v1.2d, #64", {1: vf64([0.5, 1.0])}),
    c("fcvtzs 2s upper", "fcvtzs v0.2s, v1.2s", {1: vf32([2.9, -2.9])}),
    c("fcvtzu 2s fixed", "fcvtzu v0.2s, v1.2s, #3", {1: vf32([0.124, 536870911.9])}),
    c("scvtf 4s", "scvtf v0.4s, v1.4s", {1: lanes([0x80000000, 0x7FFFFFFF, 16777217, 0xFFFFFFFF], 32)}),
    c("scvtf 4s ties", "scvtf v0.4s, v1.4s", {1: lanes([16777219, 33554438, 0xFEFFFFFF, 0x7FFFFFC0], 32)}),
    c("ucvtf 4s", "ucvtf v0.4s, v1.4s", {1: lanes([0xFFFFFFFF, 0x80000001, 16777219, 0], 32)}),
    c("ucvtf 2d", "ucvtf v0.2d, v1.2d", {1: lanes([0xFFFFFFFFFFFFFFFF, 0x8000000000000401], 64)}),
    c("scvtf 2d", "scvtf v0.2d, v1.2d", {1: lanes([0x8000000000000000, 0x7FFFFFFFFFFFFE01], 64)}),
    c("scvtf 4s fixed32", "scvtf v0.4s, v1.4s, #32", {1: lanes([0x80000000, 1, 0x7FFFFFFF, 0x01000001], 32)}),
    c("ucvtf 2d fixed64", "ucvtf v0.2d, v1.2d, #64", {1: lanes([0xFFFFFFFFFFFFFFFF, 1], 64)}),
    c("ucvtf 2s fixed upper", "ucvtf v0.2s, v1.2s, #1", {1: lanes([0xFFFFFFFF, 3], 32)}),
    c("scvtf 2d fixed alias", "scvtf v1.2d, v1.2d, #10", {1: lanes([0xFFFFFFFFFFFFFC00, 0x20000000000003FF], 64)}),
    c("fcvtn 2s nan/ovf", "fcvtn v0.2s, v1.2d", {1: vf64([SNAN64, 1e300])}),
    c("fcvtn 2s denorm/tie", "fcvtn v0.2s, v1.2d", {1: vf64([1e-50, 1.0 + 2.0 ** -24])}),
    c("fcvtn 2s f32 denorm out", "fcvtn v0.2s, v1.2d", {1: vf64([1.5 * 2.0 ** -149, -2.0 ** -150])}),
    c("fcvtn2 4s keeps low", "fcvtn2 v0.4s, v1.2d", {1: vf64([QNAN64, -0.0])}),
    c("fcvtn 4h", "fcvtn v0.4h, v1.4s", {1: vf32([65520.0, SNAN32, 2.0 ** -25, 1.5 * 2.0 ** -24])}),
    c("fcvtn 4h more", "fcvtn v0.4h, v1.4s", {1: vf32([65519.0, -2.0 ** -14 * 0.99999994, 2049.0, 2051.0])}),
    c("fcvtn2 8h", "fcvtn2 v0.8h, v1.4s", {1: vf32([65504.0, NINF, QNAN32, MIN32])}),
    c("fcvtl 2d", "fcvtl v0.2d, v1.2s", {1: vf32([SNAN32, DEN32, 1.0, 2.0])}),
    c("fcvtl2 2d", "fcvtl2 v0.2d, v1.4s", {1: vf32([1.0, 2.0, QNAN32, -0.0])}),
    c("fcvtl alias", "fcvtl v1.2d, v1.2s", {1: vf32([DEN32MAX, SNAN32B, 9.0, 9.0])}),
    c("fcmeq 4s", "fcmeq v0.4s, v1.4s, v2.4s", {1: vf32([QNAN32, 0.0, 1.0, INF]), 2: vf32([QNAN32, -0.0, 1.0, INF])}),
    c("fcmge 2d", "fcmge v0.2d, v1.2d, v2.2d", {1: vf64([QNAN64, -0.0]), 2: vf64([1.0, 0.0])}),
    c("fcmgt 4s", "fcmgt v0.4s, v1.4s, v2.4s", {1: vf32([1.0, SNAN32, DEN32, INF]), 2: vf32([QNAN32, 0.0, 0.0, INF])}),
    c("fcmgt 4s #0", "fcmgt v0.4s, v1.4s, #0.0", {1: vf32([-0.0, DEN32, QNAN32, NDEN32])}),
    c("fcmle 4s #0", "fcmle v0.4s, v1.4s, #0.0", {1: vf32([-0.0, QNAN32, NDEN32, 1.0])}),
    c("fcmlt 2d #0", "fcmlt v0.2d, v1.2d, #0.0", {1: vf64([-0.0, DEN64 | (1 << 63)])}),
    c("fcmeq 2s #0 upper", "fcmeq v0.2s, v1.2s, #0.0", {1: vf32([-0.0, DEN32])}),
    c("fcmge 4s #0", "fcmge v0.4s, v1.4s, #0.0", {1: vf32([-0.0, NINF, SNAN32, 0.0])}),
    c("fcmle 4s reg", "fcmle v0.4s, v1.4s, v2.4s", {1: vf32([1.0, QNAN32, -0.0, 3.0]), 2: vf32([1.0, 1.0, 0.0, 2.0])}),
    c("fcmlt 2d reg", "fcmlt v0.2d, v1.2d, v2.2d", {1: vf64([1.0, -1.0]), 2: vf64([2.0, QNAN64])}),
    c("fabs 2d nan", "fabs v0.2d, v1.2d", {1: vf64([SNAN64 | (1 << 63), -0.0])}),
    c("fneg 4s nan", "fneg v0.4s, v1.4s", {1: vf32([SNAN32, QNAN32, 0.0, NINF])}),
    c("fabs 2s upper", "fabs v0.2s, v1.2s", {1: vf32([QNAN32, -1.0])}),
    c("faddp 4s", "faddp v0.4s, v1.4s, v2.4s", {1: vf32([SNAN32, 1.0, INF, NINF]), 2: vf32([-0.0, -0.0, DEN32, DEN32])}),
    c("faddp 2s upper", "faddp v0.2s, v1.2s, v2.2s", {1: vf32([1.0, QNAN32]), 2: vf32([3.0, 4.0])}),
    c("faddp s scalar", "faddp s0, v1.2s", {1: vf32([QNAN32B, SNAN32, 7.0, 7.0])}),
    c("faddp d scalar", "faddp d0, v1.2d", {1: vf64([INF, NINF])}),
    c("fmov 2d imm", "fmov v0.2d, #-0.125"),
    c("fmov 2s imm upper", "fmov v0.2s, #31.0"),
    c("fmov 4s imm", "fmov v0.4s, #1.0"),
]

###############
# integer arithmetic, compare, shift
###############
INTS = [
    c("abs 16b", "abs v0.16b, v1.16b", {1: B16}),
    c("abs 2s upper", "abs v0.2s, v1.2s", {1: S4}),
    c("abs 2d", "abs v0.2d, v1.2d", {1: D2}),
    c("neg 2d", "neg v0.2d, v1.2d", {1: lanes([1 << 63, 1], 64)}),
    c("neg 4h upper", "neg v0.4h, v1.4h", {1: H8}),
    c("add 8h wrap", "add v0.8h, v1.8h, v2.8h", {1: H8, 2: H8B}),
    c("add 8b upper", "add v0.8b, v1.8b, v2.8b", {1: B16, 2: B16B}),
    c("sub 2d", "sub v0.2d, v1.2d, v2.2d", {1: D2, 2: D2B}),
    c("sub alias zero", "sub v3.4s, v3.4s, v3.4s"),
    c("mul 16b", "mul v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("mul 4s", "mul v0.4s, v1.4s, v2.4s", {1: S4, 2: S4B}),
    c("mul 8h by elem h[7]", "mul v0.8h, v1.8h, v2.h[7]", {1: H8, 2: H8B}),
    c("mul 2s by elem s[3]", "mul v0.2s, v1.2s, v2.s[3]", {1: S4, 2: S4B}),
    c("mla 4s by elem", "mla v0.4s, v1.4s, v2.s[3]", {1: S4, 2: S4B}),
    c("mla 16b", "mla v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("mls 8h", "mls v0.8h, v1.8h, v2.8h", {1: H8, 2: H8B}),
    c("mls 4h by elem upper", "mls v0.4h, v1.4h, v2.h[5]", {1: H8, 2: H8B}),
    c("cmeq 16b", "cmeq v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("cmge 16b", "cmge v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("cmgt 8h", "cmgt v0.8h, v1.8h, v2.8h", {1: H8, 2: H8B}),
    c("cmhi 4s", "cmhi v0.4s, v1.4s, v2.4s", {1: S4, 2: S4B}),
    c("cmhs 2d", "cmhs v0.2d, v1.2d, v2.2d", {1: D2, 2: D2B}),
    c("cmgt 2d", "cmgt v0.2d, v1.2d, v2.2d", {1: D2, 2: D2B}),
    c("cmtst 16b", "cmtst v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("cmle 2d #0", "cmle v0.2d, v1.2d, #0", {1: lanes([0, 1 << 63], 64)}),
    c("cmlt 8b #0 upper", "cmlt v0.8b, v1.8b, #0", {1: B16}),
    c("cmeq 4s #0", "cmeq v0.4s, v1.4s, #0", {1: S4}),
    c("cmge 8h #0", "cmge v0.8h, v1.8h, #0", {1: H8}),
    c("cmgt 2s #0 upper", "cmgt v0.2s, v1.2s, #0", {1: S4B}),
    c("cmle 16b reg", "cmle v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("cmlo 4s reg", "cmlo v0.4s, v1.4s, v2.4s", {1: S4, 2: S4B}),
    c("cmls 8h reg", "cmls v0.8h, v1.8h, v2.8h", {1: H8, 2: H8B}),
    c("smax 4s", "smax v0.4s, v1.4s, v2.4s", {1: S4, 2: S4B}),
    c("smin 16b", "smin v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("umax 8h", "umax v0.8h, v1.8h, v2.8h", {1: H8, 2: H8B}),
    c("umin 2s upper", "umin v0.2s, v1.2s, v2.2s", {1: S4, 2: S4B}),
    c("uhadd 16b", "uhadd v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("uhadd 4s", "uhadd v0.4s, v1.4s, v2.4s", {1: S4, 2: S4B}),
    c("shadd 8h", "shadd v0.8h, v1.8h, v2.8h", {1: H8, 2: H8B}),
    c("shadd 4s", "shadd v0.4s, v1.4s, v2.4s", {1: S4, 2: S4B}),
    c("shadd 8b upper", "shadd v0.8b, v1.8b, v2.8b", {1: B16, 2: B16B}),
    c("ushl 16b", "ushl v0.16b, v1.16b, v2.16b", {1: B16, 2: SH8}),
    c("sshl 16b", "sshl v0.16b, v1.16b, v2.16b", {1: B16, 2: SH8}),
    c("sshl 4s", "sshl v0.4s, v1.4s, v2.4s", {1: S4, 2: SH32}),
    c("ushl 4s", "ushl v0.4s, v1.4s, v2.4s", {1: S4B, 2: SH32}),
    c("sshl 2d", "sshl v0.2d, v1.2d, v2.2d", {1: D2, 2: SH64}),
    c("ushl 2d", "ushl v0.2d, v1.2d, v2.2d", {1: D2, 2: SH64}),
    c("sshl 8h hi-byte ignored", "sshl v0.8h, v1.8h, v2.8h", {1: H8, 2: lanes([0x0101, 0xFF0F, 0x10, 0xF0, 0x7F01, 0x8001, 0xFFFF, 0x0100], 16)}),
    c("shl 2d #63", "shl v0.2d, v1.2d, #63", {1: D2B}),
    c("shl 8b #7 upper", "shl v0.8b, v1.8b, #7", {1: B16}),
    c("ushr 16b #8", "ushr v0.16b, v1.16b, #8", {1: B16}),
    c("sshr 8h #16", "sshr v0.8h, v1.8h, #16", {1: H8}),
    c("sshr 2d #64", "sshr v0.2d, v1.2d, #64", {1: D2}),
    c("ushr 2d #64", "ushr v0.2d, v1.2d, #64", {1: D2}),
    c("usra 4s #32", "usra v0.4s, v1.4s, #32", {1: S4}),
    c("ssra 2d #64", "ssra v0.2d, v1.2d, #64", {1: D2}),
    c("ssra 8b #1 upper", "ssra v0.8b, v1.8b, #1", {1: B16}),
    c("usra 16b #7", "usra v0.16b, v1.16b, #7", {1: B16}),
    c("cnt 16b", "cnt v0.16b, v1.16b", {1: B16}),
    c("cnt 8b upper", "cnt v0.8b, v1.8b", {1: B16}),
    c("clz 4s", "clz v0.4s, v1.4s", {1: lanes([0, 1, 0x80000000, 0x0000FFFF], 32)}),
    c("clz 16b", "clz v0.16b, v1.16b", {1: B16}),
    c("clz 4h upper", "clz v0.4h, v1.4h", {1: H8}),
]

###############
# bitwise and permutes
###############
PERM = [
    c("and 8b upper", "and v0.8b, v1.8b, v2.8b", {1: B16, 2: B16B}),
    c("orr 16b reg", "orr v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("eor 16b alias", "eor v1.16b, v1.16b, v1.16b", {1: B16}),
    c("bic 8b reg upper", "bic v0.8b, v1.8b, v2.8b", {1: B16, 2: B16B}),
    c("orn 16b", "orn v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("mvn 8b upper", "mvn v0.8b, v1.8b", {1: B16}),
    c("not 16b alias", "not v1.16b, v1.16b", {1: B16}),
    c("bit 16b", "bit v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("bif 16b", "bif v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("bsl 16b", "bsl v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("bsl 8b alias upper", "bsl v1.8b, v1.8b, v2.8b", {1: B16, 2: B16B}),
    c("bif 8b alias src", "bif v0.8b, v0.8b, v1.8b", {1: B16}),
    c("rev16 16b", "rev16 v0.16b, v1.16b", {1: B16}),
    c("rev32 8h", "rev32 v0.8h, v1.8h", {1: H8}),
    c("rev32 8b upper", "rev32 v0.8b, v1.8b", {1: B16}),
    c("rev64 4s", "rev64 v0.4s, v1.4s", {1: S4}),
    c("rev64 8b", "rev64 v0.8b, v1.8b", {1: B16}),
    c("rev64 16b alias", "rev64 v1.16b, v1.16b", {1: B16}),
    c("zip1 8b upper", "zip1 v0.8b, v1.8b, v2.8b", {1: B16, 2: B16B}),
    c("zip2 16b", "zip2 v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("zip2 2s", "zip2 v0.2s, v1.2s, v2.2s", {1: S4, 2: S4B}),
    c("uzp1 4s", "uzp1 v0.4s, v1.4s, v2.4s", {1: S4, 2: S4B}),
    c("uzp2 8h", "uzp2 v0.8h, v1.8h, v2.8h", {1: H8, 2: H8B}),
    c("uzp1 4h upper", "uzp1 v0.4h, v1.4h, v2.4h", {1: H8, 2: H8B}),
    c("trn1 16b", "trn1 v0.16b, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("trn2 2d", "trn2 v0.2d, v1.2d, v2.2d", {1: D2, 2: D2B}),
    c("trn2 8b upper", "trn2 v0.8b, v1.8b, v2.8b", {1: B16, 2: B16B}),
    c("zip1 2d alias", "zip1 v1.2d, v1.2d, v2.2d", {1: D2, 2: D2B}),
    c("uzp2 alias both", "uzp2 v2.4s, v1.4s, v2.4s", {1: S4, 2: S4B}),
    c("ext 16b #15", "ext v0.16b, v1.16b, v2.16b, #15", {1: B16, 2: B16B}),
    c("ext 8b #7 upper", "ext v0.8b, v1.8b, v2.8b, #7", {1: B16, 2: B16B}),
    c("ext alias #3", "ext v1.16b, v1.16b, v1.16b, #3", {1: B16}),
    c("tbl 16b oor", "tbl v0.16b, {v1.16b}, v2.16b", {1: B16, 2: lanes([15, 16, 0, 255, 1, 2, 3, 0x80, 4, 5, 17, 6, 7, 8, 9, 14], 8)}),
    c("tbl 8b 2 regs upper", "tbl v0.8b, {v1.16b, v2.16b}, v3.8b", {1: B16, 2: B16B, 3: lanes([31, 32, 16, 0, 15, 200, 17, 1], 8)}),
    c("tbl 4 regs wrap alias", "tbl v0.16b, {v30.16b, v31.16b, v0.16b, v1.16b}, v0.16b",
      {0: lanes([63, 64, 47, 48, 32, 31, 16, 15, 0, 255, 33, 34, 49, 50, 1, 2], 8), 1: B16}),
    c("tbx 8b 3 regs upper", "tbx v0.8b, {v1.16b, v2.16b, v3.16b}, v4.8b", {1: B16, 2: B16B, 4: lanes([47, 48, 255, 0, 20, 40, 100, 3], 8)}),
    c("tbx 16b alias idx", "tbx v1.16b, {v2.16b}, v1.16b", {1: lanes([0, 16, 1, 255, 2, 3, 15, 14, 99, 4, 5, 6, 7, 8, 9, 10], 8), 2: B16B}),
]

###############
# pairwise, reductions, dot
###############
RED = [
    c("addp 2d", "addp v0.2d, v1.2d, v2.2d", {1: D2, 2: D2B}),
    c("addp 8b upper", "addp v0.8b, v1.8b, v2.8b", {1: B16, 2: B16B}),
    c("addp 4s alias", "addp v1.4s, v2.4s, v1.4s", {1: S4, 2: S4B}),
    c("addp d scalar", "addp d0, v1.2d", {1: D2}),
    c("addv b 16b", "addv b0, v1.16b", {1: B16}),
    c("addv h 4h", "addv h0, v1.4h", {1: H8}),
    c("addv s 4s", "addv s0, v1.4s", {1: S4}),
    c("uaddlv h 16b", "uaddlv h0, v1.16b", {1: lanes([0xFF] * 16, 8)}),
    c("saddlv s 8h", "saddlv s0, v1.8h", {1: lanes([0x8000] * 8, 16)}),
    c("saddlv d 4s", "saddlv d0, v1.4s", {1: lanes([0x80000000] * 4, 32)}),
    c("uaddlv d 4s", "uaddlv d0, v1.4s", {1: lanes([0xFFFFFFFF] * 4, 32)}),
    c("saddlv h 8b", "saddlv h0, v1.8b", {1: B16}),
    c("smaxv b 16b", "smaxv b0, v1.16b", {1: lanes([0x80] * 15 + [0x81], 8)}),
    c("sminv h 8h", "sminv h0, v1.8h", {1: lanes([0x7FFF] * 7 + [0xFFFF], 16)}),
    c("umaxv s 4s", "umaxv s0, v1.4s", {1: S4}),
    c("uminv b 8b", "uminv b0, v1.8b", {1: lanes([0xFF] * 8 + [0] * 8, 8)}),
    c("smaxv s 4s", "smaxv s0, v1.4s", {1: lanes([0x80000000, 0xFFFFFFFF, 0x80000001, 0xFFFFFFFE], 32)}),
    c("sminv b 8b", "sminv b0, v1.8b", {1: lanes([1, 2, 3, 4, 5, 6, 7, 0x7F, 0x80] + [0] * 7, 8)}),
    c("umaxv h 4h", "umaxv h0, v1.4h", {1: lanes([1, 2, 3, 4, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF], 16)}),
    c("udot 4s", "udot v0.4s, v1.16b, v2.16b", {0: lanes([0xFFFFFFFF, 0, 1, 0x80000000], 32), 1: lanes([0xFF] * 16, 8), 2: B16B}),
    c("sdot 4s", "sdot v0.4s, v1.16b, v2.16b", {0: lanes([0x7FFFFFFF, 0x80000000, 0, 5], 32), 1: B16, 2: B16B}),
    c("sdot 2s upper", "sdot v0.2s, v1.8b, v2.8b", {1: lanes([0x80] * 16, 8), 2: lanes([0x80] * 16, 8)}),
    c("sdot 2s by elem [3]", "sdot v0.2s, v1.8b, v2.4b[3]", {1: B16, 2: B16B}),
    c("udot 4s by elem [1]", "udot v0.4s, v1.16b, v2.4b[1]", {1: B16, 2: B16B}),
    c("sdot alias", "sdot v1.4s, v1.16b, v1.16b", {1: B16}),
]

###############
# widening and narrowing
###############
WIDE = [
    c("uaddl 8h", "uaddl v0.8h, v1.8b, v2.8b", {1: B16, 2: B16B}),
    c("saddl2 4s", "saddl2 v0.4s, v1.8h, v2.8h", {1: H8, 2: H8B}),
    c("usubl 2d", "usubl v0.2d, v1.2s, v2.2s", {1: S4, 2: S4B}),
    c("ssubl2 8h", "ssubl2 v0.8h, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("uaddl2 2d", "uaddl2 v0.2d, v1.4s, v2.4s", {1: S4, 2: S4B}),
    c("saddl 2d", "saddl v0.2d, v1.2s, v2.2s", {1: S4, 2: S4B}),
    c("usubl2 4s", "usubl2 v0.4s, v1.8h, v2.8h", {1: H8, 2: H8B}),
    c("ssubl 4s", "ssubl v0.4s, v1.4h, v2.4h", {1: H8, 2: H8B}),
    c("uaddw 4s", "uaddw v0.4s, v1.4s, v2.4h", {1: S4, 2: H8B}),
    c("saddw2 2d", "saddw2 v0.2d, v1.2d, v2.4s", {1: D2, 2: S4B}),
    c("usubw2 8h", "usubw2 v0.8h, v1.8h, v2.16b", {1: H8, 2: B16B}),
    c("ssubw 8h", "ssubw v0.8h, v1.8h, v2.8b", {1: H8, 2: B16B}),
    c("saddw 4s", "saddw v0.4s, v1.4s, v2.4h", {1: S4, 2: H8B}),
    c("uaddw2 2d", "uaddw2 v0.2d, v1.2d, v2.4s", {1: D2, 2: S4B}),
    c("ssubw2 4s", "ssubw2 v0.4s, v1.4s, v2.8h", {1: S4, 2: H8B}),
    c("usubw 2d", "usubw v0.2d, v1.2d, v2.2s", {1: D2, 2: S4B}),
    c("saddw alias", "saddw v1.8h, v1.8h, v1.8b", {1: H8}),
    c("umull 2d", "umull v0.2d, v1.2s, v2.2s", {1: S4, 2: S4B}),
    c("smull2 2d", "smull2 v0.2d, v1.4s, v2.4s", {1: S4, 2: S4B}),
    c("umull2 8h", "umull2 v0.8h, v1.16b, v2.16b", {1: B16, 2: B16B}),
    c("smull 8h", "smull v0.8h, v1.8b, v2.8b", {1: B16, 2: B16B}),
    c("smull 4s by elem h[7]", "smull v0.4s, v1.4h, v2.h[7]", {1: H8, 2: H8B}),
    c("umull 2d by elem s[3]", "umull v0.2d, v1.2s, v2.s[3]", {1: S4, 2: S4B}),
    c("smull2 4s by elem h[0]", "smull2 v0.4s, v1.8h, v2.h[0]", {1: H8, 2: H8B}),
    c("umull2 2d by elem s[1]", "umull2 v0.2d, v1.4s, v2.s[1]", {1: S4, 2: S4B}),
    c("smull alias", "smull v1.2d, v1.2s, v1.2s", {1: S4}),
    c("ushll 8h #7", "ushll v0.8h, v1.8b, #7", {1: B16}),
    c("sshll2 4s #15", "sshll2 v0.4s, v1.8h, #15", {1: H8}),
    c("sshll 2d #31", "sshll v0.2d, v1.2s, #31", {1: S4}),
    c("ushll2 2d #1", "ushll2 v0.2d, v1.4s, #1", {1: S4B}),
    c("shll 8h #8", "shll v0.8h, v1.8b, #8", {1: B16}),
    c("shll2 2d #32", "shll2 v0.2d, v1.4s, #32", {1: S4B}),
    c("shll 4s alias", "shll v1.4s, v1.4h, #16", {1: H8}),
    c("xtn 8b", "xtn v0.8b, v1.8h", {1: H8}),
    c("xtn2 4s", "xtn2 v0.4s, v1.2d", {1: D2B}),
    c("xtn 2s alias", "xtn v1.2s, v1.2d", {1: D2B}),
    c("shrn 8b #8", "shrn v0.8b, v1.8h, #8", {1: H8}),
    c("rshrn 4h #16 carry", "rshrn v0.4h, v1.4s, #16", {1: lanes([0xFFFFFFFF, 0x00008000, 0x7FFF7FFF, 0x80008000], 32)}),
    c("rshrn2 16b #1", "rshrn2 v0.16b, v1.8h, #1", {1: H8}),
    c("shrn2 8h #16", "shrn2 v0.8h, v1.4s, #16", {1: S4}),
    c("rshrn 2s #32", "rshrn v0.2s, v1.2d, #32", {1: lanes([0xFFFFFFFF80000000, 0x000000007FFFFFFF], 64)}),
    c("rshrn2 4s #1 alias", "rshrn2 v1.4s, v1.2d, #1", {1: D2}),
]

###############
# immediates and lane moves
###############
LANE = [
    c("movi 2d", "movi v0.2d, #0xff00ff0000ffff00"),
    c("movi 8b upper", "movi v0.8b, #0x80"),
    c("movi 16b", "movi v0.16b, #0xff"),
    c("movi 4s lsl24", "movi v0.4s, #0xab, lsl #24"),
    c("movi 2s msl16 upper", "movi v0.2s, #0x12, msl #16"),
    c("movi 4h lsl8 upper", "movi v0.4h, #0xc3, lsl #8"),
    c("mvni 4h lsl8", "mvni v0.4h, #0x12, lsl #8"),
    c("mvni 4s msl8", "mvni v0.4s, #0x34, msl #8"),
    c("mvni 8h", "mvni v0.8h, #0xff"),
    c("orr 4s imm lsl8", "orr v0.4s, #0xff, lsl #8"),
    c("bic 8h imm", "bic v0.8h, #0xff"),
    c("orr 2s imm upper", "orr v0.2s, #0x80, lsl #24"),
    c("bic 4h imm upper", "bic v0.4h, #0xff, lsl #8"),
    c("dup 16b wzr", "dup v0.16b, wzr"),
    c("dup 2d x1", "dup v0.2d, x1", regs={1: 0x8000000000000001}),
    c("dup 8b w1 upper", "dup v0.8b, w1", regs={1: 0x12345678ABCDEF99}),
    c("dup 4h w1 upper", "dup v0.4h, w1", regs={1: 0xFFFF0000FFFE8001}),
    c("dup 4s v.s[3]", "dup v0.4s, v1.s[3]", {1: S4B}),
    c("dup 8h v.h[7]", "dup v0.8h, v1.h[7]", {1: H8}),
    c("dup 2s alias upper", "dup v1.2s, v1.s[3]", {1: S4B}),
    c("dup 16b b[15]", "dup v0.16b, v1.b[15]", {1: B16}),
    c("dup 2d d[1] alias", "dup v1.2d, v1.d[1]", {1: D2}),
    c("mov s0 v.s[3]", "mov s0, v1.s[3]", {1: S4B}),
    c("mov b0 v.b[15]", "mov b0, v1.b[15]", {1: B16}),
    c("mov d0 v.d[1]", "mov d0, v1.d[1]", {1: D2}),
    c("mov h0 v.h[7]", "mov h0, v1.h[7]", {1: H8}),
    c("ins b[15] w1", "ins v0.b[15], w1", regs={1: 0xFFFFFFFFFFFFFF5A}),
    c("ins d[1] xzr", "ins v0.d[1], xzr"),
    c("ins s[0] wzr", "mov v0.s[0], wzr"),
    c("mov s[1] s[3] alias", "mov v0.s[1], v0.s[3]"),
    c("ins h[7] h[0]", "ins v0.h[7], v1.h[0]", {1: H8}),
    c("ins d[0] d[1]", "mov v0.d[0], v1.d[1]", {1: D2}),
    c("umov w0 b[15]", "umov w0, v1.b[15]", {1: B16}, {0: GX}),
    c("umov x0 d[1]", "umov x0, v1.d[1]", {1: D2}, {0: GX}),
    c("umov w0 h[7]", "umov w0, v1.h[7]", {1: H8}, {0: GX}),
    c("mov w0 s[3]", "mov w0, v1.s[3]", {1: S4B}, {0: GX}),
    c("smov w0 b[15]", "smov w0, v1.b[15]", {1: B16}, {0: GX}),
    c("smov x0 s[3]", "smov x0, v1.s[3]", {1: S4B}, {0: GX}),
    c("smov x0 h[7]", "smov x0, v1.h[7]", {1: H8}, {0: GX}),
    c("smov w0 h[0]", "smov w0, v1.h[0]", {1: H8}, {0: GX}),
    c("smov x0 b[0]", "smov x0, v1.b[0]", {1: B16}, {0: GX}),
    c("fmov x0 d[1]", "fmov x0, v1.d[1]", {1: D2}, {0: GX}),
    c("fmov d[1] x1", "fmov v0.d[1], x1", regs={1: 0xFFF0000000000001}),
    c("fmov d[1] xzr", "fmov v0.d[1], xzr"),
    c("mov 8b upper", "mov v0.8b, v1.8b", {1: B16}),
    c("mov 16b", "mov v0.16b, v1.16b", {1: B16}),
    c("mov 8b self", "mov v1.8b, v1.8b", {1: B16}),
]

###############
# structure loads and stores
###############
X0D = {0: DATA + 0x40}
MEMS = [
    c("ld1 16b post imm", "ld1 {v0.16b}, [x0], #16", regs=dict(X0D), mem=MEM),
    c("ld1 8bx2 post reg odd", "ld1 {v0.8b, v1.8b}, [x0], x2", regs={**X0D, 2: 5}, mem=MEM),
    c("ld1 4sx4 post", "ld1 {v0.4s, v1.4s, v2.4s, v3.4s}, [x0], #64", regs=dict(X0D), mem=MEM),
    c("ld1 1d post", "ld1 {v0.1d}, [x0], #8", regs=dict(X0D), mem=MEM),
    c("ld1 wrap v31 v0", "ld1 {v31.16b, v0.16b}, [x0]", regs=dict(X0D), mem=MEM),
    c("ld1 sp base post", "ld1 {v0.4s}, [sp], #16", regs={"sp": DATA + 0x80}, mem=MEM),
    c("ld1 2s x3 post neg reg", "ld1 {v0.2s, v1.2s, v2.2s}, [x0], x3", regs={**X0D, 3: 0xFFFFFFFFFFFFFFF0}, mem=MEM),
    c("ld2 8b upper", "ld2 {v0.8b, v1.8b}, [x0]", regs=dict(X0D), mem=MEM),
    c("ld2 2d", "ld2 {v0.2d, v1.2d}, [x0], #32", regs=dict(X0D), mem=MEM),
    c("ld3 4h post", "ld3 {v0.4h, v1.4h, v2.4h}, [x0], #24", regs=dict(X0D), mem=MEM),
    c("ld3 16b", "ld3 {v0.16b, v1.16b, v2.16b}, [x0]", regs=dict(X0D), mem=MEM),
    c("ld4 16b", "ld4 {v0.16b, v1.16b, v2.16b, v3.16b}, [x0]", regs=dict(X0D), mem=MEM),
    c("ld4 2s post reg", "ld4 {v4.2s, v5.2s, v6.2s, v7.2s}, [x0], x1", regs={**X0D, 1: 3}, mem=MEM),
    c("ld4 wrap v30", "ld4 {v30.8h, v31.8h, v0.8h, v1.8h}, [x0], #64", regs=dict(X0D), mem=MEM),
    c("st1 8bx3 post reg", "st1 {v0.8b, v1.8b, v2.8b}, [x0], x2", regs={**X0D, 2: 7}, mem=MEM),
    c("st1 1dx2", "st1 {v0.1d, v1.1d}, [x0]", regs=dict(X0D), mem=MEM),
    c("st1 4 regs wrap", "st1 {v31.16b, v0.16b, v1.16b, v2.16b}, [x0], #64", regs=dict(X0D), mem=MEM),
    c("st2 8h post", "st2 {v0.8h, v1.8h}, [x0], #32", regs=dict(X0D), mem=MEM),
    c("st2 8b", "st2 {v0.8b, v1.8b}, [x0]", regs=dict(X0D), mem=MEM),
    c("st3 2s", "st3 {v0.2s, v1.2s, v2.2s}, [x0]", regs=dict(X0D), mem=MEM),
    c("st3 16b post", "st3 {v0.16b, v1.16b, v2.16b}, [x0], #48", regs=dict(X0D), mem=MEM),
    c("st4 4s post", "st4 {v0.4s, v1.4s, v2.4s, v3.4s}, [x0], #64", regs=dict(X0D), mem=MEM),
    c("st4 4h", "st4 {v0.4h, v1.4h, v2.4h, v3.4h}, [x0]", regs=dict(X0D), mem=MEM),
    c("ld1 lane b[15] post", "ld1 {v0.b}[15], [x0], #1", regs=dict(X0D), mem=MEM),
    c("ld1 lane d[1]", "ld1 {v0.d}[1], [x0]", regs=dict(X0D), mem=MEM),
    c("ld1 lane h[7] post reg", "ld1 {v0.h}[7], [x0], x1", regs={**X0D, 1: 0x21}, mem=MEM),
    c("ld1 lane s[2]", "ld1 {v9.s}[2], [x0]", regs=dict(X0D), mem=MEM),
    c("st1 lane h[7] post", "st1 {v0.h}[7], [x0], #2", regs=dict(X0D), mem=MEM),
    c("st1 lane b[9]", "st1 {v0.b}[9], [x0]", regs=dict(X0D), mem=MEM),
    c("st1 lane d[1] post reg", "st1 {v3.d}[1], [x0], x4", regs={**X0D, 4: 0x18}, mem=MEM),
    c("ld1 lane s[3] sp base", "ld1 {v0.s}[3], [sp]", regs={"sp": DATA + 0x90}, mem=MEM),
    c("ld1r 8b post", "ld1r {v0.8b}, [x0], #1", regs=dict(X0D), mem=MEM),
    c("ld1r 2d", "ld1r {v0.2d}, [x0]", regs=dict(X0D), mem=MEM),
    c("ld1r 4h post reg", "ld1r {v0.4h}, [x0], x1", regs={**X0D, 1: 0x3}, mem=MEM),
    c("ld1r 1d", "ld1r {v0.1d}, [x0]", regs=dict(X0D), mem=MEM),
    c("ld2r 4h post", "ld2r {v0.4h, v1.4h}, [x0], #4", regs=dict(X0D), mem=MEM),
    c("ld3r 2d post", "ld3r {v0.2d, v1.2d, v2.2d}, [x0], #24", regs=dict(X0D), mem=MEM),
    c("ld4r 16b post reg", "ld4r {v0.16b, v1.16b, v2.16b, v3.16b}, [x0], x2", regs={**X0D, 2: 9}, mem=MEM),
    c("ld4r 2s", "ld4r {v4.2s, v5.2s, v6.2s, v7.2s}, [x0]", regs=dict(X0D), mem=MEM),
    c("ld2 lane s[3] post", "ld2 {v0.s, v1.s}[3], [x0], #8", regs=dict(X0D), mem=MEM),
    c("ld3 lane h[7]", "ld3 {v0.h, v1.h, v2.h}[7], [x0]", regs=dict(X0D), mem=MEM),
    c("ld4 lane b[15] post reg", "ld4 {v4.b, v5.b, v6.b, v7.b}[15], [x0], x3", regs={**X0D, 3: 0x11}, mem=MEM),
    c("ld2 lane d[1] wrap", "ld2 {v31.d, v0.d}[1], [x0]", regs=dict(X0D), mem=MEM),
    c("st2 lane d[1]", "st2 {v1.d, v2.d}[1], [x0]", regs=dict(X0D), mem=MEM),
    c("st3 lane b[9] post", "st3 {v0.b, v1.b, v2.b}[9], [x0], #3", regs=dict(X0D), mem=MEM),
    c("st4 lane s[2]", "st4 {v0.s, v1.s, v2.s, v3.s}[2], [x0]", regs=dict(X0D), mem=MEM),
]

EXTRA = [
    c("fmaxnm qnan vs snan", "fmaxnm v0.4s, v1.4s, v2.4s", {1: vf32([QNAN32, SNAN32, SNAN32, SNAN32B]), 2: vf32([SNAN32B, QNAN32, SNAN32B, SNAN32])}),
    c("fmls by elem alias d==b", "fmls v0.4s, v1.4s, v0.s[1]", {0: vf32([1.0, 2.0, QNAN32, 4.0]), 1: vf32([1.0, INF, 1.0, -0.0])}),
    c("fmls scalar s by elem", "fmls s0, s1, v2.s[3]", {0: vf32([-0.0, 1.0, 1.0, 1.0]), 1: vf32([0.0, 2.0, 2.0, 2.0]), 2: vf32([1.0, 1.0, 1.0, 0.0])}),
    c("fmov 8h imm fp16", "fmov v0.8h, #1.5"),
    c("fmov 4h imm fp16 upper", "fmov v0.4h, #-0.125"),
    c("fabs 8h fp16", "fabs v0.8h, v1.8h", {1: H8}),
    c("fneg 4h fp16 upper", "fneg v0.4h, v1.4h", {1: H8}),
    c("ld1 post reg == base", "ld1 {v0.16b}, [x0], x0", regs={0: DATA + 0x10}, mem=MEM),
    c("st1 post reg == base", "st1 {v0.8b}, [x0], x0", regs={0: DATA + 0x20}, mem=MEM),
    {**c("NZCV kept across fcmgt/cmeq", "cmp x1, x2; fcmgt v0.4s, v1.4s, v2.4s; cmeq v3.16b, v1.16b, #0; cset x4, lt",
         {1: vf32([QNAN32, 1.0, -0.0, INF]), 2: vf32([1.0, 0.0, 0.0, INF])}, {1: 1, 2: 0x8000000000000000, 4: GX}), "flags": True},
    {**c("NZCV kept across umov/smov", "cmn x1, x2; smov x5, v1.b[15]; umov w6, v1.h[7]",
         {1: B16}, {1: 0xFFFFFFFFFFFFFFFF, 2: 1, 5: GX, 6: GX}), "flags": True},
]

CASES = FP + INTS + PERM + RED + WIDE + LANE + MEMS + EXTRA + sweep(20261016, 4)
