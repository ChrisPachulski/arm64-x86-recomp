"""Scalar (non-vector) AArch64 families for the recompiler: scalar FP, conditional compare, atomics/ordering,
and misc integer ops. recompile.lift() routes here when the instruction has no vector operand and its base
mnemonic is in MNEMONICS. Library; proven by sbt/microtest.py cases_scalar."""
###############
# imports and constants
###############
from __future__ import annotations
import re, struct
from capstone.arm64 import ARM64_OP_REG, ARM64_OP_IMM, ARM64_OP_FP
from cgen import CC, reg_parts, rd, wr, mem_addr

LSE_OPS = ("ldadd", "ldclr", "ldset", "ldeor", "swp", "cas", "stadd", "stclr", "stset", "steor")
ORDERS = ("", "a", "l", "al")
SIZES = ("", "b", "h")
LSE_RE = re.compile(r"^(%s)(al|a|l)?(b|h)?$" % "|".join(LSE_OPS))
ORD_RE = re.compile(r"^(ldar|ldapr|stlr)(b|h)?$")
RMW_ORDER = {"": "__ATOMIC_RELAXED", "a": "__ATOMIC_ACQUIRE", "l": "__ATOMIC_RELEASE", "al": "__ATOMIC_SEQ_CST"}
CAS_FAIL = {"": "__ATOMIC_RELAXED", "a": "__ATOMIC_ACQUIRE", "l": "__ATOMIC_RELAXED", "al": "__ATOMIC_SEQ_CST"}
RMW_FN = {"ldadd": "__atomic_fetch_add", "ldclr": "__atomic_fetch_and", "ldset": "__atomic_fetch_or",
          "ldeor": "__atomic_fetch_xor", "swp": "__atomic_exchange_n"}
LSE_CLAIM = {op + o + s for op in LSE_OPS for o in ORDERS for s in SIZES
             if not (op.startswith("st") and o in ("a", "al"))}         # st* aliases exist only plain and l
FP_UNARY = {"fabs", "fneg", "fsqrt", "frinta", "frintm", "frintp", "fcvt"}
FP_BINARY = {"fadd", "fsub", "fmul", "fdiv", "fnmul", "fabd", "fmaxnm", "fminnm"}
FP_FMA = {"fmadd": (False, False), "fmsub": (False, True), "fnmadd": (True, True), "fnmsub": (True, False)}  # (neg addend, neg n)
FP_TOINT = {"fcvtas": (0, 0), "fcvtms": (1, 0), "fcvtmu": (1, 1), "fcvtps": (2, 0), "fcvtpu": (2, 1),
            "fcvtzs": (3, 0), "fcvtzu": (3, 1)}                         # (rounding: 0 ties-away, 1 floor, 2 ceil, 3 trunc; unsigned)
FRINT_MODE = {"frinta": 0, "frintm": 1, "frintp": 2}
CASP_RE = re.compile(r"^casp(al|a|l)?$")
CRC = {"crc32" + s: (0xEDB88320, n) for s, n in (("b", 1), ("h", 2), ("w", 4), ("x", 8))}
CRC.update({"crc32c" + s: (0x82F63B78, n) for s, n in (("b", 1), ("h", 2), ("w", 4), ("x", 8))})   # reflected polynomials
MNEMONICS: set = ({"brk", "ccmp", "ccmn", "ngc", "ngcs", "smnegl", "umnegl", "fmov", "fcsel", "fccmp", "fccmpe", "mrs", "msr"}
                  | FP_UNARY | FP_BINARY | set(FP_FMA) | set(FP_TOINT) | LSE_CLAIM | set(CRC)
                  | {"casp" + o for o in ORDERS} | {b + s for b in ("ldar", "ldapr", "stlr") for s in SIZES})
