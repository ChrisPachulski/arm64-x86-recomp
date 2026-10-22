"""Lane M7A lifter cases: scalar FP16 fmov, a gap found in review (fmov h<n>, #imm, e.g. word 0x1eee100d = fmov h13, #1.0),
for all 256 imm8 values, plus the sibling FP16 fmov register forms (h<-h, h<-w, w<-h, h<-x, x<-h). Words are emitted with .inst so
no assembler FP16 feature flag is needed; every case checks all V registers (the upper bits must be zeroed) against Unicorn.
Run via: microtest.py cases_m7a"""
###############
# imports and constants
###############
from __future__ import annotations

GARBAGE = (0x1111222233334444, 0x5555666677778888)
REGFORMS = [("fmov h3, h7", 0x1ee04000 | 7 << 5 | 3), ("fmov h0, w5", 0x1ee70000 | 5 << 5 | 0), ("fmov w6, h2", 0x1ee60000 | 2 << 5 | 6),
            ("fmov h9, x4", 0x9ee70000 | 4 << 5 | 9), ("fmov x8, h9", 0x9ee60000 | 9 << 5 | 8), ("fmov h31, wzr", 0x1ee70000 | 31 << 5 | 31)]

###############
# cases
###############
def imm_cases() -> list[dict]:
    """fmov h<d>, #imm8 for every imm8, d cycling through 0..31."""
    return [{"name": "fmov h%d #imm8 0x%02x" % (k % 32, k), "asm": ".inst 0x%08x\nret" % (0x1ee01000 | k << 13 | k % 32), "v": True,
             "vregs": {k % 32: GARBAGE}} for k in range(256)]

def reg_cases() -> list[dict]:
    """The register forms with garbage in every source and destination (upper V bits, upper X bits)."""
    vregs = {i: (GARBAGE[0] + i, GARBAGE[1] + i) for i in (2, 3, 7, 9, 13, 31)}
    return [{"name": "fmov h13 #1.0 word 0x1eee100d", "asm": ".inst 0x1eee100d\nret", "v": True, "vregs": vregs}] + [{"name": n, "asm": ".inst 0x%08x\nret" % w, "v": True, "vregs": vregs, "regs": {4: 0xfedcba9876543abc, 5: 0x89abcdef0000c3f1,
             6: 0xffffffffffffffff, 8: 0xffffffffffffffff}} for n, w in REGFORMS]

###############
# run
###############
CASES = imm_cases() + reg_cases()
assert any(".inst 0x1eee100d" in c["asm"] for c in CASES)
print("cases_m7a: %d cases" % len(CASES))
