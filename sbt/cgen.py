"""C-expression helpers shared by every AArch64 lifter module: condition codes, register read/write,
shifted/extended operands, memory addressing, SIMD loads/stores, and the vector-operand predicate.
Library; imported by recompile.py and its plug-in families (lift_scalar.py, lift_neon.py)."""
###############
# imports and constants
###############
from __future__ import annotations
from capstone.arm64 import ARM64_OP_REG, ARM64_OP_MEM, ARM64_SFT_LSL, ARM64_SFT_LSR, ARM64_SFT_ASR, ARM64_SFT_ROR

CC = {1: "(c->ZF)", 2: "(!c->ZF)", 3: "(c->CF)", 4: "(!c->CF)", 5: "(c->NF)", 6: "(!c->NF)",
      7: "(c->VF)", 8: "(!c->VF)", 9: "(c->CF&&!c->ZF)", 10: "(!(c->CF&&!c->ZF))",
      11: "(c->NF==c->VF)", 12: "(c->NF!=c->VF)", 13: "(!c->ZF&&c->NF==c->VF)",
      14: "(!(!c->ZF&&c->NF==c->VF))", 15: "(1)", 16: "(1)"}                 # capstone ARM64_CC_* -> C
SFT = {ARM64_SFT_LSL: "<<", ARM64_SFT_LSR: ">>", ARM64_SFT_ASR: "asr", ARM64_SFT_ROR: "ror"}
SIMD = set("vdsqhb")

###############
# registers and operands
###############
def reg_parts(name: str) -> tuple[str, int, int]:
    """(kind, index, width_bits); kind in x/sp/zr/v/d/s/h/b/q."""
    n = {"fp": "x29", "lr": "x30", "wsp": "sp"}.get(name, name)
    if n in ("sp",): return ("sp", 31, 64)
    if n in ("xzr", "wzr"): return ("zr", 31, 32 if name == "wzr" else 64)
    if n[0] == "x" and n[1:].isdigit(): return ("x", int(n[1:]), 64)
    if n[0] == "w" and n[1:].isdigit(): return ("x", int(n[1:]), 32)
    if n[0] in "vdshbq" and n[1:].isdigit(): return (n[0], int(n[1:]), {"q": 128, "d": 64, "s": 32, "h": 16, "b": 8, "v": 128}[n[0]])
    raise NotImplementedError("reg " + name)

def rd(kind: str, idx: int, w: int) -> str:
    """C expression reading an integer register at width w."""
    if kind == "zr": return "(uint32_t)0" if w == 32 else "(uint64_t)0"
    base = "c->SP" if kind == "sp" else "c->X[%d]" % idx
    return "(uint32_t)%s" % base if w == 32 else base

def publish(kind: str, idx: int) -> str:
    """Marker after a write of sp (recompile.localize turns it into a store to the CPU struct before a signal fence, so a signal frame lands below every live guest byte), else ''. A known sp increase leaves it out: a stale lower sp is still safe."""
    return " GD_SPW;" if kind == "sp" else ""

def wr(kind: str, idx: int, w: int, val: str) -> str:
    """C statement writing an integer register; 32-bit writes zero the top half."""
    if kind == "zr": return "(void)(%s);" % val
    base = "c->SP" if kind == "sp" else "c->X[%d]" % idx
    return ("%s = (uint64_t)(uint32_t)(%s);" % (base, val) if w == 32 else "%s = (uint64_t)(%s);" % (base, val)) + publish(kind, idx)

def op_imm(o: object) -> int:
    return o.imm

def shifted_reg(ins: object, o: object, w: int) -> str:
    """Value of a (possibly shifted/extended) register operand, as an unsigned C expr of width w."""
    kind, idx, rw = reg_parts(ins.reg_name(o.reg))
    v = rd(kind, idx, w)
    if o.shift.type in (0,) and not o.ext:
        return "(%s)" % v
    amt = o.shift.value
    if o.shift.type == ARM64_SFT_LSL: return "((%s) << %d)" % (v, amt)
    if o.shift.type == ARM64_SFT_LSR: return "((%s) >> %d)" % (v, amt)
    if o.shift.type == ARM64_SFT_ASR:
        st = "int32_t" if w == 32 else "int64_t"
        return "((uint%d_t)((%s)(%s) >> %d))" % (w, st, v, amt)
    if o.shift.type == ARM64_SFT_ROR:
        return "ror%d(%s, %d)" % (w, v, amt)
    raise NotImplementedError("shift %d" % o.shift.type)