SIGN = {32: "0x80000000u", 64: "0x8000000000000000ULL"}
C_HELPERS = r"""
#define S_GEN(N,T,F,SG,EXPM,QB,FMA,SQRT,RND,FLR,CEIL) \
static inline F s_tf##N(T u){F f;memcpy(&f,&u,sizeof f);return f;} \
static inline T s_fu##N(F f){T u;memcpy(&u,&f,sizeof u);return u;} \
static inline int s_isnan##N(T x){return (x&~(T)SG)>(T)EXPM;} \
static inline int s_issnan##N(T x){return s_isnan##N(x)&&!(x&(T)QB);} \
static inline int s_isqnan##N(T x){return s_isnan##N(x)&&(x&(T)QB);} \
static inline T s_dn##N(T r){return s_isnan##N(r)?((T)EXPM|(T)QB):r;} \
static inline int s_nan2_##N(T a,T b,T*r){ \
  if(s_issnan##N(a)){*r=a|(T)QB;return 1;} if(s_issnan##N(b)){*r=b|(T)QB;return 1;} \
  if(s_isnan##N(a)){*r=a;return 1;} if(s_isnan##N(b)){*r=b;return 1;} return 0;} \
static __attribute__((noinline,cold,preserve_all)) F s_nanbin##N(F fa,F fb,F q){ \
  T a=s_fu##N(fa), b=s_fu##N(fb), r;if(s_nan2_##N(a,b,&r))return s_tf##N(r);return s_tf##N(s_dn##N(s_fu##N(q)));} \
static inline T s_fmul##N(T a,T b){F x=s_tf##N(a),y=s_tf##N(b),q=x*y; if(__builtin_expect(q!=q,0))q=s_nanbin##N(x,y,q); return s_fu##N(q);} \
static inline T s_fsub##N(T a,T b){F x=s_tf##N(a),y=s_tf##N(b),q=x-y; if(__builtin_expect(q!=q,0))q=s_nanbin##N(x,y,q); return s_fu##N(q);} \
static inline T s_fadd##N(T a,T b){F x=s_tf##N(a),y=s_tf##N(b),q=x+y; if(__builtin_expect(q!=q,0))q=s_nanbin##N(x,y,q); return s_fu##N(q);} \
static inline T s_fdiv##N(T a,T b){F x=s_tf##N(a),y=s_tf##N(b),q=x/y; if(__builtin_expect(q!=q,0))q=s_nanbin##N(x,y,q); return s_fu##N(q);} \
static __attribute__((noinline,cold,preserve_all)) F s_nanfma##N(F fa,F fn,F fm){ \
  T a=s_fu##N(fa), n=s_fu##N(fn), m=s_fu##N(fm); \
  T an=n&~(T)SG, am=m&~(T)SG; int iz=(an==(T)EXPM&&am==0)||(an==0&&am==(T)EXPM); \
  if(iz&&s_isqnan##N(a))return s_tf##N((T)EXPM|(T)QB); \
  if(s_issnan##N(a))return s_tf##N(a|(T)QB); if(s_issnan##N(n))return s_tf##N(n|(T)QB); if(s_issnan##N(m))return s_tf##N(m|(T)QB); \
  if(s_isnan##N(a))return s_tf##N(a); if(s_isnan##N(n))return s_tf##N(n); if(s_isnan##N(m))return s_tf##N(m); \
  return s_tf##N(s_dn##N(s_fu##N(FMA(s_tf##N(n),s_tf##N(m),s_tf##N(a)))));} \
static inline T s_fma##N(T a,T n,T m){ \
  F x=s_tf##N(a),y=s_tf##N(n),z=s_tf##N(m),q=FMA(y,z,x); if(__builtin_expect(q!=q,0))q=s_nanfma##N(x,y,z); return s_fu##N(q);} \
static __attribute__((noinline,cold,preserve_all)) F s_nansqrt##N(F fa){ \
  T a=s_fu##N(fa); if(s_isnan##N(a))return s_tf##N(a|(T)QB); if((a&(T)SG)&&(a&~(T)SG))return s_tf##N((T)EXPM|(T)QB); return SQRT(fa);} \
static inline T s_sqrt##N(T a){F x=s_tf##N(a),q=SQRT(x); if(__builtin_expect(q!=q,0))q=s_nansqrt##N(x); return s_fu##N(q);} \
static inline T s_maxnm##N(T a,T b,int mn){ \
  T lim=mn?(T)EXPM:((T)EXPM|(T)SG); T r; \
  if(s_isqnan##N(a)&&!s_isqnan##N(b))a=lim; else if(s_isqnan##N(b)&&!s_isqnan##N(a))b=lim; \
  if(s_nan2_##N(a,b,&r))return r; \
  F x=s_tf##N(a), y=s_tf##N(b); \
  if(x==y)return mn?(a|b):(a&b); \
  return mn?(x<y?a:b):(x>y?a:b);} \
static __attribute__((noinline,cold,preserve_all)) F s_nanq##N(F fa){return s_tf##N(s_fu##N(fa)|(T)QB);} \
static inline T s_frint##N(T a,int md){ \
  F x=s_tf##N(a),q=md==0?RND(x):md==1?FLR(x):CEIL(x); if(__builtin_expect(q!=q,0))q=s_nanq##N(x); return s_fu##N(q);}
S_GEN(32,uint32_t,float,0x80000000u,0x7f800000u,0x00400000u,fmaf,sqrtf,roundf,floorf,ceilf)
S_GEN(64,uint64_t,double,0x8000000000000000ULL,0x7ff0000000000000ULL,0x0008000000000000ULL,fma,sqrt,round,floor,ceil)
static __attribute__((noinline,cold,preserve_all)) double s_nancvt_sd(float f){
  uint32_t a=s_fu32(f); return s_tf64(((uint64_t)(a>>31)<<63)|0x7ff8000000000000ULL|((uint64_t)(a&0x7fffffu)<<29));}
static inline uint64_t s_cvt_sd(uint32_t a){
  float x=s_tf32(a); double q=(double)x; if(__builtin_expect(q!=q,0))q=s_nancvt_sd(x); return s_fu64(q);}
static __attribute__((noinline,cold,preserve_all)) float s_nancvt_ds(double f){
  uint64_t a=s_fu64(f); return s_tf32(((uint32_t)(a>>63)<<31)|0x7fc00000u|(uint32_t)((a>>29)&0x7fffffu));}
static inline uint32_t s_cvt_ds(uint64_t a){
  double x=s_tf64(a); float q=(float)x; if(__builtin_expect(q!=q,0))q=s_nancvt_ds(x); return s_fu32(q);}
static inline uint64_t s_f2i(double v,int md,int bits,int uns){
  if(v!=v)return 0;
  double r=md==0?round(v):md==1?floor(v):md==2?ceil(v):trunc(v);
  if(uns){ if(r<=0)return 0;
    if(r>=(bits==64?18446744073709551616.0:4294967296.0))return bits==64?~0ULL:0xffffffffULL;
    return (uint64_t)r; }
  double lim=bits==64?9223372036854775808.0:2147483648.0;
  if(r>=lim)return bits==64?0x7fffffffffffffffULL:0x7fffffffULL;
  if(r<-lim)return bits==64?0x8000000000000000ULL:0xffffffff80000000ULL;
  return (uint64_t)(int64_t)r;}
static inline uint32_t s_crc(uint32_t acc,uint64_t v,int bytes,uint32_t poly){
  acc^=(uint32_t)v; v>>=32; for(int i=0;i<8*bytes;i++){ acc=(acc>>1)^(poly&(0u-(acc&1))); if(i==31) acc^=(uint32_t)v; } return acc;}
static inline uint16_t s_f64to16(uint64_t u){uint64_t m=u&0xfffffffffffffULL; uint32_t s=(uint32_t)(u>>48)&0x8000; int ex=(int)(u>>52)&0x7ff;
  if(ex==0x7ff) return (uint16_t)(m?s|0x7e00|((m>>42)&0x1ff):s|0x7c00); if(!ex) return (uint16_t)s; m|=1ULL<<52;
  int e=ex-1008, sh=e>=1?42:43-e; if(sh>63) return (uint16_t)s; if(e<1) e=0;
  uint64_t r=m>>sh, rem=m&((1ULL<<sh)-1), hf=1ULL<<(sh-1); if(rem>hf||(rem==hf&&(r&1))) r++;
  uint64_t h=(e?(uint64_t)(e-1)<<10:0)+r; return (uint16_t)(s|(h>=0x7c00?0x7c00:h));}
static inline __attribute__((target("rdrnd"))) int s_rdrand(uint64_t*v){unsigned long long x=0;
  for(int i=0;i<16;i++) if(__builtin_ia32_rdrand64_step(&x)){*v=x; return 1;} *v=0; return 0;}
uint64_t mach_absolute_time(void);
static inline uint64_t s_cntpct(void){return (uint64_t)((unsigned __int128)mach_absolute_time()*3/125);}   /* Intel ns -> 24 MHz ticks */
"""                                                                    # static inline C appended to recompile.C_PRELUDE; prefix names s_

