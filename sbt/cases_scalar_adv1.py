"""Adversarial differential cases (vs Unicorn) for lift_scalar.py: NaN payloads/quieting, signed zero, inf,
denormals, rounding ties, fp->int saturation, integer extremes, register aliasing, zr operands, 32-bit upper
zeroing, flags, lane forms, LSE/acquire-release byte/half widths. Run: sbtenv/bin/python sbt/microtest.py cases_scalar_adv1.
Case keys: name, asm, regs {xN: val}, vregs {N: (lo, hi)}, mem bytes at DATA, flags/v (compare NZCV / V regs)."""
###############
# imports and constants
###############
from __future__ import annotations
import struct

DATA = 0x240000000
HI = 0x0123456789ABCDEF                                                # garbage in V upper 64 bits
JUNK32 = 0xDEADBEEF00000000                                            # garbage above a 32-bit scalar
GJ = 0xA5A5A5A500000000                                                # garbage above a W-register value
D_QNAN = 0x7FF8000000000000
D_QNAN_PAY = 0x7FF80000DEADBEEF
D_QNAN_NEG = 0xFFF800000000ABCD
D_SNAN = 0x7FF0000000000001                                            # payload only in low bits
D_SNAN_PAY = 0x7FF4000012345678
D_SNAN_NEG = 0xFFF4000000001234
D_INF, D_NINF = 0x7FF0000000000000, 0xFFF0000000000000
D_PZ, D_NZ = 0, 0x8000000000000000
D_DEN, D_NDEN = 0x0000000000000001, 0x8000000000000001
S_QNAN_PAY, S_QNAN_NEG = 0x7FC12345, 0xFFC00321
S_SNAN, S_SNAN_NEG = 0x7F800001, 0xFFA00001
S_INF, S_NINF = 0x7F800000, 0xFF800000
S_PZ, S_NZ = 0, 0x80000000
S_DEN, S_NDEN = 0x00000001, 0x80000001


###############
# bit helpers
###############
def fd(x: float) -> int:
    """IEEE double bits."""
    return struct.unpack("<Q", struct.pack("<d", x))[0]

def fs(x: float) -> int:
    """IEEE single bits."""
    return struct.unpack("<I", struct.pack("<f", x))[0]

def vd(bits: int) -> tuple[int, int]:
    """V register holding a double with garbage in the upper lane."""
    return (bits, HI)

def vs(bits: int) -> tuple[int, int]:
    """V register holding a single with garbage above it."""
    return (JUNK32 | bits, HI)

def le(*vals: tuple[int, int]) -> bytes:
    """Little-endian memory image from (value, width_bytes) pairs."""
    return b"".join(v.to_bytes(n, "little") for v, n in vals)


