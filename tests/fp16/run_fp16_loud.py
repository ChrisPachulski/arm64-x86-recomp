"""Regression check: half-precision fcmp/fcmpe and scvtf/ucvtf (integer and fixed-point) must lift as a loud unsupported
trap, never as single precision; the s/d controls must still lift. Prints one line per word."""
###############
# imports and constants
###############
from __future__ import annotations
import os, struct, sys

SBT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "sbt")
sys.path.insert(0, SBT)
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
import recompile

LOUD = [(0x1EE12000, "fcmp h0, h1"), (0x1EE02018, "fcmpe h0, #0.0"), (0x1EE20020, "scvtf h0, w1"),
        (0x9EE30020, "ucvtf h0, x1"), (0x1EC2F420, "scvtf h0, w1, #3")]
LIFTS = [(0x1E212000, "fcmp s0, s1"), (0x1E612000, "fcmp d0, d1"), (0x1E220020, "scvtf s0, w1"), (0x9E630020, "ucvtf d0, x1")]

###############
# functions
###############
def disasm(word: int) -> object:
    """One capstone instruction (with operand detail) for a 32-bit A64 word at 0x1000."""
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    return next(md.disasm(struct.pack("<I", word), 0x1000))

def outcome(word: int) -> tuple[str, str]:
    """(capstone text, 'loud' or 'lifted') for one word through recompile.lift."""
    ins = disasm(word)
    text = "%s %s" % (ins.mnemonic, ins.op_str)
    try:
        recompile.lift(ins, set(), set())
        return text, "lifted"
    except NotImplementedError:
        return text, "loud"

def check(cases: list, want: str) -> list:
    """Lines 'PASS|FAIL word text -> got' for each case against the wanted outcome."""
    rows = []
    for word, expect_text in cases:
        text, got = outcome(word)
        ok = got == want and text == expect_text
        rows.append("%s 0x%08x %-20s -> %s%s" % ("PASS" if ok else "FAIL", word, text, got, "" if text == expect_text else " (decoded as %r)" % text))
    return rows

###############
# run
###############
ROWS = check(LOUD, "loud") + check(LIFTS, "lifted")
for _r in ROWS: print(_r)
FAILS = [r for r in ROWS if r.startswith("FAIL")]
print("summary: %d/%d PASS" % (len(ROWS) - len(FAILS), len(ROWS)))
assert not FAILS, "half-precision lift regression"
