"""Adversarial differential cases (vs Unicorn) for lift_neon.py; run: sbtenv/bin/python sbt/microtest.py cases_neon_adv1.
Case keys: name, asm, regs {xN: val}, vregs {N: (lo, hi)}, mem bytes at DATA, flags/v (compare NZCV / V regs).
Probes NaN payloads, signed zero, denormals, ties, saturation, integer extremes, aliasing, upper-half zeroing,
lane edges, post-index writeback and narrow memory widths. Cases that crash the C build sit last."""
###############
# imports and constants
###############
from __future__ import annotations
import struct

DATA = 0x240000000
GARB = (0xdeadbeefcafef00d, 0x0123456789abcdef)                        # preload of destinations
XG = 0xfedcba9876543210                                                # garbage preload of GPR destinations
MEMPAT = bytes((i * 29 + 7) & 0xFF for i in range(0x200))
Q1, Q2, S1, S2 = 0x7fc01234, 0xffc05678, 0x7f800abc, 0xff812345        # f32 quiet/signalling NaNs with payloads
INF, NINF, NZ, DEN, NDEN = 0x7f800000, 0xff800000, 0x80000000, 0x00000003, 0x807ffff0
ONE, MAX, MINN = 0x3f800000, 0x7f7fffff, 0x00800000
QD1, QD2, SD1, SD2 = 0x7ff8000000001234, 0xfff8123456789abc, 0x7ff0000000000abc, 0xfff400000fedcba9
INFD, NINFD, NZD, DEND = 0x7ff0 << 48, 0xfff0 << 48, 1 << 63, 1

###############
# builders
###############
def fb(x: float) -> int:
    """IEEE single bits of x."""
    return struct.unpack("<I", struct.pack("<f", x))[0]

def db(x: float) -> int:
    """IEEE double bits of x."""
    return struct.unpack("<Q", struct.pack("<d", x))[0]

def w4(a: int, b: int, c: int, d: int) -> tuple[int, int]:
    """V register from four 32-bit lanes, lane 0 first."""
    return ((a & 0xFFFFFFFF) | ((b & 0xFFFFFFFF) << 32), (c & 0xFFFFFFFF) | ((d & 0xFFFFFFFF) << 32))

def h8(*h: int) -> tuple[int, int]:
    """V register from eight 16-bit lanes, lane 0 first."""
    v = sum((x & 0xFFFF) << (16 * i) for i, x in enumerate(h))
    return (v & ((1 << 64) - 1), v >> 64)

def b16(bs: bytes) -> tuple[int, int]:
    """V register from 16 bytes, byte 0 first."""
    return (int.from_bytes(bs[:8], "little"), int.from_bytes(bs[8:16], "little"))

def case(name: str, asm: str, vregs: dict, regs: dict | None = None, mem: bytes | None = None) -> dict:
    """One differential case comparing V regs (and memory when mem is given)."""
    c = {"name": name, "asm": asm + "\nret", "vregs": vregs, "regs": regs or {}, "v": True,
         "flags": asm.startswith("cmp")}                               # harness seeds NZCV differently; compare only after a cmp
    return c if mem is None else {**c, "mem": mem}

