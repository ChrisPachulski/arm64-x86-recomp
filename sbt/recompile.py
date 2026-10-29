"""AArch64 -> C static recompiler (library). Lifts one decoded function's Capstone
instructions into a C function that mutates a flat CPU state, N64Recomp/XenonRecomp style.
Loads/stores use absolute guest addresses so pointer values match the arm64 original.
No arm64 is executed by the output; Unicorn is only the differential oracle in the driver.
Pure functions; proven by sbt/microtest.py (differential vs Unicorn) and the gdyld beds."""
###############
# imports and constants
###############
from __future__ import annotations
import collections, functools, re, struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from capstone.arm64 import (ARM64_OP_REG, ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_FP, ARM64_EXT_SXTW, ARM64_EXT_UXTW,
                            ARM64_SFT_LSL, ARM64_SFT_LSR, ARM64_SFT_ASR, ARM64_SFT_ROR)
from cgen import (CC, SFT, SIMD, reg_parts, rd, wr, op_imm, shifted_reg, has_vector, mem_addr,
                  simd_load, simd_store)
import lift_scalar
import lift_neon

BRANCH = {"b", "br", "bl", "blr", "ret", "cbz", "cbnz", "tbz", "tbnz"}
DATA_MNEMONIC = ".byte"                                                # capstone skipdata word (macho.iter_functions)
CALLS = {"bl", "blr", "blraa", "blrab", "blraaz", "blrabz"}
CALL_CLOBBER = {"x%d" % k for k in range(19)} | {"x30"}                 # AAPCS64 caller-saved after any call
NO_FALL = {"b", "br", "ret", "retaa", "retab", "eret", "udf", "brk", "hlt", "braa", "brab", "braaz", "brabz", "drps"}
BRANCH_IMM = {"b", "cbz", "cbnz", "tbz", "tbnz"}                       # direct intra-function edges (b.cond / bc.cond apart)
TABLE_LOADS = {"ldrb": (1, "B"), "ldrsb": (1, "b"), "ldrh": (2, "H"), "ldrsh": (2, "h"), "ldrsw": (4, "i"), "ldr": (4, "I")}
DEF_WINDOW = 48                                                        # instructions scanned back for a register's definition
MAX_TABLE = 4096                                                       # entries; a larger bound is not a switch
PAGE_WINDOW = 16                                                       # words followed after an adrp (page_uses); past it the whole page counts
UNDECODED_MARK = "/* GD_UNDECODED_BR */"                                # first body line of a function lifted with fallback
HUGE_SWITCH = 256                                                      # br switch cases past which a function keeps guest state in c-> (no locals)
SVE_REG = re.compile(r"\b(?:[zp]\d{1,2}|za\d*[hvbsdq]?)\b")             # z0-z31, p0-p15, za / za0h / za1v: never NEON or scalar
SVE_ONLY = {"addvl","addpl", "rdvl", "cntb", "cnth", "cntw", "cntd", "incb", "inch", "incw", "incd", "decb", "dech",
            "decw", "decd", "ptrue", "ptrues", "pfalse", "setffr", "rdffr", "wrffr", "smstart", "smstop", "zero"}
SCALAR_FAMILIES = {"add", "sub", "adds", "subs", "cmp", "cmn", "adc", "sbc", "adcs", "sbcs", "neg", "negs", "and", "orr", "eor",
                   "ands", "tst", "bic", "orn", "eon", "mvn", "bics", "lsl", "lsr", "asr", "ror", "lslv", "lsrv", "asrv", "rorv",
                   "sbfm", "ubfm", "bfm", "sbfiz", "sbfx", "ubfiz", "ubfx", "bfi", "bfxil", "sxtb", "sxth", "sxtw", "uxtb", "uxth",
                   "extr", "mul", "madd", "msub", "mneg", "smull", "umull", "smulh", "umulh", "smaddl", "umaddl", "smsubl",
                   "umsubl", "udiv", "sdiv", "csel", "csinc", "csinv", "csneg", "cset", "csetm", "cinc", "cinv", "cneg", "clz",
                   "rbit", "rev", "rev16", "rev32", "cls"}                 # integer-register families of lift()
REG_REF = re.compile(r"c->(?:X\[(\d+)\]|V\[(\d+)\]|(SP|NF|ZF|CF|VF)\b)")   # guest state the lifted text names
LOCAL_NAME = re.compile(r"\bgr_(?:[xv]\d+|sp|nf|zf|cf|vf)\b")
LOCAL_WRITE = re.compile(r"(?:&|\+\+|--)\s*(gr_(?:[xv]\d+|sp|nf|zf|cf|vf))\b|\b(gr_(?:[xv]\d+|sp|nf|zf|cf|vf))\b"
                         r"(?:\.\w+(?:\[[^\]]*\])?)?\s*(?:(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--)")   # assigned, incremented or address taken
SPILL, RELOAD, TAIL = "GD_SPILL ", " GD_RELOAD", "GD_TAIL;"            # markers lift_function expands per function
LOCAL_BIT = {**{"gr_x%d" % i: i for i in range(31)}, "gr_sp": 31, "gr_nf": 32, "gr_zf": 33, "gr_cf": 34, "gr_vf": 35,
             **{"gr_v%d" % i: 36 + i for i in range(32)}}             # bit of each local in a dirty mask
LOCAL_AT = sorted(LOCAL_BIT, key=LOCAL_BIT.get)
FLAG_BIT0 = LOCAL_BIT["gr_nf"]                                         # nf zf cf vf are 4 consecutive bits
REG_BITS = ((1 << len(LOCAL_AT)) - 1) & ~(15 << FLAG_BIT0)             # every local but the four flags (their stores have guards)
NZCV_BITS = 15 << FLAG_BIT0
ABI_IN = sum(1 << LOCAL_BIT[n] for n in ["gr_x%d" % i for i in range(9)] + ["gr_x16", "gr_x17", "gr_x29", "gr_x30", "gr_sp"]
             + ["gr_v%d" % i for i in range(8)]) | NZCV_BITS             # a call's stores under GD_ABI: arguments, x8, IP0/IP1, fp, lr, sp
ABI_OUT = sum(1 << LOCAL_BIT[n] for n in ["gr_x0", "gr_x1", "gr_x29", "gr_sp"] + ["gr_v%d" % i for i in range(4)]) | NZCV_BITS   # a return's: results, fp, sp
ABI_BACK = sum(1 << LOCAL_BIT[n] for n in ["gr_x0", "gr_x1"] + ["gr_v%d" % i for i in range(4)]) | NZCV_BITS   # reloaded after a call: results
ABI_CLOBBER = sum(1 << LOCAL_BIT[n] for n in ["gr_x%d" % i for i in range(19)] + ["gr_x30"] + ["gr_v%d" % i for i in range(8)]
                  + ["gr_v%d" % i for i in range(16, 32)])             # AAPCS64 caller-saved: undefined after a call
ABI_NOT_IN = sum(1 << LOCAL_BIT[n] for n in ["gr_x%d" % i for i in range(9, 16)] + ["gr_x18"] + ["gr_v%d" % i for i in range(16, 32)])   # never an argument
ABI_NOT_OUT = ABI_CLOBBER & ~ABI_BACK & ~(1 << LOCAL_BIT["gr_x30"])    # never a result
PLAIN_WRITE = re.compile(r"(?<![\w&.>])(gr_(?:[xv]\d+|sp))\s*=(?!=)")   # a whole-register assignment
DEAD_DEST = re.compile(r"\bV128 _d=gr_v\d+; ")                         # lift_neon's copy of the destination, a read only where _d is used
LANE_WRITE = re.compile(r"\b(gr_v\d+)\.(u8|u16|u32|u64|f32|f64|v\w+)(?:\[(\d+)\])?\s*=(?!=)")   # a V register's lane (or whole vector view) assigned
LANE_BYTES = {"u8": 1, "u16": 2, "u32": 4, "u64": 8, "f32": 4, "f64": 8}
ABI_CS = sum(1 << LOCAL_BIT[n] for n in ["gr_x%d" % i for i in range(19, 29)] + ["gr_v%d" % i for i in range(8, 16)])   # callee-saved
ABI_EXTRA = ABI_NOT_IN | ABI_CS                                        # what a call under the contract does not pass
SAVE_OPS = {"stp", "stnp", "str", "stur"}                              # stores that can be a prologue save
CSE_KEEP = "!GD_ABI || !defined(GD_CSE) || defined(GDA_K_%x)"          # an unread prologue save stays (saved_reads; gdyld GD_CSE, GDA_K_)
NARROW_ACCESS = {"ldrb": 1, "ldurb": 1, "ldrsb": 1, "ldursb": 1, "ldrh": 2, "ldurh": 2, "ldrsh": 2, "ldursh": 2, "ldrsw": 4,
                 "ldursw": 4, "ldpsw": 4, "strb": 1, "sturb": 1, "strh": 2, "sturh": 2}   # bytes per register, narrower than it
CS_STORE = re.compile(r"\*\(uint64_t\*\)\([^;]*?\) = \(uint64_t\)\((gr_x\d+)\);|\{ V128 _s=(gr_v\d+); \*\(uint64_t\*\)\([^;]*?\)=_s\.u64\[0\]; \}")
NAN_OP = re.compile(r"^\{ (?:V128 _[abd]=c->V\[\d+\]; )+V128 _r=\{0\}; .*c->V\[(\d+)\]=_r; \}$")   # a lift_neon FAST op (one instruction)
NAN_CHK = re.compile(r" (?:gv4i|gv2l) _m=_r\.vf(?:32|64)!=_r\.vf(?:32|64); if \(__builtin_expect\(\(__builtin_ia32_movmsk(?:ps|pd)"
                     r"\(\((?:gv4f|gv2d)\)_m\) & \d+\)!=0, 0\)\) \{ _r\.vf(?:32|64)=n_fixv_\w+\(.*?\); \}")   # its per-op NaN check
SPILL_TEXT = (["c->X[%d]=gr_x%d; " % (i, i) for i in range(31)] + ["c->SP=gr_sp; "] + ["c->%s=gr_%s; " % (f, f.lower()) for f in ("NF", "ZF", "CF", "VF")]
              + ["c->V[%d]=gr_v%d; " % (i, i) for i in range(32)])   # store of each local, in LOCAL_BIT order
SPILL_MARK = re.compile(r"GD_SPILL(D[0-9a-f]+|R)? ")                   # SPILL plus the site kind: D<hex> direct call / tail call, R return
SITE_RE = re.compile(r"GD_SPILLD([0-9a-f]+) ")                          # the callee of a direct call / tail call site
FLAG_READ = re.compile(r"(?<!&)\bgr_[nzcv]f\b(?!\s*=(?!=))")           # a flag local not written (= or &, as flags_add_l takes it)
FLAG_KILL = {"adds", "subs", "cmp", "cmn", "ands", "tst", "bics", "adcs", "sbcs", "negs", "ngcs", "fcmp", "fcmpe", "ccmp",
             "ccmn", "fccmp", "fccmpe"}                                 # always set all of NZCV
FLAG_WRITE = re.compile(r"c->(?:NF|ZF|CF|VF)\s*=(?!=)|flags_add\(")      # lifted text that sets NZCV
FUSE_SETTER = {"cmp": ("sub", 0), "subs": ("sub", 1), "negs": ("sub", -1), "cmn": ("add", 0), "adds": ("add", 1),
               "tst": ("and", 0), "ands": ("and", 1), "fcmp": ("fp", 0), "fcmpe": ("fp", 0)}   # kind, index of the first source (-1: zero)
FUSED = {"sub": {1: "(U)gf_a==(U)gf_b", 2: "(U)gf_a!=(U)gf_b", 3: "(U)gf_a>=(U)gf_b", 4: "(U)gf_a<(U)gf_b", 9: "(U)gf_a>(U)gf_b",
                 10: "(U)gf_a<=(U)gf_b", 11: "(S)gf_a>=(S)gf_b", 12: "(S)gf_a<(S)gf_b", 13: "(S)gf_a>(S)gf_b", 14: "(S)gf_a<=(S)gf_b",
                 5: "(S)(U)(gf_a-gf_b)<0", 6: "(S)(U)(gf_a-gf_b)>=0"},
         "add": {1: "(U)(gf_a+gf_b)==0", 2: "(U)(gf_a+gf_b)!=0", 5: "(S)(U)(gf_a+gf_b)<0", 6: "(S)(U)(gf_a+gf_b)>=0"},
         "and": {1: "(U)(gf_a&gf_b)==0", 2: "(U)(gf_a&gf_b)!=0", 5: "(S)(U)(gf_a&gf_b)<0", 6: "(S)(U)(gf_a&gf_b)>=0",
                 11: "(S)(U)(gf_a&gf_b)>=0", 12: "(S)(U)(gf_a&gf_b)<0", 13: "(S)(U)(gf_a&gf_b)>0", 14: "(S)(U)(gf_a&gf_b)<=0",
                 3: "0", 4: "1", 9: "0", 10: "1"},
         "fp": {1: "gf_fa==gf_fb", 2: "!(gf_fa==gf_fb)", 3: "!(gf_fa<gf_fb)", 4: "gf_fa<gf_fb", 5: "gf_fa<gf_fb", 6: "!(gf_fa<gf_fb)",
                7: "(gf_fa!=gf_fa||gf_fb!=gf_fb)", 8: "!(gf_fa!=gf_fa||gf_fb!=gf_fb)", 9: "!(gf_fa<=gf_fb)", 10: "gf_fa<=gf_fb",
                11: "gf_fa>=gf_fb", 12: "!(gf_fa>=gf_fb)", 13: "gf_fa>gf_fb", 14: "!(gf_fa>gf_fb)"}}   # capstone cc -> C, same truth as CC on the flags
