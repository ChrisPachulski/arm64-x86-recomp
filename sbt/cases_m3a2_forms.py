"""Lane M3a2 Unicorn-differential case set for the forms added in this lane: SHA-1/256/512, SM3, SM4 (every S-box
entry), eor3/bcax/rax1/xar, u/s mlal/mlsl (+2, by element), saturating and rounding arithmetic, narrowing, pairwise
long adds, fcvt* vector, fmin/fmax(nm)v, half <-> single/double conversions, frintz scalar, crc32(c), nzcv/rndr/cntpct
system registers, casp, ldnp/stnp. Random plus edge operands, every arrangement. Run via: microtest.py cases_m3a2_forms"""
###############
# imports and constants
###############
from __future__ import annotations
import random, struct

DATA = 0x240000000
SEED = 0x3A32
N_RANDOM = 3                                                           # random operand sets per form and arrangement
EXT = ".arch_extension sm4\n.arch_extension sha3\n.arch_extension rng\n.arch_extension crc\n.arch_extension lse\n"
EDGE64 = [0, 2 ** 64 - 1, 0x8000000000000000, 0x7FFFFFFFFFFFFFFF, 0x8080808080808080, 0x7F7F7F7F7F7F7F7F, 0x0001000100010001]
F32 = [0x7F800001, 0xFFC00003, 0x7F800000, 0xFF800000, 0, 0x80000000, 0x3F000000, 0xBF000000, 0x40200000, 0xC0200000,
       0x4F000000, 0xCF000001, 0x5F800000, 0x00000001, 0x7F7FFFFF, 0x3FC00000, 0x40600000, 0xBFC00000]
F64 = [0x7FF0000000000001, 0xFFF8000000000003, 0x7FF0000000000000, 0, 0x8000000000000000, 0x3FE0000000000000,
       0xC004000000000000, 0x43E0000000000000, 0xC3E0000000000001, 0x41DFFFFFFFC00000, 0x3FF8000000000000, 1]
F16 = [0x7C01, 0xFE03, 0x7C00, 0xFC00, 0, 0x8000, 0x0001, 0x03FF, 0x0400, 0x7BFF, 0x3C00, 0xBC01, 0x3555, 0x7E00]
ARR = {8: ["8b", "16b"], 16: ["4h", "8h"], 32: ["2s", "4s"], 64: ["2d"]}

###############
# operand builders
###############
def vrand(rng: random.Random, regs: list[int]) -> dict:
    """Random 128-bit contents for the listed V registers."""
    return {r: (rng.getrandbits(64), rng.getrandbits(64)) for r in regs}

def vedge(k: int, regs: list[int]) -> dict:
    """Edge-pattern contents (rotating through EDGE64) for the listed V registers."""
    return {r: (EDGE64[(k + j) % len(EDGE64)], EDGE64[(k + 2 * j + 1) % len(EDGE64)]) for j, r in enumerate(regs)}

def lanes(vals: list[int], bits: int) -> tuple[int, int]:
    """Lane values (lane 0 first) -> (lo, hi) halves."""
    q = sum((v & ((1 << bits) - 1)) << (i * bits) for i, v in enumerate(vals))
    return q & (2 ** 64 - 1), q >> 64

def vcase(name: str, asm: str, vregs: dict, regs: dict | None = None, **extra: object) -> dict:
    """One microtest case comparing all V registers (and flags when asked)."""
    return {"name": name, "asm": EXT + asm + "\nret", "vregs": vregs, "regs": regs or {}, "v": True, **extra}

def operand_sets(rng: random.Random, regs: list[int]) -> list[dict]:
    """N_RANDOM random sets plus two edge sets."""
    return [vrand(rng, regs) for _ in range(N_RANDOM)] + [vedge(k, regs) for k in (0, 3)]