###############
# cases
###############
FP = [
    case("fadd 4s nan order", "fadd v0.4s, v1.4s, v2.4s", {0: GARB, 1: w4(Q1, S1, ONE, INF), 2: w4(S2, Q2, Q2, NINF)}),
    case("fsub 2d snan b", "fsub v3.2d, v4.2d, v5.2d", {3: GARB, 4: (QD2, INFD), 5: (SD1, INFD)}),
    case("fmul 2s inf*0 upper", "fmul v0.2s, v1.2s, v2.2s", {0: GARB, 1: w4(INF, NINF, 1, 1), 2: w4(NZ, 0, 1, 1)}),
    case("fdiv 4s zero/denorm", "fdiv v0.4s, v1.4s, v2.4s", {0: GARB, 1: w4(0, ONE, DEN, NDEN), 2: w4(NZ, NZ, MAX, fb(0.5))}),
    case("fmla 4s qnan addend inf*0", "fmla v0.4s, v1.4s, v2.4s",
         {0: w4(Q1, S1, Q2, fb(1e-38)), 1: w4(INF, INF, S2, fb(1e-38)), 2: w4(0, 0, Q1, fb(-1.0))}),
    case("fmla 2d by elem alias", "fmla v0.2d, v0.2d, v0.d[1]", {0: (db(3.0), db(-0.0))}),
    case("fmls 4s nan sign", "fmls v0.4s, v1.4s, v2.4s",
         {0: w4(ONE, ONE, 0, NZ), 1: w4(Q1, S1, ONE, 0), 2: w4(ONE, ONE, Q2, 0)}),
    case("fmls 2d -0 result", "fmls v0.2d, v1.2d, v2.2d", {0: (0, NZD), 1: (0, 0), 2: (0, 0)}),
    case("fmaxnm 4s nan/zero", "fmaxnm v0.4s, v1.4s, v2.4s", {0: GARB, 1: w4(Q1, S1, NZ, Q1), 2: w4(ONE, ONE, 0, Q2)}),
    case("fminnm 2d nan/zero", "fminnm v0.2d, v1.2d, v2.2d", {0: GARB, 1: (QD1, 0), 2: (SD2, NZD)}),
    case("fminnm 4s q vs s", "fminnm v0.4s, v1.4s, v2.4s", {0: GARB, 1: w4(Q1, NINF, DEN, NZ), 2: w4(S2, Q2, NDEN, 0)}),
    case("fabd 4s nan sign", "fabd v0.4s, v1.4s, v2.4s", {0: GARB, 1: w4(Q2, INF, NZ, DEN), 2: w4(ONE, INF, 0, NDEN)}),
    case("fsqrt 4s edges", "fsqrt v0.4s, v1.4s", {0: GARB, 1: w4(NZ, NDEN, S2, NINF)}),
    case("fsqrt 2d denorm", "fsqrt v0.2d, v1.2d", {0: GARB, 1: (DEND, SD1)}),
    case("frinta 4s ties", "frinta v0.4s, v1.4s", {0: GARB, 1: w4(fb(2.5), fb(-2.5), fb(-0.4), fb(0.49999997))}),
    case("frintm/p 4s -0", "frintm v0.4s, v1.4s\nfrintp v2.4s, v1.4s", {0: GARB, 2: GARB, 1: w4(fb(-0.3), DEN, NDEN, S1)}),
    case("frintz 2d", "frintz v0.2d, v1.2d", {0: GARB, 1: (db(-0.99), db(4503599627370497.0))}),
    case("fcm* 4s nan/zero", "fcmeq v0.4s, v1.4s, v2.4s\nfcmge v3.4s, v1.4s, v2.4s\nfcmgt v4.4s, v1.4s, v2.4s",
         {0: GARB, 3: GARB, 4: GARB, 1: w4(Q1, NZ, INF, DEN), 2: w4(Q1, 0, INF, 0)}),
    case("fcmle/lt #0 2s", "fcmle v0.2s, v1.2s, #0.0\nfcmlt v2.2s, v1.2s, #0.0", {0: GARB, 2: GARB, 1: w4(NZ, NDEN, 1, 1)}),
    case("fcmge #0 2d nan", "fcmge v0.2d, v1.2d, #0.0", {0: GARB, 1: (QD1, NZD)}),
    case("fcvtzs 4s saturate", "fcvtzs v0.4s, v1.4s", {0: GARB, 1: w4(fb(3e9), fb(-3e9), Q2, fb(-2147483648.0))}),
    case("fcvtzs 4s #31", "fcvtzs v0.4s, v1.4s, #31", {0: GARB, 1: w4(ONE, fb(-1.0), fb(0.99999994), fb(-0.75))}),
    case("fcvtzs 2d #64", "fcvtzs v0.2d, v1.2d, #64", {0: GARB, 1: (db(-0.5), db(0.5))}),
    case("fcvtzs 2d sat", "fcvtzs v0.2d, v1.2d", {0: GARB, 1: (db(9.3e18), NINFD)}),
    case("fcvtzu 4s edges", "fcvtzu v0.4s, v1.4s", {0: GARB, 1: w4(fb(-0.9), fb(4.3e9), S1, fb(4294967040.0))}),
    case("fcvtzu 2d #1 edges", "fcvtzu v0.2d, v1.2d, #1", {0: GARB, 1: (db(9.3e18), db(-1.0))}),
    case("scvtf 4s ties", "scvtf v0.4s, v1.4s", {0: GARB, 1: w4(16777217, 0x80000000, 0x7fffffff, 16777219)}),
    case("scvtf 4s #32", "scvtf v0.4s, v1.4s, #32", {0: GARB, 1: w4(1, 0x80000000, 0x7fffffff, 0xffffffff)}),
    case("ucvtf 2d u64 max", "ucvtf v0.2d, v1.2d", {0: GARB, 1: (0xffffffffffffffff, (1 << 53) + 1)}),
    case("ucvtf 4s #16", "ucvtf v0.4s, v1.4s, #16", {0: GARB, 1: w4(0xffffffff, 1, 0x80000001, 0x1000001)}),
    case("scvtf 2d #64 min", "scvtf v0.2d, v1.2d, #64", {0: GARB, 1: (1 << 63, 0x7fffffffffffffff)}),
    case("fcvtl nan payload", "fcvtl v0.2d, v1.2s", {0: GARB, 1: w4(S2, DEN, 1, 1)}),
    case("fcvtl2 alias", "fcvtl2 v1.2d, v1.4s", {1: w4(1, 1, Q1, NDEN)}),
    case("fcvtn nan/ovf upper", "fcvtn v0.2s, v1.2d", {0: GARB, 1: (SD2, db(3.5e38))}),
    case("fcvtn2 denorm tie", "fcvtn2 v0.4s, v1.2d", {0: GARB, 1: (db(1.5 * 2 ** -149), db(-1e-46))}),
    case("fneg/fabs 2d nan", "fneg v0.2d, v1.2d\nfabs v2.2d, v1.2d", {0: GARB, 2: GARB, 1: (QD2, SD1)}),
    case("fneg 2s upper", "fneg v0.2s, v1.2s", {0: GARB, 1: w4(0, NZ, 5, 5)}),
    case("faddp 4s nan", "faddp v0.4s, v1.4s, v2.4s", {0: GARB, 1: w4(S1, Q2, INF, NINF), 2: w4(NZ, NZ, 0, NZ)}),
    case("faddp scalar d", "faddp d0, v1.2d", {0: GARB, 1: (QD1, SD2)}),
    case("faddp scalar s", "faddp s0, v1.2s", {0: GARB, 1: w4(NZ, NZ, ONE, ONE)}),
    case("fmov 4s/2d/2s imm", "fmov v0.4s, #-0.125\nfmov v1.2d, #31.0\nfmov v2.2s, #1.0", {0: GARB, 1: GARB, 2: GARB}),
    case("fmul s by elem upper", "fmul s0, s1, v2.s[3]", {0: GARB, 1: w4(fb(3.0), 9, 9, 9), 2: w4(0, 0, 0, fb(-0.0))}),
    case("fmla d by elem", "fmla d0, d1, v2.d[1]", {0: (db(1.0), 77), 1: (INFD, 5), 2: (5, 0)}),
    case("fmulx-free fmul 2d den", "fmul v0.2d, v1.2d, v2.2d", {0: GARB, 1: (DEND, db(2.0 ** -1022)), 2: (db(0.5), db(0.5))}),
]

