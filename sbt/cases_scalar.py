"""Differential microtest cases (vs Unicorn) for lift_scalar.py; run via: sbtenv/bin/python sbt/microtest.py cases_scalar.
Case keys: name, asm, regs {xN: val}, vregs {N: (lo, hi)}, mem bytes at DATA, flags/v (compare NZCV / V regs).
Rows pack several instructions per case on distinct registers; V inputs carry garbage in unused bits."""
###############
# imports and constants
###############
from __future__ import annotations
import struct

DATA = 0x240000000
HI = 0x0123456789ABCDEF                                                # garbage in V upper 64 bits
LO_JUNK = 0xDEADBEEF00000000                                           # garbage above a 32-bit scalar
F32 = {"qn": 0x7FC12345, "qnn": 0xFFC54321, "sn": 0x7F812345, "snn": 0xFF800001, "pz": 0, "nz": 0x80000000,
       "inf": 0x7F800000, "ninf": 0xFF800000, "dn": 0x00000001, "ndn": 0x807FFFFF, "max": 0x7F7FFFFF,
       "one": 0x3F800000, "m25": 0xC0200000, "half": 0x3F000000, "three": 0x40400000, "mhalf": 0xBF000000,
       "p25": 0x40200000, "p15": 0x3FC00000, "m15": 0xBFC00000, "big": 0x4AFFFFFF, "e30": 0x7149F2CA,
       "m4": 0xC0800000, "fus": 0x3F800800, "mone": 0xBF800000, "minn": 0x00800000}
F64 = {"qn": 0x7FF8000000012345, "qnn": 0xFFF800000ABCDEF0, "sn": 0x7FF0000000012345, "snn": 0xFFF4000000000001,
       "pz": 0, "nz": 0x8000000000000000, "inf": 0x7FF0000000000000, "ninf": 0xFFF0000000000000, "dn": 1,
       "ndn": 0x800FFFFFFFFFFFFF, "max": 0x7FEFFFFFFFFFFFFF, "one": 0x3FF0000000000000, "m25": 0xC004000000000000,
       "half": 0x3FE0000000000000, "three": 0x4008000000000000, "mhalf": 0xBFE0000000000000,
       "p25": 0x4004000000000000, "p15": 0x3FF8000000000000, "m15": 0xBFF8000000000000, "big": 0x432FFFFFFFFFFFFF,
       "e30": 0x46293E5939A08CEA, "m4": 0xC010000000000000, "fus": 0x3FF0000008000000, "mone": 0xBFF0000000000000,
       "minn": 0x0010000000000000}
BIN_ROWS = [("qn", "sn"), ("sn", "qn"), ("qn", "qnn"), ("qnn", "qn"), ("one", "qn"), ("qn", "one"), ("one", "sn"),
            ("snn", "one"), ("pz", "nz"), ("nz", "pz"), ("inf", "inf"), ("inf", "pz"), ("ninf", "inf"), ("dn", "ndn"),
            ("max", "max"), ("max", "m25"), ("one", "m25"), ("half", "three"), ("qn", "ninf"), ("ninf", "qn"),
            ("snn", "qn"), ("nz", "nz"), ("sn", "snn"), ("snn", "sn")]
FMA_ROWS = [("inf", "pz", "qn"), ("inf", "pz", "sn"), ("pz", "ninf", "one"), ("sn", "qn", "qnn"), ("qn", "sn", "qnn"),
            ("qn", "qnn", "one"), ("one", "qn", "qnn"), ("one", "one", "sn"), ("max", "max", "ninf"),
            ("one", "three", "m25"), ("fus", "fus", "mone"), ("dn", "dn", "nz"), ("nz", "one", "nz"),
            ("pz", "m25", "pz"), ("inf", "one", "ninf"), ("snn", "one", "qn"), ("sn", "snn", "one"),
            ("sn", "one", "snn"), ("one", "snn", "sn"), ("qnn", "qn", "one")]
UN_ROWS = ["qn", "qnn", "sn", "snn", "pz", "nz", "inf", "ninf", "dn", "ndn", "max", "one", "m25", "half", "mhalf",
           "p25", "p15", "m15", "big", "e30", "m4", "minn"]