C_PRELUDE = r"""
#include <stdint.h>
#include <string.h>
#include <math.h>
#define GUEST_BASE 0x200000000ULL
typedef float gv4f __attribute__((vector_size(16), aligned(8))); typedef double gv2d __attribute__((vector_size(16), aligned(8))); typedef int32_t gv4i __attribute__((vector_size(16), aligned(8))); typedef int64_t gv2l __attribute__((vector_size(16), aligned(8))); typedef uint8_t gv16u8 __attribute__((vector_size(16), aligned(8))); typedef uint16_t gv8u16 __attribute__((vector_size(16), aligned(8))); typedef uint32_t gv4u32 __attribute__((vector_size(16), aligned(8))); typedef uint64_t gv2u64 __attribute__((vector_size(16), aligned(8))); typedef int8_t gv16i8 __attribute__((vector_size(16), aligned(8))); typedef int16_t gv8i16 __attribute__((vector_size(16), aligned(8))); typedef uint8_t gh8u8 __attribute__((vector_size(8))); typedef uint16_t gh4u16 __attribute__((vector_size(8))); typedef uint32_t gh2u32 __attribute__((vector_size(8))); typedef int8_t gh8i8 __attribute__((vector_size(8))); typedef int16_t gh4i16 __attribute__((vector_size(8))); typedef int32_t gh2i32 __attribute__((vector_size(8)));
typedef union { uint64_t u64[2]; uint32_t u32[4]; uint16_t u16[8]; uint8_t u8[16]; double f64[2]; float f32[4]; gv4f vf32; gv2d vf64; gv16u8 vu8; gv8u16 vu16; gv4u32 vu32; gv2u64 vu64; } V128;
typedef struct { uint64_t X[31]; uint64_t SP; uint32_t NF,ZF,CF,VF; V128 V[32]; int fault; uint64_t fpc; uint64_t unw; } CPU;
#define GD_RC(a) if (__builtin_expect(c->unw != 0, 0)) { if (c->unw != (a) + GUEST_BASE) return; c->unw = 0; }
#ifndef GD_FLAGS_ALL
#define GD_FLAGS_ALL 1
#endif
#ifndef GD_ABI
#define GD_ABI 0
#endif
#define GD_SIGF __atomic_signal_fence(__ATOMIC_SEQ_CST)                 /* compiler-only: memory ops stay on their side */
#define GD_SPW GD_SIGF                                                  /* sp written to c-> directly (no locals) */
#define GD_LOOP __asm__ __volatile__("" ::: "memory")                   /* loop head: guest memory is re-read and stores land every turn */
static inline void gd_ent_ret(CPU*c,uint64_t ra){ if(!c->unw && c->X[30]!=ra) c->unw=c->X[30]; }
static inline uint32_t ror32(uint32_t x,unsigned n){n&=31;return n?(x>>n)|(x<<(32-n)):x;}
static inline uint64_t ror64(uint64_t x,unsigned n){n&=63;return n?(x>>n)|(x<<(64-n)):x;}
static inline uint32_t clz32(uint32_t x){return x?__builtin_clz(x):32;}
static inline uint64_t clz64(uint64_t x){return x?__builtin_clzll(x):64;}
static inline uint32_t cls32(uint32_t x){return clz32(x^(((int32_t)x)>>31))-1;}
static inline uint64_t cls64(uint64_t x){return clz64(x^(((int64_t)x)>>63))-1;}
static inline uint32_t rbit32(uint32_t x){return __builtin_bitreverse32(x);}
static inline uint64_t rbit64(uint64_t x){return __builtin_bitreverse64(x);}
static inline uint32_t rev32(uint32_t x){return __builtin_bswap32(x);}
static inline uint64_t rev64(uint64_t x){return __builtin_bswap64(x);}
static inline uint32_t rev16_32(uint32_t x){return ((x&0xff)<<8)|((x>>8)&0xff)|(((x>>16)&0xff)<<24)|(((x>>24)&0xff)<<16);}
static inline uint64_t rev16_64(uint64_t x){uint64_t r=0;for(int i=0;i<8;i+=2){uint64_t a=(x>>(i*8))&0xff,b=(x>>((i+1)*8))&0xff;r|=(b<<(i*8))|(a<<((i+1)*8));}return r;}
static inline uint64_t rev32_64(uint64_t x){return ((uint64_t)__builtin_bswap32((uint32_t)x)<<32)|__builtin_bswap32((uint32_t)(x>>32));}
static inline int32_t div_s32(int32_t a,int32_t b){if(b==-1&&a==INT32_MIN)return a;return a/b;}
static inline int64_t div_s64(int64_t a,int64_t b){if(b==-1&&a==INT64_MIN)return a;return a/b;}
static inline void flags_add(CPU*c,int w,uint64_t a,uint64_t b,uint64_t ci){
  unsigned __int128 full=(unsigned __int128)a+(unsigned __int128)b+ci;
  uint64_t res=(uint64_t)full & (w==32?0xffffffffULL:~0ULL);
  c->ZF=(res==0); c->NF=(res>>(w-1))&1; c->CF=(uint64_t)(full>>w)&1;
  uint64_t sa=(a>>(w-1))&1, sb=(b>>(w-1))&1, sr=(res>>(w-1))&1; c->VF=(sa==sb)&&(sr!=sa);
}
static inline void flags_add_l(uint32_t*N,uint32_t*Z,uint32_t*C,uint32_t*V,int w,uint64_t a,uint64_t b,uint64_t ci){
  unsigned __int128 full=(unsigned __int128)a+(unsigned __int128)b+ci;
  uint64_t res=(uint64_t)full & (w==32?0xffffffffULL:~0ULL);
  *Z=(res==0); *N=(res>>(w-1))&1; *C=(uint64_t)(full>>w)&1;
  uint64_t sa=(a>>(w-1))&1, sb=(b>>(w-1))&1, sr=(res>>(w-1))&1; *V=(sa==sb)&&(sr!=sa);
}
void extern_stub(CPU*c,uint64_t a);
void dispatch(CPU*c,uint64_t a);
typedef struct { uint64_t a; void (*f)(CPU*); } GPair;                  /* guest address -> translated function */
extern const GPair gd_nopair;
void gd_icall_slow(CPU*c,uint64_t t,const GPair**ic);
#define GD_ICALL(t) do { static const GPair* _ic = &gd_nopair; const GPair* _p = __atomic_load_n(&_ic, __ATOMIC_RELAXED); \
  if (__builtin_expect(_p->a == (t), 1)) _p->f(c); else gd_icall_slow(c, (t), &_ic); } while (0)   /* per-site inline cache */
extern int gd_imp_slow;                                                 /* gbridge: an import diagnostic is armed */
#define GDL_P(i) ((void*)(uintptr_t)c->X[i])
#define GD_LEAF(s, e) if (__builtin_expect(_t == (s) && !gd_imp_slow, 1)) { e; } else   /* gdyld GDL_<got>: the leaf import, called here */
typedef struct { const void* e; } GMsgIC;                               /* per-site objc_msgSend cache (gobjc.hpp MIc) */
void gd_msgsend(CPU*c,GMsgIC*ic,int k,uint64_t s);
#ifndef GD_MSG_SLOT0
#define GD_MSG_SLOT0 1ULL
#define GD_MSG_SLOT1 1ULL
#define GD_MSG_SLOT2 1ULL
#endif
#define GD_MSGSEND(t, k, s) do { static GMsgIC _mc; if (__builtin_expect((t) == (s), 1)) gd_msgsend(c, &_mc, (k), (s)); else GD_ICALL(t); } while (0)   /* k: 0 objc_msgSend, 1 Super, 2 Super2; s its import slot (gdyld header) */
void unsupported(CPU*c,uint64_t a);
void gd_die(const char*what,uint64_t a);
""" + lift_scalar.C_HELPERS + lift_neon.C_HELPERS                      # runtime contract; drivers define the 3 hooks

###############
# loads and stores
###############
LOADS = {"ldr": ("uint", None), "ldrb": ("uint8_t", None), "ldrh": ("uint16_t", None),
         "ldur": ("uint", None), "ldurb": ("uint8_t", None), "ldurh": ("uint16_t", None),
         "ldrsb": ("int8_t", "s"), "ldrsh": ("int16_t", "s"), "ldrsw": ("int32_t", "s"),
         "ldursb": ("int8_t", "s"), "ldursh": ("int16_t", "s"), "ldursw": ("int32_t", "s")}
STORES = {"str": "uint", "strb": "uint8_t", "strh": "uint16_t",
          "stur": "uint", "sturb": "uint8_t", "sturh": "uint16_t"}

###############
# per-instruction lifting
###############
def lift(ins: object, fstarts: set, calls: set) -> str:
    """Return C statements for one instruction (no label). May raise NotImplementedError."""
    m = ins.mnemonic
    base_m = m.split(".")[0]
    ops = ins.operands
    def R(i: int) -> tuple: return reg_parts(ins.reg_name(ops[i].reg))

    if m == "stg" and not ins.writeback:                               # MTE tag store: x86 has no tags, data untouched
        return ";"
    if m in ("nop", "hint", "yield", "prfm", "prfum", "pacibsp", "autibsp", "isb", "pfm", "autia1716", "autib1716",
             "pacia1716", "pacib1716"):                                # hints and prefetches: no architectural effect
        return ";"
    if m == "udf":                                                     # permanently undefined: SIGILL, as on arm64
        return "__builtin_trap();"
    if trap_kind(ins) == "sve":                                        # only behind a runtime SVE/SME test the x86 host answers "no"
        return 'gd_die("SVE/SME instruction `%s %s` (this x86-64 host has no SVE/SME) at", 0x%xULL); return;' % (
            m, ins.op_str, ins.address)
    if trap_kind(ins) == "sysreg":                                     # EL1 ID register, read only behind an env-only OpenSSL bit
        return 'gd_die("EL1 system register read `%s %s` (no EL0 value to give) at", 0x%xULL); return;' % (
            m, ins.op_str, ins.address)
    if m in ("dmb", "dsb"):                                           # guest threads run on host threads
        return "__atomic_thread_fence(__ATOMIC_SEQ_CST);"
    if base_m in lift_neon.MNEMONICS and (has_vector(ins) or lift_neon.scalar_form(ins, base_m)):
        return lift_neon.lift_neon(ins, base_m, ops)
    if not has_vector(ins) and base_m in lift_scalar.MNEMONICS:
        return lift_scalar.lift_scalar(ins, base_m, ops)
    if base_m == "mov" and len(ops) == 2 and ops[1].type == ARM64_OP_REG:
        dk, di, dw = R(0); sk, si, sw = R(1)
        return wr(dk, di, dw, rd(sk, si, dw))
    if base_m in ("mov", "movz") and ops[1].type == ARM64_OP_IMM:
        dk, di, dw = R(0)
        val = ops[1].imm << (ops[1].shift.value if ops[1].shift.type else 0)
        return wr(dk, di, dw, "0x%xULL" % (val & ((1 << dw) - 1)))
    if base_m == "movn":
        dk, di, dw = R(0)
        val = ~(ops[1].imm << (ops[1].shift.value if ops[1].shift.type else 0))
        return wr(dk, di, dw, "0x%xULL" % (val & ((1 << dw) - 1)))
    if base_m == "movk":
        dk, di, dw = R(0)
        sh = ops[1].shift.value if ops[1].shift.type else 0
        mask = ~(0xFFFF << sh) & ((1 << dw) - 1)
        cur = rd(dk, di, dw)
        return wr(dk, di, dw, "((%s & 0x%xULL) | 0x%xULL)" % (cur, mask, (ops[1].imm << sh)))

    if has_vector(ins) and base_m in SCALAR_FAMILIES:                  # e.g. cls v0.16b: no NEON case; never lift it as x registers
        raise NotImplementedError("vector form of " + base_m)
    if base_m in ("add", "sub", "adds", "subs", "cmp", "cmn", "adc", "sbc", "adcs", "sbcs", "neg", "negs"):
        return lift_addsub(ins, base_m, ops, R)
    if base_m in ("and", "orr", "eor", "ands", "tst", "bic", "orn", "eon", "mvn", "bics"):
        return lift_logic(ins, base_m, ops, R)
    if base_m in ("lsl", "lsr", "asr", "ror", "lslv", "lsrv", "asrv", "rorv"):
        return lift_shift(ins, base_m, ops, R)
    if base_m in ("sbfm", "ubfm", "bfm", "sbfiz", "sbfx", "ubfiz", "ubfx", "bfi", "bfxil",
                  "sxtb", "sxth", "sxtw", "uxtb", "uxth", "extr"):
        return lift_bitfield(ins, base_m, ops, R)
    if base_m in ("mul", "madd", "msub", "mneg", "smull", "umull", "smulh", "umulh",
                  "smaddl", "umaddl", "smsubl", "umsubl", "udiv", "sdiv"):
        return lift_muldiv(ins, base_m, ops, R)
    if base_m in ("csel", "csinc", "csinv", "csneg", "cset", "csetm", "cinc", "cinv", "cneg"):
        return lift_csel(ins, base_m, ops, R)
    if base_m in ("clz", "rbit", "rev", "rev16", "rev32", "cls"):
        return lift_bitops(ins, base_m, ops, R)

    if base_m in LOADS: return lift_load(ins, base_m, ops)
    if base_m in STORES: return lift_store(ins, base_m, ops)
    if base_m in ("ldp", "ldpsw", "stp", "ldnp", "stnp"):               # ldnp/stnp: ldp/stp with a non-temporal hint
        return lift_pair(ins, {"ldnp": "ldp", "stnp": "stp"}.get(base_m, base_m), ops)

    if base_m == "adrp":
        dk, di, dw = R(0)
        return wr(dk, di, 64, "(0x%xULL + GUEST_BASE)" % ops[1].imm)
    if base_m == "adr":
        dk, di, dw = R(0)
        return wr(dk, di, 64, "(0x%xULL + GUEST_BASE)" % ops[1].imm)

    if base_m in ("fmov", "fcmp", "fcmpe", "scvtf", "ucvtf", "cnt", "uaddlv", "addv", "movi"):
        return lift_fp(ins, base_m, ops, R)

    raise NotImplementedError(base_m)

def lift_addsub(ins: object, m: str, ops: list, R: object) -> str:
    setf = m in ("adds", "subs", "cmp", "cmn", "adcs", "sbcs", "negs")
    is_sub = m in ("sub", "subs", "cmp", "neg", "negs", "sbc", "sbcs")
    cmp = m in ("cmp", "cmn")
    if cmp:
        dk, di, dw = ("zr", 31, reg_parts(ins.reg_name(ops[0].reg))[2]); ai = 0; bi = 1
    else:
        dk, di, dw = R(0); ai = 1; bi = 2
    if m in ("neg", "negs"):
        a = "0"; b = operand_val(ins, ops[1], dw)
    else:
        a = rd(*reg_parts(ins.reg_name(ops[ai].reg))[:2], dw) if ops[ai].type == ARM64_OP_REG else "0"
        if ops[ai].type == ARM64_OP_REG:
            ka, ia, _ = reg_parts(ins.reg_name(ops[ai].reg)); a = rd(ka, ia, dw)
        b = operand_val(ins, ops[bi], dw)
    cin = "c->CF" if m in ("adc", "sbc", "adcs", "sbcs") else "0"
    if is_sub:
        bb = "(~(uint64_t)(%s))" % b
        cin = "1" if m in ("sub", "subs", "cmp", "neg", "negs") else cin
    else:
        bb = "(uint64_t)(%s)" % b
    res = "(%s + %s + %s)" % ("(uint64_t)(%s)" % a, bb, cin)
    mask = (1 << dw) - 1
    out = []
    out.append("{ uint64_t _a=(uint64_t)(%s), _b=%s, _ci=%s;" % (a, bb, cin))
    out.append("  uint64_t _r=(_a + _b + _ci) & 0x%xULL;" % mask)
    if setf:
        out.append("  flags_add(c, %d, _a & 0x%xULL, _b & 0x%xULL, _ci);" % (dw, mask, mask))
    if not cmp:
        rise = dk == "sp" and m == "add" and ops[ai].type == ARM64_OP_REG and reg_parts(ins.reg_name(ops[ai].reg))[0] == "sp" \
            and ops[bi].type == ARM64_OP_IMM                           # add sp, sp, #imm frees a frame: no sp publish needed
        out.append("  " + (wr(dk, di, dw, "_r").replace(" GD_SPW;", "") if rise else wr(dk, di, dw, "_r")))
    out.append("}")
    return "\n".join(out)

def operand_val(ins: object, o: object, w: int) -> str:
    if o.type == ARM64_OP_IMM:
        v = o.imm
        if o.shift.type == ARM64_SFT_LSL and o.shift.value: v = v << o.shift.value
        return "0x%xULL" % (v & ((1 << w) - 1))
    if o.ext:
        k, i, rw = reg_parts(ins.reg_name(o.reg))
        ew = {1: 8, 2: 16, 3: 32, 4: 64, 5: 8, 6: 16, 7: 32, 8: 64}.get(o.ext, w)
        signed = o.ext in (5, 6, 7, 8)
        raw = "c->X[%d]" % i if k == "x" else ("c->SP" if k == "sp" else "0")
        ct = "int%d_t" % ew if signed else "uint%d_t" % ew
        v = "((uint64_t)(%s)(%s))" % (ct, raw)
        if o.shift.value: v = "(%s << %d)" % (v, o.shift.value)
        return v
    return shifted_reg(ins, o, w)