###############
# floating point cases
###############
FP_CASES = [
    {"name": "fabs sNaN neg no quiet", "asm": "fabs d0,d1\nfabs s2,s3\nret",
     "vregs": {0: vd(HI), 1: vd(D_SNAN_NEG), 2: vd(HI), 3: vs(S_SNAN_NEG)}, "v": True},
    {"name": "fabs alias -0 -inf", "asm": "fabs d0,d0\nfabs s1,s1\nfabs d2,d3\nret",
     "vregs": {0: vd(D_NZ), 1: vs(S_NINF), 3: vd(D_NDEN)}, "v": True},
    {"name": "fsqrt -0 -den sNaN", "asm": "fsqrt d0,d1\nfsqrt d2,d3\nfsqrt d4,d5\nfsqrt d6,d7\nret",
     "vregs": {1: vd(D_NZ), 3: vd(D_NDEN), 5: vd(D_SNAN_NEG), 7: vd(D_DEN)}, "v": True},
    {"name": "fsqrt s -inf qNaN den", "asm": "fsqrt s0,s1\nfsqrt s2,s3\nfsqrt s4,s5\nfsqrt s6,s6\nret",
     "vregs": {1: vs(S_NINF), 3: vs(S_QNAN_NEG), 5: vs(S_DEN), 6: vs(fs(2.0))}, "v": True},
    {"name": "frinta ties d", "asm": "frinta d0,d1\nfrinta d2,d3\nfrinta d4,d5\nfrinta d6,d7\nfrinta d8,d9\nret",
     "vregs": {1: vd(fd(2.5)), 3: vd(fd(-2.5)), 5: vd(fd(-0.4)), 7: vd(fd(0.49999999999999994)), 9: vd(D_SNAN_PAY)}, "v": True},
    {"name": "frinta s ties/den", "asm": "frinta s0,s1\nfrinta s2,s3\nfrinta s4,s5\nfrinta s6,s7\nret",
     "vregs": {1: vs(fs(0.5)), 3: vs(fs(-1.5)), 5: vs(S_NDEN), 7: vs(fs(8388607.5))}, "v": True},
    {"name": "frintm/p signed zero", "asm": "frintm d0,d1\nfrintp d2,d3\nfrintm d4,d5\nfrintp s6,s7\nfrintm s8,s9\nret",
     "vregs": {1: vd(fd(0.3)), 3: vd(fd(-0.3)), 5: vd(D_NZ), 7: vs(fs(-0.75)), 9: vs(S_NDEN)}, "v": True},
    {"name": "frintm/p NaN inf", "asm": "frintm d0,d1\nfrintp d2,d3\nfrintp s4,s5\nfrintm s6,s7\nret",
     "vregs": {1: vd(D_SNAN), 3: vd(D_NINF), 5: vs(S_SNAN_NEG), 7: vs(S_INF)}, "v": True},
    {"name": "fcvt s->d NaN payload", "asm": "fcvt d0,s1\nfcvt d2,s3\nfcvt d4,s5\nfcvt d6,s7\nret",
     "vregs": {1: vs(S_SNAN_NEG), 3: vs(S_QNAN_PAY), 5: vs(S_NDEN), 7: vs(S_NINF)}, "v": True},
    {"name": "fcvt d->s NaN payload", "asm": "fcvt s0,d1\nfcvt s2,d3\nfcvt s4,d5\nfcvt s6,d7\nret",
     "vregs": {1: vd(D_SNAN), 3: vd(D_SNAN_PAY), 5: vd(D_QNAN_NEG), 7: vd(D_QNAN_PAY)}, "v": True},
    {"name": "fcvt d->s round/den/ovf", "asm": "fcvt s0,d1\nfcvt s2,d3\nfcvt s4,d5\nfcvt s6,d7\nfcvt s8,d9\nret",
     "vregs": {1: vd(fd(1.0 + 2.0 ** -24)), 3: vd(fd(1.0 + 3 * 2.0 ** -24)), 5: vd(fd(1e-45)),
               7: vd(fd(-1e39)), 9: vd(D_NDEN)}, "v": True},
    {"name": "fcvt alias d0<-s0", "asm": "fcvt d0,s0\nfcvt s1,d1\nret",
     "vregs": {0: vs(fs(-3.25)), 1: vd(fd(1e-40))}, "v": True},
    {"name": "fnmul NaN sign", "asm": "fnmul d0,d1,d2\nfnmul d3,d4,d5\nfnmul s6,s7,s8\nret",
     "vregs": {1: vd(D_QNAN_PAY), 2: vd(fd(1.0)), 4: vd(fd(2.0)), 5: vd(D_SNAN_NEG), 7: vs(S_QNAN_NEG), 8: vs(S_SNAN)}, "v": True},
    {"name": "fnmul inf*0 zeros", "asm": "fnmul d0,d1,d2\nfnmul d3,d4,d5\nfnmul s6,s7,s8\nfnmul d9,d9,d9\nret",
     "vregs": {1: vd(D_INF), 2: vd(D_NZ), 4: vd(D_PZ), 5: vd(fd(-1.0)), 7: vs(S_DEN), 8: vs(fs(0.5)), 9: vd(fd(-3.0))}, "v": True},
    {"name": "fabd NaN/inf/zero", "asm": "fabd d0,d1,d2\nfabd d3,d4,d5\nfabd d6,d7,d7\nfabd s8,s9,s10\nret",
     "vregs": {1: vd(fd(1.0)), 2: vd(D_SNAN_NEG), 4: vd(D_NINF), 5: vd(D_NINF), 7: vd(fd(-5.0)),
               9: vs(S_QNAN_NEG), 10: vs(fs(1.0))}, "v": True},
    {"name": "fabd den underflow", "asm": "fabd d0,d1,d2\nfabd s3,s4,s5\nret",
     "vregs": {1: vd(D_DEN), 2: vd(0x0000000000000003), 4: vs(S_DEN), 5: vs(S_NDEN)}, "v": True},
    {"name": "fmaxnm/fminnm +-0", "asm": "fmaxnm d0,d1,d2\nfmaxnm d3,d2,d1\nfminnm d4,d1,d2\nfminnm d5,d2,d1\nfmaxnm s6,s7,s8\nfminnm s9,s7,s8\nret",
     "vregs": {1: vd(D_PZ), 2: vd(D_NZ), 7: vs(S_NZ), 8: vs(S_PZ)}, "v": True},
    {"name": "fmaxnm qNaN vs num", "asm": "fmaxnm d0,d1,d2\nfminnm d3,d2,d1\nfmaxnm d4,d1,d5\nfminnm d6,d1,d7\nret",
     "vregs": {1: vd(D_QNAN_NEG), 2: vd(fd(-7.0)), 5: vd(D_NINF), 7: vd(D_INF)}, "v": True},
    {"name": "fmaxnm NaN pairs", "asm": "fmaxnm d0,d1,d2\nfminnm d3,d2,d1\nfmaxnm d4,d1,d5\nfminnm s6,s7,s8\nfmaxnm s9,s8,s7\nret",
     "vregs": {1: vd(D_QNAN_PAY), 2: vd(D_SNAN_NEG), 5: vd(D_QNAN_NEG), 7: vs(S_QNAN_PAY), 8: vs(S_SNAN)}, "v": True},
    {"name": "fmaxnm den/alias", "asm": "fmaxnm d0,d0,d1\nfminnm s2,s3,s2\nfmaxnm d4,d4,d4\nret",
     "vregs": {0: vd(D_NDEN), 1: vd(D_DEN), 2: vs(S_DEN), 3: vs(S_NDEN), 4: vd(D_SNAN)}, "v": True},
    {"name": "fmadd inf*0+qNaN", "asm": "fmadd d0,d1,d2,d3\nfmadd d4,d2,d1,d5\nfmadd s6,s7,s8,s9\nret",
     "vregs": {1: vd(D_INF), 2: vd(D_PZ), 3: vd(D_QNAN_PAY), 5: vd(D_SNAN_NEG), 7: vs(S_NZ), 8: vs(S_NINF), 9: vs(S_QNAN_NEG)}, "v": True},
    {"name": "fmadd NaN priority", "asm": "fmadd d0,d1,d2,d3\nfmadd d4,d5,d1,d3\nfmadd d6,d5,d7,d8\nret",
     "vregs": {1: vd(D_SNAN_PAY), 2: vd(fd(1.0)), 3: vd(D_QNAN_NEG), 5: vd(D_QNAN_PAY), 7: vd(D_SNAN), 8: vd(fd(2.0))}, "v": True},
    {"name": "fmsub NaN n sign flip", "asm": "fmsub d0,d1,d2,d3\nfmsub d4,d2,d1,d3\nfmsub s5,s6,s7,s8\nret",
     "vregs": {1: vd(D_QNAN_PAY), 2: vd(fd(3.0)), 3: vd(fd(1.0)), 6: vs(S_SNAN), 7: vs(fs(1.0)), 8: vs(fs(0.0))}, "v": True},
    {"name": "fnmadd NaN a sign flip", "asm": "fnmadd d0,d1,d2,d3\nfnmadd d4,d1,d2,d5\nfnmadd s6,s7,s7,s8\nret",
     "vregs": {1: vd(fd(2.0)), 2: vd(fd(3.0)), 3: vd(D_QNAN_PAY), 5: vd(D_SNAN_NEG), 7: vs(fs(1.5)), 8: vs(S_QNAN_NEG)}, "v": True},
    {"name": "fnmsub NaN signs", "asm": "fnmsub d0,d1,d2,d3\nfnmsub d4,d5,d2,d6\nfnmsub s7,s8,s9,s10\nret",
     "vregs": {1: vd(fd(2.0)), 2: vd(fd(3.0)), 3: vd(D_QNAN_NEG), 5: vd(D_QNAN_NEG), 6: vd(fd(1.0)),
               8: vs(fs(1.0)), 9: vs(S_SNAN_NEG), 10: vs(fs(1.0))}, "v": True},
    {"name": "fma signed zero", "asm": "fmadd d0,d1,d2,d3\nfnmsub d4,d1,d1,d5\nfmsub d6,d1,d1,d5\nfnmadd d7,d1,d1,d5\nret",
     "vregs": {1: vd(D_NZ), 2: vd(D_PZ), 3: vd(D_NZ), 5: vd(D_PZ)}, "v": True},
    {"name": "fma fused rounding", "asm": "fmadd d0,d1,d2,d3\nfmsub s4,s5,s6,s7\nfnmadd d8,d1,d2,d9\nret",
     "vregs": {1: vd(fd(1.0 + 2.0 ** -52)), 2: vd(fd(1.0 - 2.0 ** -52)), 3: vd(fd(-1.0)),
               5: vs(fs(1.0 + 2.0 ** -23)), 6: vs(fs(1.0 + 2.0 ** -23)), 7: vs(fs(1.0)), 9: vd(fd(-1.0))}, "v": True},
    {"name": "fma inf-inf/den", "asm": "fmadd d0,d1,d2,d3\nfnmsub d4,d5,d5,d6\nfmadd s7,s8,s8,s9\nret",
     "vregs": {1: vd(D_INF), 2: vd(fd(1.0)), 3: vd(D_NINF), 5: vd(fd(2.0 ** -540)), 6: vd(D_DEN),
               8: vs(fs(2.0 ** -75)), 9: vs(S_NDEN)}, "v": True},
    {"name": "fmov s<-w upper junk", "asm": "fmov s0,w1\nfmov d2,x3\nfmov s4,wzr\nfmov d5,xzr\nret",
     "regs": {1: GJ | 0x3F800000, 3: 0xFFF4000000000001},
     "vregs": {0: vd(HI), 2: vd(HI), 4: vd(HI), 5: vd(HI)}, "v": True},
    {"name": "fmov w<-s zero upper", "asm": "fmov w0,s1\nfmov x2,d3\nfmov w4,s4\nret",
     "regs": {0: 0xFFFFFFFFFFFFFFFF, 2: 0xFFFFFFFFFFFFFFFF},
     "vregs": {1: vs(S_SNAN_NEG), 3: vd(D_SNAN_NEG), 4: vs(S_NDEN)}, "v": True},
    {"name": "fmov imm/reg zeroing", "asm": "fmov d0,#-1.25\nfmov s1,#31.0\nfmov d2,d2\nfmov s3,s4\nfmov s5,#0.125\nret",
     "vregs": {0: vd(HI), 1: vd(HI), 2: vd(D_SNAN_NEG), 3: vd(HI), 4: vs(S_SNAN), 5: vd(HI)}, "v": True},
    {"name": "fcsel d/s alias", "asm": "cmp x0,x1\nfcsel d2,d3,d4,lt\nfcsel s5,s6,s5,ge\nfcsel d7,d7,d7,eq\nret",
     "regs": {0: 0x8000000000000000, 1: 1},
     "vregs": {3: vd(D_SNAN_NEG), 4: vd(fd(1.0)), 5: vs(S_NDEN), 6: vs(S_QNAN_PAY), 7: vd(D_NZ)}, "v": True},
    {"name": "fcsel V-flag cond", "asm": "adds x9,x0,x1\nfcsel d2,d3,d4,vs\nfcsel s5,s6,s7,hi\nret",
     "regs": {0: 0x7FFFFFFFFFFFFFFF, 1: 1}, "vregs": {3: vd(fd(1.0)), 4: vd(fd(2.0)), 6: vs(fs(3.0)), 7: vs(fs(4.0))}, "v": True},
    {"name": "fccmp true NaN", "asm": "cmp x0,x0\nfccmp d1,d2,#4,eq\nret",
     "regs": {0: 5}, "vregs": {1: vd(fd(1.0)), 2: vd(D_QNAN_PAY)}, "flags": True},
    {"name": "fccmp false imm", "asm": "cmp x0,x1\nfccmp d1,d2,#9,eq\nret",
     "regs": {0: 5, 1: 6}, "vregs": {1: vd(fd(1.0)), 2: vd(fd(1.0))}, "flags": True},
    {"name": "fccmp +0==-0", "asm": "cmp x0,x0\nfccmp s1,s2,#0,eq\nret",
     "regs": {0: 1}, "vregs": {1: vs(S_PZ), 2: vs(S_NZ)}, "flags": True},
    {"name": "fccmp less den", "asm": "cmp x0,x1\nfccmp d1,d2,#15,lt\nret",
     "regs": {0: 0x8000000000000000, 1: 0}, "vregs": {1: vd(D_NDEN), 2: vd(D_DEN)}, "flags": True},
    {"name": "fccmpe greater inf", "asm": "cmp x0,x1\nfccmpe s1,s2,#0,ne\nret",
     "regs": {0: 1, 1: 2}, "vregs": {1: vs(S_INF), 2: vs(fs(3.4e38))}, "flags": True},
    {"name": "fccmpe sNaN s", "asm": "cmp x0,x1\nfccmpe s1,s2,#2,hs\nret",
     "regs": {0: 9, 1: 2}, "vregs": {1: vs(S_SNAN), 2: vs(fs(0.0))}, "flags": True},
    {"name": "fccmp chained csel", "asm": "fcmp d0,d1\nfccmp d2,d3,#0,mi\ncset x4,gt\ncset x5,vs\nret",
     "vregs": {0: vd(fd(1.0)), 1: vd(fd(2.0)), 2: vd(fd(5.0)), 3: vd(fd(-5.0))}, "flags": True},
]