TOINT_F32 = [0x40200000, 0xC0200000, 0xBF000000, 0x3F000000, 0x3FC00000, 0x7FC12345, 0x7F812345, 0x7F800000,
             0xFF800000, 0x4F32D05E, 0xCF32D05E, 0x4EFFFFFF, 0x4F000000, 0xCF000000, 0x5F0AC723, 0xDF0AC723,
             0x4F7FFFFF, 0x4F800000, 0x5F000000, 0x5F800000, 0xBF800000, 0x00000001, 0x80000000, 0xBF7FFFFF]
D2S_EXTRA = [0x3FF0000010000000, 0x3FF0000030000000, 0x47EFFFFFE0000000, 0x47EFFFFFDFFFFFFF, 0x3690000000000000,
             0x36A0000000000000, 0x7FF0000000000001, 0xFFF0000020000000, 0xB6A8000000000000]
FCCMP_ROWS = [("mi", 8, "one", "one"), ("pl", 8, "one", "three"), ("vc", 0, "qn", "one"), ("vc", 0, "sn", "one"),
              ("eq", 15, "one", "one"), ("lt", 4, "one", "m25"), ("lt", 4, "m25", "one"), ("ne", 2, "ninf", "inf")]
CCMP_ROWS = [("ccmp", "x", "reg", 5, 5, "lt", 0), ("ccmp", "x", "reg", 0x8000000000000000, 1, "mi", 2),
             ("ccmp", "x", "reg", 5, 5, "eq", 9), ("ccmp", "w", "reg", 0x180000000, 1, "lt", 0),
             ("ccmp", "w", "reg", 3, 5, "ge", 15), ("ccmp", "x", "imm", 7, 31, "mi", 1),
             ("ccmp", "x", "imm", 7, 7, "gt", 6), ("ccmp", "w", "imm", 0xFFFFFFFF00000000, 0, "ne", 4),
             ("ccmp", "w", "imm", 0x7FFFFFFF, 31, "lt", 0), ("ccmn", "w", "imm", 0xFFFFFFFF, 1, "mi", 4),
             ("ccmn", "w", "imm", 0x7FFFFFFF, 1, "eq", 4), ("ccmn", "x", "imm", 0xFFFFFFFFFFFFFFFF, 1, "lt", 0),
             ("ccmn", "x", "imm", 0x7FFFFFFFFFFFFFFF, 1, "ge", 8), ("ccmn", "x", "reg", 0x7FFFFFFFFFFFFFFF, 1, "mi", 0),
             ("ccmn", "w", "reg", 0x80000000, 0x80000000, "lt", 0)]
LSE_RMW = ["ldadd", "ldclr", "ldset", "ldeor", "swp", "cas"]
LSE_ST = ["stadd", "stclr", "stset", "steor"]
MEM_INIT = bytes.fromhex("ffeeddccbbaa9988" "f0debc9a78563412" "0100000000000080" "fe7fffff7fffffff") * 2

###############
# case builders
###############
def table(w: int) -> dict:
    """Named bit patterns for a scalar width."""
    return F32 if w == 32 else F64

def vinit(w: int, bits: int) -> tuple[int, int]:
    """(lo, hi) for a V register holding a w-bit scalar with garbage elsewhere."""
    return ((LO_JUNK | bits) if w == 32 else bits, HI)