def lift_logic(ins: object, m: str, ops: list, R: object) -> str:
    setf = m in ("ands", "tst", "bics")
    tst = m == "tst"
    if tst:
        dw = reg_parts(ins.reg_name(ops[0].reg))[2]; ai = 0; bi = 1; dk, di = ("zr", 31)
    else:
        dk, di, dw = R(0); ai = 1; bi = 2
    if m == "mvn":
        ka, ia, _ = reg_parts(ins.reg_name(ops[1].reg)) if ops[1].type == ARM64_OP_REG else ("zr", 31, dw)
        expr = "(~(%s))" % operand_val(ins, ops[1], dw)
        return wr(dk, di, dw, expr)
    ka, ia, _ = reg_parts(ins.reg_name(ops[ai].reg))
    a = rd(ka, ia, dw)
    b = operand_val(ins, ops[bi], dw)
    if m in ("bic", "bics"): b = "(~(%s))" % b
    if m == "orn": b = "(~(%s))" % b
    if m == "eon": b = "(~(%s))" % b
    op = {"and": "&", "ands": "&", "tst": "&", "bic": "&", "bics": "&",
          "orr": "|", "orn": "|", "eor": "^", "eon": "^"}[m]
    mask = (1 << dw) - 1
    expr = "(((uint64_t)(%s) %s (uint64_t)(%s)) & 0x%xULL)" % (a, op, b, mask)
    out = ["{ uint64_t _r=%s;" % expr]
    if setf:
        out.append("  c->NF=(_r>>%d)&1; c->ZF=(_r==0); c->CF=0; c->VF=0;" % (dw - 1))
    if not tst:
        out.append("  " + wr(dk, di, dw, "_r"))
    out.append("}")
    return "\n".join(out)

def lift_shift(ins: object, m: str, ops: list, R: object) -> str:
    dk, di, dw = R(0)
    ka, ia, _ = reg_parts(ins.reg_name(ops[1].reg)); a = rd(ka, ia, dw)
    base = m.rstrip("v")
    if ops[2].type == ARM64_OP_IMM:
        amt = "%d" % (ops[2].imm % dw)
    else:
        kc, ic, _ = reg_parts(ins.reg_name(ops[2].reg)); amt = "((%s) %% %d)" % (rd(kc, ic, dw), dw)
    if base == "lsl": expr = "((uint%d_t)(%s) << %s)" % (dw, a, amt)
    elif base == "lsr": expr = "((uint%d_t)(%s) >> %s)" % (dw, a, amt)
    elif base == "asr": expr = "((int%d_t)(%s) >> %s)" % (dw, a, amt)
    elif base == "ror": expr = "ror%d(%s, %s)" % (dw, a, amt)
    else: raise NotImplementedError(m)
    return wr(dk, di, dw, expr)

def lift_bitfield(ins: object, m: str, ops: list, R: object) -> str:
    dk, di, dw = R(0)
    ka, ia, _ = reg_parts(ins.reg_name(ops[1].reg)); a = rd(ka, ia, dw)
    if m in ("sxtb", "sxth", "sxtw", "uxtb", "uxth"):
        sw = {"sxtb": 8, "sxth": 16, "sxtw": 32, "uxtb": 8, "uxth": 16}[m]
        ct = ("int%d_t" % sw) if m[0] == "s" else ("uint%d_t" % sw)
        return wr(dk, di, dw, "(%s)(%s)" % (ct, a))
    if m == "extr":
        kb, ib, _ = reg_parts(ins.reg_name(ops[2].reg)); b = rd(kb, ib, dw)
        lsb = ops[3].imm
        return wr(dk, di, dw, "(((uint%d_t)(%s)<<%d) | ((uint%d_t)(%s)>>%d))" % (dw, a, dw - lsb, dw, b, lsb) if lsb else "(%s)" % b)
    if m in ("ubfx", "sbfx"):
        lsb = ops[2].imm; width = ops[3].imm
        sh = "(((uint%d_t)(%s)>>%d) & 0x%xULL)" % (dw, a, lsb, (1 << width) - 1)
        if m == "sbfx":
            return wr(dk, di, dw, "((int%d_t)(%s<<%d)>>%d)" % (dw, sh, dw - width, dw - width))
        return wr(dk, di, dw, sh)
    if m in ("ubfiz", "sbfiz"):
        lsb = ops[2].imm; width = ops[3].imm
        field = "((uint%d_t)(%s) & 0x%xULL)" % (dw, a, (1 << width) - 1)
        val = "((uint%d_t)%s << %d)" % (dw, field, lsb)
        if m == "sbfiz":
            sh = dw - width - lsb                                      # sign-extend from bit lsb+width-1
            return wr(dk, di, dw, "((int%d_t)(%s << %d) >> %d)" % (dw, val, sh, sh))
        return wr(dk, di, dw, val)
    if m in ("bfi", "bfxil", "bfm"):
        return lift_bfm(ins, m, ops, R, dk, di, dw, a)
    raise NotImplementedError(m)

def lift_bfm(ins: object, m: str, ops: list, R: object, dk: str, di: int, dw: int, a: str) -> str:
    cur = rd(dk, di, dw)
    if m == "bfi":
        lsb = ops[2].imm; width = ops[3].imm
        field = "(((uint%d_t)(%s) & 0x%xULL) << %d)" % (dw, a, (1 << width) - 1, lsb)
        keep = ~(((1 << width) - 1) << lsb) & ((1 << dw) - 1)
        return wr(dk, di, dw, "((%s & 0x%xULL) | %s)" % (cur, keep, field))
    if m == "bfxil":
        lsb = ops[2].imm; width = ops[3].imm
        field = "(((uint%d_t)(%s) >> %d) & 0x%xULL)" % (dw, a, lsb, (1 << width) - 1)
        keep = ~((1 << width) - 1) & ((1 << dw) - 1)
        return wr(dk, di, dw, "((%s & 0x%xULL) | %s)" % (cur, keep, field))
    raise NotImplementedError(m)

def lift_muldiv(ins: object, m: str, ops: list, R: object) -> str:
    dk, di, dw = R(0)
    if m in ("mul", "mneg"):
        ka, ia, _ = R(1); kb, ib, _ = R(2)
        e = "((uint%d_t)(%s) * (uint%d_t)(%s))" % (dw, rd(ka, ia, dw), dw, rd(kb, ib, dw))
        return wr(dk, di, dw, ("-" + e) if m == "mneg" else e)
    if m in ("madd", "msub"):
        ka, ia, _ = R(1); kb, ib, _ = R(2); kc, ic, _ = R(3)
        mul = "((uint%d_t)(%s) * (uint%d_t)(%s))" % (dw, rd(ka, ia, dw), dw, rd(kb, ib, dw))
        op = "-" if m == "msub" else "+"
        return wr(dk, di, dw, "((uint%d_t)(%s) %s %s)" % (dw, rd(kc, ic, dw), op, mul))
    if m in ("smulh", "umulh"):
        ka, ia, _ = R(1); kb, ib, _ = R(2)
        ct = "__int128" if m == "smulh" else "unsigned __int128"
        cc = "int64_t" if m == "smulh" else "uint64_t"
        return wr(dk, di, 64, "(uint64_t)(((%s)(%s)%s * (%s)(%s)%s) >> 64)" % (ct, cc, rd(ka, ia, 64), ct, cc, rd(kb, ib, 64)))
    if m in ("smull", "umull", "smaddl", "umaddl", "smsubl", "umsubl"):
        ka, ia, _ = R(1); kb, ib, _ = R(2)
        ct = "int64_t" if m[0] == "s" else "uint64_t"
        st = "int32_t" if m[0] == "s" else "uint32_t"
        mul = "((%s)(%s)(%s) * (%s)(%s)(%s))" % (ct, st, rd(ka, ia, 32), ct, st, rd(kb, ib, 32))
        if m in ("smull", "umull"): return wr(dk, di, 64, mul)
        kc, ic, _ = R(3); op = "-" if "msub" in m else "+"
        return wr(dk, di, 64, "((%s)%s %s %s)" % (ct, rd(kc, ic, 64), op, mul))
    if m in ("udiv", "sdiv"):
        ka, ia, _ = R(1); kb, ib, _ = R(2)
        a = rd(ka, ia, dw); b = rd(kb, ib, dw)
        if m == "udiv":
            return wr(dk, di, dw, "((uint%d_t)(%s)==0 ? 0 : (uint%d_t)(%s) / (uint%d_t)(%s))" % (dw, b, dw, a, dw, b))
        return wr(dk, di, dw, "((int%d_t)(%s)==0 ? 0 : div_s%d((int%d_t)(%s),(int%d_t)(%s)))" % (dw, b, dw, dw, a, dw, b))
    raise NotImplementedError(m)

def lift_csel(ins: object, m: str, ops: list, R: object) -> str:
    dk, di, dw = R(0)
    cc = CC[ins.cc]
    if m in ("cset", "csetm"):
        val = "1" if m == "cset" else ("0xffffffffULL" if dw == 32 else "0xffffffffffffffffULL")
        return wr(dk, di, dw, "(%s ? %s : 0)" % (cc, val))
    ka, ia, _ = R(1); a = rd(ka, ia, dw)
    if m in ("cinc", "cinv", "cneg"):
        t = {"cinc": "((%s)+1)", "cinv": "(~(%s))", "cneg": "(-(%s))"}[m] % a
        return wr(dk, di, dw, "(%s ? %s : %s)" % (CC[ins.cc], t, a))   # cond ? op(Xn) : Xn
    kb, ib, _ = R(2); b = rd(kb, ib, dw)
    if m == "csel": tb = b
    elif m == "csinc": tb = "((%s)+1)" % b
    elif m == "csinv": tb = "(~(%s))" % b
    elif m == "csneg": tb = "(-(%s))" % b
    else: raise NotImplementedError(m)
    return wr(dk, di, dw, "(%s ? (%s) : (%s))" % (cc, a, tb))

def lift_bitops(ins: object, m: str, ops: list, R: object) -> str:
    dk, di, dw = R(0); ka, ia, _ = R(1); a = rd(ka, ia, dw)
    if m == "clz": return wr(dk, di, dw, "clz%d(%s)" % (dw, a))
    if m == "rbit": return wr(dk, di, dw, "rbit%d(%s)" % (dw, a))
    if m == "rev": return wr(dk, di, dw, "rev%d(%s)" % (dw, a))
    if m == "rev16": return wr(dk, di, dw, "rev16_%d(%s)" % (dw, a))
    if m == "rev32": return wr(dk, di, dw, "rev32_64(%s)" % a)
    if m == "cls": return wr(dk, di, dw, "cls%d(%s)" % (dw, a))
    raise NotImplementedError(m)

def lift_load(ins: object, m: str, ops: list) -> str:
    cty, sign = LOADS[m]
    dk, di, dw = reg_parts(ins.reg_name(ops[0].reg))
    post = ops[2].imm if len(ops) > 2 and ops[2].type == ARM64_OP_IMM else None
    if ops[1].type == ARM64_OP_IMM:                                    # literal: capstone gives the absolute vmaddr
        addr, pre, postwb = "(0x%xULL + GUEST_BASE)" % ops[1].imm, "", ""
    else:
        addr, pre, postwb = mem_addr(ins, ops[1], post)
    out = []
    if pre: out.append(pre)
    if dk in SIMD:
        out.append(simd_load(di, dw, addr))
    else:
        if cty == "uint": cty = "uint%d_t" % dw
        load = "(*(%s*)(%s))" % (cty, addr)
        val = (("(uint64_t)(int64_t)(%s)" if dw == 64 else "(uint32_t)(int32_t)(%s)") % load) if sign == "s" else load
        out.append(wr(dk, di, dw, val))
    if postwb: out.append(postwb)
    return " ".join(out)

def lift_store(ins: object, m: str, ops: list) -> str:
    cty = STORES[m]
    sk, si, sw = reg_parts(ins.reg_name(ops[0].reg))
    post = ops[2].imm if len(ops) > 2 and ops[2].type == ARM64_OP_IMM else None
    addr, pre, postwb = mem_addr(ins, ops[1], post)
    out = []
    if pre: out.append(pre)
    if sk in SIMD:
        out.append(simd_store(si, sw, addr))
    else:
        if cty == "uint": cty = "uint%d_t" % sw
        out.append("*(%s*)(%s) = (%s)(%s);" % (cty, addr, cty, rd(sk, si, sw)))
    if postwb: out.append(postwb)
    return " ".join(out)

def lift_pair(ins: object, m: str, ops: list) -> str:
    r1k, r1i, w = reg_parts(ins.reg_name(ops[0].reg))
    r2k, r2i, _ = reg_parts(ins.reg_name(ops[1].reg))
    memop = ops[2]
    post = ops[3].imm if len(ops) > 3 and ops[3].type == ARM64_OP_IMM else None
    addr, pre, postwb = mem_addr(ins, memop, post)
    sz = w // 8
    out = ([pre] if pre else []) + ["{ uint64_t _ad = %s;" % addr]    # base may also be a dest; capture once (after an sp pre-index)
    ad = "_ad"
    if r1k in SIMD:
        out.append(simd_store(r1i, w, ad) if m == "stp" else simd_load(r1i, w, ad))
        out.append(simd_store(r2i, w, "(%s + %d)" % (ad, sz)) if m == "stp" else simd_load(r2i, w, "(%s + %d)" % (ad, sz)))
    elif m == "stp":
        cty = "uint%d_t" % w
        out.append("*(%s*)(%s) = (%s)(%s);" % (cty, ad, cty, rd(r1k, r1i, w)))
        out.append("*(%s*)(%s + %d) = (%s)(%s);" % (cty, ad, sz, cty, rd(r2k, r2i, w)))
    elif m == "ldpsw":                                                # two signed 32-bit words -> 64-bit
        v1 = "(*(uint32_t*)(%s))" % ad; v2 = "(*(uint32_t*)(%s + 4))" % ad
        out.append(wr(r1k, r1i, 64, "(uint64_t)(int64_t)(int32_t)%s" % v1))
        out.append(wr(r2k, r2i, 64, "(uint64_t)(int64_t)(int32_t)%s" % v2))
    else:
        cty = "uint%d_t" % w
        v1 = "(*(%s*)(%s))" % (cty, ad); v2 = "(*(%s*)(%s + %d))" % (cty, ad, sz)
        out.append(wr(r1k, r1i, w, v1)); out.append(wr(r2k, r2i, w, v2))
    if postwb: out.append(postwb)
    out.append("}")
    return " ".join(out)

