"""Differential microtest cases (vs Unicorn) for lift_neon.py; run via: sbtenv/bin/python sbt/microtest.py cases_neon.
Case keys: name, asm, regs {xN: val}, vregs {N: (lo, hi)}, mem bytes at DATA, flags/v (compare NZCV / V regs).
One case per vector operand shape seen in real-world arm64 libraries, each running several edge-value sets."""
###############
# imports and constants
###############
from __future__ import annotations
import struct

DATA = 0x240000000
GARB = (0xdeadbeefcafef00d, 0x0123456789abcdef)                        # preload of non-accumulating destinations
MEMPAT = bytes((i * 37 + 11) & 0xFF for i in range(0x200))
Q1, Q2, S1, S2 = 0x7fc01234, 0xffc05678, 0x7f800abc, 0xff812345        # f32 quiet/signalling NaNs with payloads
INF, NINF, Z, NZ, DEN, NDEN = 0x7f800000, 0xff800000, 0, 0x80000000, 0x00000003, 0x807ffff0
MAX, NMAX, MINN, ONE, ONE5, NEG25 = 0x7f7fffff, 0xff7fffff, 0x00800000, 0x3f800000, 0x3fc00000, 0xc0200000
THIRD, THREE, HALF, NHALF, BIG, NBIG = 0x3eaaaaab, 0x40400000, 0x3f000000, 0xbf000000, 0x4f000000, 0xcf000001
QD1, QD2, SD1, SD2 = 0x7ff8000000001234, 0xfff8123456789abc, 0x7ff0000000000abc, 0xfff400000fedcba9
INFD, NINFD, ZD, NZD, DEND, NDEND = 0x7ff0 << 48, 0xfff0 << 48, 0, 1 << 63, 1, 0x800ffffffffffff0
MAXD, MINND, ONED, HALFD = 0x7fefffffffffffff, 1 << 52, 0x3ff0000000000000, 0x3fe0000000000000
THIRDD, THREED = 0x3fd5555555555555, 0x4008000000000000

###############
# builders
###############
def fbits(x: float) -> int:
    """IEEE single bits of x."""
    return struct.unpack("<I", struct.pack("<f", x))[0]

def dbits(x: float) -> int:
    """IEEE double bits of x."""
    return struct.unpack("<Q", struct.pack("<d", x))[0]

def pk(vals: list, e: int) -> tuple[int, int]:
    """Pack 128/e element values (little-endian lanes) into (lo, hi)."""
    v = sum((x & ((1 << e) - 1)) << (e * i) for i, x in enumerate(vals))
    return (v & 0xFFFFFFFFFFFFFFFF, v >> 64)

def swap(s: tuple) -> tuple:
    """Same set with the 64-bit halves of every vector swapped (puts top lanes into 64-bit ops)."""
    return tuple((v[1], v[0]) if isinstance(v, tuple) else v for v in s)

def case(name: str, fmt: str, sets: list, mem: bytes | None = None) -> dict:
    """One case running fmt once per (d, a, b) set on registers 3k, 3k+1, 3k+2; ints go to x regs."""
    regs, vregs, lines = {}, {}, []
    for k, s in enumerate(sets):
        lines.append(fmt.format(d=3 * k, a=3 * k + 1, b=3 * k + 2))
        for r, v in zip((3 * k, 3 * k + 1, 3 * k + 2), s):
            if isinstance(v, tuple): vregs[r] = v
            else: regs[r] = v
    c = {"name": name, "asm": "\n".join(lines) + "\nret", "regs": regs, "vregs": vregs, "v": True}
    return {**c, "mem": mem} if mem is not None else c

def lanes32(sets: list) -> list:
    """f32 lane lists -> packed (d, a, b) sets."""
    return [tuple(pk(x, 32) for x in s) for s in sets]