###############
# register access
###############
def vreg(ins: object, o: object) -> tuple[str, int, int]:
    """(kind, idx, width) of a scalar FP register operand; only s and d are lifted."""
    k, i, w = reg_parts(ins.reg_name(o.reg))
    if k not in ("s", "d"): raise NotImplementedError("scalar fp reg " + ins.reg_name(o.reg))
    return k, i, w

def vget(idx: int, w: int) -> str:
    """C read of the low w bits of V[idx]."""
    return "c->V[%d].%s" % (idx, "u32[0]" if w == 32 else "u64[0]")

def vput(idx: int, w: int, val: str) -> str:
    """C statement writing a scalar FP result and zeroing the rest of the 128-bit register."""
    cast = {16: "(uint64_t)(uint16_t)", 32: "(uint64_t)(uint32_t)"}.get(w, "(uint64_t)")
    return "c->V[%d].u64[0]=%s(%s); c->V[%d].u64[1]=0;" % (idx, cast, val, idx)

def ireg(ins: object, o: object) -> tuple[str, int, int]:
    """(kind, idx, width) of an integer register operand."""
    return reg_parts(ins.reg_name(o.reg))

def set_nzcv(nzcv: int) -> str:
    """C statements loading NZCV from a 4-bit immediate."""
    return "c->NF=%d; c->ZF=%d; c->CF=%d; c->VF=%d;" % ((nzcv >> 3) & 1, (nzcv >> 2) & 1, (nzcv >> 1) & 1, nzcv & 1)