###############
# fp -> int cases
###############
TOINT_CASES = [
    {"name": "fcvtas ties", "asm": "fcvtas x0,d1\nfcvtas x2,d3\nfcvtas w4,d5\nfcvtas w6,s7\nfcvtas x8,s9\nret",
     "regs": {4: 0xFFFFFFFFFFFFFFFF, 6: 0xFFFFFFFFFFFFFFFF},
     "vregs": {1: vd(fd(2.5)), 3: vd(fd(-2.5)), 5: vd(fd(-0.5)), 7: vs(fs(0.5)), 9: vs(fs(-1.5))}},
    {"name": "fcvtas sat 64", "asm": "fcvtas x0,d1\nfcvtas x2,d3\nfcvtas x4,d5\nfcvtas x6,d7\nfcvtas x8,d9\nret",
     "vregs": {1: vd(fd(9.3e18)), 3: vd(fd(-9.3e18)), 5: vd(D_INF), 7: vd(D_NINF), 9: vd(D_QNAN_NEG)}},
    {"name": "fcvtas sat 32", "asm": "fcvtas w0,d1\nfcvtas w2,d3\nfcvtas w4,d5\nfcvtas w6,s7\nfcvtas w8,d9\nret",
     "regs": {0: 0xFFFFFFFFFFFFFFFF, 2: 0xFFFFFFFFFFFFFFFF, 8: 0xFFFFFFFFFFFFFFFF},
     "vregs": {1: vd(fd(2147483647.5)), 3: vd(fd(-2147483648.5)), 5: vd(fd(-2147483648.4)), 7: vs(S_SNAN), 9: vd(fd(-2147483647.5))}},
    {"name": "fcvtas den/-0", "asm": "fcvtas x0,d1\nfcvtas w2,s3\nfcvtas x4,d5\nret",
     "regs": {0: 7, 2: 7, 4: 7}, "vregs": {1: vd(D_NDEN), 3: vs(S_NZ), 5: vd(fd(0.49999999999999994))}},
    {"name": "fcvtms floor", "asm": "fcvtms x0,d1\nfcvtms w2,d3\nfcvtms x4,s5\nfcvtms w6,s7\nfcvtms x8,d9\nret",
     "regs": {2: 0xFFFFFFFFFFFFFFFF, 6: 0xFFFFFFFFFFFFFFFF},
     "vregs": {1: vd(fd(-0.5)), 3: vd(D_NDEN), 5: vs(fs(-1e-30)), 7: vs(fs(-2147483648.0)), 9: vd(fd(-9223372036854775808.0))}},
    {"name": "fcvtms sat", "asm": "fcvtms w0,d1\nfcvtms w2,d3\nfcvtms x4,d5\nfcvtms x6,s7\nfcvtms w8,s9\nret",
     "vregs": {1: vd(fd(-2147483648.25)), 3: vd(fd(2147483648.0)), 5: vd(fd(-9.3e18)), 7: vs(S_INF), 9: vs(S_QNAN_NEG)}},
    {"name": "fcvtmu neg/frac", "asm": "fcvtmu x0,d1\nfcvtmu w2,d3\nfcvtmu x4,s5\nfcvtmu w6,s7\nret",
     "regs": {0: 7, 2: 0xFFFFFFFFFFFFFFFF, 4: 7, 6: 7}, "vregs": {1: vd(fd(-0.5)), 3: vd(fd(4294967295.99)), 5: vs(S_NINF), 7: vs(fs(0.999))}},
    {"name": "fcvtmu sat", "asm": "fcvtmu x0,d1\nfcvtmu x2,d3\nfcvtmu w4,d5\nfcvtmu w6,s7\nfcvtmu x8,d9\nret",
     "regs": {4: 0xFFFFFFFFFFFFFFFF},
     "vregs": {1: vd(fd(18446744073709549568.0)), 3: vd(fd(18446744073709551616.0)), 5: vd(fd(4294967296.0)),
               7: vs(fs(4294967296.0)), 9: vd(fd(9223372036854775808.0))}},
    {"name": "fcvtmu NaN -0 to zr", "asm": "fcvtmu x0,d1\nfcvtmu w2,s3\nfcvtmu xzr,d4\nret",
     "regs": {0: 7, 2: 7}, "vregs": {1: vd(D_SNAN_NEG), 3: vs(S_NZ), 4: vd(fd(5.0))}},
]