###############
# case families
###############
def crypto_cases(rng: random.Random) -> list[dict]:
    """SHA-1/256/512, SM3, eor3/bcax/rax1/xar, with distinct and aliased registers."""
    forms = ["sha1c q0, s1, v2.4s", "sha1p q0, s1, v2.4s", "sha1m q0, s1, v2.4s", "sha1h s0, s1", "sha1h s0, s0",
             "sha1su0 v0.4s, v1.4s, v2.4s", "sha1su1 v0.4s, v1.4s", "sha256h q0, q1, v2.4s", "sha256h2 q0, q1, v2.4s",
             "sha256su0 v0.4s, v1.4s", "sha256su1 v0.4s, v1.4s, v2.4s", "sha512h q0, q1, v2.2d", "sha512h2 q0, q1, v2.2d",
             "sha512su0 v0.2d, v1.2d", "sha512su1 v0.2d, v1.2d, v2.2d", "sm3ss1 v0.4s, v1.4s, v2.4s, v3.4s",
             "sm3partw1 v0.4s, v1.4s, v2.4s", "sm3partw2 v0.4s, v1.4s, v2.4s", "sm4ekey v0.4s, v1.4s, v2.4s",
             "sm4e v0.4s, v1.4s", "sm4e v0.4s, v0.4s", "eor3 v0.16b, v1.16b, v2.16b, v3.16b", "eor3 v2.16b, v1.16b, v0.16b, v2.16b",
             "bcax v0.16b, v1.16b, v2.16b, v3.16b", "rax1 v0.2d, v1.2d, v2.2d", "sha256h q1, q1, v1.4s"]
    forms += ["sm3tt%s v0.4s, v1.4s, v2.s[%d]" % (k, i) for k in ("1a", "1b", "2a", "2b") for i in range(4)]
    forms += ["xar v0.2d, v1.2d, v2.2d, #%d" % i for i in (0, 1, 32, 63)]
    return [vcase("%s #%d" % (f, k), f, vs) for f in forms for k, vs in enumerate(operand_sets(rng, [0, 1, 2, 3]))]

def sm4_sbox_cases(rng: random.Random) -> list[dict]:
    """sm4e with a zero state so round 0 feeds key bytes 4k..4k+3 to the S-box: all 256 entries across 64 cases."""
    return [vcase("sm4e sbox %02x..%02x" % (4 * k, 4 * k + 3), "sm4e v0.4s, v1.4s",
                  {0: (0, 0), 1: (int.from_bytes(bytes(range(4 * k, 4 * k + 4)), "little") | rng.getrandbits(32) << 32,
                                  rng.getrandbits(64))}) for k in range(64)]