###############
# data sets
###############
F32 = lanes32([([ONE, Q1, S1, ONE], [Q1, S1, Q1, ONE5], [S2, Q2, S2, Q2]),
               ([Q2, NZ, DEN, NMAX], [Z, NZ, DEN, MAX], [NZ, NZ, NDEN, MAX]),
               ([Q2, Q1, S2, INF], [INF, Z, INF, NINF], [Z, NINF, Z, INF]),
               ([ONE, NEG25, Z, THIRD], [THIRD, NEG25, BIG, MINN], [THREE, ONE5, NBIG, HALF]),
               ([MAX, NMAX, ONE, NZ], [MAX, NMAX, Q1, NDEN], [MAX, MAX, NHALF, S1])])
F2 = F32 + [swap(s) for s in F32]
F64 = [tuple(pk(x, 64) for x in s) for s in
       [([ONED, QD1], [QD1, SD1], [SD2, QD2]), ([SD1, QD2], [INFD, ZD], [ZD, NINFD]),
        ([NZD, DEND], [NZD, DEND], [NZD, NDEND]), ([ONED, THIRDD], [THIRDD, MAXD], [THREED, MAXD]),
        ([QD2, ONED], [INFD, MINND], [NINFD, HALFD]), ([ZD, NZD], [NINFD, QD2], [NINFD, ONED])]]
CV = lanes32([(GARB, [ONE5, NEG25, HALF, NHALF], GARB),
              (GARB, [fbits(2.5), fbits(-1.5), fbits(0.49999997), NZ], GARB),
              (GARB, [Q1, S1, INF, NINF], GARB),
              (GARB, [BIG, NBIG, 0x4f800000, 0x4f7fffff], GARB),
              (GARB, [fbits(1e10), fbits(-1e10), DEN, 0x4b000001], GARB)])
CV2 = [(GARB, (a[0], a[1]), GARB) for _, a, _ in CV] + [(GARB, (a[1], a[0]), GARB) for _, a, _ in CV]
INT = [((0x1111222233334444, 0x5555666677778888), (0x80007fffffff0001, 0x00ff7f80fffe8001), (0x00018000000ffff, 0x7f0180810002_7fff)),
       ((0x7fffffffffffffff, 0x8000000000000000), (0x7fffffff80000000, 0xffffffff00000000), (0x800000007fffffff, 0x00000001ffffffff)),
       ((0xffffffffffffffff, 0), (0x0123456789abcdef, 0xfedcba9876543210), (0x0123456789abcdef, 0)),
       ((0x0f0f0f0f0f0f0f0f, 0xf0f0f0f0f0f0f0f0), (0x8000000000000000, 0x7fffffffffffffff), (0x8000000000000000, 0xffffffffffffffff)),
       ((0x00ff00ff00ff00ff, 0xff00ff00ff00ff00), (0xff00ff00ff00ff00, 0x00ff00ff00ff00ff), (0x0f0f0f0f0f0f0f0f, 0xf0f0f0f0f0f0f0f0))]
SH = [(GARB, INT[0][1], (0x000000ff00000001, 0x000000e100000020)), (GARB, INT[1][1], (0x00000000000000c1, 0x0000000000000040)),
      (GARB, INT[3][1], (0x000000800000007f, 0x000000c000000040)), (GARB, INT[2][1], (0x00f10010000ffff0, 0x001100ef0008fff8)),
      (GARB, INT[4][1], (0x0000000000000008, 0x00000000000000f8))]
NARROW64 = [(GARB, pk(x, 64), GARB) for x in
            [[0x7ff8123456789abc, 0xfff0000fedcba987], [0x3ff0000010000000, 0x3ff0000030000000],
             [dbits(1e39), dbits(-1e-46)], [dbits(1e-40), MAXD], [0x47efffffefffffff, NZD], [ONED, dbits(-3.4e38)]]]
NARROW64_HI = [(GARB if k % 2 else INT[k % 5][0], a, b) for k, (_, a, b) in enumerate(NARROW64)]

###############
# cases
###############
def simple(spec: list, sets: list) -> list:
    """Cases for (name, fmt) pairs that share one data-set family."""
    return [case(n, f, sets) for n, f in spec]