###############
# integer families
###############
def lift_ccmp(ins: object, m: str, ops: list) -> str:
    """ccmp/ccmn reg|imm: flags of Rn-op2 (or Rn+op2) when cond holds, else the #nzcv immediate."""
    k, i, w = ireg(ins, ops[0])
    mask = (1 << w) - 1
    if ops[1].type == ARM64_OP_IMM: b = "0x%xULL" % (ops[1].imm & mask)
    else: b = rd(*ireg(ins, ops[1])[:2], w)
    bb, ci = ("(~(uint64_t)(%s))" % b, "1") if m == "ccmp" else ("(uint64_t)(%s)" % b, "0")
    return ("if %s { flags_add(c, %d, (uint64_t)(%s) & 0x%xULL, %s & 0x%xULL, %s); } else { %s }"
            % (CC[ins.cc], w, rd(k, i, w), mask, bb, mask, ci, set_nzcv(ops[2].imm)))

def lift_ngc(ins: object, m: str, ops: list) -> str:
    """ngc/ngcs: Rd = ~Rm + C (sbc from zero), flags for ngcs."""
    dk, di, w = ireg(ins, ops[0]); sk, si, _ = ireg(ins, ops[1])
    mask = (1 << w) - 1
    out = ["{ uint64_t _b=(~(uint64_t)(%s)) & 0x%xULL, _ci=c->CF; uint64_t _r=(_b + _ci) & 0x%xULL;" % (rd(sk, si, w), mask, mask)]
    if m == "ngcs": out.append("flags_add(c, %d, 0, _b, _ci);" % w)
    out.append(wr(dk, di, w, "_r") + " }")
    return " ".join(out)