def lift_fp(ins: object, m: str, ops: list, R: object) -> str:
    """Minimal FP/NEON: the popcount idiom, zeroing, int<->float, basic float ALU."""
    if m == "movi":                                                    # scalar movi d<n>, #imm64 (byte-mask immediate)
        k, i, w = R(0)
        return "c->V[%d].u64[0]=0x%xULL; c->V[%d].u64[1]=0;" % (i, ops[1].imm & (2 ** 64 - 1), i)
    if m == "cnt":                                                     # per-byte popcount, 8B
        k, i, w = R(0); ks, isrc, _ = R(1)
        return ("for(int _j=0;_j<8;_j++) c->V[%d].u8[_j]=__builtin_popcount(c->V[%d].u8[_j]);" % (i, isrc))
    if m in ("uaddlv", "addv"):                                        # horizontal add of 8 bytes -> H
        kd, idv, _ = R(0); ks, isrc, _ = R(1)
        return ("{ uint32_t _s=0; for(int _j=0;_j<8;_j++) _s+=c->V[%d].u8[_j]; "
                "c->V[%d].u64[0]=_s; c->V[%d].u64[1]=0; }" % (isrc, idv, idv))
    if m == "fmov":
        kd, idv, wd = R(0)
        if ops[1].type == ARM64_OP_FP:
            return "c->V[%d].f64[0]=%r; c->V[%d].u64[1]=0;" % (idv, float(ops[1].fp), idv) if kd == "d" else \
                   "c->V[%d].f32[0]=%r; c->V[%d].u32[1]=0; c->V[%d].u64[1]=0;" % (idv, float(ops[1].fp), idv, idv)
        ks, isrc, ws = R(1)
        if kd in "dsq" and ks == "x":                                  # gpr -> fpr
            fld = "u64[0]" if kd == "d" else "u32[0]"
            return "c->V[%d].%s = (uint%d_t)%s; c->V[%d].u64[1]=0;" % (idv, fld, 64 if kd == "d" else 32, rd(ks, isrc, 64 if kd == "d" else 32), idv) + (" c->V[%d].u32[1]=0;" % idv if kd == "s" else "")
        if kd == "x" and ks in "dsq":                                  # fpr -> gpr
            fld = "u64[0]" if ks == "d" else "u32[0]"
            return wr(kd, idv, 64 if kd == "x" else 32, "c->V[%d].%s" % (isrc, fld))
        if kd in "dsq" and ks in "dsq":
            return "c->V[%d]=c->V[%d];" % (idv, isrc)
    if m in ("scvtf", "ucvtf"):
        kd, idv, _ = R(0); ks, isrc, ws = R(1)
        if "h" in (kd, ks): raise NotImplementedError("fp16 " + m)    # half precision: loud, never lifted as single
        fld = "f64[0]" if kd == "d" else "f32[0]"
        src = rd(ks, isrc, ws) if ks in ("x", "sp", "zr") else "c->V[%d].%s" % (isrc, "u64[0]" if ks == "d" else "u32[0]")
        ct = ("int%d_t" % ws) if m == "scvtf" else ("uint%d_t" % ws)
        clr = " c->V[%d].u32[1]=0; c->V[%d].u64[1]=0;" % (idv, idv) if kd == "s" else " c->V[%d].u64[1]=0;" % idv
        fbits = " / %r" % float(2 ** ops[2].imm) if len(ops) == 3 else ""  # fixed-point: exact power-of-two scale after one rounding
        return "c->V[%d].%s = (%s)(%s)(%s)%s;" % (idv, fld, "double" if kd == "d" else "float", ct, src, fbits) + clr
    if m in ("fcmp", "fcmpe"):
        ka, ia, _ = R(0)
        if ka == "h": raise NotImplementedError("fp16 " + m)            # half precision: loud, never lifted as single
        fld = "f64[0]" if ka == "d" else "f32[0]"
        b = "0.0" if ops[1].type == ARM64_OP_FP else "c->V[%d].%s" % (reg_parts(ins.reg_name(ops[1].reg))[1], fld)
        a = "c->V[%d].%s" % (ia, fld)
        return ("{ double _x=%s,_y=%s; c->NF=(_x<_y); c->ZF=(_x==_y); c->CF=(_x>=_y||_x!=_x||_y!=_y); c->VF=(_x!=_x||_y!=_y); }" % (a, b))
    raise NotImplementedError("fp:" + m)

def trap_kind(ins: object) -> str:
    """'data', 'udf', 'sve' (SVE/SME: z/p/za registers anywhere in the operands, or SVE-only ops), 'sysreg' (mrs of an EL1 ID register) or '' for one instruction."""
    if ins.mnemonic == DATA_MNEMONIC: return "data"
    if ins.mnemonic == "udf": return "udf"
    if ins.mnemonic == "mrs" and re.search(r"\b(midr|mpidr|revidr|id_[a-z0-9_]+)_el1\b", ins.op_str): return "sysreg"
    return "sve" if ins.mnemonic in SVE_ONLY or SVE_REG.search(ins.op_str) else ""

###############
# code versus data: recursive descent from the entry, jump tables
###############
def xname(name: str) -> str:
    """Canonical 64-bit name of an integer register ('w8' -> 'x8', 'lr' -> 'x30'); other names unchanged."""
    n = {"lr": "x30", "fp": "x29", "wsp": "sp", "wzr": "xzr"}.get(name, name)
    return "x" + n[1:] if n[:1] == "w" and n[1:].isdigit() else n

def writes(ins: object) -> set:
    """Integer registers (canonical x names) one instruction writes; calls clobber x0-x18 and x30."""
    if ins.mnemonic in CALLS: return CALL_CLOBBER
    return {xname(ins.reg_name(r)) for r in ins.regs_access()[1]}

def jump_edges(insns: list) -> set:
    """Targets of the direct branches (b, b.cond, bc.cond, cbz/cbnz, tbz/tbnz) among insns."""
    return {i.operands[-1].imm for i in insns if (i.mnemonic in BRANCH_IMM or i.mnemonic.startswith(("b.", "bc.")))
            and i.operands and i.operands[-1].type == ARM64_OP_IMM}

NAC = -1                                                               # reg_values: not one constant on every path

def guest_edges(insns: list, at: dict, brs: dict) -> list[list[int]]:
    """Successor indexes per instruction as the guest runs: direct branches and the fall-through, a call returning to the
    next instruction; a br goes to its targets in brs (br address -> (kind, targets)) and else leaves the function."""
    out = []
    for n, ins in enumerate(insns):
        m = ins.mnemonic
        if m == DATA_MNEMONIC: out.append([]); continue
        tg = brs.get(ins.address, ("", []))[1] if m == "br" else [ins.operands[-1].imm] if (m in BRANCH_IMM or m.startswith(("b.", "bc."))) \
            and ins.operands and ins.operands[-1].type == ARM64_OP_IMM else []
        out.append([at[t] for t in tg if t in at] + ([n + 1] if m not in NO_FALL and n + 1 < len(insns) else []))
    return out

def reg_after(insns: list, n: int, reg: str, v: int, joins: set) -> int:
    """reg_values' transfer: reg's value after insns[n], v before it; constant only for adr/adrp, add #imm and mov of a
    constant (const_val's idioms, with reg's own value carried), NAC for any other write (a call clobbers CALL_CLOBBER)."""
    i = insns[n]
    if reg not in writes(i): return v
    ops = i.operands
    if not ops or ops[0].type != ARM64_OP_REG or i.reg_name(ops[0].reg)[:1] != "x" or xname(i.reg_name(ops[0].reg)) != reg: return NAC
    if i.mnemonic in ("adr", "adrp"): return ops[1].imm
    if i.mnemonic == "mov" and len(ops) == 2 and ops[1].type == ARM64_OP_IMM: return ops[1].imm & (2 ** 64 - 1)
    if i.mnemonic in ("add", "mov") and len(ops) >= 2 and ops[1].type == ARM64_OP_REG:
        src = xname(i.reg_name(ops[1].reg))
        b = v if src == reg else const_val(insns, n, src, joins)
        if b is None or b == NAC: return NAC
        if i.mnemonic == "mov" and len(ops) == 2: return b
        if i.mnemonic == "add" and len(ops) == 3 and ops[2].type == ARM64_OP_IMM:
            return (b + (ops[2].imm << (ops[2].shift.value if ops[2].shift.type else 0))) & (2 ** 64 - 1)
    return NAC

def reg_values(insns: list, at: dict, roots: list, edges: list, reg: str, joins: set) -> list:
    """Forward constant propagation of one x register over guest_edges: per instruction index, its value where the
    instruction starts (None: no path reaches it, NAC: not one constant on every path). Roots hold an unknown value (the
    caller's, a landing pad's)."""
    val, work = [None] * len(insns), []
    for r in roots:
        if r in at: val[at[r]] = NAC; work.append(at[r])
    while work:
        n = work.pop()
        out = reg_after(insns, n, reg, val[n], joins)
        for t in edges[n]:
            v = out if val[t] is None else val[t] if val[t] == out else NAC
            if v != val[t]: val[t] = v; work.append(t)
    return val

def hoisted(h: dict, k: int, reg: str) -> int | None:
    """reg's constant where insns[k] starts on every path of the CFG reach knows so far (h: its hoist state), else None."""
    if "edges" not in h: h["edges"] = guest_edges(h["insns"], h["at"], h["brs"])
    if reg not in h["vals"]: h["vals"][reg] = reg_values(h["insns"], h["at"], h["roots"], h["edges"], reg, h["joins"])
    v = h["vals"][reg][k]
    return None if v is None or v == NAC else v

def find_def(insns: list, k: int, reg: str, joins: set) -> int | None:
    """Index of the writer of reg that every path into insns[k] passes: the nearest one in straight-line code with no join (an address in joins: branch target, resume point) after it; None at a join, a stop or the window end."""
    for j in range(k - 1, max(-1, k - DEF_WINDOW), -1):
        if insns[j + 1].address in joins: return None                 # another path enters between the writer and k
        if insns[j].mnemonic in NO_FALL or insns[j].mnemonic == DATA_MNEMONIC: return None
        if reg in writes(insns[j]): return j
    return None

def const_val(insns: list, k: int, reg: str, joins: set, depth: int = 0) -> int | None:
    """Value of reg just before insns[k] on every path when built by adr / adrp (+ add #imm) / mov, else None."""
    j = find_def(insns, k, reg, joins)
    if j is None or depth > 4: return None
    i = insns[j]; ops = i.operands
    if i.mnemonic in ("adr", "adrp"): return ops[1].imm
    if i.mnemonic not in ("add", "mov") or len(ops) < 2 or ops[1].type != ARM64_OP_REG: return None
    mask = 0xFFFFFFFF if i.reg_name(ops[0].reg)[:1] == "w" else 2 ** 64 - 1   # a w destination truncates
    if i.mnemonic == "add" and len(ops) == 3 and ops[2].type == ARM64_OP_IMM:
        base = const_val(insns, j, xname(i.reg_name(ops[1].reg)), joins, depth + 1)
        return None if base is None else (base + (ops[2].imm << (ops[2].shift.value if ops[2].shift.type else 0))) & mask
    if i.mnemonic == "mov" and len(ops) == 2:
        v = const_val(insns, j, xname(i.reg_name(ops[1].reg)), joins, depth + 1)
        return None if v is None else v & mask
    return None

def zero_upper(insns: list, k: int, reg: str, joins: set) -> bool:
    """True when reg's 64-bit value just before insns[k] has its upper 32 bits zero (last written as a w register)."""
    j = find_def(insns, k, reg, joins)
    o = insns[j].operands if j is not None else []
    return bool(o) and o[0].type == ARM64_OP_REG and insns[j].reg_name(o[0].reg)[:1] == "w"

def flag_setter(insns: list, j: int, stop: int, idx: str, joins: set) -> int | None:
    """Index of the instruction that set the NZCV insns[j] reads, past instructions that write neither NZCV nor idx (clang
    may schedule a load between cmp and b.hi), with no join after it; None at a join, call, stop or index `stop`."""
    for s in range(j - 1, stop, -1):
        if insns[s + 1].address in joins: return None
        i = insns[s]
        if i.mnemonic in NO_FALL or i.mnemonic in CALLS or i.mnemonic == DATA_MNEMONIC: return None
        w = writes(i)
        if "nzcv" in w: return s
        if idx in w: return None
    return None

def copy_of(insns: list, s: int, a: str, b: str, joins: set) -> bool:
    """a holds b's value where insns[s] starts (in b's compared width): a straight-line `mov a, b`, b not written since."""
    j = find_def(insns, s, a, joins)
    if j is None: return False
    i = insns[j]; o = i.operands
    if i.mnemonic != "mov" or len(o) != 2 or o[1].type != ARM64_OP_REG or xname(i.reg_name(o[1].reg)) != b: return False
    return all(b not in writes(insns[t]) for t in range(j + 1, s))

def and_twin_bound(insns: list, j: int, src: str, mask: int, stop: int, joins: set) -> int | None:
    """Bound of `and idx, src, #mask` at insns[j] (mask < 2^32) from an earlier `and c, src, #mask` + cmp c,#N + b.hi/b.hs
    on its straight-line path (clang recomputes the masked index after the bound check), src not written in between."""
    for t in range(j - 1, stop, -1):
        if insns[t + 1].address in joins: return None
        i = insns[t]
        if i.mnemonic in NO_FALL or i.mnemonic == DATA_MNEMONIC or src in writes(i): return None
        if i.mnemonic not in ("b.hi", "b.hs") or i.address in joins: continue
        s = flag_setter(insns, t, stop, "", joins)
        if s is None or insns[s].mnemonic != "cmp" or insns[s].operands[1].type != ARM64_OP_IMM: return None
        c = insns[s]; o = c.operands
        d = find_def(insns, s, xname(c.reg_name(o[0].reg)), joins)
        do = insns[d].operands if d is not None else []
        if d is None or insns[d].mnemonic != "and" or len(do) != 3 or do[1].type != ARM64_OP_REG or do[2].type != ARM64_OP_IMM \
                or xname(insns[d].reg_name(do[1].reg)) != src or do[2].imm != mask: return None
        if any(src in writes(insns[u]) for u in range(d + 1, j)): return None
        return (o[1].imm << (o[1].shift.value if o[1].shift.type else 0)) + (1 if i.mnemonic == "b.hi" else 0)
    return None

def table_bound(insns: list, k: int, idx: str, wide: bool, joins: set) -> int | None:
    """Entry count proven on every path into the table load insns[k] (wide: the load indexes with all 64 bits): the fall-through of cmp idx,#N + b.hi/b.hs (instructions that write neither NZCV nor idx may sit between them; the cmp may be on the register idx was copied from), or idx = and #(2^m-1) (tightened by an equal masked value's cmp: and_twin_bound), with no join in between (a jump past the bound)."""
    for j in range(k - 1, max(-1, k - DEF_WINDOW), -1):
        if insns[j + 1].address in joins: return None
        i = insns[j]
        if i.mnemonic in NO_FALL or i.mnemonic == DATA_MNEMONIC: return None
        s = flag_setter(insns, j, max(-1, k - DEF_WINDOW), idx, joins) if i.mnemonic in ("b.hi", "b.hs") and i.address not in joins else None
        if s is not None and insns[s].mnemonic == "cmp":
            c = insns[s]; o = c.operands
            cw = c.reg_name(o[0].reg)
            same = xname(cw) == idx or copy_of(insns, s, idx, xname(cw), joins)      # cmp on the register idx was copied from
            if same and o[1].type == ARM64_OP_IMM and (not wide or cw[0] == "x" or zero_upper(insns, s, idx, joins)):
                return (o[1].imm << (o[1].shift.value if o[1].shift.type else 0)) + (1 if i.mnemonic == "b.hi" else 0)
        if idx in writes(i):
            o = i.operands
            if i.mnemonic == "mov" and len(o) == 2 and o[1].type == ARM64_OP_REG:
                wide = wide and i.reg_name(o[0].reg)[0] == "x"        # a w copy zero-extends: only the low half matters
                idx = xname(i.reg_name(o[1].reg)); continue            # the bound was proven on the copy's source
            if i.mnemonic == "and" and o[2].type == ARM64_OP_IMM and (o[2].imm + 1) & o[2].imm == 0:
                t = and_twin_bound(insns, j, xname(i.reg_name(o[1].reg)), o[2].imm, max(-1, k - DEF_WINDOW), joins) \
                    if o[1].type == ARM64_OP_REG and o[2].imm < 2 ** 32 else None
                return o[2].imm + 1 if t is None else min(o[2].imm + 1, t)
            return None
    return None