INT_SPEC = [(m + " " + arr, "%s v{d}.%s, v{a}.%s, v{b}.%s" % (m, arr, arr, arr)) for m, arrs in
            [("add", "2d 2s 4h 4s"), ("sub", "2d 2s 4s"), ("mul", "2s 4s 8h"), ("mla", "2s 4s"), ("mls", "4h"),
             ("and", "16b 8b"), ("bic", "16b 8b"), ("eor", "16b 8b"), ("orr", "16b 8b"), ("orn", "16b"),
             ("bif", "16b 8b"), ("bit", "8b 16b"), ("bsl", "16b 8b"),
             ("cmeq", "16b 2d 2s 4h 4s"), ("cmge", "4s"), ("cmgt", "2d"), ("cmhi", "2d 2s 4s"), ("cmhs", "2d"),
             ("cmtst", "16b 4s"), ("smax", "2s 4s"), ("smin", "2s 4s"), ("umax", "2s"), ("umin", "2s"),
             ("uhadd", "4h"), ("shadd", "4h"), ("uzp1", "4h 4s 8b 8h"), ("uzp2", "4s"), ("trn1", "8h"), ("trn2", "4s"),
             ("zip1", "16b 2d 2s 4h 4s"), ("zip2", "2s")] for arr in arrs.split()]
UNARY_SPEC = [(m + " " + arr, "%s v{d}.%s, v{a}.%s" % (m, arr, arr)) for m, arrs in
              [("abs", "2d 2s"), ("neg", "2d 2s"), ("mvn", "16b 8b"), ("cnt", "16b 8b"), ("clz", "2s"),
               ("rev32", "4h"), ("rev64", "2s 4h 4s"), ("rev16", "16b"), ("scvtf", "2d 2s 4s"), ("ucvtf", "2s 4s")]
              for arr in arrs.split()]
ZERO_SPEC = [("%s %s #0" % (m, arr), "%s v{d}.%s, v{a}.%s, #0" % (m, arr, arr)) for m, arr in
             [("cmeq", "2s"), ("cmge", "4s"), ("cmle", "2s"), ("cmlt", "2d"), ("cmlt", "2s")]]
SHIFT_SPEC = [("%s %s #%d" % (m, arr, n), "%s v{d}.%s, v{a}.%s, #%d" % (m, arr, arr, n)) for m, arr, n in
              [("shl", "2d", 2), ("shl", "2s", 31), ("shl", "4s", 24), ("sshr", "2d", 8), ("sshr", "2d", 64),
               ("sshr", "2s", 16), ("sshr", "2s", 32), ("sshr", "4s", 16), ("ushr", "2d", 6), ("ushr", "2d", 64),
               ("ushr", "2s", 1), ("ushr", "4h", 15), ("ushr", "4s", 24), ("ssra", "2s", 16), ("ssra", "4s", 16),
               ("usra", "2d", 62), ("usra", "2s", 14), ("usra", "4s", 32)]]