def lift_mnegl(ins: object, m: str, ops: list) -> str:
    """smnegl/umnegl: Xd = -(ext(Wn) * ext(Wm))."""
    dk, di, _ = ireg(ins, ops[0]); ak, ai, _ = ireg(ins, ops[1]); bk, bi, _ = ireg(ins, ops[2])
    ct, st = ("int64_t", "int32_t") if m == "smnegl" else ("uint64_t", "uint32_t")
    return wr(dk, di, 64, "(uint64_t)0 - (uint64_t)((%s)(%s)(%s) * (%s)(%s)(%s))" % (ct, st, rd(ak, ai, 32), ct, st, rd(bk, bi, 32)))

###############
# atomics and ordering
###############
def lift_lse(ins: object, m: str, ops: list) -> str:
    """LSE ld<op>/st<op>/swp/cas in every order and width as host __atomic builtins on the guest address."""
    op, order, size = LSE_RE.match(m).groups()
    order = order or ""
    w = {"b": 8, "h": 16}.get(size, ireg(ins, ops[0])[2])
    ct = "uint%d_t" % w
    rw = 64 if w == 64 else 32
    sk, si, _ = ireg(ins, ops[0])
    addr = mem_addr(ins, ops[-1], None)[0]
    rs = "(%s)(%s)" % (ct, rd(sk, si, rw))
    if op == "cas":
        tk, ti, _ = ireg(ins, ops[1])
        return ("{ %s _e=%s; __atomic_compare_exchange_n((%s*)(%s), &_e, (%s)(%s), 0, %s, %s); %s }"
                % (ct, rs, ct, addr, ct, rd(tk, ti, rw), RMW_ORDER[order], CAS_FAIL[order], wr(sk, si, rw, "_e")))
    base = "ld" + op[2:] if op.startswith("st") else op
    val = "(%s)~%s" % (ct, rs) if base == "ldclr" else rs
    call = "%s((%s*)(%s), %s, %s)" % (RMW_FN[base], ct, addr, val, RMW_ORDER[order])
    if op.startswith("st"): return "(void)%s;" % call
    tk, ti, _ = ireg(ins, ops[1])
    return "{ %s _o=%s; %s }" % (ct, call, wr(tk, ti, rw, "_o"))

def lift_casp(ins: object, m: str, ops: list) -> str:
    """casp{,a,l,al} Xs,Xs+1,Xt,Xt+1,[Xn] (and the w-pair form): one 128/64-bit host compare-exchange; Xs pair gets the old value."""
    order = CASP_RE.match(m).group(1) or ""
    (sk, si, w), (s2k, s2i, _), (tk, ti, _), (t2k, t2i, _) = [ireg(ins, o) for o in ops[:4]]
    ct, sh = ("unsigned __int128", 64) if w == 64 else ("uint64_t", 32)
    pair = lambda k1, i1, k2, i2: "((%s)(%s)<<%d|(%s)(%s))" % (ct, rd(k2, i2, w), sh, ct, rd(k1, i1, w))
    addr = mem_addr(ins, ops[4], None)[0]
    return ("{ %s _e=%s, _n=%s; __atomic_compare_exchange_n((%s*)(%s), &_e, _n, 0, %s, %s); %s %s }"
            % (ct, pair(sk, si, s2k, s2i), pair(tk, ti, t2k, t2i), ct, addr, RMW_ORDER[order], CAS_FAIL[order],
               wr(sk, si, w, "(uint64_t)_e"), wr(s2k, s2i, w, "(uint64_t)(_e>>%d)" % sh)))