def jump_table(insns: list, j: int, lo: int, hi: int, read: object, joins: set, hoist: dict | None = None) -> list | None:
    """Targets of `add T, B, E{lsl|sxtw #s}` fed by a bounded ld{r,rb,rh,rsb,rsh,rsw} E,[tab, idx]; None if not that idiom.
    hoist (reach's state): B or tab may be a register set before a join (a table base kept across a loop); its value comes
    from hoisted and goes into hoist["uses"], which reach checks against the final CFG."""
    i = insns[j]; ops = i.operands
    if i.mnemonic != "add" or len(ops) != 3 or ops[2].type != ARM64_OP_REG or read is None: return None
    pend, breg = [], xname(i.reg_name(ops[1].reg))
    base = const_val(insns, j, breg, joins)
    if base is None and hoist is not None and (base := hoisted(hoist, j, breg)) is not None: pend.append((j, breg, base))
    e = xname(i.reg_name(ops[2].reg))
    jl = find_def(insns, j, e, joins)
    if base is None or jl is None or insns[jl].mnemonic not in TABLE_LOADS: return None
    ld = insns[jl]; mo = ld.operands[1]
    if mo.type != ARM64_OP_MEM or not mo.mem.index or mo.mem.disp: return None
    treg = xname(ld.reg_name(mo.mem.base))
    tab = const_val(insns, jl, treg, joins)
    if tab is None and hoist is not None and (tab := hoisted(hoist, jl, treg)) is not None: pend.append((jl, treg, tab))
    n = table_bound(insns, jl, xname(ld.reg_name(mo.mem.index)), ld.reg_name(mo.mem.index)[0] == "x", joins)
    width, fmt = TABLE_LOADS[ld.mnemonic]
    if tab is None or n is None or not 0 < n <= MAX_TABLE: return None
    if ld.mnemonic == "ldr" and ld.reg_name(ld.operands[0].reg)[0] != "w": return None
    if (1 << (mo.shift.value if mo.shift.type else 0)) != width: return None   # index scaled by the entry size
    raw = read(tab, n * width)
    if raw is None or len(raw) != n * width: return None
    wdst = ld.reg_name(ld.operands[0].reg)[0] == "w"                   # a w destination zero-extends into x
    ents = [x & 0xFFFFFFFF if wdst else x & (2 ** 64 - 1) for x in struct.unpack("<%d%s" % (n, fmt), raw)]
    if ops[2].ext == ARM64_EXT_SXTW: ents = [(x & 0xFFFFFFFF) - ((x & 0x80000000) << 1) for x in ents]
    elif ops[2].ext == ARM64_EXT_UXTW: ents = [x & 0xFFFFFFFF for x in ents]
    elif ops[2].ext: return None
    sh = ops[2].shift.value if ops[2].shift.type == ARM64_SFT_LSL else 0
    if ops[2].shift.type not in (0, ARM64_SFT_LSL): return None
    tg = [(base + (x << sh)) & (2 ** 64 - 1) for x in ents]
    if not all(lo <= t < hi and t % 4 == 0 for t in tg): return None
    if hoist is not None: hoist["uses"] += pend
    return tg

def table_load(insns: list, k: int, joins: set) -> int | None:
    """Index of the table load whose entry the br at insns[k] adds to a base (br_kind's 'table' idiom: `add T, B, E` fed by `ld E, [tab, idx]`, mov copies of T followed), else None."""
    reg = xname(insns[k].reg_name(insns[k].operands[0].reg))
    for _hop in range(4):
        j = find_def(insns, k, reg, joins)
        if j is None: return None
        i = insns[j]; ops = i.operands
        if i.mnemonic == "mov" and len(ops) == 2 and ops[1].type == ARM64_OP_REG:
            k, reg = j, xname(i.reg_name(ops[1].reg)); continue
        if i.mnemonic != "add" or len(ops) != 3 or ops[2].type != ARM64_OP_REG: return None
        jl = find_def(insns, j, xname(i.reg_name(ops[2].reg)), joins)
        return jl if jl is not None and insns[jl].mnemonic in TABLE_LOADS else None
    return None

def br_kind(insns: list, k: int, lo: int, hi: int, read: object, joins: set, hoist: dict | None = None) -> tuple[str, list]:
    """Classify the br at insns[k]: ('table'|'const', in-function targets), ('tail', []) constant target outside the function, ('pointer', []) a code pointer from an argument, call or memory, ('undecoded', []) anything else."""
    reg = xname(insns[k].reg_name(insns[k].operands[0].reg))
    for _hop in range(4):
        j = find_def(insns, k, reg, joins)
        if reg == "x30" and (j is None or insns[j].mnemonic in CALLS): return ("undecoded", [])   # a return address
        if j is None or insns[j].mnemonic in CALLS: return ("pointer", [])
        i = insns[j]; ops = i.operands
        cv = const_val(insns, k, reg, joins)
        if cv is not None: return ("const", [cv]) if lo <= cv < hi else ("tail", [])
        if i.mnemonic == "mov" and len(ops) == 2 and ops[1].type == ARM64_OP_REG:
            k, reg = j, xname(i.reg_name(ops[1].reg)); continue
        if i.mnemonic in ("ldp", "ldnp") and ops[2].type == ARM64_OP_MEM and not ops[2].mem.index:
            return ("pointer", [])                                     # a pair of pointers from an object (closure, vtable)
        if i.mnemonic in ("ldr", "ldur", "ldapr", "ldar") and len(ops) >= 2 and ops[1].type == ARM64_OP_MEM:
            m = ops[1].mem                                             # pointer from memory; indexed off a constant base = label table
            static = m.index and const_val(insns, j, xname(i.reg_name(m.base)), joins) is not None
            return ("undecoded", []) if static else ("pointer", [])
        tg = jump_table(insns, j, lo, hi, read, joins, hoist)
        return ("table", tg) if tg is not None else ("undecoded", [])
    return ("undecoded", [])

def walk(insns: list, at: dict, roots: list, read: object, joins: set, hoist: dict | None = None) -> tuple[set, dict]:
    """One recursive-descent pass from roots -> (reached addresses, br address -> br_kind) under the given joins (hoist: jump_table's)."""
    lo, hi = insns[0].address, insns[-1].address + insns[-1].size
    seen, brs, work = set(), {}, [a for a in roots if a in at]
    while work:
        n = at[work.pop()]
        while n < len(insns) and insns[n].address not in seen:
            ins = insns[n]; m = ins.mnemonic
            seen.add(ins.address)
            if m == DATA_MNEMONIC: break                               # control reaches data: a loud trap there
            if m == "br":
                brs[ins.address] = br_kind(insns, n, lo, hi, read, joins, hoist)
                work += [t for t in brs[ins.address][1] if t in at]
                break
            if m in BRANCH_IMM or m.startswith(("b.", "bc.")):
                t = ins.operands[-1].imm
                if t in at: work.append(t)
            if m in NO_FALL: break
            n += 1
    return seen, brs

def reach(insns: list, roots: list, read: object = None, inside: bool = True) -> tuple[set, dict, bool]:
    """Recursive descent over one function -> (reached addresses, br address -> (kind, targets), fallback). Joins are every direct-branch target, root and decoded br target, grown to a fixed point. Fallback: an undecoded br (or a 'pointer' br while `inside`, i.e. some pointer into this function's interior may exist) may land anywhere, so every decoded word counts as reached and the br switch lists them all."""
    at = {ins.address: n for n, ins in enumerate(insns)}
    joins = jump_edges(insns) | set(roots)                             # every edge, reached or not: a superset is conservative
    brs = {}
    for _round in range(len(insns) + 1):
        hoist = {"insns": insns, "at": at, "roots": roots, "brs": brs, "joins": joins, "vals": {}, "uses": []}   # optimistic: last round's CFG
        seen, brs = walk(insns, at, roots, read, joins, hoist)
        found = {t for _k, ts in brs.values() for t in ts} - joins
        if not found: break
        joins = joins | found
    if hoist["uses"]:                                                  # each hoisted base must hold on the final CFG, its tables' edges included
        edges, vals = guest_edges(insns, at, brs), {}
        for k, reg, v in hoist["uses"]:
            if reg not in vals: vals[reg] = reg_values(insns, at, roots, edges, reg, joins)
            if vals[reg][k] != v: return {i.address for i in insns if i.mnemonic != DATA_MNEMONIC}, brs, True
    if any(k == "undecoded" or (k == "pointer" and inside) for k, _t in brs.values()):
        return {i.address for i in insns if i.mnemonic != DATA_MNEMONIC}, brs, True
    return seen, brs, False

def page_uses(page: int, d: int, w: tuple) -> set:
    """[lo, hi) ranges of the adrp result page in register d over the straight-line words w after it: exact for add/sub #imm and load/store offsets (through mov copies), the whole page when it may escape otherwise (stored, passed, other arithmetic, live across a branch or past the window)."""
    regs, out, whole = {d}, set(), {(page, page + 0x1000)}
    for y in w:
        rd, rn, rm, ra = y & 31, (y >> 5) & 31, (y >> 16) & 31, (y >> 10) & 31
        if y & 0x9F000000 in (0x10000000, 0x90000000):                 # adr / adrp: a pure write of rd
            regs.discard(rd)
        elif y & 0xBF800000 == 0x91000000:                             # add / sub (immediate), 64-bit, no flags
            v = ((y >> 10) & 0xFFF) << (12 if y >> 22 & 1 else 0)
            if rn in regs: out.add((page - v, page - v + 1) if y >> 30 & 1 else (page + v, page + v + 1))
            regs.discard(rd)
        elif y & 0xFFE0FFE0 == 0xAA0003E0:                             # mov xd, xm (orr xd, xzr, xm)
            regs.add(rd) if rm in regs else regs.discard(rd)
        elif y & 0x3B000000 == 0x39000000:                             # load / store, unsigned offset (rd is rt)
            simd, opc = y >> 26 & 1, y >> 22 & 3
            gpr_load = not simd and opc and not (y >> 30 == 3 and opc == 2)   # size 3 opc 2 is prfm: rt is no register
            if not simd and not opc and rd in regs: return out | whole  # stores the page value
            if rn in regs:
                v = ((y >> 10) & 0xFFF) << (y >> 30)
                out.add((page + v, page + v + 1))
            if gpr_load: regs.discard(rd)
        elif y & 0x7C000000 == 0x14000000 or y & 0xFE000000 in (0x54000000, 0xD6000000) or y & 0x7E000000 in (0x34000000, 0x36000000):
            return out | whole if regs else out                        # control flow (b/bl, b.cond, br/blr/ret, cbz, tbz) with the page live
        elif {rd, rn, rm, ra} & regs:                                  # any other instruction naming it: may escape
            return out | whole
        if not regs: return out
    return out | whole