LONG_SPEC = [(m + " " + s, m + " " + f) for m, s, f in
             [("ushll", "2d", "v{d}.2d, v{a}.2s, #0"), ("ushll", "4s", "v{d}.4s, v{a}.4h, #0"),
              ("ushll", "8h", "v{d}.8h, v{a}.8b, #0"), ("ushll", "8h #3", "v{d}.8h, v{a}.8b, #3"),
              ("ushll2", "4s", "v{d}.4s, v{a}.8h, #0"), ("ushll2", "8h", "v{d}.8h, v{a}.16b, #0"),
              ("sshll", "2d", "v{d}.2d, v{a}.2s, #0"), ("sshll", "4s", "v{d}.4s, v{a}.4h, #0"),
              ("sshll", "4s #5", "v{d}.4s, v{a}.4h, #5"), ("sshll2", "2d", "v{d}.2d, v{a}.4s, #0"),
              ("shll", "2d", "v{d}.2d, v{a}.2s, #32"), ("shll", "4s", "v{d}.4s, v{a}.4h, #16"),
              ("shll2", "4s", "v{d}.4s, v{a}.8h, #16"),
              ("saddl", "2d", "v{d}.2d, v{a}.2s, v{b}.2s"), ("saddl", "4s", "v{d}.4s, v{a}.4h, v{b}.4h"),
              ("saddl2", "2d", "v{d}.2d, v{a}.4s, v{b}.4s"), ("ssubl", "4s", "v{d}.4s, v{a}.4h, v{b}.4h"),
              ("uaddl", "4s", "v{d}.4s, v{a}.4h, v{b}.4h"), ("uaddl", "8h", "v{d}.8h, v{a}.8b, v{b}.8b"),
              ("uaddl2", "4s", "v{d}.4s, v{a}.8h, v{b}.8h"), ("usubl", "2d", "v{d}.2d, v{a}.2s, v{b}.2s"),
              ("saddw", "2d", "v{d}.2d, v{a}.2d, v{b}.2s"), ("saddw", "4s", "v{d}.4s, v{a}.4s, v{b}.4h"),
              ("uaddw", "4s", "v{d}.4s, v{a}.4s, v{b}.4h"), ("uaddw", "8h", "v{d}.8h, v{a}.8h, v{b}.8b"),
              ("usubw", "4s", "v{d}.4s, v{a}.4s, v{b}.4h"), ("usubw", "8h", "v{d}.8h, v{a}.8h, v{b}.8b"),
              ("ssubw2", "4s", "v{d}.4s, v{a}.4s, v{b}.8h"),
              ("smull", "4s", "v{d}.4s, v{a}.4h, v{b}.4h"), ("umull", "2d", "v{d}.2d, v{a}.2s, v{b}.2s"),
              ("umull2", "2d", "v{d}.2d, v{a}.4s, v{b}.4s"), ("smull", "4s elem", "v{d}.4s, v{a}.4h, v{b}.h[5]"),
              ("xtn", "2s", "v{d}.2s, v{a}.2d"), ("xtn", "4h", "v{d}.4h, v{a}.4s"), ("xtn", "8b", "v{d}.8b, v{a}.8h"),
              ("xtn2", "4s", "v{d}.4s, v{a}.2d"), ("rshrn", "8b", "v{d}.8b, v{a}.8h, #2"),
              ("rshrn", "2s #32", "v{d}.2s, v{a}.2d, #32"), ("rshrn2", "16b", "v{d}.16b, v{a}.8h, #8"),
              ("shrn", "4h", "v{d}.4h, v{a}.4s, #3"),
              ("addp", "d 2d", "d{d}, v{a}.2d"), ("addv", "h 8h", "h{d}, v{a}.8h"), ("addv", "s 4s", "s{d}, v{a}.4s"),
              ("addv", "b 16b", "b{d}, v{a}.16b"), ("addp", "4s", "v{d}.4s, v{a}.4s, v{b}.4s"),
              ("saddlv", "d 4s", "d{d}, v{a}.4s"), ("uaddlv", "h 8b", "h{d}, v{a}.8b"),
              ("uaddlv", "s 8h", "s{d}, v{a}.8h"), ("uaddlv", "h 16b", "h{d}, v{a}.16b"),
              ("umaxv", "b 16b", "b{d}, v{a}.16b"), ("umaxv", "b 8b", "b{d}, v{a}.8b"), ("umaxv", "h 4h", "h{d}, v{a}.4h"),
              ("umaxv", "s 4s", "s{d}, v{a}.4s"), ("uminv", "h 4h", "h{d}, v{a}.4h"), ("uminv", "s 4s", "s{d}, v{a}.4s"),
              ("smaxv", "h 8h", "h{d}, v{a}.8h"), ("sminv", "s 4s", "s{d}, v{a}.4s"),
              ("udot", "4s", "v{d}.4s, v{a}.16b, v{b}.16b"), ("sdot", "2s", "v{d}.2s, v{a}.8b, v{b}.8b"),
              ("udot", "4s elem", "v{d}.4s, v{a}.16b, v{b}.4b[3]"),
              ("ext", "16b #8", "v{d}.16b, v{a}.16b, v{b}.16b, #8"), ("ext", "16b #3", "v{d}.16b, v{a}.16b, v{b}.16b, #3"),
              ("ext", "8b #6", "v{d}.8b, v{a}.8b, v{b}.8b, #6"), ("mul", "4s elem", "v{d}.4s, v{a}.4s, v{b}.s[2]")]]