INT = [
    case("add/sub 16b wrap", "add v0.16b, v1.16b, v2.16b\nsub v3.16b, v1.16b, v2.16b",
         {0: GARB, 3: GARB, 1: b16(bytes([0xff, 0x80, 0x7f] * 5 + [1])), 2: b16(bytes([1, 0x80, 0x81] * 5 + [2]))}),
    case("add 2d alias", "add v0.2d, v0.2d, v0.2d", {0: (1 << 63, 0xffffffffffffffff)}),
    case("mul 8b upper", "mul v0.8b, v1.8b, v2.8b", {0: GARB, 1: (0xff80ff7f10203040, 9), 2: (0xff02807f10101010, 9)}),
    case("mla 8h by h[7]", "mla v0.8h, v1.8h, v2.h[7]", {0: h8(*range(8)), 1: h8(0x8000, 0xffff, 3, 4, 5, 6, 7, 0x7fff), 2: h8(0, 0, 0, 0, 0, 0, 0, 0xffff)}),
    case("mls 4s by s[3] alias", "mls v1.4s, v1.4s, v1.s[3]", {1: w4(0x80000000, 3, 0xffffffff, 0x7fffffff)}),
    case("shadd/uhadd 4s", "shadd v0.4s, v1.4s, v2.4s\nuhadd v3.4s, v1.4s, v2.4s",
         {0: GARB, 3: GARB, 1: w4(0x7fffffff, 0x80000000, 0xffffffff, 0xffffffff), 2: w4(0x7fffffff, 0x80000000, 0xfffffffe, 0)}),
    case("shadd 16b neg odd", "shadd v0.16b, v1.16b, v2.16b", {0: GARB, 1: b16(bytes([0x80, 0xff, 0x7f, 0x81] * 4)), 2: b16(bytes([0xff, 0xfe, 0x7f, 0] * 4))}),
    case("smin/umax 8h", "smin v0.8h, v1.8h, v2.8h\numax v3.8h, v1.8h, v2.8h\nsmax v4.4h, v1.4h, v2.4h\numin v5.4h, v1.4h, v2.4h",
         {0: GARB, 3: GARB, 4: GARB, 5: GARB, 1: h8(0x8000, 0x7fff, 0xffff, 0, 1, 0x8001, 5, 5), 2: h8(0x7fff, 0x8000, 0, 0xffff, 0x8000, 0x8000, 5, 6)}),
    case("sshl 2d edges", "sshl v0.2d, v1.2d, v2.2d\nushl v3.2d, v1.2d, v2.2d", {0: GARB, 3: GARB, 1: (1 << 63, 0x8000000000000001), 2: (0xc0, 0x40)}),
    case("sshl 16b edges", "sshl v0.16b, v1.16b, v2.16b\nushl v3.16b, v1.16b, v2.16b",
         {0: GARB, 3: GARB, 1: b16(bytes([0x81] * 16)), 2: b16(bytes([0x80, 0x7f, 7, 8, 0xf9, 0xf8, 0xf7, 0xff, 1, 0, 0x40, 0xc0, 0x20, 0xe0, 3, 0xfd]))}),
    case("sshl 4s low byte only", "sshl v0.4s, v1.4s, v2.4s", {0: GARB, 1: w4(0x80000000, 1, 0xf0, 0x40000000), 2: w4(0x101, 0xff01, 0xffffff04, 0x1f)}),
    case("sshr/ushr 2d #64", "sshr v0.2d, v1.2d, #64\nushr v2.2d, v1.2d, #64", {0: GARB, 2: GARB, 1: (1 << 63, 0x7fffffffffffffff)}),
    case("sshr/ushr 16b #8", "sshr v0.16b, v1.16b, #8\nushr v2.8b, v1.8b, #8", {0: GARB, 2: GARB, 1: b16(bytes([0x80, 0x7f] * 8))}),
    case("ssra/usra 4s #32", "ssra v0.4s, v1.4s, #32\nusra v2.4s, v1.4s, #32", {0: w4(1, 2, 3, 4), 2: w4(1, 2, 3, 4), 1: w4(0x80000000, 1, 0xffffffff, 0x7fffffff)}),
    case("ssra 2d #1 wrap", "ssra v0.2d, v1.2d, #1", {0: (0x7fffffffffffffff, 0), 1: (2, 1 << 63)}),
    case("shl 2d #63 / 8b #7", "shl v0.2d, v1.2d, #63\nshl v2.8b, v1.8b, #7", {0: GARB, 2: GARB, 1: (0xff, 3)}),
    case("abs/neg 16b min", "abs v0.16b, v1.16b\nneg v2.16b, v1.16b", {0: GARB, 2: GARB, 1: b16(bytes([0x80, 0xff, 1, 0x7f] * 4))}),
    case("abs/neg 2d min", "abs v0.2d, v1.2d\nneg v2.2d, v1.2d", {0: GARB, 2: GARB, 1: (1 << 63, 0xffffffffffffffff)}),
    case("cnt/clz 16b", "cnt v0.16b, v1.16b\nclz v2.16b, v1.16b", {0: GARB, 2: GARB, 1: b16(bytes([0, 0xff, 1, 0x80] * 4))}),
    case("clz 4s/8h zero", "clz v0.4s, v1.4s\nclz v2.4h, v1.4h", {0: GARB, 2: GARB, 1: w4(0, 1, 0xffffffff, 0x10000)}),
    case("cm* 2d extremes", "cmeq v0.2d, v1.2d, v2.2d\ncmhi v3.2d, v1.2d, v2.2d\ncmhs v4.2d, v1.2d, v2.2d\ncmgt v5.2d, v1.2d, v2.2d\ncmge v6.2d, v1.2d, v2.2d\ncmtst v7.2d, v1.2d, v2.2d",
         {k: GARB for k in (0, 3, 4, 5, 6, 7)} | {1: (1 << 63, 5), 2: (0x7fffffffffffffff, 5)}),
    case("cm* #0 8b", "cmle v0.8b, v1.8b, #0\ncmlt v2.8b, v1.8b, #0\ncmeq v3.8b, v1.8b, #0\ncmge v4.8b, v1.8b, #0\ncmgt v5.8b, v1.8b, #0",
         {k: GARB for k in (0, 2, 3, 4, 5)} | {1: b16(bytes([0x80, 0, 1, 0xff, 0x7f, 0, 0x80, 2] + [9] * 8))}),
    case("bit/bif/bsl alias", "bit v0.16b, v0.16b, v1.16b\nbif v2.16b, v3.16b, v2.16b\nbsl v4.8b, v4.8b, v5.8b",
         {0: GARB, 1: (0xff00ff00f0f0f0f0, 0x0123456789abcdef), 2: (0x5555aaaa5555aaaa, 0xffff0000ffff0000), 3: (0x1234, 0x5678), 4: GARB, 5: (0x1111, 0x2222)}),
    case("logic 8b upper", "and v0.8b, v1.8b, v2.8b\norr v3.8b, v1.8b, v2.8b\neor v4.8b, v1.8b, v2.8b\nbic v5.8b, v1.8b, v2.8b\norn v6.8b, v1.8b, v2.8b\nmvn v7.8b, v1.8b\nnot v8.16b, v8.16b",
         {k: GARB for k in (0, 3, 4, 5, 6, 7, 8)} | {1: (0xf0f0ff00, 7), 2: (0xff00ff00ff, 9)}),
    case("mov 8b upper", "mov v0.8b, v1.8b\nmov v2.16b, v2.16b", {0: GARB, 1: GARB, 2: GARB}),
    case("movi/mvni forms", "movi v0.2d, #0xff00ff0000ff00ff\nmovi v1.4h, #0xab, lsl #8\nmvni v2.4s, #0x12, msl #16\nmovi v3.8b, #0x81\nmovi v4.2s, #0x7f, msl #8",
         {k: GARB for k in range(5)}),
    case("orr/bic imm", "orr v0.4h, #0x34, lsl #8\nbic v1.4s, #0xff, lsl #24\norr v2.8h, #0xff\nbic v3.2s, #0x80", {k: GARB for k in range(4)}),
    case("ext 16b #15 / 8b #7", "ext v0.16b, v1.16b, v2.16b, #15\next v3.8b, v1.8b, v2.8b, #7\next v4.16b, v4.16b, v4.16b, #8",
         {0: GARB, 3: GARB, 4: GARB, 1: b16(bytes(range(16))), 2: b16(bytes(range(0x80, 0x90)))}),
    case("zip/uzp/trn 8b", "zip1 v0.8b, v1.8b, v2.8b\nzip2 v3.8b, v1.8b, v2.8b\nuzp1 v4.8b, v1.8b, v2.8b\nuzp2 v5.8b, v1.8b, v2.8b\ntrn1 v6.8b, v1.8b, v2.8b\ntrn2 v7.8b, v1.8b, v2.8b",
         {k: GARB for k in (0, 3, 4, 5, 6, 7)} | {1: b16(bytes(range(16))), 2: b16(bytes(range(0x80, 0x90)))}),
    case("zip/uzp/trn 2d/4s alias", "zip2 v0.2d, v0.2d, v1.2d\nuzp1 v1.4s, v2.4s, v1.4s\ntrn2 v2.4s, v2.4s, v2.4s",
         {0: (1, 2), 1: w4(10, 11, 12, 13), 2: w4(20, 21, 22, 23)}),
    case("rev16/32/64", "rev16 v0.16b, v1.16b\nrev32 v2.8h, v1.8h\nrev64 v3.4s, v1.4s\nrev64 v4.8b, v1.8b\nrev32 v5.8b, v1.8b",
         {k: GARB for k in (0, 2, 3, 4, 5)} | {1: b16(bytes(range(16)))}),
    case("tbl 4 regs wrap", "tbl v0.16b, {v30.16b, v31.16b, v0.16b, v1.16b}, v2.16b",
         {30: b16(bytes(range(16))), 31: b16(bytes(range(16, 32))), 0: b16(bytes(range(32, 48))), 1: b16(bytes(range(48, 64))),
          2: b16(bytes([0, 15, 16, 31, 32, 47, 48, 63, 64, 255, 1, 17, 33, 49, 0x80, 62]))}),
    case("tbx 8b keep upper", "tbx v0.8b, {v1.16b}, v2.8b", {0: GARB, 1: b16(bytes(range(0x40, 0x50))), 2: b16(bytes([0, 16, 15, 0xff, 3, 200, 7, 8] + [0] * 8))}),
    case("tbl 8b 2reg upper", "tbl v0.8b, {v1.16b, v2.16b}, v0.8b", {0: b16(bytes([31, 0, 32, 16, 15, 1, 2, 3] * 2)), 1: b16(bytes(range(16))), 2: b16(bytes(range(16, 32)))}),
    case("addp vec/scalar", "addp v0.2d, v1.2d, v2.2d\naddp v3.16b, v1.16b, v2.16b\naddp d4, v1.2d\naddp v5.4h, v1.4h, v2.4h",
         {0: GARB, 3: GARB, 4: GARB, 5: GARB, 1: (0xffffffffffffffff, 1), 2: (0x8000000000000000, 0x8000000000000000)}),
    case("addv/saddlv/uaddlv", "addv b0, v1.16b\nsaddlv h2, v1.16b\nuaddlv h3, v1.16b\nuaddlv d4, v5.4s\nsaddlv d6, v5.4s\naddv s7, v5.4s",
         {k: GARB for k in (0, 2, 3, 4, 6, 7)} | {1: b16(bytes([0x80] * 16)), 5: w4(0xffffffff, 0xffffffff, 0x80000000, 0x80000000)}),
    case("min/max v", "smaxv b0, v1.16b\nsminv b2, v1.16b\numaxv h3, v1.8h\numinv s4, v1.4s\nsmaxv s5, v1.4s\nsminv h6, v1.4h",
         {k: GARB for k in (0, 2, 3, 4, 5, 6)} | {1: b16(bytes([0x7f, 0x80, 0, 0xff, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 0x81]))}),
    case("sdot/udot extremes", "sdot v0.4s, v1.16b, v2.16b\nudot v3.4s, v1.16b, v2.16b\nsdot v4.2s, v1.8b, v2.4b[3]\nudot v5.4s, v1.16b, v2.4b[1]",
         {0: w4(0x7fffffff, 0, 0x80000000, 1), 3: w4(0xffffffff, 0, 0, 1), 4: GARB, 5: GARB,
          1: b16(bytes([0x80] * 8 + [0xff] * 8)), 2: b16(bytes([0x80] * 4 + [0x7f] * 4 + [0xff] * 4 + [0x80] * 4))}),
    case("long signed 2 forms", "saddl2 v0.8h, v1.16b, v2.16b\nssubl2 v3.4s, v1.8h, v2.8h\nssubw2 v4.2d, v4.2d, v1.4s\nsaddw v5.8h, v5.8h, v2.8b",
         {0: GARB, 3: GARB, 4: (5, 1 << 63), 5: h8(0x7fff, 0x8000, 0xffff, 0, 1, 2, 3, 4),
          1: b16(bytes([0] * 8 + [0x80, 0xff, 0x7f, 1] * 2)), 2: b16(bytes([0x80, 0x7f, 0xff, 0x01] * 4))}),
    case("long unsigned forms", "uaddl v0.8h, v1.8b, v2.8b\nusubl2 v3.2d, v1.4s, v2.4s\nuaddw2 v4.4s, v4.4s, v1.8h\nusubw v5.2d, v5.2d, v2.2s",
         {0: GARB, 3: GARB, 4: w4(0xffffffff, 1, 2, 3), 5: (0, 1), 1: b16(bytes([0xff] * 16)), 2: b16(bytes([1, 2, 3, 4] * 4))}),
    case("mull by elem / 2d", "smull2 v0.4s, v1.8h, v2.h[7]\numull v3.2d, v1.2s, v2.2s\nsmull v4.2d, v1.2s, v2.s[3]\numull2 v5.8h, v1.16b, v2.16b",
         {0: GARB, 3: GARB, 4: GARB, 5: GARB, 1: (0xffffffff80000000, 0x8000ffff7fff0001), 2: (0xffffffff7fffffff, 0x8000123456789abc)}),
    case("shll/ushll/sshll", "shll v0.8h, v1.8b, #8\nshll2 v2.4s, v1.8h, #16\nushll2 v3.8h, v1.16b, #7\nsshll v4.2d, v1.2s, #0\nsshll2 v5.2d, v1.4s, #31",
         {k: GARB for k in (0, 2, 3, 4, 5)} | {1: (0x80000000ff017f80, 0xfffffffe80000001)}),
    case("xtn/xtn2 upper", "xtn v0.8b, v1.8h\nxtn2 v2.16b, v1.8h\nxtn v3.2s, v1.2d", {0: GARB, 2: GARB, 3: GARB, 1: (0x123456789abcdef0, 0xfedcba9876543210)}),
    case("shrn/rshrn edges", "shrn v0.4h, v1.4s, #16\nrshrn v2.2s, v3.2d, #32\nrshrn2 v4.16b, v1.8h, #8\nrshrn v5.8b, v1.8h, #1",
         {0: GARB, 2: GARB, 4: GARB, 5: GARB, 1: w4(0xffffffff, 0x80008000, 0x7fff7fff, 0x00ff00ff), 3: (0xffffffffffffffff, 0x7fffffff80000000)}),
]