def has_vector(ins: object) -> bool:
    """True when any register operand carries a vector arrangement (v0.4s) or a lane index (v1.h[0])."""
    return any(o.type == ARM64_OP_REG and (o.vas or o.vector_index >= 0) for o in ins.operands)

###############
# memory
###############
def mem_addr(ins: object, o: object, insns_imm: int | None) -> tuple[str, str, str]:
    """Return (addr_expr, writeback_stmt_pre, writeback_stmt_post) for a MEM operand."""
    if o.type != ARM64_OP_MEM: raise NotImplementedError("operand is not memory")  # o.mem would read the union
    m = o.mem
    bk, bi, bw = reg_parts(ins.reg_name(m.base))
    base = "c->SP" if bk == "sp" else "c->X[%d]" % bi
    if m.index:
        ik, ii, iw = reg_parts(ins.reg_name(m.index))
        ew = {1: 8, 2: 16, 3: 32, 4: 64, 5: 8, 6: 16, 7: 32, 8: 64}.get(o.ext, 64)  # UXTB..SXTX
        signed = o.ext in (5, 6, 7, 8)                                 # SXTB/SXTH/SXTW/SXTX sign-extend
        src = rd(ik, ii, 32 if ew <= 32 and o.ext else 64)
        if signed:
            iexpr = "((uint64_t)(int64_t)(int%d_t)(%s))" % (ew, src)
        else:
            iexpr = "((uint64_t)(uint%d_t)(%s))" % (ew, src) if o.ext else "(uint64_t)(%s)" % src
        if o.shift.type == ARM64_SFT_LSL and o.shift.value:
            iexpr = "(%s << %d)" % (iexpr, o.shift.value)
        return ("(%s + %s)" % (base, iexpr), "", "")
    disp = m.disp
    if ins.writeback and insns_imm is not None:                        # post-index: addr=base, then base+=imm
        return ("(%s)" % base, "", "%s += %d;%s" % (base, insns_imm, publish(bk, bi) if insns_imm < 0 else ""))
    if ins.writeback and bk == "sp" and disp < 0:                      # pre-index lowering sp: lower it first, a signal frame must not land on the new slot
        return ("(%s)" % base, "%s += %d;%s" % (base, disp, publish(bk, bi)), "")
    if ins.writeback:                                                  # pre-index: addr=base+disp, base+=disp after access
        return ("(%s + %d)" % (base, disp), "", "%s += %d;" % (base, disp))
    return ("(%s + %d)" % (base, disp), "", "")

def simd_load(idx: int, w: int, addr: str) -> str:
    """Load w bits from addr into V[idx], zeroing the rest of the 128-bit register; V[idx] is written as one whole value (keeps it promotable to a vector register)."""
    if w == 128:
        return "{ V128 _l; memcpy(&_l, (const void*)(%s), 16); c->V[%d]=_l; }" % (addr, idx)
    fld = {64: "u64[0]", 32: "u32[0]", 16: "u16[0]", 8: "u8[0]"}[w]
    ct = {64: "uint64_t", 32: "uint32_t", 16: "uint16_t", 8: "uint8_t"}[w]
    return "{ V128 _l={0}; _l.%s=*(%s*)(%s); c->V[%d]=_l; }" % (fld, ct, addr, idx)

def simd_store(idx: int, w: int, addr: str) -> str:
    """Store the low w bits of V[idx] to addr, reading V[idx] as one whole value."""
    if w == 128:
        return "{ V128 _s=c->V[%d]; memcpy((void*)(%s), &_s, 16); }" % (idx, addr)
    fld = {64: "u64[0]", 32: "u32[0]", 16: "u16[0]", 8: "u8[0]"}[w]
    ct = {64: "uint64_t", 32: "uint32_t", 16: "uint16_t", 8: "uint8_t"}[w]
    return "{ V128 _s=c->V[%d]; *(%s*)(%s)=_s.%s; }" % (idx, ct, addr, fld)