SHL_SPEC = [(m + " " + arr, "%s v{d}.%s, v{a}.%s, v{b}.%s" % (m, arr, arr, arr)) for m, arrs in
            [("ushl", "2d 2s 4h 16b"), ("sshl", "2d 4s 8h")] for arr in arrs.split()]
FP_SPEC = [(m + " " + arr, "%s v{d}.%s, v{a}.%s, v{b}.%s" % (m, arr, arr, arr)) for m, arrs in
           [("fadd", "2s 4s"), ("fsub", "2s 4s"), ("fmul", "2s 4s"), ("fdiv", "2s 4s"), ("fabd", "2s 4s"),
            ("fmaxnm", "2s 4s"), ("fminnm", "4s"), ("fmla", "2s 4s"), ("fmls", "2s 4s"), ("faddp", "2s 4s"),
            ("fcmeq", "2s 4s"), ("fcmge", "2s 4s"), ("fcmgt", "2s 4s")] for arr in arrs.split()] + \
          [(m + " " + s, m + " " + f) for m, s, f in
           [("fmla", "s elem", "s{d}, s{a}, v{b}.s[2]"), ("fmla", "2s elem", "v{d}.2s, v{a}.2s, v{b}.s[3]"),
            ("fmla", "4s elem", "v{d}.4s, v{a}.4s, v{b}.s[1]"), ("fmls", "s elem", "s{d}, s{a}, v{b}.s[3]"),
            ("fmls", "2s elem", "v{d}.2s, v{a}.2s, v{b}.s[0]"), ("fmul", "s elem", "s{d}, s{a}, v{b}.s[1]"),
            ("fmul", "2s elem", "v{d}.2s, v{a}.2s, v{b}.s[3]"), ("fmul", "4s elem", "v{d}.4s, v{a}.4s, v{b}.s[0]"),
            ("faddp", "s 2s", "s{d}, v{a}.2s"), ("fcmeq", "4s #0", "v{d}.4s, v{a}.4s, #0.0"),
            ("fcmge", "2s #0", "v{d}.2s, v{a}.2s, #0.0"), ("fcmgt", "2s #0", "v{d}.2s, v{a}.2s, #0.0"),
            ("fcmle", "2s #0", "v{d}.2s, v{a}.2s, #0.0"), ("fcmlt", "2s #0", "v{d}.2s, v{a}.2s, #0.0"),
            ("fcmlt", "4s #0", "v{d}.4s, v{a}.4s, #0.0"), ("fabs", "2s", "v{d}.2s, v{a}.2s"),
            ("fabs", "4s", "v{d}.4s, v{a}.4s"), ("fneg", "2s", "v{d}.2s, v{a}.2s"), ("fneg", "4s", "v{d}.4s, v{a}.4s"),
            ("fsqrt", "2s", "v{d}.2s, v{a}.2s"), ("fsqrt", "4s", "v{d}.4s, v{a}.4s"),
            ("fcvtl", "2d", "v{d}.2d, v{a}.2s"), ("fcvtl2", "2d", "v{d}.2d, v{a}.4s")]]