LANE = [
    case("umov w0 b[15] zeroes x", "umov w0, v1.b[15]\nmov w2, v1.s[3]\numov x3, v1.d[1]", {1: (0, 0x80ffffffffffff9a)}, {0: XG, 2: XG, 3: XG}),
    case("smov w/x", "smov w0, v1.h[7]\nsmov x2, v1.b[15]\nsmov x3, v1.s[3]\nsmov w4, v1.b[0]", {1: (0x7f, 0x80000000ff800000)}, {0: XG, 2: XG, 3: XG, 4: XG}),
    case("ins gpr zr/trunc", "mov v0.d[1], xzr\nmov v1.b[15], w2\nins v2.h[0], wzr\nmov v3.s[3], w4", {k: GARB for k in range(4)}, {2: 0x1ff, 4: XG}),
    case("ins lane alias", "mov v0.s[3], v0.s[0]\nmov v1.d[0], v1.d[1]\nmov v2.b[0], v3.b[15]", {0: GARB, 1: GARB, 2: GARB, 3: GARB}),
    case("dup gpr forms", "dup v0.16b, wzr\ndup v1.8b, w2\ndup v2.2d, x2\ndup v3.4h, w2", {k: GARB for k in range(4)}, {2: XG}),
    case("dup lane alias/upper", "dup v0.2d, v0.d[1]\ndup v1.2s, v1.s[3]\ndup v2.16b, v1.b[15]\ndup s3, v1.s[1]\ndup h4, v0.h[7]", {k: GARB for k in range(5)}),
    case("fmov d[1] gpr", "fmov v0.d[1], x1\nfmov x2, v3.d[1]", {0: GARB, 3: GARB}, {1: XG, 2: 5}),
]