def lift_crc(ins: object, m: str, ops: list) -> str:
    """crc32{b,h,w,x} / crc32c{b,h,w,x}: reflected CRC update of Wn by the low bytes of Rm, no pre/post inversion."""
    poly, nb = CRC[m]
    dk, di, _ = ireg(ins, ops[0]); ak, ai, _ = ireg(ins, ops[1]); bk, bi, bw = ireg(ins, ops[2])
    return wr(dk, di, 32, "s_crc(%s, (uint%d_t)%s, %d, 0x%xu)" % (rd(ak, ai, 32), 8 * nb, rd(bk, bi, bw), nb, poly))

def lift_sysreg(ins: object, m: str, ops: list) -> str:
    """mrs/msr nzcv, mrs rndr/rndrrs (RDRAND; NZCV 0100 on failure), mrs cntpct_el0/cntvct_el0 (24 MHz ticks)."""
    regs, name = [ireg(ins, o) for o in ops if o.type == ARM64_OP_REG], ins.op_str.replace(" ", "").split(",")[1 if m == "mrs" else 0]
    k, i, _ = regs[0]
    if name == "nzcv" and m == "mrs": return wr(k, i, 64, "((uint64_t)c->NF<<31)|((uint64_t)c->ZF<<30)|((uint64_t)c->CF<<29)|((uint64_t)c->VF<<28)")
    if name == "nzcv": return "{ uint64_t _v=%s; c->NF=(_v>>31)&1; c->ZF=(_v>>30)&1; c->CF=(_v>>29)&1; c->VF=(_v>>28)&1; }" % rd(k, i, 64)
    if name in ("rndr", "rndrrs") and m == "mrs":
        return "{ uint64_t _v; int _ok=s_rdrand(&_v); %s c->NF=0; c->ZF=!_ok; c->CF=0; c->VF=0; }" % wr(k, i, 64, "_v")
    if name in ("cntpct_el0", "cntvct_el0") and m == "mrs": return wr(k, i, 64, "s_cntpct()")
    raise NotImplementedError("sysreg %s %s" % (m, name))

def lift_ordered(ins: object, m: str, ops: list) -> str:
    """ldar*/stlr* as seq_cst (ARM RCsc), ldapr* as acquire (RCpc); w/b/h loads zero-extend."""
    op, size = ORD_RE.match(m).groups()
    k, i, rw = ireg(ins, ops[0])
    w = {"b": 8, "h": 16}.get(size, rw)
    ct = "uint%d_t" % w
    addr = mem_addr(ins, ops[1], None)[0]
    if op == "stlr":
        return "__atomic_store_n((%s*)(%s), (%s)(%s), __ATOMIC_SEQ_CST);" % (ct, addr, ct, rd(k, i, rw))
    order = "__ATOMIC_SEQ_CST" if op == "ldar" else "__ATOMIC_ACQUIRE"
    return wr(k, i, rw, "__atomic_load_n((%s*)(%s), %s)" % (ct, addr, order))