FPD_SPEC = [(m + " 2d", "%s v{d}.2d, v{a}.2d, v{b}.2d" % m) for m in
            ("fadd", "fsub", "fmul", "fdiv", "fmla", "fmls", "fcmgt", "fmaxnm", "faddp")] + \
           [("fmul 2d elem", "fmul v{d}.2d, v{a}.2d, v{b}.d[1]"), ("fmla d elem", "fmla d{d}, d{a}, v{b}.d[1]"),
            ("faddp d 2d", "faddp d{d}, v{a}.2d"), ("fsqrt 2d", "fsqrt v{d}.2d, v{a}.2d"), ("fneg 2d", "fneg v{d}.2d, v{a}.2d")]
CV_SPEC = [(m + " " + arr, "%s v{d}.%s, v{a}.%s" % (m, arr, arr)) for m, arrs in
           [("frinta", "2s 4s"), ("frintm", "2s"), ("frintp", "2s"), ("frintz", "2s"), ("fcvtzs", "2s 4s"),
            ("fcvtzu", "2s 4s")] for arr in arrs.split()] + \
          [("fcvtzs 4s #8", "fcvtzs v{d}.4s, v{a}.4s, #8"), ("fcvtzu 2s #31", "fcvtzu v{d}.2s, v{a}.2s, #31")]
CVD_SPEC = [("fcvtzs 2d", "fcvtzs v{d}.2d, v{a}.2d"), ("fcvtzu 2d", "fcvtzu v{d}.2d, v{a}.2d"),
            ("frinta 2d", "frinta v{d}.2d, v{a}.2d"), ("fcvtn 2s", "fcvtn v{d}.2s, v{a}.2d")]
INT2_SPEC = [("scvtf 4s #4", "scvtf v{d}.4s, v{a}.4s, #4"), ("ucvtf 2d", "ucvtf v{d}.2d, v{a}.2d"),
             ("ucvtf 2s #16", "ucvtf v{d}.2s, v{a}.2s, #16")]
IMM_SPEC = [(f.replace("{d}", "N"), f) for f in
            ["movi v{d}.16b, #1", "movi v{d}.8b, #0xa5", "movi v{d}.2d, #0", "movi v{d}.2d, #0xff00ff0000ff00ff",
             "movi v{d}.2s, #0x20", "movi v{d}.2s, #0x80, lsl #24", "movi v{d}.4h, #1", "movi v{d}.8h, #0x7f, lsl #8",
             "movi v{d}.4s, #4", "movi v{d}.4s, #0x40, lsl #24", "movi v{d}.4s, #0x12, msl #8", "movi v{d}.2s, #0x34, msl #16",
             "mvni v{d}.2s, #0x80, lsl #16", "mvni v{d}.2s, #0x7f, msl #16", "mvni v{d}.4s, #0x80, lsl #24",
             "mvni v{d}.4s, #0x7f, msl #16", "mvni v{d}.4h, #0x3", "orr v{d}.2s, #0x20, lsl #8", "orr v{d}.4s, #0x3f, lsl #24",
             "orr v{d}.8h, #0x1", "bic v{d}.2s, #0xf", "bic v{d}.4h, #0xfe", "bic v{d}.4s, #0x80, lsl #24",
             "fmov v{d}.2d, #0.5", "fmov v{d}.2s, #-1.0", "fmov v{d}.4s, #1.0"]]
LANE_SPEC = [("dup 2d elem", "dup v{d}.2d, v{a}.d[1]"), ("dup 2s elem", "dup v{d}.2s, v{a}.s[3]"),
             ("dup 4s elem", "dup v{d}.4s, v{a}.s[0]"), ("dup 16b elem", "dup v{d}.16b, v{a}.b[13]"),
             ("mov d lane", "mov d{d}, v{a}.d[1]"), ("mov s lane", "mov s{d}, v{a}.s[3]"), ("mov h lane", "mov h{d}, v{a}.h[5]"),
             ("mov 16b", "mov v{d}.16b, v{a}.16b"), ("mov 8b", "mov v{d}.8b, v{a}.8b"),
             ("mov d[1] d[0]", "mov v{d}.d[1], v{a}.d[0]"), ("mov h[3] h[1]", "mov v{d}.h[3], v{a}.h[1]"),
             ("mov s[1] s[2]", "mov v{d}.s[1], v{a}.s[2]"), ("mov b[15] b[0]", "mov v{d}.b[15], v{a}.b[0]"),
             ("mov s[0] wzr", "mov v{d}.s[0], wzr"), ("mov d[1] xzr", "mov v{d}.d[1], xzr")]