###############
# integer cases
###############
INT_CASES = [
    {"name": "ccmp reg true ovf", "asm": "cmp x9,x9\nccmp x0,x1,#0,eq\nret",
     "regs": {0: 0x8000000000000000, 1: 1}, "flags": True},
    {"name": "ccmp reg false imm", "asm": "cmp x9,x10\nccmp x0,x1,#13,eq\nret",
     "regs": {0: 1, 1: 1, 9: 1, 10: 2}, "flags": True},
    {"name": "ccmp w upper garbage", "asm": "cmp x9,x9\nccmp w0,w1,#0,eq\nret",
     "regs": {0: GJ | 5, 1: 0x7FFFFFFF00000005}, "flags": True},
    {"name": "ccmp w ovf", "asm": "cmp x9,x9\nccmp w0,w1,#0,eq\nret",
     "regs": {0: GJ | 0x80000000, 1: GJ | 1}, "flags": True},
    {"name": "ccmp imm 31", "asm": "cmp x9,x9\nccmp x0,#31,#15,eq\nret",
     "regs": {0: 31}, "flags": True},
    {"name": "ccmp w imm borrow", "asm": "cmp x9,x9\nccmp w0,#1,#2,eq\nret",
     "regs": {0: GJ}, "flags": True},
    {"name": "ccmn reg ovf", "asm": "cmp x9,x10\nccmn x0,x1,#0,lt\nret",
     "regs": {0: 0x7FFFFFFFFFFFFFFF, 1: 1, 9: 0, 10: 1}, "flags": True},
    {"name": "ccmn imm carry w", "asm": "cmp x9,x10\nccmn w0,#1,#0,ne\nret",
     "regs": {0: GJ | 0xFFFFFFFF, 9: 0, 10: 1}, "flags": True},
    {"name": "ccmn false imm vs", "asm": "cmp x9,x9\nccmn x0,#5,#1,ne\ncset x2,vs\nret",
     "regs": {0: 0}, "flags": True},
    {"name": "ccmp zr operand", "asm": "cmp x9,x9\nccmp xzr,x1,#0,eq\nret",
     "regs": {1: 0x8000000000000000}, "flags": True},
    {"name": "ccmp zr rhs w", "asm": "cmp x9,x9\nccmp w0,wzr,#0,eq\nret",
     "regs": {0: GJ}, "flags": True},
    {"name": "ccmp V-flag cond", "asm": "adds x9,x10,x11\nccmp x0,x1,#4,vs\ncset x2,eq\nret",
     "regs": {0: 3, 1: 3, 10: 0x7FFFFFFFFFFFFFFF, 11: 1}, "flags": True},
    {"name": "ngc C=0/1", "asm": "cmp x9,x10\nngc x0,x1\ncmp x10,x9\nngc x2,x3\nret",
     "regs": {1: 5, 3: 5, 9: 1, 10: 2}},
    {"name": "ngcs zero C=1", "asm": "cmp x9,x9\nngcs x0,x1\nret",
     "regs": {1: 0}, "flags": True},
    {"name": "ngcs zero C=0", "asm": "cmp x9,x10\nngcs x0,x1\nret",
     "regs": {1: 0, 9: 1, 10: 2}, "flags": True},
    {"name": "ngcs INT_MIN", "asm": "cmp x9,x9\nngcs x0,x1\nret",
     "regs": {1: 0x8000000000000000}, "flags": True},
    {"name": "ngcs w INT_MIN C=0", "asm": "cmp x9,x10\nngcs w0,w1\nret",
     "regs": {0: 0xFFFFFFFFFFFFFFFF, 1: GJ | 0x80000000, 9: 1, 10: 2}, "flags": True},
    {"name": "ngc w alias", "asm": "cmp x9,x9\nngc w0,w0\nngc w1,wzr\nret",
     "regs": {0: GJ | 7, 1: 0xFFFFFFFFFFFFFFFF}},
    {"name": "ngcs xzr flags only", "asm": "cmp x9,x9\nngcs xzr,x1\nret",
     "regs": {1: 1}, "flags": True},
    {"name": "smnegl extremes", "asm": "smnegl x0,w1,w2\nsmnegl x3,w4,w5\nsmnegl x6,w6,w6\nret",
     "regs": {1: GJ | 0x80000000, 2: GJ | 0x80000000, 4: GJ | 0x7FFFFFFF, 5: GJ | 0x80000000, 6: GJ | 0xFFFFFFFF}},
    {"name": "umnegl extremes", "asm": "umnegl x0,w1,w2\numnegl x3,w4,wzr\numnegl x5,w5,w6\nret",
     "regs": {1: GJ | 0xFFFFFFFF, 2: GJ | 0xFFFFFFFF, 4: 9, 5: GJ | 0x80000000, 6: 2}},
]