###############
# scalar floating point
###############
def lift_fmov(ins: object, ops: list) -> str:
    """Every scalar fmov: fpr<-fpr, fpr<-#imm, fpr<-gpr (incl. zr), gpr<-fpr, FP16 included; upper V bits zeroed."""
    dk, di, dw = reg_parts(ins.reg_name(ops[0].reg))
    if ops[1].type == ARM64_OP_FP:
        if dk not in ("h", "s", "d"): raise NotImplementedError("fmov imm to " + dk)
        fmt = {16: "e", 32: "f", 64: "d"}[dw]                          # every imm8 value is exact in all three
        bits = struct.unpack("<" + fmt.replace("e", "H").replace("f", "I").replace("d", "Q"), struct.pack("<" + fmt, ops[1].fp))[0]
        return vput(di, dw, "0x%xULL" % bits)
    sk, si, sw = reg_parts(ins.reg_name(ops[1].reg))
    if "h" in (dk, sk) and {dk, sk} <= {"h", "x", "zr"}:              # FP16: the low 16 bits, zero-extended
        src = "c->V[%d].u16[0]" % si if sk == "h" else "(uint16_t)%s" % rd(sk, si, sw)
        return vput(di, 16, src) if dk == "h" else wr(dk, di, dw, "(uint64_t)" + src)
    if sw != dw: raise NotImplementedError("fmov width %d<-%d" % (dw, sw))
    if dk in ("s", "d") and sk in ("s", "d"): return vput(di, dw, vget(si, sw))
    if dk in ("s", "d") and sk in ("x", "zr"): return vput(di, dw, rd(sk, si, sw))
    if dk in ("x", "zr") and sk in ("s", "d"): return wr(dk, di, dw, vget(si, sw))
    raise NotImplementedError("fmov %s<-%s" % (dk, sk))

def lift_fcmp_cond(ins: object, ops: list) -> str:
    """fccmp/fccmpe: IEEE compare flags when cond holds, else the #nzcv immediate."""
    _, ai, w = vreg(ins, ops[0]); _, bi, bw = vreg(ins, ops[1])
    if bw != w: raise NotImplementedError("fccmp mixed widths")
    a = "s_tf%d(%s)" % (w, vget(ai, w)); b = "s_tf%d(%s)" % (w, vget(bi, w))
    return ("if %s { double _x=%s,_y=%s; c->NF=(_x<_y); c->ZF=(_x==_y); c->CF=(_x>=_y||_x!=_x||_y!=_y); "
            "c->VF=(_x!=_x||_y!=_y); } else { %s }" % (CC[ins.cc], a, b, set_nzcv(ops[2].imm)))

def lift_fp_toint(ins: object, m: str, ops: list) -> str:
    """fcvt{a,m,p,z}{s,u}: scale by 2^fbits, round, saturate to the integer width, NaN -> 0."""
    dk, di, dw = ireg(ins, ops[0])
    _, si, sw = vreg(ins, ops[1])
    md, uns = FP_TOINT[m]
    scale = " * %r" % float(2 ** ops[2].imm) if len(ops) == 3 else ""  # exact power-of-two multiply
    val = "s_f2i((double)s_tf%d(%s)%s, %d, %d, %d)" % (sw, vget(si, sw), scale, md, dw, uns)
    if dk in ("s", "d"): return vput(di, dw, val)
    if dk not in ("x", "zr"): raise NotImplementedError(m + " to " + dk)
    return wr(dk, di, dw, val)

def lift_fcvt_half(ins: object, ops: list) -> str:
    """fcvt between h and s/d: widening is exact (NaNs quieted), narrowing rounds to nearest even in one step."""
    (dk, di, dw), (sk, si, sw) = [reg_parts(ins.reg_name(o.reg)) for o in ops[:2]]
    src = "c->V[%d].u%d[0]" % (si, sw)
    if sk == "h" and dk == "s": return vput(di, 32, "n_bits32(n_h2fq(%s))" % src)
    if sk == "h" and dk == "d": return vput(di, 64, "n_bits64(n_f32to64(n_h2fq(%s)))" % src)
    val = "n_f32to16(n_flt32(%s))" % src if sk == "s" else "s_f64to16(%s)" % src
    if dk != "h" or sk not in ("s", "d"): raise NotImplementedError("fcvt %s<-%s" % (dk, sk))
    return "c->V[%d].u64[0]=(uint64_t)%s; c->V[%d].u64[1]=0;" % (di, val, di)