GPR_SRC_SPEC = [("dup 2d x", "dup v{d}.2d, x{a}"), ("dup 2s w", "dup v{d}.2s, w{a}"), ("dup 4h w", "dup v{d}.4h, w{a}"),
                ("dup 4s w", "dup v{d}.4s, w{a}"), ("dup 8b w", "dup v{d}.8b, w{a}"), ("dup 16b w", "dup v{d}.16b, w{a}"),
                ("mov d[1] x", "mov v{d}.d[1], x{a}"), ("mov s[0] w", "mov v{d}.s[0], w{a}"), ("mov s[3] w", "mov v{d}.s[3], w{a}"),
                ("mov b[9] w", "mov v{d}.b[9], w{a}"), ("fmov d[1] x", "fmov v{d}.d[1], x{a}")]
GPR_DST_SPEC = [("umov w b", "umov w{d}, v{a}.b[0]"), ("umov w b15", "umov w{d}, v{a}.b[15]"),
                ("umov w h", "umov w{d}, v{a}.h[6]"), ("mov w s", "mov w{d}, v{a}.s[1]"), ("mov x d", "mov x{d}, v{a}.d[1]"),
                ("smov w h", "smov w{d}, v{a}.h[4]"), ("smov x b", "smov x{d}, v{a}.b[7]"), ("smov x s", "smov x{d}, v{a}.s[3]"),
                ("fmov x d[1]", "fmov x{d}, v{a}.d[1]")]
GPR_SETS = [(GARB, 0x8123456789abcdef, GARB), (INT[0][0], 0x00000000ffffff80, GARB), (INT[1][0], 0x7fff, GARB)]
VEC_SETS = [(INT[k][0], INT[k][1], GARB) for k in range(5)]
DST_SETS = [(0xdeadbeefdeadbeef, INT[k][1], GARB) for k in range(5)]
TBL = [{"name": "tbl 16b {16b}", "asm": "tbl v0.16b, {v1.16b}, v2.16b\nret",
        "vregs": {0: GARB, 1: INT[2][1], 2: (0x1f0f1000ff0e0102, 0x8008070605040309)}, "v": True},
       {"name": "tbl 8b {16b}", "asm": "tbl v0.8b, {v1.16b}, v2.8b\nret",
        "vregs": {0: GARB, 1: INT[2][1], 2: (0x1f0f1000ff0e0102, 0x8008070605040309)}, "v": True},
       {"name": "tbl 8b {2x16b}", "asm": "tbl v0.8b, {v5.16b, v6.16b}, v2.8b\ntbl v3.8b, {v31.16b, v0.16b}, v4.8b\nret",
        "vregs": {0: GARB, 5: INT[2][1], 6: INT[0][1], 2: (0x1f0f2000ff1e1102, 0x80080706), 31: INT[1][1],
                  4: (0x1f0f2000ff1e1102, 0x80080706)}, "v": True},
       {"name": "tbx 8b {16b}", "asm": "tbx v0.8b, {v1.16b}, v2.8b\nret",
        "vregs": {0: GARB, 1: INT[2][1], 2: (0x1f0f1000ff0e0102, 0x8008070605040309)}, "v": True}]