MEM = [
    case("ld1 b[15] post #1", "ld1 {v0.b}[15], [x0], #1", {0: GARB}, {0: DATA + 3}, MEMPAT),
    case("ld1 h[7] post reg", "ld1 {v0.h}[7], [x0], x1", {0: GARB}, {0: DATA + 2, 1: 0xfffffffffffffffe}, MEMPAT),
    case("ld1 d[1] lane", "ld1 {v0.d}[1], [x0]", {0: GARB}, {0: DATA + 8}, MEMPAT),
    case("ld2 s[3] lanes post", "ld2 {v0.s, v1.s}[3], [x0], #8", {0: GARB, 1: GARB}, {0: DATA + 4}, MEMPAT),
    case("st1 s[3] post", "st1 {v0.s}[3], [x0], #4", {0: GARB}, {0: DATA + 0x10}, MEMPAT),
    case("st4 b[15] post", "st4 {v0.b, v1.b, v2.b, v3.b}[15], [x0], #4",
         {0: GARB, 1: (0, 0x11 << 56), 2: (0, 0x22 << 56), 3: (0, 0x33 << 56)}, {0: DATA + 0x21}, MEMPAT),
    case("st3 h[7] wrap regs", "st3 {v31.h, v0.h, v1.h}[7], [x0]", {31: (0, 0xaaaa << 48), 0: (0, 0xbbbb << 48), 1: (0, 0xcccc << 48)}, {0: DATA + 0x30}, MEMPAT),
    case("ld2 8b post upper", "ld2 {v0.8b, v1.8b}, [x0], #16", {0: GARB, 1: GARB}, {0: DATA + 1}, MEMPAT),
    case("ld3 4h wrap post reg", "ld3 {v30.4h, v31.4h, v0.4h}, [x0], x1", {30: GARB, 31: GARB, 0: GARB}, {0: DATA + 6, 1: 100}, MEMPAT),
    case("ld4 16b post", "ld4 {v0.16b, v1.16b, v2.16b, v3.16b}, [x0], #64", {}, {0: DATA + 5}, MEMPAT),
    case("ld4 2d", "ld4 {v4.2d, v5.2d, v6.2d, v7.2d}, [x0]", {}, {0: DATA + 8}, MEMPAT),
    case("ld1r 8b post", "ld1r {v0.8b}, [x0], #1", {0: GARB}, {0: DATA + 9}, MEMPAT),
    case("ld2r 4h post reg", "ld2r {v0.4h, v1.4h}, [x0], x2", {0: GARB, 1: GARB}, {0: DATA + 2, 2: 6}, MEMPAT),
    case("ld3r 2d post", "ld3r {v0.2d, v1.2d, v2.2d}, [x0], #24", {}, {0: DATA + 8}, MEMPAT),
    case("ld4r 16b", "ld4r {v28.16b, v29.16b, v30.16b, v31.16b}, [x0]", {}, {0: DATA + 0x41}, MEMPAT),
    case("ld1 x4 16b post", "ld1 {v0.16b, v1.16b, v2.16b, v3.16b}, [x0], #64", {}, {0: DATA + 7}, MEMPAT),
    case("ld1 x2 1d post reg", "ld1 {v0.1d, v1.1d}, [x0], x1", {0: GARB, 1: GARB}, {0: DATA, 1: 3}, MEMPAT),
    case("ld1 base==step", "ld1 {v0.16b}, [x0], x0", {}, {0: DATA + 0x10}, MEMPAT),
    case("st2 2d post", "st2 {v0.2d, v1.2d}, [x0], #32", {0: GARB, 1: (1, 2)}, {0: DATA + 0x40}, MEMPAT),
    case("st3 8b post reg", "st3 {v0.8b, v1.8b, v2.8b}, [x0], x1", {0: GARB, 1: (0x1111111111111111, 9), 2: (0x2222222222222222, 9)}, {0: DATA + 0x51, 1: 0xfffffffffffffff0}, MEMPAT),
    case("st1 x3 sp post", "st1 {v0.4s, v1.4s, v2.4s}, [sp], #48", {0: GARB, 1: (3, 4), 2: (5, 6)}, {"sp": DATA + 0x100}, MEMPAT),
    case("st4 4h", "st4 {v0.4h, v1.4h, v2.4h, v3.4h}, [x0]", {0: GARB, 1: (0x1111222233334444, 7), 2: (0x5555666677778888, 7), 3: (0x9999aaaabbbbcccc, 7)}, {0: DATA + 0x80}, MEMPAT),
]