def fp_cases(name: str, fmt: str, rows: list, dw: int, sw: int, per: int) -> list:
    """Cases for one FP shape: each row is one instruction on fresh registers (dest first, then sources)."""
    pd, ps = "s" if dw == 32 else "d", "s" if sw == 32 else "d"
    out = []
    for c0 in range(0, len(rows), per):
        asm, vregs = [], {}
        for k, row in enumerate(rows[c0:c0 + per]):
            row = row if isinstance(row, tuple) else (row,)
            base = k * (len(row) + 1)
            vregs[base] = vinit(dw, 0x5555555555555555 & ((1 << dw) - 1))
            regs = ["%s%d" % (ps, base + 1 + j) for j in range(len(row))]
            for j, nm in enumerate(row):
                vregs[base + 1 + j] = vinit(sw, table(sw)[nm] if isinstance(nm, str) else nm)
            asm.append(fmt.format(d="%s%d" % (pd, base), s=regs))
        out.append({"name": "%s #%d" % (name, c0 // per), "asm": "\n".join(asm + ["ret"]), "vregs": vregs, "v": True})
    return out

def toint_cases(m: str, rw: str, sw: int) -> list:
    """fcvt[am][su] into w/x registers from s/d sources, one instruction per row (x0..x27)."""
    vals = TOINT_F32 if sw == 32 else [struct.unpack("<Q", struct.pack("<d", struct.unpack("<f", struct.pack("<I", b))[0]))[0]
                                       for b in TOINT_F32 if b not in (0x7FC12345, 0x7F812345)] + \
        [F64["qn"], F64["sn"], 0x43DFFFFFFFFFFFFF, 0xC3E0000000000000, 0xC3E0000000000001, 0x41DFFFFFFFC00000]
    ps = "s" if sw == 32 else "d"
    asm = ["%s %s%d, %s%d" % (m, rw, k, ps, k) for k in range(len(vals))]
    return [{"name": "%s %s<-%s" % (m, rw, ps), "asm": "\n".join(asm + ["ret"]), "v": True,
             "regs": {k: 0xAAAAAAAAAAAAAAAA for k in range(len(vals))},
             "vregs": {k: vinit(sw, v) for k, v in enumerate(vals)}}]

def fccmp_cases(m: str, w: int) -> list:
    """One fccmp/fccmpe per case after cmp x0,x1 (N=1: mi/lt/ne/vc true; pl/eq false); flags compared."""
    t = table(w); p = "s" if w == 32 else "d"
    return [{"name": "%s %s %s #%d %s/%s" % (m, p, cc, nz, a, b), "flags": True, "v": True,
             "asm": "cmp x0, x1\n%s %s1, %s2, #%d, %s\nret" % (m, p, p, nz, cc),
             "regs": {0: 1, 1: 2}, "vregs": {1: vinit(w, t[a]), 2: vinit(w, t[b])}} for cc, nz, a, b in FCCMP_ROWS]

def ccmp_cases() -> list:
    """One ccmp/ccmn per case after cmp x0,x1 (N=1 baseline); reg and imm forms, both widths."""
    out = []
    for m, r, kind, a, b, cc, nz in CCMP_ROWS:
        op2 = "%s3" % r if kind == "reg" else "#%d" % b
        out.append({"name": "%s %s %s %s #%d" % (m, r, kind, cc, nz), "flags": True,
                    "asm": "cmp x0, x1\n%s %s2, %s, #%d, %s\nret" % (m, r, op2, nz, cc), "regs": {0: 1, 1: 2, 2: a, 3: b}})
    return out

def lse_cases(op: str) -> list:
    """Each order of one LSE family, all four widths per case on distinct addresses; regs and memory compared."""
    out = []
    for o in (("", "l") if op.startswith("st") else ("", "a", "l", "al")):
        asm = []
        for k, (sz, r) in enumerate((("b", "w"), ("h", "w"), ("", "w"), ("", "x"))):
            args = "%s%d, [x%d]" % (r, 10 + k, k) if op.startswith("st") else "%s%d, %s%d, [x%d]" % (r, 10 + k, r, 20 + k, k)
            asm.append("%s%s%s %s" % (op, o, sz, args))
        regs = {k: DATA + 16 * k for k in range(4)}
        regs.update({10: 0xFEDCBA9876543211, 11: 0x8000000000008001, 12: 0x00000000000000FF, 13: 0x0F0F0F0F0F0F0F0F})
        if op == "cas": regs.update({10: 0xABCD00FF, 11: 0x1234, 12: 0x78563412, 13: 0xFFFFFF7FFFFF7FFE})  # b,x match; h,w miss
        regs.update({20: 0xA5A5A5A5A5A5A5A5, 21: 0x5A5A5A5A5A5A5A5A, 22: 0x1111111111111111, 23: 0x2222222222222222})
        out.append({"name": "%s%s b/h/w/x" % (op, o), "asm": "\n".join(asm + ["ret"]), "regs": regs, "mem": MEM_INIT})
    return out

###############
# cases
###############
CASES: list = []
for _m in ("fadd", "fsub", "fmul", "fdiv", "fnmul", "fabd", "fmaxnm", "fminnm"):
    for _w in (32, 64):
        CASES += fp_cases("%s %d" % (_m, _w), _m + " {d}, {s[0]}, {s[1]}", BIN_ROWS, _w, _w, 10)
for _m in ("fmadd", "fmsub", "fnmadd", "fnmsub"):
    for _w in (32, 64):
        CASES += fp_cases("%s %d" % (_m, _w), _m + " {d}, {s[0]}, {s[1]}, {s[2]}", FMA_ROWS, _w, _w, 8)
for _m in ("fabs", "fneg", "fsqrt", "frinta", "frintm", "frintp"):
    for _w in (32, 64):
        CASES += fp_cases("%s %d" % (_m, _w), _m + " {d}, {s[0]}", UN_ROWS, _w, _w, 16)
CASES += fp_cases("fcvt d<-s", "fcvt {d}, {s[0]}", UN_ROWS, 64, 32, 16)
CASES += fp_cases("fcvt s<-d", "fcvt {d}, {s[0]}", UN_ROWS + D2S_EXTRA, 32, 64, 16)
for _w in (32, 64):
    _p = "s" if _w == 32 else "d"
    CASES.append({"name": "fcsel %s conds" % _p, "v": True,
                  "asm": "cmp x0, x1\n" + "\n".join("fcsel %s%d, %s%d, %s%d, %s" % (_p, 3 * k, _p, 3 * k + 1, _p, 3 * k + 2, cc)
                                                    for k, cc in enumerate(("lt", "gt", "eq", "ne", "mi", "vs", "hs", "le")))
                         + "\nret", "regs": {0: 1, 1: 2},
                  "vregs": {r: vinit(_w, table(_w)[("sn", "qnn", "one", "nz", "dn", "inf")[r % 6]] if r % 3 else 0) for r in range(24)}})
    for _m in ("fccmp", "fccmpe"):
        CASES += fccmp_cases(_m, _w)
for _m in ("fcvtas", "fcvtms", "fcvtmu", "fcvtps", "fcvtpu", "fcvtzs", "fcvtzu"):
    for _r in ("w", "x"):
        for _w in (32, 64):
            CASES += toint_cases(_m, _r, _w)
CASES.append({"name": "scvtf/ucvtf fixed-point", "v": True,
              "asm": "scvtf s0, w0, #8\nucvtf s1, w1, #6\nscvtf d2, x2, #32\nucvtf d3, x3, #63\nscvtf s4, x4, #1\n"
                     "ucvtf d5, w5, #16\nscvtf d6, w6\nret",
              "regs": {0: 0xFFFFFF80, 1: 0xFFFFFFFF, 2: 0x8000000000000001, 3: 0xFFFFFFFFFFFFFFFF, 4: 0x7FFFFFFFFFFFFFFF,
                       5: 0x00012345, 6: 0x80000000},
              "vregs": {k: (LO_JUNK, HI) for k in range(7)}})
CASES.append({"name": "fcvtz fixed-point and fpr destination", "v": True,
              "asm": "fcvtzs w0, s0, #8\nfcvtzu w1, s1, #6\nfcvtzs x2, d2, #32\nfcvtzu x3, d3, #63\nfcvtzs w4, s4, #8\n"
                     "fcvtzs s5, s5\nfcvtzu s6, s6\nfcvtzs d7, d7\nfcvtzu d8, d8\nfcvtzs s9, s9\nret",
              "regs": {k: 0xAAAAAAAAAAAAAAAA for k in range(10)},
              "vregs": {0: vinit(32, F32["m25"]), 1: vinit(32, F32["p25"]), 2: vinit(64, F64["m25"]),
                        3: vinit(64, F64["p15"]), 4: vinit(32, 0x4F000000), 5: vinit(32, F32["m25"]),
                        6: vinit(32, 0x4F800000), 7: vinit(64, F64["qn"]), 8: vinit(64, F64["m25"]),
                        9: vinit(32, F32["e30"])}})
CASES.append({"name": "fmov all scalar forms", "v": True,
              "asm": "fmov s1, s2\nfmov s3, #1.0\nfmov s4, w5\nfmov w6, s7\nfmov d8, #-1.5\nfmov d9, d10\nfmov d11, x12\n"
                     "fmov x13, d14\nfmov d15, xzr\nfmov s16, wzr\nfmov s17, #-0.125\nfmov d18, #31.0\nfmov wzr, s19\nret",
              "regs": {5: 0xFFFFFFFF7FC12345, 6: 0xAAAAAAAAAAAAAAAA, 12: 0x7FF0000000000001, 13: 1},
              "vregs": {k: (0xFFF4000000000001 ^ k, HI) for k in range(20)}})
CASES += ccmp_cases()
CASES += [{"name": "ngc x C=0/1", "asm": "cmp x0, x1\nngc x2, x3\ncmp x1, x0\nngc x4, x3\nngc x5, xzr\nret", "flags": True,
           "regs": {0: 1, 1: 2, 3: 5}},
          {"name": "ngc w", "asm": "cmp x0, x1\nngc w2, w3\nret", "regs": {0: 2, 1: 1, 3: 0xFFFFFFFF80000000}},
          {"name": "ngcs xzr C=0", "asm": "cmp x0, x1\nngcs xzr, x3\nret", "flags": True, "regs": {0: 1, 1: 2, 3: 0}},
          {"name": "ngcs xzr C=1", "asm": "cmp x1, x0\nngcs xzr, x3\nret", "flags": True, "regs": {0: 1, 1: 2, 3: 0x8000000000000000}},
          {"name": "ngcs x C=1 zero", "asm": "cmp x1, x0\nngcs x2, x3\nret", "flags": True, "regs": {0: 1, 1: 2, 3: 0}},
          {"name": "ngcs w C=0", "asm": "cmp x0, x1\nngcs w2, w3\nret", "flags": True, "regs": {0: 1, 1: 2, 3: 0x7FFFFFFF}},
          {"name": "smnegl/umnegl", "asm": "smnegl x0, w1, w2\nsmnegl x3, w4, w5\numnegl x6, w7, w8\numnegl x9, w10, w11\n"
                                           "smnegl x12, w12, w13\nret",
           "regs": {1: 0xFFFFFFFF80000000, 2: 0x80000000, 4: 0x123FFFFFFFF, 5: 7, 7: 0xFFFFFFFF, 8: 0xFFFFFFFF,
                    10: 0x80000000, 11: 3, 12: 0x7FFFFFFF, 13: 0x80000000}},
          {"name": "brk (unreachable, lifts+compiles)", "asm": "b 1f\nbrk #1\n1:\nmov x0, #7\nret"}]
for _op in LSE_RMW + LSE_ST:
    CASES += lse_cases(_op)
CASES += [{"name": "ldadd Rt==Rs, swpal base==Rt", "asm": "ldadd w8, w8, [x0]\nswpal x21, x7, [x7]\nldaddal x9, xzr, [x1]\nret",
           "regs": {0: DATA, 8: 0x7, 1: DATA + 8, 9: 3, 7: DATA + 16, 21: 0x99}, "mem": MEM_INIT},
          {"name": "casal base==Rs miss/hit", "asm": "casal x9, x22, [x19]\ncasal x10, x22, [x19]\ncasal w19, w20, [x19]\nret",
           "regs": {19: DATA + 8, 9: 1, 10: 0x123456789ABCDEF0, 22: 0x55, 20: 9},
           "mem": bytes(8) + (0x123456789ABCDEF0).to_bytes(8, "little")},
          {"name": "ldar/ldapr/stlr all widths", "mem": MEM_INIT,
           "asm": "ldar x2, [x0]\nldarb w3, [x0]\nldarh w4, [x0]\nldar w5, [x0]\nldar wzr, [x0]\nldapr x6, [x1]\n"
                  "ldaprb w7, [x1]\nldaprh w8, [x1]\nldapr w9, [x1]\nstlr x10, [x11]\nstlrb w12, [x13]\nstlrh w14, [x15]\n"
                  "stlr w16, [x17]\nstlr xzr, [x18]\nstlr wzr, [x19]\nldar x21, [x21]\nldapr x22, [x22]\nldaprb w23, [sp]\nret",
           "regs": {0: DATA, 1: DATA + 8, 10: 0x1122334455667788, 11: DATA + 0x20, 12: 0xFFFFFFFFFFFFFFAB, 13: DATA + 0x28,
                    14: 0x1234CDEF, 15: DATA + 0x30, 16: 0xFFFFFFFF89ABCDEF, 17: DATA + 0x38, 18: DATA + 0x40,
                    19: DATA + 0x10, 21: DATA + 0x18, 22: DATA, "sp": DATA + 0x48}}]