MEMC = [{"name": n, "asm": a + "\nret", "regs": {8: DATA + 0x40, 9: DATA + 0x80, 10: 12, 1: DATA + 0x100},
         "vregs": {k: INT[k % 5][k % 2] for k in range(20)}, "mem": MEMPAT, "v": True} for n, a in
        [("ld1 3x2d", "ld1 {v4.2d, v5.2d, v6.2d}, [x8]"), ("ld1 2x8b post", "ld1 {v4.8b, v5.8b}, [x8], #16"),
         ("ld1 d lane", "ld1 {v2.d}[1], [x8]"), ("ld1 s lane", "ld1 {v0.s}[1], [x9]"),
         ("ld1 s lane post #4", "ld1 {v4.s}[2], [x8], #4"), ("ld1 h lane post x", "ld1 {v4.h}[5], [x8], x10"),
         ("ld1r 2s", "ld1r {v8.2s}, [x8]"), ("ld1r 4s", "ld1r {v7.4s}, [x9]"), ("ld1r 8b", "ld1r {v0.8b}, [x8]"),
         ("ld1r 2d post", "ld1r {v3.2d}, [x8], #8"), ("ld2 4s", "ld2 {v2.4s, v3.4s}, [x8]"),
         ("ld2 2s post", "ld2 {v2.2s, v3.2s}, [x8], #16"), ("ld3 8h", "ld3 {v1.8h, v2.8h, v3.8h}, [x9]"),
         ("ld4 16b", "ld4 {v0.16b, v1.16b, v2.16b, v3.16b}, [x9]"), ("ld4 16b post", "ld4 {v0.16b, v1.16b, v2.16b, v3.16b}, [x9], #64"),
         ("ld2r 4h", "ld2r {v5.4h, v6.4h}, [x8]"), ("ld2 s lane", "ld2 {v5.s, v6.s}[3], [x8]"),
         ("st1 3x2d", "st1 {v0.2d, v1.2d, v2.2d}, [x8]"), ("st1 8b", "st1 {v3.8b}, [x8]"), ("st1 d lane", "st1 {v4.d}[1], [x9]"),
         ("st1 h lane", "st1 {v19.h}[2], [x8]"), ("st1 s lane", "st1 {v1.s}[1], [x8]"),
         ("st1 s lane post x", "st1 {v5.s}[0], [x1], x10"), ("st1 4s post", "st1 {v5.4s}, [x1], #16"),
         ("st2 2d", "st2 {v0.2d, v1.2d}, [x8]"), ("st3 4h", "st3 {v6.4h, v7.4h, v8.4h}, [x9]"),
         ("st4 4s", "st4 {v16.4s, v17.4s, v18.4s, v19.4s}, [x8]"), ("st4 8b post", "st4 {v1.8b, v2.8b, v3.8b, v4.8b}, [x8], #32"),
         ("st2 b lane", "st2 {v1.b, v2.b}[9], [x8]")]]
CORE_REGRESS = [{"name": "popcount 16b idiom", "asm": "cnt v0.16b, v1.16b\nuaddlv h2, v0.16b\naddv b3, v0.8b\nret",
                 "vregs": {1: INT[0][1]}, "v": True}]

CASES: list = (simple(INT_SPEC, INT) + simple(UNARY_SPEC, [(GARB, a, GARB) for _, a, _ in INT]) + simple(ZERO_SPEC, INT)
               + simple(SHIFT_SPEC, INT) + simple(LONG_SPEC, INT) + simple(SHL_SPEC, SH) + simple(FP_SPEC, F2)
               + simple(FPD_SPEC, F64) + simple(CV_SPEC, CV + CV2[5:]) + simple(CVD_SPEC, NARROW64)
               + simple(INT2_SPEC, INT) + [case("fcvtn2 4s", "fcvtn2 v{d}.4s, v{a}.2d", NARROW64_HI)]
               + [case(n, f, [(GARB,)]) for n, f in IMM_SPEC] + [case("orr/bic imm acc", "orr v{d}.4h, #0x5a, lsl #8\nbic v{d}.8h, #0x81",
                                                                     [(INT[k][1],) for k in range(3)])]
               + simple(LANE_SPEC, VEC_SETS) + simple(GPR_SRC_SPEC, GPR_SETS) + simple(GPR_DST_SPEC, DST_SETS)
               + TBL + MEMC + CORE_REGRESS)