FLAGS = [
    case("neon leaves NZCV", "cmp x1, x2\ncmeq v0.4s, v1.4s, v2.4s\nfcmgt v3.2d, v1.2d, v2.2d\naddv s4, v1.4s", {0: GARB, 1: (5, 6), 2: (5, 7), 3: GARB, 4: GARB}, {1: 1, 2: 2}),
]

MORE = [
    case("fmla 4s by s[0] alias", "fmla v0.4s, v0.4s, v0.s[0]", {0: w4(fb(-2.0), Q1, INF, NZ)}),
    case("fcvtzs/scvtf 2s upper", "fcvtzs v0.2s, v1.2s\nscvtf v2.2s, v3.2s", {0: GARB, 2: GARB, 1: w4(fb(-1.5), fb(2.5), 1, 1), 3: w4(7, 0x80000000, 1, 1)}),
    case("frinta 2d ties", "frinta v0.2d, v1.2d\nfrintm v2.2d, v3.2d", {0: GARB, 2: GARB, 1: (db(-0.5), db(4503599627370495.5)), 3: (SD2, NZD)}),
    case("fdiv 2d den/inf", "fdiv v0.2d, v1.2d, v2.2d", {0: GARB, 1: (DEND, INFD), 2: (db(2.0), NINFD)}),
    case("uxtl/sxtl2 alias", "uxtl v0.8h, v1.8b\nsxtl2 v2.4s, v1.8h\nuxtl2 v3.2d, v1.4s", {0: GARB, 2: GARB, 3: GARB, 1: (0x80ff7f01fffe8000, 0xffff8000ffffffff)}),
    case("dup d / mov h scalar", "dup d0, v1.d[1]\nmov h2, v1.h[7]\nmov b3, v1.b[8]", {0: GARB, 2: GARB, 3: GARB, 1: GARB}),
    case("ld1r 1d", "ld1r {v0.1d}, [x0], #8", {0: GARB}, {0: DATA + 0x18}, MEMPAT),
    case("fabs/fneg fp16 bits", "fabs v0.8h, v1.8h\nfneg v2.4h, v1.4h", {0: GARB, 2: GARB, 1: h8(0xfe01, 0x7e00, 0x8000, 0x3c00, 1, 2, 3, 0xffff)}),
    case("fmov 8h #1.0 (fp16)", "fmov v0.8h, #1.0", {0: GARB}),
    case("fmov 4h #-2.0 (fp16)", "fmov v0.4h, #-2.0", {0: GARB}),
]

CRASH = [
    case("fcvtn 4h (fp16)", "fcvtn v0.4h, v1.4s", {0: GARB, 1: w4(ONE, 0, 0, 0)}),
    case("fcvtn2 8h (fp16)", "fcvtn2 v0.8h, v1.4s", {0: GARB, 1: w4(ONE, 0, 0, 0)}),
]

CASES = FP + INT + LANE + MEM + FLAGS + MORE + CRASH