def code_refs(addr: int, raw: bytes) -> set:
    """[lo, hi) ranges an address that adr or adrp forms in raw at addr may end up as: adr its exact target; adrp what page_uses follows it to (exact through copies and add, else its whole 4 KB page)."""
    w = struct.unpack("<%dI" % (len(raw) // 4), raw[:len(raw) // 4 * 4])
    sx = lambda v: v - (1 << 21) if v & (1 << 20) else v              # 21-bit signed immediate
    out = set()
    for n, x in enumerate(w):
        if x & 0x9F000000 == 0x10000000:                               # adr
            t = addr + 4 * n + sx(((x >> 5) & 0x7FFFF) << 2 | (x >> 29) & 3)
            out.add((t, t + 1))
        elif x & 0x9F000000 == 0x90000000 and x & 31 != 31:            # adrp (xzr destination: no value)
            page = ((addr + 4 * n) & ~0xFFF) + (sx(((x >> 5) & 0x7FFFF) << 2 | (x >> 29) & 3) << 12)
            out |= page_uses(page, x & 31, w[n + 1:n + 1 + PAGE_WINDOW])
    return out

###############
# function assembly
###############
def local_of(m: re.Match) -> str:
    """C local standing for one CPU field reference (REG_REF match)."""
    return "gr_x%s" % m.group(1) if m.group(1) else "gr_v%s" % m.group(2) if m.group(2) else "gr_" + m.group(3).lower()

def field_of(name: str) -> str:
    """CPU field of a gr_ local."""
    k = name[3:]
    if not k[1:].isdigit(): return "c->" + k.upper()                   # sp and the flags (gr_vf is the V flag, not a register)
    return "c->X[%s]" % k[1:] if k[0] == "x" else "c->V[%s]" % k[1:]

def local_type(name: str) -> str:
    """C type of a gr_ local."""
    k = name[3:]
    return "uint64_t" if k == "sp" or k[0] == "x" else "V128" if k[1:].isdigit() else "uint32_t"

def mask_of(names: object) -> int:
    """Dirty-mask bits of gr_ local names."""
    m = 0
    for n in names: m |= 1 << LOCAL_BIT[n]
    return m

@functools.lru_cache(maxsize=None)
def spill_of(mask: int, fwrap: str) -> str:
    """C stores of the locals in a dirty mask back to the CPU struct; the NZCV stores go inside fwrap (a %s format: the preprocessor condition of the site, see flag_wrap)."""
    regs = "".join(SPILL_TEXT[k] for k in range(FLAG_BIT0) if mask >> k & 1) + "".join(SPILL_TEXT[k] for k in range(FLAG_BIT0 + 4, len(LOCAL_AT)) if mask >> k & 1)
    flags = "".join(SPILL_TEXT[k] for k in range(FLAG_BIT0, FLAG_BIT0 + 4) if mask >> k & 1)
    return regs + (fwrap % flags if flags else "")

def flag_wrap(kind: str, self_start: int) -> str:
    """Preprocessor guard of the NZCV stores at a spill site: a direct call or tail call to f ('D<hex>') stores them when f reads flags at entry (GDF_IN_<f>), a return ('R') when a caller reads them after the call (GDF_RET_<own start>), any other site only when gdyld could not place every flag use (GD_FLAGS_ALL; 1 unless gdyld's header says 0)."""
    cond = "defined(GDF_IN_%s)" % kind[1:] if kind[:1] == "D" else "defined(GDF_RET_%x)" % self_start if kind == "R" else "0"
    return "\n#if GD_FLAGS_ALL || %s\n%%s\n#endif\n" % cond

def flag_facts(parts: list[tuple[int, str]], edges: list, entries: list[int], insns: list, fstarts: set, blind: frozenset = frozenset()) -> dict:
    """Where the NZCV values this function's flag sinks see come from (flag_origins: 'E' its entry, ('N', address) a resume or extra entry, ('S', target) the return of a bl to an import stub (or extern), 'I' an indirect call's, an int: that direct callee's return, ('B', origin) that origin carried through an undecoded br's edges to every word (blind); values it sets itself are not listed): 'local' at its own flag reads, 'ret' at its returns, 'sites' {callee: origins} at each direct call or tail call, plus 'tails' direct tail-call targets, 'stails' stub (or extern) tail-call targets and 'itail' an indirect tail exit. gdyld.flag_plan closes these over the image: a return matters when a caller needs the callee's flags, a call site when the callee reads flags at entry."""
    inn = flag_origins(edges, entries, insns, fstarts, blind)
    addrs = {i.address for i in insns}
    out = {"local": set(), "ret": set(), "sites": {}, "tails": set(), "stails": set(), "itail": False}
    last = max((n for n, (succ, _c) in enumerate(edges) if inn[n] is not None), default=-1)
    for n, t in parts:
        o = inn[n] if n >= 0 and inn[n] is not None else frozenset()
        if n < 0 and "GD_SPILLR" in t and last >= 0 and insns[last].mnemonic not in NO_FALL:
            out["ret"] |= flag_out(insns[last], inn[last], fstarts, edges[last][1])   # the last instruction falls into the closing return
        if n < 0 or not o: continue
        if FLAG_READ.search(t): out["local"] |= o
        if "GD_SPILLR" in t: out["ret"] |= o
        for g in SITE_RE.findall(t): out["sites"][int(g, 16)] = out["sites"].get(int(g, 16), frozenset()) | o
    for n, ins in enumerate(insns):
        if inn[n] is None: continue
        m = ins.mnemonic
        if (m in BRANCH_IMM or m.startswith(("b.", "bc."))) and ins.operands and ins.operands[-1].type == ARM64_OP_IMM:
            t = ins.operands[-1].imm
            if t not in addrs:
                if t in fstarts: out["tails"].add(t)
                else: out["stails"].add(t)                             # an import stub (or an extern_stub stop)
        if m == "br": out["itail"] = True                              # a br may dispatch out of the function
    return {**out, "local": frozenset(out["local"]), "ret": frozenset(out["ret"])}

def flag_out(ins: object, o: frozenset, fstarts: set, call: bool) -> frozenset:
    """Origins of NZCV after one instruction given those before it: a direct call's callee, ('S', target) after a bl to anything else (an import stub), 'I' after an indirect call, none after a full NZCV write (FLAG_KILL), else unchanged."""
    if call:
        t = ins.operands[0].imm if ins.mnemonic == "bl" and ins.operands and ins.operands[0].type == ARM64_OP_IMM else None
        return frozenset([t if t in fstarts else ("S", t) if t is not None else "I"])
    return frozenset() if ins.mnemonic in FLAG_KILL else o

def flag_origins(edges: list, entries: list[int], insns: list, fstarts: set, blind: frozenset = frozenset()) -> list[frozenset | None]:
    """Forward dataflow per instruction index: the origins (flag_facts) of the NZCV value where it starts ('E' the function start, ('N', address) a resume or extra entry point); None where no C path reaches it. The edges out of an instruction index in blind (an undecoded br's, to every word) tag each origin they carry ('B', origin), once."""
    inn = [None] * len(edges)
    work = []
    for k, e in enumerate(entries):
        inn[e] = (inn[e] or frozenset()) | frozenset(["E" if k == 0 else ("N", insns[e].address)]); work.append(e)
    while work:
        n = work.pop()
        succ, call = edges[n]
        o = flag_out(insns[n], inn[n], fstarts, call)
        if n in blind: o = frozenset(x if isinstance(x, tuple) and x[0] == "B" else ("B", x) for x in o)
        for s in succ:
            if inn[s] is None or not o <= inn[s]:
                inn[s] = o if inn[s] is None else inn[s] | o
                work.append(s)
    return inn

def flow_edges(insns: list, reached: set, cases: set) -> list[tuple[list[int], bool]]:
    """Per instruction index, as the lifted C runs: (successor indices, True for a call after which every local equals the CPU struct again). A br reaches every case of the function's gd_ijump switch."""
    at = {i.address: n for n, i in enumerate(insns)}
    out = []
    for n, ins in enumerate(insns):
        m = ins.mnemonic
        if ins.address not in reached or m == DATA_MNEMONIC: out.append(([], False)); continue
        tg = sorted(cases) if m == "br" else [ins.operands[-1].imm] if (m in BRANCH_IMM or m.startswith(("b.", "bc."))) \
            and ins.operands and ins.operands[-1].type == ARM64_OP_IMM else []
        nxt = [n + 1] if m not in NO_FALL and n + 1 < len(insns) else []
        out.append(([at[t] for t in tg if t in at and t in reached] + nxt, m in ("bl", "blr")))
    return out

def dirty_in(edges: list, writes: list[int], entries: list[int], edge_clean: dict | None = None, keep: int = 0) -> list[int | None]:
    """Forward dataflow: mask of the locals that may differ from the CPU struct where each instruction starts (None: no C path reaches it). Entries start clean; a call leaves everything clean (stored before, reloaded after) but keep, which it may neither store nor reload (localize abi: callee-saved registers); edge_clean[(n, s)]: locals a spill on the edge n -> s stores (loop_entry_spills)."""
    din, work = [None] * len(edges), []
    for e in entries:
        if din[e] is None: din[e] = 0; work.append(e)
    while work:
        n = work.pop()
        succ, call = edges[n]
        out = (din[n] | writes[n]) & keep if call else din[n] | writes[n]
        for s in succ:
            o = out & ~edge_clean.get((n, s), 0) if edge_clean else out
            if din[s] is None or din[s] | o != din[s]:
                din[s] = o if din[s] is None else din[s] | o
                work.append(s)
    return din

def loop_entry_spills(edges: list, writes: list[int], din: list, texts: dict, insns: list) -> dict:
    """{(pred, head): mask} of the locals to store on each forward edge into a loop head whose index range holds a call: those dirty on the edge that no instruction in the range writes (a register set before the loop and only read in it would otherwise be stored at every call in every turn). Only edges a spill can be placed on: the head's own fallthrough, or a `goto L_<head>;` in the predecessor's text (texts: index -> its joined text)."""
    last, preds, ncall = {}, {}, [0]                                   # head -> last back-edge source; head -> forward preds; calls before each index
    for n, (succ, call) in enumerate(edges):
        ncall.append(ncall[-1] + call)
        for s in succ:
            if s <= n: last[s] = max(last.get(s, n), n)
            else: preds.setdefault(s, set()).add(n)
    out = {}
    for h in sorted(last):
        if ncall[last[h] + 1] == ncall[h]: continue
        inloop = 0
        for n in range(h, last[h] + 1): inloop |= writes[n]           # ponytail: sum of loop extents (n x nesting depth), fine for real code
        for p in sorted(preds.get(h, ())):
            if din[p] is None or edges[p][1]: continue
            m = (din[p] | writes[p]) & REG_BITS & ~inloop
            fall = h == p + 1 and insns[p].mnemonic not in NO_FALL
            if m and (fall or "goto L_%x;" % insns[h].address in texts.get(p, "")): out[(p, h)] = m
    return out

def abi_split(mask: int, keep: int, fwrap: str, split: bool, cond: str = "!GD_ABI") -> str:
    """spill_of(mask, fwrap), with the stores outside keep only under the preprocessor condition cond when split (the image runs under the AAPCS64 register contract only when gdyld's header says GD_ABI 1)."""
    if not split or not mask & ~keep: return spill_of(mask, fwrap)
    return spill_of(mask & keep, fwrap) + "\n#if %s\n%s\n#endif\n" % (cond, spill_of(mask & ~keep, ""))

def reg_names(mask: int) -> str:
    """The guest registers of a LOCAL_BIT mask, for a report."""
    return ", ".join(LOCAL_AT[k][3:] for k in range(len(LOCAL_AT)) if mask >> k & 1)

def sp_after(ins: object, d: int | None) -> int | None:
    """sp's offset from its value at the function's entry after ins, from d before it (None: unknown): sub/add sp, sp, #imm and sp-based writeback are followed, any other write of sp loses it."""
    if d is None or "sp" not in (ins.reg_name(r) for r in ins.regs_access()[1]): return d
    ops, mem = ins.operands, [o for o in ins.operands if o.type == ARM64_OP_MEM]
    if ins.mnemonic in ("add", "sub") and len(ops) == 3 and ops[2].type == ARM64_OP_IMM and ins.reg_name(ops[1].reg) == "sp":
        v = ops[2].imm << (ops[2].shift.value if ops[2].shift.type == ARM64_SFT_LSL else 0)
        return d - v if ins.mnemonic == "sub" else d + v
    if ins.writeback and mem and ins.reg_name(mem[0].mem.base) == "sp" and not mem[0].mem.index:
        return d + (ops[-1].imm if ins.post_index else mem[0].mem.disp)
    return None

def saved_by(ins: object, d: int | None) -> int:
    """Mask of the callee-saved registers ins stores below sp's entry value, a prologue save (d: sp_after's offset before ins)."""
    mem = [o for o in ins.operands if o.type == ARM64_OP_MEM]
    if d is None or ins.mnemonic not in SAVE_OPS or not mem or ins.reg_name(mem[0].mem.base) != "sp" or mem[0].mem.index: return 0
    if d + (0 if ins.post_index else mem[0].mem.disp) >= 0: return 0
    names = [ins.reg_name(o.reg) for o in ins.operands if o.type == ARM64_OP_REG]
    return mask_of("gr_x" + r[1:] if r[0] == "x" else "gr_v" + r[1:] for r in names if r[0] in "xdq" and r[1:].isdigit()) & ABI_CS

def abi_check(parts: list[tuple[int, str]], edges: list, entries: list[int], insns: list, fstarts: set,
              noret: frozenset = frozenset(), brt: dict | None = None, sites: dict | None = None, blind: frozenset = frozenset()) -> tuple[dict, tuple]:
    """({index of a direct call: mask of the ABI_NOT_OUT registers read after it}: the site reloads them all and the callee keeps every store at its returns, gdyld GDA_RET_<callee>; compiled code does this for an undefined value or a callee with its own convention, (reads, writes, calls), the unread prologue saves (saved_reads; none when a call is read past)): what gdyld abi_plan closes over the image's calls to tell which functions break the AAPCS64 register contract GD_ABI relies on, as machine-outlined bodies do: reads, the ABI_EXTRA registers live at the entry (read before written) or whose entry values a load takes back from their save slots (saved_reads); writes, the callee-saved registers written where no prologue save (saved_by, stored below the entry sp on every path there) came first; calls, [(sites[index], ABI_EXTRA registers that may still hold their entry values there and are not yet saved (owned), callee-saved registers saved on every path there)] per reached call or tail call site (sites: index -> ('d', callee) or ('g', GOT vmaddr)). Backward liveness over the lifted text (parts with locals): a read is a mention that is not an assignment (lift_neon's unused _d copy is none), a prologue save, or of a callee-saved register already saved on every path there (the function owns it; its reads past correlated branches the liveness cannot follow are its own), a text without `if (` kills what it assigns whole (a V register: all 16 bytes of its lanes), a call kills ABI_CLOBBER (what it reads is the callee's own entry check), a direct call into noret has no successor, and an exit or br keeps the results live (a br reaches its own decoded table's targets (brt: index -> target indices; else every case but the function start, a tail call that sets its own arguments), and an undecoded one (blind) has no successor here: a compiled jump table's targets read only what is defined at the br, never an entry value of ABI_EXTRA registers, and write callee-saved registers only after the prologue saves before it, while its edges to every word make every register look live and every save look skipped); a callee-saved register is not live at an exit, its value is not read there."""
    n, texts = len(edges), {}
    for i, t in parts:
        if i >= 0: texts[i] = texts.get(i, "") + t + "\n"
    rd, kl, anyw, preds = [0] * n, [0] * n, [0] * n, [[] for _ in range(n)]
    for i, t in texts.items():
        if DEAD_DEST.search(t) and len(re.findall(r"\b_d\b", t)) == 1: t = DEAD_DEST.sub("", t)
        occ, whole, lanes, cover = collections.Counter(LOCAL_NAME.findall(t)), collections.Counter(PLAIN_WRITE.findall(t)), collections.Counter(), {}
        for r, f, k in LANE_WRITE.findall(t):
            lanes[r] += 1
            if f[0] == "v": cover[r] = set(range(16))
            else: w = LANE_BYTES[f]; cover.setdefault(r, set()).update(range(int(k) * w, int(k) * w + w))
        rd[i] = mask_of(x for x in occ if occ[x] > whole[x] + lanes[x]) & ~NZCV_BITS
        kl[i] = 0 if "if (" in t else mask_of(list(whole) + [r for r, c in cover.items() if len(c) >= 16])
        anyw[i] = mask_of(list(whole) + list(lanes))
    succs = [[] if i in blind or call and insns[i].mnemonic == "bl" and insns[i].operands[0].imm in noret else
             (brt[i] if brt and i in brt else [x for x in succ if x]) if insns[i].mnemonic == "br" else succ for i, (succ, call) in enumerate(edges)]
    for i, (succ, call) in enumerate(edges):
        if call: kl[i] |= ABI_CLOBBER
        for s in succs[i]: preds[s].append(i)
    unseen, work = object(), [0]
    spd = [unseen] * n; spd[0] = 0                                     # sp offsets: one value on every path, else None
    for e in entries[1:]: spd[e] = None; work.append(e)
    while work:
        i = work.pop(); d = sp_after(insns[i], spd[i])
        for s in succs[i]:
            if spd[s] is unseen: spd[s] = d; work.append(s)
            elif spd[s] is not None and spd[s] != d: spd[s] = None; work.append(s)
    sv = [0 if spd[i] is unseen else saved_by(insns[i], spd[i]) for i in range(n)]
    def flow(vals: list, work: list, step: object, join: object) -> None:
        while work:
            i = work.pop(); o = step(i, vals[i])
            for s in succs[i]:
                v = o if vals[s] is None else join(vals[s], o)
                if v != vals[s]: vals[s] = v; work.append(s)
    save_step, entry_step = lambda i, v: v | sv[i], lambda i, v: v & ~kl[i]
    both, either = lambda a, b: a & b, lambda a, b: a | b
    saved, entry = [None] * n, [None] * n                              # saved on every path; may still hold the entry value
    saved[0], entry[0] = 0, (1 << len(LOCAL_AT)) - 1
    flow(saved, [0], save_step, both); flow(entry, [0], entry_step, either)
    at_calls = [i for i, (_s, call) in enumerate(edges) if call and saved[i] is not None]
    for e in entries[1:]:                                              # a resume point is re-entered past one of the calls
        s = functools.reduce(both, (save_step(i, saved[i]) for i in at_calls), ABI_CS)
        v = functools.reduce(either, (entry_step(i, entry[i]) for i in at_calls), 0)
        saved[e] = s if saved[e] is None else saved[e] & s
        entry[e] = v if entry[e] is None else entry[e] | v
    flow(saved, list(entries[1:]), save_step, both); flow(entry, list(entries[1:]), entry_step, either)
    raw = list(rd)
    for i in range(n): rd[i] &= ~sv[i] & ~(ABI_CS & (saved[i] or 0))   # a function that saved a register owns it
    exit_live = ABI_OUT & ~NZCV_BITS
    live, work = [0] * n, list(range(n))
    while work:
        i = work.pop()
        out = exit_live if not succs[i] or insns[i].mnemonic == "br" else 0
        for s in succs[i]: out |= live[s]
        v = rd[i] | out & ~kl[i]
        if v != live[i]: live[i] = v; work += preds[i]
    late = {}
    for i, (succ, call) in enumerate(edges):
        if call and insns[i].mnemonic == "bl" and insns[i].operands[0].imm in fstarts:
            after = 0
            for s in succs[i]: after |= live[s]
            if after & ABI_NOT_OUT: late[i] = after & ABI_NOT_OUT
    wrote = 0
    for i in range(n):
        if saved[i] is not None: wrote |= anyw[i] & ABI_CS & ~saved[i]
    calls = [(r, entry[i] & ABI_EXTRA & ~saved[i], saved[i]) for i, r in sorted((sites or {}).items()) if saved[i] is not None]
    unread, back = saved_reads(insns, succs, preds, entries, spd, sv, anyw, kl, raw, flow)
    return late, (live[0] & ABI_EXTRA | back, wrote, calls), ({} if late else unread)

def saved_reads(insns: list, succs: list, preds: list, entries: list[int], spd: list, sv: list, anyw: list, kl: list, raw: list,
                flow: object) -> tuple[dict[int, int], int]:
    """(unread, read) for abi_check's prologue saves, the stores of callee-saved registers that hold their entry values on every path there: read, the callee-saved registers whose entry value a load takes back from its save slot into a register then used (any but a callee-saved one, or one live after it: liveness over the unmasked reads `raw` and abi_check's kills `kl`, no callee-saved register live at an exit), which reads the caller's register the way an entry read does; unread ({index: registers}), the saves no such load reads, in a function with one entry. A load may read a slot when it is sp- or fp-based at an offset that overlaps the slot, or at an unknown one (x29 set from sp by add or mov keeps its offset), on a path where no store at a known offset covered the slot since the save; other bases point into objects, not save slots. Under the register contract callers keep these registers themselves, so an unread save only feeds the epilogue's restore, whose result is dead, and a guest unwinder (gdyld GD_CSE: none loaded): localize puts it under CSE_KEEP."""
    n, every = len(insns), (1 << len(LOCAL_AT)) - 1
    must = [None] * n; must[0] = every                                 # holds the entry value on every path
    flow(must, [0], lambda i, v: v & ~anyw[i], lambda a, b: a & b)
    def span(ins: object, d: int) -> tuple[int, int, list]:
        m = [o for o in ins.operands if o.type == ARM64_OP_MEM][0].mem
        regs = [ins.reg_name(o.reg) for o in ins.operands if o.type == ARM64_OP_REG]
        a = d + (0 if ins.post_index else m.disp)
        size = NARROW_ACCESS.get(ins.mnemonic, 0)
        return a, a + sum(size or {"q": 16, "v": 16, "x": 8, "d": 8, "w": 4, "s": 4, "h": 2, "b": 1}.get(r[0], 16) for r in regs), regs
    slots = []                                                         # (save index, register bit, first byte, end) per saved register
    for i in range(n):
        if not sv[i] or must[i] is None or not isinstance(spd[i], int) or sv[i] & ~must[i]: continue
        a, _e, regs = span(insns[i], spd[i])
        if mask_of("gr_x" + r[1:] if r[0] == "x" else "gr_v" + r[1:] for r in regs if r[0] in "xd" and r[1:].isdigit()) != sv[i] or len(regs) != bin(sv[i]).count("1"):
            continue                                                   # a q register or a register outside the contract's saves
        for k, r in enumerate(regs):
            slots.append((i, 1 << LOCAL_BIT["gr_x" + r[1:] if r[0] == "x" else "gr_v" + r[1:]], a + 8 * k, a + 8 * k + 8))
    if not slots: return {}, 0
    unseen, work = object(), [0]                                       # x29 less the entry sp: one value on every path, else None
    fpd = [unseen] * n; fpd[0] = None
    for e in entries[1:]: fpd[e] = None; work.append(e)
    while work:
        i = work.pop(); ins = insns[i]; d = fpd[i]
        if "x29" in writes(ins):
            o = ins.operands
            d = (spd[i] + (o[2].imm if len(o) == 3 else 0)) if ins.mnemonic in ("add", "mov") and len(o) in (2, 3) and o[1].type == ARM64_OP_REG \
                and ins.reg_name(o[1].reg) == "sp" and (len(o) == 2 or o[2].type == ARM64_OP_IMM and not o[2].shift.type) and isinstance(spd[i], int) else None
        for s in succs[i]:
            if fpd[s] is unseen: fpd[s] = d; work.append(s)
            elif fpd[s] is not None and fpd[s] != d: fpd[s] = None; work.append(s)
    def access(ins: object, j: int) -> tuple[int, int] | None | bool:
        """(first byte, end) of a stack access off sp or x29, None at an unknown offset, False for any other base."""
        mem = [o for o in ins.operands if o.type == ARM64_OP_MEM]
        base = ins.reg_name(mem[0].mem.base) if mem else ""
        if base not in ("sp", "x29", "fp"): return False
        d = spd[j] if base == "sp" else fpd[j]
        if mem[0].mem.index or not isinstance(d, int): return None
        a, e, _r = span(ins, d)
        return a, max(e, a + 1)
    gen, kill = [0] * n, [0] * n
    for j, ins in enumerate(insns):
        if ins.mnemonic.startswith("st") and ins.mnemonic != DATA_MNEMONIC and (r := access(ins, j)):
            for k, (i, _b, a, e) in enumerate(slots):
                if i == j: gen[j] |= 1 << k
                elif r[0] <= a and e <= r[1]: kill[j] |= 1 << k      # the whole slot overwritten
    held = [None] * n; held[0] = 0                                     # slots that may still hold the entry value
    for e in entries[1:]: held[e] = (1 << len(slots)) - 1
    flow(held, [0] + list(entries[1:]), lambda i, v: v & ~kill[i] | gen[i], lambda a, b: a | b)
    live, work = [0] * n, list(range(n))
    while work:
        i = work.pop()
        out = 0
        for s in succs[i]: out |= live[s]
        v = raw[i] | out & ~kl[i]
        if v != live[i]: live[i] = v; work += preds[i]
    read, used = 0, set()
    for j, ins in enumerate(insns):
        if not ins.mnemonic.startswith("ld") or ins.mnemonic == DATA_MNEMONIC or not held[j] or (r := access(ins, j)) is False: continue
        after = 0
        for s in succs[j]: after |= live[s]
        dest = anyw[j] & ~(1 << LOCAL_BIT["gr_sp"])
        if not (dest & ~ABI_CS or dest & after): continue
        for k, (i, b, a, e) in enumerate(slots):
            if held[j] >> k & 1 and (r is None or a < r[1] and r[0] < e): read |= b; used.add(i)
    return ({} if entries[1:] else {i: sv[i] for i, _b, _a, _e in slots if i not in used}), read

def place_edge_spills(parts: list[tuple[int, str]], spills: dict, insns: list, split: bool = False) -> list[tuple[int, str]]:
    """parts with each loop_entry_spills store placed on its edge: inside the predecessor's `goto L_<head>;` and after its last part when it falls into the head (split: abi_split against ABI_IN)."""
    by_pred = {}
    for (p, h), m in spills.items(): by_pred.setdefault(p, []).append((h, m))
    last_part = {n: k for k, (n, _t) in enumerate(parts) if n >= 0}
    out = []
    for k, (n, t) in enumerate(parts):
        for h, m in by_pred.get(n, []):
            go = "goto L_%x;" % insns[h].address
            t = t.replace(go, "{ %s%s }" % (abi_split(m, ABI_IN, "", split), go))
        out.append((n, t))
        if n >= 0 and last_part[n] == k:
            out += [(n, "  " + abi_split(m, ABI_IN, "", split)) for h, m in by_pred.get(n, []) if h == n + 1 and insns[n].mnemonic not in NO_FALL]
    return out

def localize(parts: list[tuple[int, str]], edges: list, entries: list[int], regs: bool, insns: list, fstarts: set,
             blind: frozenset = frozenset(), abi: bool = False, noret: frozenset = frozenset(), brt: dict | None = None,
             sites: dict | None = None) -> tuple[str, str, dict | None]:
    """(body, entry declarations, flag_facts) from (instruction index or -1, text) parts with SPILL / RELOAD / TAIL markers. regs: the guest registers, NZCV and V registers the text names become C locals; each SPILL (and each return) stores only the locals that may be dirty there (dirty_in, plus what the instruction itself wrote), its NZCV stores under the site's flag_wrap guard, each RELOAD reloads them all; else the text keeps c-> (the CPU struct is always current) and the markers vanish (flag_facts as for regs: what the function's callers and callees owe it). abi: the image may run under the AAPCS64 register contract (gdyld GD_ABI): the facts get 'abi_late' and 'abi_fn' (abi_check), and in a function with one entry the stores and reloads the contract makes unneeded go under !GD_ABI: a call stores ABI_IN, a return ABI_OUT, a reload after a call takes ABI_BACK (callee-saved registers keep their locals; caller-saved ones are undefined). A call site (sites: index -> ('d', callee) or ('g', GOT vmaddr)) also stores and reloads everything when gdyld finds its callee breaks the contract (GDA_X_<callee>, GDA_G_<GOT>), and a direct call abi_check finds read after always does (gdyld makes the callee's returns and tail calls store everything: GDA_RET_<callee>). Functions with resume points or extra entries keep every store and reload: the guest unwinder, setjmp and a return past a host call site read the CPU struct."""
    parts = [(n, t.replace("return;", "GD_SPILLR return;") if "return;" in t else t) for n, t in parts]   # every exit but a tail call's
    lparts = [(n, REG_REF.sub(local_of, t.replace("flags_add(c, ", "flags_add_l(&c->NF,&c->ZF,&c->CF,&c->VF, "))
                   .replace("GD_SPW;", "c->SP=gr_sp; GD_SIGF;")) for n, t in parts]
    late, fn, cse = abi_check(lparts, edges, entries, insns, fstarts, noret, brt, sites, blind) if abi else ({}, None, {})
    why = {"abi_late": {insns[i].operands[0].imm: m for i, m in late.items()}, "abi_fn": fn} if abi else {}
    if not regs: return ("\n".join(SPILL_MARK.sub("", t).replace(RELOAD, "").replace(TAIL, "return;") for _n, t in parts), "",
                         {**flag_facts(lparts, edges, entries, insns, fstarts, blind), **why})
    split = abi and len(entries) == 1
    parts = [(n, cs_keep(t, cse[n], insns[0].address) if split and n in cse else t) for n, t in lparts]
    writes, every, texts = [0] * len(edges), 0, {}
    for n, t in parts:
        w = mask_of(a or b for a, b in LOCAL_WRITE.findall(t))
        every |= w
        if n >= 0: writes[n] |= w; texts[n] = texts.get(n, "") + t
    keep = ABI_CS if split else 0
    din = dirty_in(edges, writes, entries, keep=keep)
    spills = loop_entry_spills(edges, writes, din, texts, insns)
    if spills:
        parts = place_edge_spills(parts, spills, insns, split)
        din = dirty_in(edges, writes, entries, spills, keep)
    used = mask_of(n for _n, t in parts for n in LOCAL_NAME.findall(t))
    names = [n for k, n in enumerate(LOCAL_AT) if used >> k & 1]
    reload = " " + "".join("%s=%s; " % (n, field_of(n)) for n in names if not split or ABI_BACK >> LOCAL_BIT[n] & 1)
    rest = "".join("%s=%s; " % (n, field_of(n)) for n in names if split and not ABI_BACK >> LOCAL_BIT[n] & 1)
    reload_of = lambda sc: reload + ("\n#if !GD_ABI%s\n%s\n#endif\n" % (sc, rest) if rest else "")
    site = {i: " || defined(GDA_%s_%x)" % ("X" if r[0] == "d" else "G", r[1]) for i, r in (sites or {}).items()}   # its callee breaks the contract
    full = " " + "".join("%s=%s; " % (n, field_of(n)) for n in names)
    back = "!GD_ABI || defined(GDA_RET_%x)" % insns[0].address         # this function's callers read registers past its results
    facts = {**flag_facts(parts, edges, entries, insns, fstarts, blind), **why}
    start = insns[0].address
    body = []
    for n, t in parts:
        if "GD_SPILL" in t:
            mask = every if n < 0 or din[n] is None else din[n] | writes[n]
            t = SPILL_MARK.sub(lambda m: abi_split(mask, ABI_OUT if m.group(1) == "R" else ABI_IN, flag_wrap(m.group(1) or "", start),
                                                   split and n not in late, (back if m.group(1) == "R" or TAIL in t else "!GD_ABI") + site.get(n, "")), t)
        body.append(t.replace(RELOAD, full if n in late else reload_of(site.get(n, ""))).replace(TAIL, "return;") if "GD_" in t else t)
    return "\n".join(body), "".join("  %s %s=%s;\n" % (local_type(n), n, field_of(n)) for n in names), facts

def cs_keep(t: str, mask: int, start: int) -> str:
    """t with its stores of the callee-saved registers in mask under CSE_KEEP (saved_reads), unchanged unless each has one."""
    hits = [m for m in CS_STORE.finditer(t) if mask >> LOCAL_BIT[m.group(1) or m.group(2)] & 1]
    if len(hits) != bin(mask).count("1"): return t
    keep = CSE_KEEP % start
    at = {m.span() for m in hits}
    return CS_STORE.sub(lambda m: "\n#if %s\n%s\n#endif\n" % (keep, m.group(0)) if m.span() in at else m.group(0), t)

def flag_capture(ins: object) -> tuple[str, int, str] | None:
    """(kind, width, C statements saving the setter's source operands into gf_a/gf_b or gf_fa/gf_fb before it runs) for a compare-like NZCV setter FUSED can rewrite readers of, else None."""
    k = FUSE_SETTER.get(ins.mnemonic)
    if k is None or has_vector(ins): return None
    kind, i = k
    ops = ins.operands
    if kind == "fp":
        ka, ia, wa = reg_parts(ins.reg_name(ops[0].reg))
        if ka not in ("d", "s"): return None                           # half precision: not fused
        fld = "f64[0]" if ka == "d" else "f32[0]"
        b = "0.0" if ops[1].type == ARM64_OP_FP else "c->V[%d].%s" % (reg_parts(ins.reg_name(ops[1].reg))[1], fld)
        return ("fp", 64, "gf_fa=(double)c->V[%d].%s; gf_fb=(double)(%s);" % (ia, fld, b))
    w = reg_parts(ins.reg_name(ops[0].reg))[2]
    if i >= 0 and ops[i].type != ARM64_OP_REG: return None
    a = "0" if i < 0 else rd(*reg_parts(ins.reg_name(ops[i].reg))[:2], w)
    return (kind, w, "gf_a=(uint64_t)(%s); gf_b=(uint64_t)(%s);" % (a, operand_val(ins, ops[i + 1 if i >= 0 else 1], w)))

def fuse_reader(text: str, cc: int, state: tuple | None) -> str:
    """Reader text with its condition CC[cc] rewritten from the captured compare operands (state: flag_capture's kind and width), else unchanged."""
    if state is None or cc not in FUSED[state[0]] or CC.get(cc, "") not in text: return text
    expr = FUSED[state[0]][cc].replace("(U)", "(uint%d_t)" % state[1]).replace("(S)", "(int%d_t)" % state[1])
    return text.replace(CC[cc], "(%s)" % expr)

def loop_heads(edges: list, insns: list, addrs: set, fstarts: set) -> set[int]:
    """Instruction indexes that get a GD_LOOP barrier: every target of an edge that does not go forward (every cycle has one), and the entry when a direct tail call leaves the function (clang may turn a tail call that inlining makes self-recursive into a loop). Without it -O2 keeps a polled guest word in a register or sinks a loop's stores past it (spin-waits, relaxed atomics, setjmp-volatile locals)."""
    back = {s for n, (succ, _c) in enumerate(edges) for s in succ if s <= n}
    tails = any((i.mnemonic in BRANCH_IMM or i.mnemonic.startswith(("b.", "bc."))) and i.operands and i.operands[-1].type == ARM64_OP_IMM
                and i.operands[-1].imm not in addrs and i.operands[-1].imm in fstarts for i in insns)
    return back | ({0} if tails else set())

def exit_to(tgt: int, addrs: set, fstarts: set) -> str:
    """C statement leaving through a direct branch: goto inside the function, else a tail call (a function start or extern_stub)."""
    if tgt in addrs: return "goto L_%x;" % tgt
    if tgt in fstarts: return "GD_SPILLD%x func_%x(c); %s" % (tgt, tgt, TAIL)
    return "%sextern_stub(c, 0x%xULL); %s" % (SPILL, tgt, TAIL)

def icall_of(msgk: int | None) -> str:
    """The inline-cached call of _t: GD_MSGSEND (the site's own objc_msgSend cache) when the target is bound to the objc_msgSend family member msgk, else GD_ICALL."""
    return "GD_ICALL(_t);" if msgk is None else "GD_MSGSEND(_t, %d, GD_MSG_SLOT%d);" % (msgk, msgk)

def got_call(got: int, ret: int | None, msgk: int | None = None) -> str:
    """Call through an import stub's GOT slot (x16 = target, as the stub's adrp/ldr/br leaves it) via the site's inline cache, or, when gdyld defines GDL_<got> (the slot is bound to a LEAF_DIRECT import) and the slot still holds that import, the host function itself; ret: the return address of a bl, None for a tail call; msgk: the GOT is bound to that objc_msgSend family member (icall_of)."""
    lr = "c->X[30] = 0x%xULL + GUEST_BASE; " % ret if ret is not None else ""
    leaf = "\n#ifdef GDL_%x\nGDL_%x\n#endif\n" % (got, got) if msgk is None else ""   # gdyld: the slot's leaf import, inline
    head = "{ uint64_t _t = *(volatile uint64_t*)(0x%xULL + GUEST_BASE); c->X[16] = _t; %s%s%s%s" % (got, lr, SPILL, leaf, icall_of(msgk))
    return head + (" } GD_RC(0x%xULL)%s" % (ret, RELOAD) if ret is not None else " %s }" % TAIL)

def got_load(insns: list, k: int, reg: str, joins: set) -> int | None:
    """vmaddr of the memory word reg holds just before insns[k] when it was loaded by `ldr reg, [base, #off]` from a constant base (an adrp GOT page, as objc_msgSend$sel stubs do), else None."""
    j = find_def(insns, k, reg, joins)
    if j is None or insns[j].mnemonic != "ldr" or len(insns[j].operands) != 2 or insns[j].operands[1].type != ARM64_OP_MEM: return None
    if insns[j].reg_name(insns[j].operands[0].reg)[0] != "x": return None
    m = insns[j].operands[1].mem
    if m.index or insns[j].writeback: return None
    base = const_val(insns, j, xname(insns[j].reg_name(m.base)), joins)
    return None if base is None else base + m.disp

def nan_groups(body: list[tuple[int, str]], insns: list, joins: set) -> tuple[list[tuple[int, str]], set[int]]:
    """(body, V registers snapshotted) with each run of 2+ consecutive vector FP ops of one element width (lift_neon FAST: add, sub, mul, div, fmla, fmls; no other path enters after its first) checked once: the ops run without their per-op NaN check, then one test, at the run's width, of every V register the run wrote; a NaN lane there re-runs the whole run from a snapshot of those registers through the per-op exact path. Exact: these ops turn a NaN operand lane into a NaN result lane of the same width, so when no written register ends with a NaN lane, no value the run's final state depends on was NaN, and non-NaN IEEE results are the same on x86-64 and AArch64; NaNs in values the run overwrote are not architectural (FPSR is not modelled on either path). One width per run: a NaN read at the other width can be a finite number (its high word as a float, or two floats as a double), so the final test would miss it."""
    code = {n: k for k, (n, t) in enumerate(body) if n >= 0 and NAN_OP.match(t.strip()) and len(NAN_CHK.findall(t)) == 1}
    wid = {n: 64 if "_m=_r.vf64" in body[k][1] else 32 for n, k in code.items()}
    runs, cur = [], []
    for n in sorted(code):
        if cur and n == cur[-1] + 1 and code[n] == code[cur[-1]] + 2 and wid[n] == wid[cur[-1]] and insns[n].address not in joins:
            cur.append(n)
        else: runs.append(cur); cur = [n]
    runs.append(cur)
    out, saved = list(body), set()
    for run in (r for r in runs if len(r) > 1):
        texts = [body[code[n]][1].strip() for n in run]
        dst = sorted({int(NAN_OP.match(t).group(1)) for t in texts})
        saved |= set(dst)
        fast = [NAN_CHK.sub("", t) for t in texts]
        vi, vf, vt, mm = ("gv4i", "gv4f", "vf32", "ps") if wid[run[0]] == 32 else ("gv2l", "gv2d", "vf64", "pd")
        test = "|".join("(%s)(c->V[%d].%s!=c->V[%d].%s)" % (vi, r, vt, r, vt) for r in dst)
        fast[0] = "".join("gs_%d=c->V[%d]; " % (r, r) for r in dst) + fast[0]
        fast[-1] += " { %s _gm=%s; if (__builtin_expect(__builtin_ia32_movmsk%s((%s)_gm)!=0, 0)) { %s%s } }" % (
            vi, test, mm, vf, "".join("c->V[%d]=gs_%d; " % (r, r) for r in dst), " ".join(texts))
        for n, t in zip(run, fast): out[code[n]] = (n, "  " + t)
    return out, saved

def lift_function(insns: list, fstarts: set, cname: str, resume: list | None = None,
                  read: object = None, inside: bool = True, regs: bool = True, stubs: dict | None = None,
                  ic: bool = False, msg: dict | None = None, abi: bool = False, noret: frozenset = frozenset()) -> tuple[str, list, set, str]:
    """lift_function_x without the flag facts."""
    return lift_function_x(insns, fstarts, cname, resume, read, inside, regs, stubs, ic, msg, abi, noret)[:4]

def lift_function_x(insns: list, fstarts: set, cname: str, resume: list | None = None,
                    read: object = None, inside: bool = True, regs: bool = True, stubs: dict | None = None,
                    ic: bool = False, msg: dict | None = None, abi: bool = False,
                    noret: frozenset = frozenset()) -> tuple[str, list, set, str, dict | None]:
    """Lift a whole function -> (c_source, unsupported_list, call_targets, kind, flag_facts: where NZCV values cross calls, returns and entries, None when unknown); with `resume` it takes int gd_entry. Only words reached from the entry and resume points are lifted; read(vmaddr, n) -> bytes decodes jump tables; inside=False is the caller's proof that no code pointer into this function's interior exists (see reach); regs keeps guest registers in C locals (localize); ic: indirect calls and calls/tail calls into import stubs (stubs: stub vmaddr -> GOT vmaddr) go through a per-site inline cache (GD_ICALL) instead of dispatch / extern_stub; msg (GOT vmaddr -> objc_msgSend family member, with ic): calls through those GOT words (import stubs, objc_msgSend$sel stubs' ldr/br) get a per-site send cache (GD_MSGSEND); abi: localize's (the AAPCS64 register contract; each direct, stub and GOT-loaded call or tail call is a localize site); noret: function starts that never return (abi_check)."""
    msg = msg if ic and msg else {}
    body = []                                                          # (instruction index or -1, C text)
    unsupported = []
    calls = set()
    has_extern = False
    has_indirect = False
    ijump = False
    addrs = {i.address for i in insns}
    gots = stubs if ic and stubs else {}
    sites = {}                                                         # localize sites
    icall = "GD_ICALL(_t);" if ic else "dispatch(c, _t);"
    reached, brs, fallback = reach(insns, [insns[0].address] + list(resume or []), read, inside)
    joins = jump_edges(insns) | set(resume or []) | {t for _k, ts in brs.values() for t in ts}   # where another path may enter
    fz, fused = None, False                                            # flag_capture state reaching this instruction on its one path
    pos = {ins.address: n for n, ins in enumerate(insns)}
    jtab = {} if fallback else {jl: (pos[a], tg) for a, (kd, tg) in brs.items() if kd == "table"
                                 for jl in [table_load(insns, pos[a], joins)] if jl is not None}   # table load -> (its br, targets)
    jbr = {kb: tg for kb, tg in jtab.values()}
    for n, ins in enumerate(insns):
        if ins.address not in reached:                                 # never reached by control flow: data, not lifted
            if n == 0 or insns[n - 1].address in reached:
                body.append((-1, "/* 0x%x: not reached from the entry: data */" % ins.address))
            fz = None; continue
        body.append((n, "L_%x:" % ins.address))
        if ins.mnemonic == DATA_MNEMONIC:                              # undecodable word reached by control flow
            body.append((n, "  unsupported(c, 0x%xULL); return; /* data %s */" % (ins.address, ins.op_str))); fz = None; continue
        bm = ins.mnemonic.split(".")[0]
        if fallback or ins.address in joins: fz = None
        k0 = len(body)
        cap = None if fallback else flag_capture(ins)
        if cap: body.append((n, "  " + cap[2])); fused = True
        if n in jtab:                                                  # the table index, before the load may overwrite it: its br
                                                                       # switches on it (a table read_vm read is never written)
            k, i, w = reg_parts(ins.reg_name(ins.operands[1].mem.index)); body.append((n, "  gd_jx = %s;" % rd(k, i, w)))
        try:
            if bm == "ret":
                body.append((n, "  return;"))
            elif ins.mnemonic == "b" and ins.operands and ins.operands[0].type == ARM64_OP_IMM:
                tgt = ins.operands[0].imm
                if tgt in fstarts and tgt not in addrs: calls.add(tgt); sites[n] = ("d", tgt)
                if tgt not in addrs and tgt not in fstarts: has_extern = True
                if tgt in gots and tgt not in addrs and tgt not in fstarts: sites[n] = ("g", gots[tgt])
                body.append((n, "  " + (got_call(gots[tgt], None, msg.get(gots[tgt])) if tgt in gots and tgt not in addrs and tgt not in fstarts
                                        else exit_to(tgt, addrs, fstarts))))
            elif ins.mnemonic.startswith(("b.", "bc.")) and ins.operands:  # bc.cond (FEAT_HBC) branches like b.cond
                tgt = ins.operands[0].imm
                if tgt in fstarts and tgt not in addrs: calls.add(tgt); sites[n] = ("d", tgt)
                if tgt not in addrs and tgt not in fstarts: has_extern = True
                body.append((n, "  if (%s) { %s }" % (CC[ins.cc], exit_to(tgt, addrs, fstarts))))
            elif bm in ("cbz", "cbnz"):
                k, i, w = reg_parts(ins.reg_name(ins.operands[0].reg)); tgt = ins.operands[1].imm
                test = "==0" if bm == "cbz" else "!=0"
                if tgt in fstarts and tgt not in addrs: calls.add(tgt); sites[n] = ("d", tgt)
                body.append((n, "  if ((%s) %s) { %s }" % (rd(k, i, w), test, exit_to(tgt, addrs, fstarts))))
            elif bm in ("tbz", "tbnz"):
                k, i, w = reg_parts(ins.reg_name(ins.operands[0].reg)); bit = ins.operands[1].imm; tgt = ins.operands[2].imm
                test = "==0" if bm == "tbz" else "!=0"
                if tgt in fstarts and tgt not in addrs: calls.add(tgt); sites[n] = ("d", tgt)
                body.append((n, "  if (((%s >> %d) & 1) %s) { %s }" % (rd(k, i, 64), bit, test, exit_to(tgt, addrs, fstarts))))
            elif bm == "bl":
                tgt = ins.operands[0].imm
                lr = "c->X[30] = 0x%xULL + GUEST_BASE; " % (ins.address + 4)   # guest return address: frame records + unwinder
                rc = " GD_RC(0x%xULL)%s" % (ins.address + 4, RELOAD)  # unw: the guest returned past this call site
                if tgt in fstarts:
                    calls.add(tgt); sites[n] = ("d", tgt); body.append((n, "  %sGD_SPILLD%x func_%x(c);%s" % (lr, tgt, tgt, rc)))
                elif tgt in gots:
                    has_extern = True; sites[n] = ("g", gots[tgt]); body.append((n, "  " + got_call(gots[tgt], ins.address + 4, msg.get(gots[tgt]))))
                else:
                    has_extern = True; body.append((n, "  %s%sextern_stub(c, 0x%xULL);%s" % (lr, SPILL, tgt, rc)))
            elif bm == "blr":
                has_indirect = True
                k, i, w = reg_parts(ins.reg_name(ins.operands[0].reg))
                g = got_load(insns, n, xname(ins.reg_name(ins.operands[0].reg)), joins)
                mk = msg.get(g) if msg else None
                if g is not None: sites[n] = ("g", g)
                body.append((n, "  { uint64_t _t = %s; c->X[30] = 0x%xULL + GUEST_BASE; %s%s } GD_RC(0x%xULL)%s" % (
                    rd(k, i, 64), ins.address + 4, SPILL, icall if mk is None else icall_of(mk), ins.address + 4, RELOAD)))
            elif bm == "br":                                           # inside the function: jump table; else tail call
                has_indirect = True; ijump = True
                k, i, w = reg_parts(ins.reg_name(ins.operands[0].reg))
                g = got_load(insns, n, xname(ins.reg_name(ins.operands[0].reg)), joins)
                mk = msg.get(g) if msg else None
                if g is not None: sites[n] = ("g", g)
                dense = "" if n not in jbr else " switch (gd_jx) { %s default: break; }" % " ".join(
                    "case %d: goto L_%x ;" % (j, t) for j, t in enumerate(jbr[n]))   # spaced: not a place_edge_spills edge
                body.append((n, "  { uint64_t _t = %s;%s if (_t - (0x%xULL + GUEST_BASE) < 0x%xULL) { gd_t = _t - GUEST_BASE; goto gd_ijump; }"
                                " %s%s %s }" % (rd(k, i, 64), dense, insns[0].address, insns[-1].address + 4 - insns[0].address, SPILL,
                                                icall if mk is None else icall_of(mk), TAIL)))
            else:
                body.append((n, "  " + lift(ins, fstarts, calls).replace("\n", "\n  ")))
        except NotImplementedError as e:
            unsupported.append((ins.address, ins.mnemonic, str(e)))
            body.append((n, "  unsupported(c, 0x%xULL); /* %s %s */" % (ins.address, ins.mnemonic, ins.op_str))); cap = fz = None
        except (IndexError, KeyError, ValueError, TypeError) as e:     # operand shape the lifter has no case for
            unsupported.append((ins.address, ins.mnemonic, "shape:%s:%s" % (type(e).__name__, e)))
            body.append((n, "  unsupported(c, 0x%xULL); /* %s %s */" % (ins.address, ins.mnemonic, ins.op_str))); cap = fz = None
        if fz is not None and ins.cc and not cap:                      # a reader of the captured compare's flags
            body[k0:] = [(i, fuse_reader(t, ins.cc, fz)) for i, t in body[k0:]]
        written = bm in ("bl", "blr") or FLAG_WRITE.search("".join(t for _i, t in body[k0:]))
        fz = (cap[0], cap[1]) if cap else None if written else fz
    body, gsv = (body, set()) if fallback else nan_groups(body, insns, joins)
    pre = ("  uint64_t gd_t = 0;\n" if ijump else "") + ("  uint64_t gd_jx = 0;\n" if jtab else "") + ("  uint64_t gf_a = 0, gf_b = 0; double gf_fa = 0, gf_fb = 0;\n" if fused else "") \
        + "".join("  V128 gs_%d;\n" % r for r in sorted(gsv))           # before any goto (C++)
    body.append((-1, "  return;"))
    cases = (reached if fallback else {insns[0].address} | {t for _k, ts in brs.values() for t in ts}) if ijump else set()
    if ijump:                                                          # decoded tables list their targets; an undecoded one lists every word
        body.append((-1, "gd_ijump: switch (gd_t) {\n%s\n  default: %sdispatch(c, gd_t + GUEST_BASE); %s }" % ("\n".join(
            "  case 0x%xULL: goto L_%x;" % (a, a) for a in sorted(cases)), SPILL, TAIL)))
    at = {i.address: n for n, i in enumerate(insns)}
    edges = flow_edges(insns, reached, cases)
    heads = loop_heads(edges, insns, addrs, fstarts)
    body = [(n, t + " GD_LOOP;" if n in heads and t == "L_%x:" % insns[n].address else t) for n, t in body]
    blind = frozenset(n for n, i in enumerate(insns) if i.mnemonic == "br") if fallback else frozenset()   # br edges to every word
    regs = regs and len(cases) <= HUGE_SWITCH                          # a huge every-word switch: phis per local per label stall clang
    text, decl, facts = localize(body, edges, [0] + [at[a] for a in resume or [] if a in at], regs, insns, fstarts, blind, abi, noret,
                                 None if fallback else {at[a]: [at[t] for t in ts if t in at] for a, (_k, ts) in brs.items() if a in at}, sites)
    mark = "  " + UNDECODED_MARK + "\n" if fallback else ""           # gdyld's build report names these functions
    if resume:
        bad = [hex(a) for a in resume if a not in addrs]
        if bad: raise ValueError("%s: resume points outside the function: %s" % (cname, bad))
        jumps = " ".join("case %d: goto L_%x;" % (j, a) for j, a in enumerate(resume))
        src = "void %s(CPU *restrict c, int gd_entry) {\n%s%s%s  switch (gd_entry) { %s default: break; }\n%s\n}\n" % (cname, mark, decl, pre, jumps, text)
    else:
        src = "void %s(CPU *restrict c) {\n%s%s%s%s\n}\n" % (cname, mark, decl, pre, text)   # restrict: guest memory never points into the host CPU struct
    kind = "extern" if has_extern else ("indirect" if has_indirect else ("intra" if calls else "leaf"))
    return src, unsupported, calls, kind, facts