def long_cases(rng: random.Random) -> list[dict]:
    """u/s mlal/mlsl, their 2 forms, and by-element forms in every arrangement."""
    out = []
    for op in ("umlal", "smlal", "umlsl", "smlsl"):
        for d, a, a2 in (("8h", "8b", "16b"), ("4s", "4h", "8h"), ("2d", "2s", "4s")):
            out += [vcase("%s %s #%d" % (op, d, k), "%s v0.%s, v1.%s, v2.%s" % (op, d, a, a), vs)
                    for k, vs in enumerate(operand_sets(rng, [0, 1, 2]))]
            out += [vcase("%s2 %s #%d" % (op, d, k), "%s2 v0.%s, v1.%s, v2.%s" % (op, d, a2, a2), vs)
                    for k, vs in enumerate(operand_sets(rng, [0, 1, 2]))]
        for d, a, a2, t, n in (("4s", "4h", "8h", "h", 8), ("2d", "2s", "4s", "s", 4)):
            for i in (0, n - 1, n // 2):
                vs = vrand(rng, [0, 1, 2])
                out += [vcase("%s %s elem %d" % (op, d, i), "%s v0.%s, v1.%s, v2.%s[%d]" % (op, d, a, t, i), vs),
                        vcase("%s2 %s elem %d" % (op, d, i), "%s2 v0.%s, v1.%s, v2.%s[%d]" % (op, d, a2, t, i), vs)]
    return out

def arith_cases(rng: random.Random) -> list[dict]:
    """sabd/uabd, saturating add/sub, register shifts (edge shift bytes), rounding shifts by immediate (+ scalar d)."""
    out = []
    for e, arrs in ARR.items():
        for arr in arrs:
            ops3 = ["uqadd", "uqsub", "sqadd", "sqsub", "sqshl", "srshl", "urshl"] + (["sabd", "uabd"] if e < 64 else [])
            for op in ops3:
                out += [vcase("%s %s #%d" % (op, arr, k), "%s v0.%s, v1.%s, v2.%s" % (op, arr, arr, arr), vs)
                        for k, vs in enumerate(operand_sets(rng, [0, 1, 2]))]
            shifts = [-128, -e - 1, -e, -e + 1, -1, 0, 1, e - 1, e, 127]
            n = 128 // e
            for op in ("sqshl", "srshl", "urshl"):
                sh = [shifts[(j + k) % len(shifts)] for j in range(n) for k in (0,)]
                out.append(vcase("%s %s edge shifts" % (op, arr), "%s v0.%s, v1.%s, v2.%s" % (op, arr, arr, arr),
                                 {0: (0, 0), 1: vrand(rng, [1])[1], 2: lanes(sh, e)}))
            for op in ("srshr", "urshr", "srsra", "ursra"):
                out += [vcase("%s %s #%d" % (op, arr, i), "%s v0.%s, v1.%s, #%d" % (op, arr, arr, i), vrand(rng, [0, 1]))
                        for i in (1, e // 2, e)]
    out += [vcase("%s d #%d" % (op, i), "%s d0, d1, #%d" % (op, i), vrand(rng, [0, 1]))
            for op in ("srshr", "urshr", "srsra", "ursra") for i in (1, 15, 64)]
    return out

def narrow_cases(rng: random.Random) -> list[dict]:
    """sq/uq xtn, sqxtun, sq/uq shrn, addhn/subhn, low and 2 (high) forms, every arrangement."""
    out = []
    for d, d2, s, e in (("8b", "16b", "8h", 16), ("4h", "8h", "4s", 32), ("2s", "4s", "2d", 64)):
        for op, tail in (("sqxtn", ""), ("uqxtn", ""), ("sqxtun", ""), ("sqshrn", ", #%d" % (e // 4)),
                         ("uqshrn", ", #1"), ("sqshrn", ", #%d" % (e // 2)), ("addhn", ", v2.%s" % s), ("subhn", ", v2.%s" % s)):
            for k, vs in enumerate(operand_sets(rng, [0, 1, 2])):
                out += [vcase("%s %s%s #%d" % (op, d, tail, k), "%s v0.%s, v1.%s%s" % (op, d, s, tail), vs),
                        vcase("%s2 %s%s #%d" % (op, d2, tail, k), "%s2 v0.%s, v1.%s%s" % (op, d2, s, tail), vs)]
    return out

def pairwise_cases(rng: random.Random) -> list[dict]:
    """uaddlp/saddlp/uadalp/sadalp in all six arrangements."""
    return [vcase("%s %s #%d" % (op, d, k), "%s v0.%s, v1.%s" % (op, d, s), vs)
            for op in ("uaddlp", "saddlp", "uadalp", "sadalp")
            for d, s in (("4h", "8b"), ("8h", "16b"), ("2s", "4h"), ("4s", "8h"), ("1d", "2s"), ("2d", "4s"))
            for k, vs in enumerate(operand_sets(rng, [0, 1]))]

def float_cases(rng: random.Random) -> list[dict]:
    """fcvt{a,m,p,n}{s,u} vector, fmin/fmax(nm)v, fcvtl/fcvtl2 half, scalar fcvt h<->s/d, frintz scalar: specials + random."""
    out = []
    for k in range(0, len(F32), 4):
        v32 = {1: lanes(F32[k:k + 4] + F32[:4 - len(F32[k:k + 4])], 32), 0: (0, 0)}
        v64 = {1: lanes((F64 + F64)[k // 2 * 2:k // 2 * 2 + 2], 64), 0: (0, 0)}
        out += [vcase("fcvt%s%s 4s specials %d" % (r, u, k), "fcvt%s%s v0.4s, v1.4s" % (r, u), v32) for r in "ampn" for u in "su"]
        out += [vcase("fcvt%s%s 2s specials %d" % (r, u, k), "fcvt%s%s v0.2s, v1.2s" % (r, u), v32) for r in "ampn" for u in "su"]
        out += [vcase("fcvt%s%s 2d specials %d" % (r, u, k), "fcvt%s%s v0.2d, v1.2d" % (r, u), v64) for r in "ampn" for u in "su"]
        out += [vcase("%s specials %d" % (op, k), "%s s0, v1.4s" % op, v32) for op in ("fmaxnmv", "fminnmv", "fmaxv", "fminv")]
        out += [vcase("frintz s specials %d" % k, "frintz s0, s1", v32), vcase("frintz d specials %d" % k, "frintz d0, d1", v64)]
    for k in range(0, len(F16), 4):
        h = F16[k:k + 8] + F16[:max(0, 8 - len(F16[k:k + 8]))]
        vh = {1: lanes(h, 16), 0: (0, 0)}
        out += [vcase("fcvtl 4s<-4h specials %d" % k, "fcvtl v0.4s, v1.4h", vh), vcase("fcvtl2 4s<-8h specials %d" % k, "fcvtl2 v0.4s, v1.8h", vh),
                vcase("fcvt s<-h %d" % k, "fcvt s0, h1", vh), vcase("fcvt d<-h %d" % k, "fcvt d0, h1", vh)]
    halfway = [0x3F801000, 0x3F803000, 0x387FC000, 0x33000000, 0x33000001, 0x477FF000, 0x477FEFFF, 0x38800000, 0x387FFFFF]
    for k, x in enumerate(F32 + halfway + [rng.getrandbits(32) for _ in range(6)]):
        out.append(vcase("fcvt h<-s %#x" % x, "fcvt h0, s1", {0: (0, 0), 1: (x, 0)}))
    dhalf = [0x3FF0020000000000, 0x3FF0060000000000, 0x3FF0020000000001, 0x3E70000000000000, 0x40EFFE0000000000, 0x40EFFDFFFFFFFFFF,
             0x3E6FFFFFFFFFFFFF, 0x3F10000000000000, 0x0000000000000001]
    for k, x in enumerate(F64 + dhalf + [rng.getrandbits(64) for _ in range(6)]):
        out.append(vcase("fcvt h<-d %#x" % x, "fcvt h0, d1", {0: (0, 0), 1: (x, 0)}))
    out += [vcase("fcvtl 4s<-4h random %d" % k, "fcvtl v0.4s, v1.4h", vrand(rng, [0, 1])) for k in range(3)]
    return out

def scalar_cases(rng: random.Random) -> list[dict]:
    """crc32(c) b/h/w/x, msr/mrs nzcv, rndr success, cntpct monotonic, casp family, ldnp/stnp every width."""
    out = []
    for c in ("", "c"):
        for s, rt in (("b", "w"), ("h", "w"), ("w", "w"), ("x", "x")):
            out += [{"name": "crc32%s%s #%d" % (c, s, k), "asm": EXT + "crc32%s%s w0, w1, %s2\nret" % (c, s, rt),
                     "regs": {1: rng.getrandbits(64), 2: rng.getrandbits(64)}} for k in range(3)]
    out += [{"name": "msr/mrs nzcv %#x" % v, "asm": EXT + "msr nzcv, x1\nmrs x2, nzcv\ncset x3, hi\ncset x4, lt\nret",
             "regs": {1: v}, "flags": True} for v in (0, 0xF0000000, 0xA5A5A5A5A5A5A5A5, 0x50000000, 0x0FFFFFFF)]
    out.append({"name": "rndr success flags", "asm": EXT + "mrs x0, rndr\ncset x1, ne\ncmp x0, #0\ncset x2, ne\nmov x0, #0\n"
                "mrs x3, rndrrs\ncset x4, ne\nmov x3, #0\nret", "flags": True})
    out.append({"name": "cntpct monotonic", "asm": EXT + "mrs x0, cntpct_el0\nmrs x1, cntpct_el0\ncmp x1, x0\ncset x2, hs\n"
                "mov x0, #0\nmov x1, #0\nret"})
    for op in ("casp", "caspa", "caspl", "caspal"):
        for hit in (True, False):
            old = (rng.getrandbits(64), rng.getrandbits(64))
            mem = struct.pack("<2Q", *old) + bytes(16)
            cmp = old if hit else (old[0] ^ 1, old[1])
            out.append({"name": "%s x %s" % (op, "hit" if hit else "miss"), "asm": EXT + "%s x4, x5, x0, x1, [x8]\nret" % op,
                        "regs": {4: cmp[0], 5: cmp[1], 0: rng.getrandbits(64), 1: rng.getrandbits(64), 8: DATA}, "mem": mem})
            cw = (old[0] & 0xFFFFFFFF, old[0] >> 32) if hit else (old[0] & 0xFFFFFFFF, (old[0] >> 32) ^ 4)
            out.append({"name": "%s w %s" % (op, "hit" if hit else "miss"), "asm": EXT + "%s w4, w5, w0, w1, [x8]\nret" % op,
                        "regs": {4: cw[0] | 0xDEAD << 40, 5: cw[1], 0: rng.getrandbits(64), 1: rng.getrandbits(64), 8: DATA}, "mem": mem})
    mem = bytes(rng.getrandbits(8) for _ in range(0x200))
    for r, sz in (("w", 4), ("x", 8), ("s", 4), ("d", 8), ("q", 16)):
        out.append(vcase("ldnp/stnp %s" % r, "ldnp %s1, %s2, [x3, #%d]\nstnp %s2, %s1, [x3, #%d]\nldnp %s4, %s5, [x3, #-%d]"
                         % (r, r, 4 * sz, r, r, 8 * sz, r, r, 2 * sz), vrand(rng, [1, 2, 4, 5]), {3: DATA + 0x100}, mem=mem))
    out.append({"name": "ldnp base is dest", "asm": EXT + "ldnp x3, x4, [x3, #16]\nret", "regs": {3: DATA + 0x100}, "mem": mem})
    return out

###############
# assemble the case list
###############
RNG = random.Random(SEED)
CASES = (crypto_cases(RNG) + sm4_sbox_cases(RNG) + long_cases(RNG) + arith_cases(RNG) + narrow_cases(RNG)
         + pairwise_cases(RNG) + float_cases(RNG) + scalar_cases(RNG))
print("cases_m3a2_forms: %d cases" % len(CASES))