###############
# acquire/release and LSE cases
###############
MEM_FF = le((0xFFFFFFFFFFFFFFFF, 8), (0x8899AABBCCDDEEFF, 8))
ORDER_CASES = [
    {"name": "ldar widths zero-ext", "asm": "ldarb w0,[x9]\nldarh w1,[x9]\nldar w2,[x9]\nldar x3,[x9]\nret",
     "regs": {0: GJ, 1: GJ, 2: GJ, 9: DATA}, "mem": MEM_FF},
    {"name": "ldapr widths", "asm": "ldaprb w0,[x9]\nldaprh w1,[x9]\nldapr w2,[x9]\nldapr x3,[x9]\nret",
     "regs": {0: GJ, 1: GJ, 2: GJ, 9: DATA + 8}, "mem": MEM_FF},
    {"name": "ldar base==dest", "asm": "ldar x9,[x9]\nldarb w10,[x10]\nret",
     "regs": {9: DATA + 8, 10: DATA}, "mem": MEM_FF},
    {"name": "stlr widths", "asm": "stlrb w0,[x9]\nstlrh w1,[x10]\nstlr w2,[x11]\nstlr x3,[x12]\nret",
     "regs": {0: 0x1122334455667788, 1: 0x1122334455667788, 2: 0x1122334455667788, 3: 0x1122334455667788,
              9: DATA, 10: DATA + 8, 11: DATA + 16, 12: DATA + 24}, "mem": bytes([0xEE] * 32)},
    {"name": "stlr zr", "asm": "stlr xzr,[x9]\nstlrb wzr,[x10]\nret",
     "regs": {9: DATA, 10: DATA + 9}, "mem": bytes([0xEE] * 16)},
]