def lift_fp(ins: object, m: str, ops: list) -> str:
    """Scalar s/d arithmetic: unary, binary, fused multiply-add, fcvt, fcsel; ARM NaN rules via s_ helpers."""
    if m == "fcvt" and "h" in {reg_parts(ins.reg_name(o.reg))[0] for o in ops[:2]}: return lift_fcvt_half(ins, ops)
    _, di, dw = vreg(ins, ops[0])
    srcs = [vreg(ins, o) for o in ops[1:] if o.type == ARM64_OP_REG]
    _, ai, aw = srcs[0]
    a = vget(ai, aw)
    if m == "fcvt":
        if (dw, aw) == (64, 32): return vput(di, 64, "s_cvt_sd(%s)" % a)
        if (dw, aw) == (32, 64): return vput(di, 32, "s_cvt_ds(%s)" % a)
        raise NotImplementedError("fcvt %d<-%d" % (dw, aw))
    if any(s[2] != dw for s in srcs): raise NotImplementedError(m + " mixed widths")
    v = [vget(s[1], dw) for s in srcs]
    sg = SIGN[dw]
    if m == "fabs": return vput(di, dw, "%s & ~%s" % (a, sg))
    if m == "fneg": return vput(di, dw, "%s ^ %s" % (a, sg))
    if m in ("fadd", "fsub", "fmul", "fdiv"): return vput(di, dw, "s_%s%d(%s, %s)" % (m, dw, v[0], v[1]))
    if m == "fsqrt": return vput(di, dw, "s_sqrt%d(%s)" % (dw, a))
    if m in FRINT_MODE: return vput(di, dw, "s_frint%d(%s, %d)" % (dw, a, FRINT_MODE[m]))
    if m == "fnmul": return vput(di, dw, "s_fmul%d(%s, %s) ^ %s" % (dw, v[0], v[1], sg))
    if m == "fabd": return vput(di, dw, "s_fsub%d(%s, %s) & ~%s" % (dw, v[0], v[1], sg))
    if m in ("fmaxnm", "fminnm"): return vput(di, dw, "s_maxnm%d(%s, %s, %d)" % (dw, v[0], v[1], m == "fminnm"))
    if m == "fcsel": return vput(di, dw, "(%s ? %s : %s)" % (CC[ins.cc], v[0], v[1]))
    if m in FP_FMA:
        nega, negn = FP_FMA[m]
        n = "(%s ^ %s)" % (v[0], sg) if negn else v[0]
        ad = "(%s ^ %s)" % (v[2], sg) if nega else v[2]
        return vput(di, dw, "s_fma%d(%s, %s, %s)" % (dw, ad, n, v[1]))
    raise NotImplementedError("scalar fp " + m)

###############
# lifting
###############
def lift_scalar(ins: object, m: str, ops: list) -> str:
    """C statements for one claimed scalar instruction."""
    if m == "brk": return "__builtin_trap();"
    if m in ("ccmp", "ccmn"): return lift_ccmp(ins, m, ops)
    if m in ("ngc", "ngcs"): return lift_ngc(ins, m, ops)
    if m in ("smnegl", "umnegl"): return lift_mnegl(ins, m, ops)
    if ORD_RE.match(m): return lift_ordered(ins, m, ops)
    if CASP_RE.match(m): return lift_casp(ins, m, ops)
    if m in CRC: return lift_crc(ins, m, ops)
    if m in ("mrs", "msr"): return lift_sysreg(ins, m, ops)
    if LSE_RE.match(m): return lift_lse(ins, m, ops)
    if m == "fmov": return lift_fmov(ins, ops)
    if m in ("fccmp", "fccmpe"): return lift_fcmp_cond(ins, ops)
    if m in FP_TOINT: return lift_fp_toint(ins, m, ops)
    if m in MNEMONICS: return lift_fp(ins, m, ops)
    raise NotImplementedError("scalar:" + m)