LSE_CASES = [
    {"name": "ldaddb wrap", "asm": "ldaddb w0,w1,[x9]\nret",
     "regs": {0: GJ | 0x1FF, 1: GJ, 9: DATA}, "mem": le((0xF0, 1), (0x77, 1))},
    {"name": "ldaddh/l wrap", "asm": "ldaddlh w0,w1,[x9]\nldaddal x2,x3,[x10]\nldadda w4,w5,[x11]\nret",
     "regs": {0: 0x10002, 1: GJ, 2: 1, 3: 0, 4: 1, 5: GJ, 9: DATA, 10: DATA + 8, 11: DATA + 16},
     "mem": le((0xFFFF, 2), (0x5555, 2), (0, 4), (0xFFFFFFFFFFFFFFFF, 8), (0xFFFFFFFF, 4), (0xAAAAAAAA, 4))},
    {"name": "ldclr/ldset/ldeor b h", "asm": "ldclrb w0,w1,[x9]\nldsetah w2,w3,[x10]\nldeoralb w4,w5,[x11]\nldclral x6,x7,[x12]\nret",
     "regs": {0: GJ | 0x0F, 1: GJ, 2: GJ | 0x8001, 3: GJ, 4: 0xFFFFFFFF, 5: GJ, 6: 0x8000000000000001, 7: 0,
              9: DATA, 10: DATA + 2, 11: DATA + 4, 12: DATA + 8},
     "mem": le((0xAB, 1), (0xCD, 1), (0x1234, 2), (0x5A, 1), (0, 3), (0xFFFFFFFFFFFFFFFF, 8))},
    {"name": "ldset/ldeor w x", "asm": "ldsetl w0,w1,[x9]\nldeora x2,x3,[x10]\nldeorh w4,w5,[x11]\nldsetalb w6,w7,[x12]\nret",
     "regs": {0: 0x80000000, 1: GJ, 2: 0xFFFFFFFFFFFFFFFF, 3: 0, 4: 0xFFFF0001, 5: GJ, 6: 0x180, 7: GJ,
              9: DATA, 10: DATA + 8, 11: DATA + 16, 12: DATA + 18},
     "mem": le((0x7FFFFFFF, 4), (0, 4), (0x0123456789ABCDEF, 8), (0x8000, 2), (0x01, 1))},
    {"name": "swp widths", "asm": "swpb w0,w1,[x9]\nswpah w2,w3,[x10]\nswpl w4,w5,[x11]\nswpal x6,x7,[x12]\nret",
     "regs": {0: 0x12345678, 1: GJ, 2: 0xFEDCBA98, 3: GJ, 4: GJ | 0xCAFEF00D, 5: GJ, 6: 0x1111111111111111, 7: 0,
              9: DATA, 10: DATA + 2, 11: DATA + 4, 12: DATA + 8},
     "mem": le((0xFF, 1), (0, 1), (0x8001, 2), (0xFFFFFFFF, 4), (0x2222222222222222, 8))},
    {"name": "swp alias Rs==Rt", "asm": "swp x0,x0,[x9]\nswpb w1,w1,[x10]\nret",
     "regs": {0: 0xAAAA, 1: GJ | 0x1BB, 9: DATA, 10: DATA + 8}, "mem": le((0x5555, 8), (0xCC, 1))},
    {"name": "ldadd Rt==base", "asm": "ldadd x9,x9,[x9]\nldaddh w10,w10,[x11]\nret",
     "regs": {9: DATA, 10: 0x10001, 11: DATA + 8}, "mem": le((3, 8), (0xFFFF, 2))},
    {"name": "ldadd zr src/dst", "asm": "ldadd xzr,x0,[x9]\nldadd x1,xzr,[x10]\nldaddb wzr,w2,[x11]\nret",
     "regs": {0: 7, 1: 5, 2: GJ, 9: DATA, 10: DATA + 8, 11: DATA + 16}, "mem": le((9, 8), (10, 8), (0x80, 1))},
    {"name": "cas success/fail", "asm": "cas x0,x1,[x9]\ncasa x2,x3,[x10]\ncasl w4,w5,[x11]\ncasal w6,w7,[x12]\nret",
     "regs": {0: 5, 1: 99, 2: 6, 3: 98, 4: GJ | 0xFFFFFFFF, 5: 0x12345678, 6: 1, 7: 2,
              9: DATA, 10: DATA + 8, 11: DATA + 16, 12: DATA + 20},
     "mem": le((5, 8), (7, 8), (0xFFFFFFFF, 4), (0x80000000, 4))},
    {"name": "casb/h upper bits", "asm": "casb w0,w1,[x9]\ncasah w2,w3,[x10]\ncaslb w4,w5,[x11]\ncasalh w6,w7,[x12]\nret",
     "regs": {0: GJ | 0x123480, 1: 0x1FF, 2: 0xFFFF0000 | 0x7FFF, 3: 0xABCD, 4: 0x01, 5: 0x02, 6: 0x10000, 7: 0x4444,
              9: DATA, 10: DATA + 2, 11: DATA + 4, 12: DATA + 6},
     "mem": le((0x80, 1), (0, 1), (0x7FFF, 2), (0xFE, 1), (0, 1), (0x0000, 2))},
    {"name": "cas alias/zr", "asm": "cas x0,x0,[x9]\ncas x1,xzr,[x10]\ncas w2,w3,[x2]\nret",
     "regs": {0: 0x4242, 1: 0x77, 2: DATA + 16, 3: 0x99, 9: DATA, 10: DATA + 8},
     "mem": le((0x4242, 8), (0x77, 8), (DATA + 16, 8))},
    {"name": "stadd/stclr/stset/steor", "asm": "staddb w0,[x9]\nstclrh w1,[x10]\nstsetl w2,[x11]\nsteorlb w3,[x12]\nstaddl x4,[x13]\nret",
     "regs": {0: 0x101, 1: 0xFF00F00F, 2: 0x80000000, 3: 0xFF, 4: 0xFFFFFFFFFFFFFFFF,
              9: DATA, 10: DATA + 2, 11: DATA + 4, 12: DATA + 8, 13: DATA + 16},
     "mem": le((0xFF, 1), (0, 1), (0xFFFF, 2), (1, 4), (0x5A, 1), (0, 7), (0, 8))},
    {"name": "st*l h/x widths", "asm": "steorh w0,[x9]\nstclrlb w1,[x10]\nstsetb w2,[x11]\nstclr x3,[x12]\nret",
     "regs": {0: 0xFFFFFFFF, 1: 0x0F, 2: 0x180, 3: 0x00000000FFFFFFFF, 9: DATA, 10: DATA + 2, 11: DATA + 3, 12: DATA + 8},
     "mem": le((0x1234, 2), (0xFF, 1), (0x00, 1), (0, 4), (0xFFFFFFFFFFFFFFFF, 8))},
    {"name": "ldadd sp base", "asm": "ldaddal x0,x1,[sp]\nret",
     "regs": {0: 1, "sp": DATA + 0x40}, "mem": le((0, 0x40), (0xFFFFFFFFFFFFFFFF, 8))},
]

CASES = FP_CASES + TOINT_CASES + INT_CASES + ORDER_CASES + LSE_CASES
