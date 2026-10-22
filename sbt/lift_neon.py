"""AdvSIMD (NEON) AArch64 families for the recompiler: every instruction form with a vector arrangement
(v0.4s) or lane (v1.h[0]) operand. recompile.lift() routes here when the instruction has a vector operand and
its base mnemonic is in MNEMONICS. Library; proven by sbt/microtest.py cases_neon."""
###############
# imports and constants
###############
from __future__ import annotations
import re, struct
from capstone import arm64 as A64
from capstone.arm64 import ARM64_OP_REG, ARM64_OP_IMM, ARM64_OP_FP, ARM64_OP_MEM, ARM64_SFT_LSL, ARM64_SFT_MSL
from cgen import reg_parts, rd, wr, simd_load, simd_store

VAS = {getattr(A64, k): (int(k[10:-1]), {"B": 8, "H": 16, "S": 32, "D": 64, "Q": 128}[k[-1]])
       for k in dir(A64) if re.fullmatch(r"ARM64_VAS_\d+[BHSDQ]", k)}    # vas enum -> (count, esize)
CLEAR = {128: "", 64: "_r.u64[1]=0;", 32: "_r.u32[1]=0; _r.u64[1]=0;", 16: "_r.u16[1]=0; _r.u32[1]=0; _r.u64[1]=0;",
         8: "_r.u8[1]=0; _r.u16[1]=0; _r.u32[1]=0; _r.u64[1]=0;"}      # zero V bits above the written width
GPR = ("x", "zr", "sp")
VU = {8: "vu8", 16: "vu16", 32: "vu32", 64: "vu64"}                    # V128 member: unsigned lanes of e bits
VUT = {16: "gv8u16", 32: "gv4u32", 64: "gv2u64"}                       # unsigned 128-bit vector of e-bit lanes
VST = {8: "gv16i8", 16: "gv8i16", 32: "gv4i", 64: "gv2l"}              # signed 128-bit vector of e-bit lanes
HUT = {8: "gh8u8", 16: "gh4u16", 32: "gh2u32"}                         # unsigned 64-bit vector of e-bit lanes
VINT = {"add": "{a}+{b}", "sub": "{a}-{b}", "mul": "{a}*{b}", "and": "{a}&{b}", "orr": "{a}|{b}", "eor": "{a}^{b}",
        "bic": "{a}&~{b}", "orn": "{a}|~{b}", "shl": "{a}<<{N}", "ushr": "{a}>>{N}"}   # wrapping lane ops, same bits as lift_elem
VNARROW = {"xtn": "{x}", "shrn": "{x}>>{N}", "rshrn": "({x}+{R})>>{N}"}   # mod 2^es: the carry lands above the kept half (N <= es/2)
FAST = {"fadd": "{a}+{b}", "fsub": "{a}-{b}", "fmul": "{a}*{b}", "fdiv": "{a}/{b}",
        "fmla": "__builtin_elementwise_fma({a},{b},{d})", "fmls": "__builtin_elementwise_fma(-{a},{b},{d})"}   # NaN result iff a NaN input or an invalid op
BITWISE = {"and", "orr", "eor", "bic", "orn", "mvn", "not", "bit", "bif", "bsl"}
ELEM = {"add": ("{a}+{b}", "u"), "sub": ("{a}-{b}", "u"), "mul": ("(uint64_t){a}*{b}", "u"),
        "mla": ("{d}+(uint64_t){a}*{b}", "u"), "mls": ("{d}-(uint64_t){a}*{b}", "u"),
        "and": ("{a}&{b}", "u"), "orr": ("{a}|{b}", "u"), "eor": ("{a}^{b}", "u"), "bic": ("{a}&~{b}", "u"),
        "orn": ("{a}|~{b}", "u"), "mvn": ("~{a}", "u"), "not": ("~{a}", "u"),
        "bit": ("({d}&~{b})|({a}&{b})", "u"), "bif": ("({d}&{b})|({a}&~{b})", "u"), "bsl": ("({d}&{a})|(~{d}&{b})", "u"),
        "cmeq": ("({a}=={b})?{M}:0", "u"), "cmtst": ("({a}&{b})?{M}:0", "u"), "cmhi": ("({a}>{b})?{M}:0", "u"),
        "cmhs": ("({a}>={b})?{M}:0", "u"), "cmgt": ("({sa}>{sb})?{M}:0", "u"), "cmge": ("({sa}>={sb})?{M}:0", "u"),
        "cmle": ("({sa}<={sb})?{M}:0", "u"), "cmlt": ("({sa}<{sb})?{M}:0", "u"),
        "smin": ("{sa}<{sb}?{a}:{b}", "u"), "smax": ("{sa}>{sb}?{a}:{b}", "u"),
        "umin": ("{a}<{b}?{a}:{b}", "u"), "umax": ("{a}>{b}?{a}:{b}", "u"),
        "uhadd": ("((uint64_t){a}+{b})>>1", "u"), "shadd": ("(uint64_t)(({sa}+{sb})>>1)", "u"),
        "ushl": ("n_ushl({a},{b})", "u"), "sshl": ("n_sshl({sa},{b})", "u"),
        "abs": ("{sa}<0?0-(uint64_t){a}:(uint64_t){a}", "u"), "neg": ("0-(uint64_t){a}", "u"),
        "cnt": ("__builtin_popcountll({a})", "u"), "clz": ("n_clz({a},{E})", "u"),
        "rbit": ("__builtin_bitreverse8((uint8_t){a})", "u"),           # vector RBIT: .8b / .16b only
        "shl": ("(uint64_t){a}<<{N}", "u"), "ushr": ("n_lsr({a},{N})", "u"), "sshr": ("n_asr({sa},{N})", "u"),
        "usra": ("{d}+n_lsr({a},{N})", "u"), "ssra": ("{d}+n_asr({sa},{N})", "u"),
        "fadd": ("n_fadd{S}({fa},{fb})", "f"), "fsub": ("n_fsub{S}({fa},{fb})", "f"),
        "fmul": ("n_fmul{S}({fa},{fb})", "f"), "fdiv": ("n_fdiv{S}({fa},{fb})", "f"),
        "fmaxnm": ("n_fmaxnm{S}({fa},{fb})", "f"), "fminnm": ("n_fminnm{S}({fa},{fb})", "f"),
        "fabd": ("n_fabd{S}({fa},{fb})", "f"), "fmla": ("n_fma{S}({fd},{fa},{fb})", "f"),
        "fmls": ("n_fma{S}({fd},n_fneg{S}({fa}),{fb})", "f"),
        "fabs": ("{a}&~{SB}", "u"), "fneg": ("{a}^{SB}", "u"), "fsqrt": ("n_fsqrt{S}({fa})", "f"),
        "frinta": ("n_frint{S}({fa},0)", "f"), "frintm": ("n_frint{S}({fa},1)", "f"),
        "frintp": ("n_frint{S}({fa},2)", "f"), "frintz": ("n_frint{S}({fa},3)", "f"),
        "fcmeq": ("({fa}=={fb})?{M}:0", "u"), "fcmge": ("({fa}>={fb})?{M}:0", "u"),
        "fcmgt": ("({fa}>{fb})?{M}:0", "u"), "fcmle": ("({fa}<={fb})?{M}:0", "u"), "fcmlt": ("({fa}<{fb})?{M}:0", "u"),
        "fcvtzs": ("n_cvts((double){fa}*{P},{E})", "u"), "fcvtzu": ("n_cvtu((double){fa}*{P},{E})", "u"),
        "scvtf": ("({T}){sa}/{P}", "f"), "ucvtf": ("({T}){a}/{P}", "f"),
        "fmax": ("n_fmax{S}({fa},{fb})", "f"), "fmin": ("n_fmin{S}({fa},{fb})", "f"),
        "frintn": ("n_frint{S}({fa},4)", "f"), "frintx": ("n_frint{S}({fa},5)", "f"), "frinti": ("n_frint{S}({fa},5)", "f"),
        "frecpe": ("n_frecpe({a},{E})", "u"), "frsqrte": ("n_frsqrte({a},{E})", "u"),
        "frecps": ("n_frecps{S}({fa},{fb})", "f"), "frsqrts": ("n_frsqrts{S}({fa},{fb})", "f"),
        "sqdmulh": ("n_sqdmulh({sa},{sb},{E},0)", "u"), "sqrdmulh": ("n_sqdmulh({sa},{sb},{E},1)", "u"),
        "sli": ("((uint64_t){a}<<{N})|({d}&((1ULL<<{N})-1))", "u"), "sri": ("n_lsr({a},{N})|({d}&~n_lsr({M},{N}))", "u"),
        "sabd": ("{sa}>{sb}?(uint64_t)({sa}-{sb}):(uint64_t)({sb}-{sa})", "u"), "uabd": ("{a}>{b}?{a}-{b}:{b}-{a}", "u"),
        "uqadd": ("n_satu((__int128){a}+{b},{E})", "u"), "uqsub": ("n_satu((__int128){a}-(__int128){b},{E})", "u"),
        "sqadd": ("n_sats((__int128){sa}+{sb},{E})", "u"), "sqsub": ("n_sats((__int128){sa}-(__int128){sb},{E})", "u"),
        "sqshl": ("n_sqshl({sa},{b},{E})", "u"), "srshl": ("n_srshl({sa},{b})", "u"), "urshl": ("n_urshl({a},{b})", "u"),
        "srshr": ("n_srshl({sa},(uint64_t)-{N})", "u"), "urshr": ("n_urshl({a},(uint64_t)-{N})", "u"),
        "srsra": ("{d}+n_srshl({sa},(uint64_t)-{N})", "u"), "ursra": ("{d}+n_urshl({a},(uint64_t)-{N})", "u"),
        **{"fcvt%s%s" % (r, u): ("n_cvt%s((double)n_frint{S}({fa},%d),{E})" % (u, k), "u")
           for r, k in (("a", 0), ("m", 1), ("p", 2), ("n", 4)) for u in "su"}}
HALF_F32 = {"fmax", "fmin", "fmaxnm", "fminnm", "frinta", "frintm", "frintp", "frintz", "frintn", "frintx", "frinti"}
SCALAR = {"shl", "ushr", "sshr", "sli", "sri", "cmeq", "fmax", "fmin", "frintn", "frintx", "frinti", "frecpe", "frsqrte",
          "frecps", "frsqrts", "sqdmulh", "sqrdmulh", "frintz", "srshr", "urshr", "srsra", "ursra"}  # scalar forms lift_scalar does not claim
REG_ONLY = {"sqshl", "srshl", "urshl"}                                 # register-shift forms; the #imm forms differ
AES_OP = {"aese": 0, "aesd": 1, "aesmc": 2, "aesimc": 3}
LONG = {"ushll": "{x}<<{N}", "sshll": "{x}<<{N}", "shll": "{x}<<{N}", "uaddl": "{x}+{y}", "saddl": "{x}+{y}",
        "usubl": "{x}-{y}", "ssubl": "{x}-{y}", "uaddw": "{w}+{y}", "saddw": "{w}+{y}", "usubw": "{w}-{y}",
        "ssubw": "{w}-{y}", "umull": "{x}*{y}", "smull": "{x}*{y}", "umlal": "{d}+{x}*{y}", "smlal": "{d}+{x}*{y}",
        "umlsl": "{d}-{x}*{y}", "smlsl": "{d}-{x}*{y}"}
NARROW = {"xtn": ("{x}", "u"), "shrn": ("{x}>>{N}", "u"), "rshrn": ("((uint64_t){x}+(1ULL<<({N}-1)))>>{N}", "u"),
          "fcvtn": ("n_f64to32({f})", "f"), "sqxtn": ("n_sats({sx},{H})", "u"), "uqxtn": ("n_satu({x},{H})", "u"),
          "sqxtun": ("n_satu({sx},{H})", "u"), "sqshrn": ("n_sats({sx}>>{N},{H})", "u"), "uqshrn": ("n_satu({x}>>{N},{H})", "u"),
          "addhn": ("({x}+{y})>>{H}", "u"), "subhn": ("({x}-{y})>>{H}", "u")}
ADDLP = {"uaddlp": ("u", False), "saddlp": ("s", False), "uadalp": ("u", True), "sadalp": ("s", True)}
FREDUCE = {"fmaxnmv": "fmaxnm", "fminnmv": "fminnm", "fmaxv": "fmax", "fminv": "fmin"}
CRYPTO = {"sha1c": "n_sha1hash({d},{ns},{m},0)", "sha1p": "n_sha1hash({d},{ns},{m},1)", "sha1m": "n_sha1hash({d},{ns},{m},2)",
          "sha1h": "n_sha1h({ns})", "sha1su0": "n_sha1su0({d},{n},{m})", "sha1su1": "n_sha1su1({d},{n})",
          "sha256h": "n_sha256hash({d},{n},{m},1)", "sha256h2": "n_sha256hash({n},{d},{m},0)",
          "sha256su0": "n_sha256su0({d},{n})", "sha256su1": "n_sha256su1({d},{n},{m})",
          "sha512h": "n_sha512h({d},{n},{m})", "sha512h2": "n_sha512h2({d},{n},{m})",
          "sha512su0": "n_sha512su0({d},{n})", "sha512su1": "n_sha512su1({d},{n},{m})",
          "sm3ss1": "n_sm3ss1({n},{m},{a})", "sm3tt1a": "n_sm3tt({d},{n},{m}.u32[{i}],0)",
          "sm3tt1b": "n_sm3tt({d},{n},{m}.u32[{i}],1)", "sm3tt2a": "n_sm3tt({d},{n},{m}.u32[{i}],2)",
          "sm3tt2b": "n_sm3tt({d},{n},{m}.u32[{i}],3)", "sm3partw1": "n_sm3pw1({d},{n},{m})",
          "sm3partw2": "n_sm3pw2({d},{n},{m})", "sm4e": "n_sm4({d},{n},0)", "sm4ekey": "n_sm4({n},{m},1)",
          "eor3": "n_eor3({n},{m},{a})", "bcax": "n_bcax({n},{m},{a})", "rax1": "n_rax1({n},{m})", "xar": "n_xar({n},{m},{imm})"}
C_HELPERS = r"""
static inline gv4f n_ones_vf32(gv4f v,int n){gv4f o={1,1,1,1}; gv4f r=n==2?__builtin_shufflevector(v,o,0,1,6,7):__builtin_shufflevector(v,o,0,5,6,7); __asm__("":"+x"(r)); return r;}
static inline gv2d n_ones_vf64(gv2d v,int n){(void)n; gv2d o={1,1}; gv2d r=__builtin_shufflevector(v,o,0,3); __asm__("":"+x"(r)); return r;}
static inline uint64_t n_lsr(uint64_t x,unsigned n){return n>=64?0:x>>n;}
static inline uint64_t n_asr(int64_t x,unsigned n){return (uint64_t)(x>>(n>63?63:n));}
static inline uint64_t n_ushl(uint64_t x,uint64_t b){int s=(int8_t)(uint8_t)b; if(s>=0) return s>=64?0:x<<s; return -s>=64?0:x>>-s;}
static inline uint64_t n_sshl(int64_t x,uint64_t b){int s=(int8_t)(uint8_t)b; if(s>=0) return s>=64?0:(uint64_t)x<<s; return (uint64_t)(x>>(-s>63?63:-s));}
static inline uint64_t n_clz(uint64_t x,int e){return x?(uint64_t)(__builtin_clzll(x)-(64-e)):(uint64_t)e;}
static inline uint64_t n_cvts(double x,int bits){if(x!=x)return 0; double l=ldexp(1.0,bits-1);
  if(x>=l)return ~0ULL>>(65-bits); if(x<-l)return ~0ULL<<(bits-1); return (uint64_t)(int64_t)x;}
static inline uint64_t n_cvtu(double x,int bits){if(x!=x||x<0)return 0; if(x>=ldexp(1.0,bits))return ~0ULL>>(64-bits); return (uint64_t)x;}
#define N_FP(S,T,U,F,QB,DN,SB) \
static inline U n_bits##S(T x){U u; memcpy(&u,&x,sizeof u); return u;} \
static inline T n_flt##S(U u){T x; memcpy(&x,&u,sizeof x); return x;} \
static inline int n_snan##S(T x){return x!=x && !(n_bits##S(x)&QB);} \
static inline T n_quiet##S(T x){return n_flt##S(n_bits##S(x)|QB);} \
static inline T n_nan2##S(T a,T b){if(n_snan##S(a))return n_quiet##S(a); if(n_snan##S(b))return n_quiet##S(b); return a!=a?a:b;} \
static inline T n_dn##S(T r){return r!=r?n_flt##S(DN):r;} \
static inline T n_fneg##S(T a){return n_flt##S(n_bits##S(a)^SB);} \
static inline T n_fadd##S(T a,T b){T r=a+b; if(__builtin_expect(r==r,1))return r; return (a!=a||b!=b)?n_nan2##S(a,b):n_dn##S(r);} \
static inline T n_fsub##S(T a,T b){T r=a-b; if(__builtin_expect(r==r,1))return r; return (a!=a||b!=b)?n_nan2##S(a,b):n_dn##S(r);} \
static inline T n_fmul##S(T a,T b){T r=a*b; if(__builtin_expect(r==r,1))return r; return (a!=a||b!=b)?n_nan2##S(a,b):n_dn##S(r);} \
static inline T n_fdiv##S(T a,T b){T r=a/b; if(__builtin_expect(r==r,1))return r; return (a!=a||b!=b)?n_nan2##S(a,b):n_dn##S(r);} \
static inline T n_fabd##S(T a,T b){return n_flt##S(n_bits##S(n_fsub##S(a,b))&~(U)SB);} \
static inline T n_fmaxnm##S(T a,T b){if(n_snan##S(a)||n_snan##S(b)||(a!=a&&b!=b))return n_nan2##S(a,b); \
  if(a!=a)return b; if(b!=b)return a; if(a==b)return n_flt##S(n_bits##S(a)&n_bits##S(b)); return a>b?a:b;} \
static inline T n_fminnm##S(T a,T b){if(n_snan##S(a)||n_snan##S(b)||(a!=a&&b!=b))return n_nan2##S(a,b); \
  if(a!=a)return b; if(b!=b)return a; if(a==b)return n_flt##S(n_bits##S(a)|n_bits##S(b)); return a<b?a:b;} \
static inline T n_fma##S(T c,T a,T b){T q=fma##F(a,b,c); if(__builtin_expect(q==q,1))return q; if(c!=c||a!=a||b!=b){ \
  if(c!=c&&!n_snan##S(c)&&((isinf(a)&&b==0)||(a==0&&isinf(b))))return n_flt##S(DN); \
  if(n_snan##S(c))return n_quiet##S(c); if(n_snan##S(a))return n_quiet##S(a); if(n_snan##S(b))return n_quiet##S(b); \
  return c!=c?c:(a!=a?a:b);} return n_dn##S(fma##F(a,b,c));} \
static inline T n_fsqrt##S(T a){if(a!=a)return n_quiet##S(a); if(a<0)return n_flt##S(DN); return sqrt##F(a);} \
static inline T n_rne##S(T a){T t=trunc##F(a); return fabs##F(a-t)==(T)0.5?2*round##F(a/2):round##F(a);} \
static inline T n_frint##S(T a,int m){if(a!=a)return n_quiet##S(a); \
  return m==0?round##F(a):m==1?floor##F(a):m==2?ceil##F(a):m==3?trunc##F(a):m==4?n_rne##S(a):rint##F(a);} \
static inline T n_fmax##S(T a,T b){if(a!=a||b!=b)return n_nan2##S(a,b); if(a==b)return n_flt##S(n_bits##S(a)&n_bits##S(b)); return a>b?a:b;} \
static inline T n_fmin##S(T a,T b){if(a!=a||b!=b)return n_nan2##S(a,b); if(a==b)return n_flt##S(n_bits##S(a)|n_bits##S(b)); return a<b?a:b;} \
static inline T n_frecps##S(T a,T b){if((isinf(a)&&b==0)||(a==0&&isinf(b)))return (T)2; return n_fma##S((T)2,n_fneg##S(a),b);} \
static inline T n_frsqrts##S(T a,T b){if((isinf(a)&&b==0)||(a==0&&isinf(b)))return (T)1.5; \
  T r=n_fma##S((T)3,n_fneg##S(a),b); return r!=r?r:r/2;}
N_FP(32,float,uint32_t,f,0x400000u,0x7fc00000u,0x80000000u)
N_FP(64,double,uint64_t,,0x8000000000000ULL,0x7ff8000000000000ULL,0x8000000000000000ULL)
#define N_FIXV(S,VT,OP,E) \
static __attribute__((noinline,cold,preserve_all)) VT n_fixv_##OP##S(VT a,VT b,VT d,VT r,int n){for(int j=0;j<n;j++)r[j]=E;(void)d;return r;}
#define N_FIXALL(S,VT) N_FIXV(S,VT,fadd,n_fadd##S(a[j],b[j])) N_FIXV(S,VT,fsub,n_fsub##S(a[j],b[j])) N_FIXV(S,VT,fmul,n_fmul##S(a[j],b[j])) \
  N_FIXV(S,VT,fdiv,n_fdiv##S(a[j],b[j])) N_FIXV(S,VT,fmla,n_fma##S(d[j],a[j],b[j])) N_FIXV(S,VT,fmls,n_fma##S(d[j],n_fneg##S(a[j]),b[j]))
N_FIXALL(32,gv4f)
N_FIXALL(64,gv2d)
static inline double n_f32to64(float x){if(x!=x){uint32_t u=n_bits32(x);
  return n_flt64(((uint64_t)(u>>31)<<63)|0x7ff8000000000000ULL|((uint64_t)(u&0x3fffff)<<29));} return (double)x;}
static inline float n_f64to32(double x){if(x!=x){uint64_t u=n_bits64(x);
  return n_flt32((uint32_t)((u>>63)<<31)|0x7fc00000u|(uint32_t)((u>>29)&0x3fffff));} return (float)x;}
static inline uint16_t n_f32to16(float x){uint32_t u=n_bits32(x),m=u&0x7fffff,s=(u>>16)&0x8000; int ex=(u>>23)&0xff;
  if(ex==0xff) return (uint16_t)(m?s|0x7e00|((m>>13)&0x1ff):s|0x7c00); if(ex) m|=0x800000;
  int e=(ex?ex:1)-112, sh=e>=1?13:14-e; if(sh>31) return (uint16_t)s; if(e<1) e=0;
  uint32_t r=m>>sh, rem=m&((1u<<sh)-1), hf=1u<<(sh-1); if(rem>hf||(rem==hf&&(r&1))) r++;
  uint32_t h=(e?(uint32_t)(e-1)<<10:0)+r; return (uint16_t)(s|(h>=0x7c00?0x7c00:h));}
static inline float n_h2f(uint64_t h){uint32_t s=(uint32_t)(h&0x8000)<<16, e=(h>>10)&0x1f, m=h&0x3ff;
  if(e==0x1f) return n_flt32(s|0x7f800000u|(m<<13)); if(e) return n_flt32(s|((e+112)<<23)|(m<<13));
  float f=ldexpf((float)m,-24); return s?-f:f;}
#define n_f2h n_f32to16
static inline uint64_t n_rsqrt_est(uint64_t a){a=a<256?a*2+1:((a>>1)<<1)*2+2; uint64_t t=(uint64_t)sqrt(268435456.0/a);
  while(a*t*t<268435456ULL)t++; while(t>513&&a*(t-1)*(t-1)>=268435456ULL)t--; return (t<513?513:t)/2;}
static inline uint64_t n_frecpe(uint64_t x,int N){int F=N==16?10:N==32?23:52, E=N-1-F; uint64_t M52=(1ULL<<52)-1;
  uint64_t sg=(x>>(N-1))&1, emax=(1ULL<<E)-1, ex=(x>>F)&emax, fr=x&((1ULL<<F)-1), sb=sg<<(N-1);
  if(ex==emax) return fr?x|(1ULL<<(F-1)):sb; if(ex==0&&fr<(1ULL<<(F-2))) return sb|(emax<<F);
  uint64_t f=fr<<(52-F); int64_t e=(int64_t)ex; if(e==0){ if(!((f>>51)&1)){e=-1; f=(f<<2)&M52;} else f=(f<<1)&M52; }
  int64_t re=(int64_t)(emax-2)-e; uint64_t est=((1ULL<<19)/((256|(f>>44))*2+1)+1)/2, fo=(est&0xff)<<44;
  if(re==0) fo=(1ULL<<51)|(fo>>1); else if(re==-1){fo=(1ULL<<50)|(fo>>2); re=0;}
  return sb|((uint64_t)re<<F)|(fo>>(52-F));}
static inline uint64_t n_frsqrte(uint64_t x,int N){int F=N==16?10:N==32?23:52, E=N-1-F; uint64_t M52=(1ULL<<52)-1;
  uint64_t sg=(x>>(N-1))&1, emax=(1ULL<<E)-1, ex=(x>>F)&emax, fr=x&((1ULL<<F)-1), qb=1ULL<<(F-1);
  if(ex==emax&&fr) return x|qb; if(ex==0&&fr==0) return (sg<<(N-1))|(emax<<F); if(sg) return (emax<<F)|qb; if(ex==emax) return 0;
  uint64_t f=fr<<(52-F); int64_t e=(int64_t)ex; if(e==0){ while(!((f>>51)&1)){f=(f<<1)&M52; e--;} f=(f<<1)&M52; }
  uint64_t sc=(e&1)?(128|(f>>45)):(256|(f>>44)); int64_t re=((int64_t)(3*(emax>>1)-1)-e)/2;
  return ((uint64_t)re<<F)|((n_rsqrt_est(sc)&0xff)<<(F-8));}
static inline uint64_t n_sqdmulh(int64_t a,int64_t b,int e,int rnd){__int128 p=(__int128)a*b*2+(rnd?((__int128)1<<(e-1)):0); p>>=e;
  int64_t hi=(int64_t)((1ULL<<(e-1))-1), lo=-hi-1; return (uint64_t)(p>hi?hi:p<lo?lo:(int64_t)p);}
static inline uint64_t n_clmul8(uint64_t a,uint64_t b){uint64_t r=0; for(int i=0;i<8;i++) if((b>>i)&1) r^=a<<i; return r;}
#include <wmmintrin.h>
#define N_CRYPTO __attribute__((target("aes,pclmul")))
static inline N_CRYPTO V128 n_aes(V128 s,V128 k,int op){__m128i x,y,z=_mm_setzero_si128(); memcpy(&x,&s,16); memcpy(&y,&k,16);
  x=op==0?_mm_aesenclast_si128(_mm_xor_si128(x,y),z):op==1?_mm_aesdeclast_si128(_mm_xor_si128(x,y),z):
    op==2?_mm_aesenc_si128(_mm_aesdeclast_si128(x,z),z):_mm_aesimc_si128(x); memcpy(&s,&x,16); return s;}
static inline N_CRYPTO V128 n_pmull64(uint64_t a,uint64_t b){__m128i x=_mm_clmulepi64_si128(_mm_cvtsi64_si128((long long)a),
  _mm_cvtsi64_si128((long long)b),0); V128 r; memcpy(&r,&x,16); return r;}
static inline float n_h2fq(uint64_t h){float f=n_h2f(h); return f!=f?n_flt32(n_bits32(f)|0x400000u):f;}
static inline uint64_t n_sats(__int128 v,int e){__int128 hi=((__int128)1<<(e-1))-1, lo=-hi-1; return (uint64_t)(v>hi?hi:v<lo?lo:v);}
static inline uint64_t n_satu(__int128 v,int e){__int128 hi=((__int128)1<<e)-1; return (uint64_t)(v>hi?hi:v<0?0:v);}
static inline uint64_t n_sqshl(int64_t a,uint64_t b,int e){int s=(int8_t)(uint8_t)b; if(s<0) return (uint64_t)(a>>(-s>63?63:-s));
  if(a==0) return 0; if(s>=e) return n_sats(a<0?-((__int128)1<<100):((__int128)1<<100),e); return n_sats((__int128)a<<s,e);}
static inline uint64_t n_srshl(int64_t a,uint64_t b){int s=(int8_t)(uint8_t)b; if(s>=0) return s>=64?0:(uint64_t)a<<s;
  if(-s>64) return 0; return (uint64_t)(((__int128)a+((__int128)1<<(-s-1)))>>-s);}
static inline uint64_t n_urshl(uint64_t a,uint64_t b){int s=(int8_t)(uint8_t)b; if(s>=0) return s>=64?0:a<<s;
  if(-s>64) return 0; return (uint64_t)(((unsigned __int128)a+((unsigned __int128)1<<(-s-1)))>>-s);}
static inline uint32_t n_rol32(uint32_t x,int n){n&=31; return n?(x<<n)|(x>>(32-n)):x;}
static inline uint32_t n_ror32(uint32_t x,int n){return n_rol32(x,32-(n&31));}
static inline uint64_t n_ror64(uint64_t x,int n){n&=63; return n?(x>>n)|(x<<(64-n)):x;}
static inline uint32_t n_sha_f(uint32_t x,uint32_t y,uint32_t z,int f){return f==0?((y^z)&x)^z:f==1?x^y^z:(x&y)|((x|y)&z);}
static inline V128 n_sha1hash(V128 x,uint32_t y,V128 w,int f){for(int e=0;e<4;e++){
  y=y+n_rol32(x.u32[0],5)+n_sha_f(x.u32[1],x.u32[2],x.u32[3],f)+w.u32[e]; x.u32[1]=n_rol32(x.u32[1],30);
  uint32_t t=x.u32[3]; x.u32[3]=x.u32[2]; x.u32[2]=x.u32[1]; x.u32[1]=x.u32[0]; x.u32[0]=y; y=t;} return x;}
static inline V128 n_sha1h(uint32_t x){V128 r={0}; r.u32[0]=n_rol32(x,30); return r;}
static inline V128 n_sha1su0(V128 a,V128 b,V128 c){V128 r; r.u64[0]=a.u64[1]^a.u64[0]^c.u64[0]; r.u64[1]=b.u64[0]^a.u64[1]^c.u64[1]; return r;}
static inline V128 n_sha1su1(V128 x,V128 y){uint32_t t[4]={x.u32[0]^y.u32[1],x.u32[1]^y.u32[2],x.u32[2]^y.u32[3],x.u32[3]}; V128 r;
  for(int e=0;e<4;e++) r.u32[e]=n_rol32(t[e],1); r.u32[3]^=n_rol32(t[0],2); return r;}
static inline V128 n_sha256hash(V128 x,V128 y,V128 w,int part1){for(int e=0;e<4;e++){
  uint32_t ch=n_sha_f(y.u32[0],y.u32[1],y.u32[2],0), mj=n_sha_f(x.u32[0],x.u32[1],x.u32[2],2);
  uint32_t t=y.u32[3]+(n_ror32(y.u32[0],6)^n_ror32(y.u32[0],11)^n_ror32(y.u32[0],25))+ch+w.u32[e];
  x.u32[3]+=t; y.u32[3]=t+(n_ror32(x.u32[0],2)^n_ror32(x.u32[0],13)^n_ror32(x.u32[0],22))+mj;
  uint32_t x3=x.u32[3], y3=y.u32[3];
  x.u32[3]=x.u32[2]; x.u32[2]=x.u32[1]; x.u32[1]=x.u32[0]; x.u32[0]=y3;
  y.u32[3]=y.u32[2]; y.u32[2]=y.u32[1]; y.u32[1]=y.u32[0]; y.u32[0]=x3;} return part1?x:y;}
static inline uint32_t n_s256s0(uint32_t x){return n_ror32(x,7)^n_ror32(x,18)^(x>>3);}
static inline uint32_t n_s256s1(uint32_t x){return n_ror32(x,17)^n_ror32(x,19)^(x>>10);}
static inline V128 n_sha256su0(V128 a,V128 b){uint32_t t[4]={a.u32[1],a.u32[2],a.u32[3],b.u32[0]}; V128 r;
  for(int e=0;e<4;e++) r.u32[e]=n_s256s0(t[e])+a.u32[e]; return r;}
static inline V128 n_sha256su1(V128 a,V128 b,V128 c){uint32_t t0[4]={b.u32[1],b.u32[2],b.u32[3],c.u32[0]}; V128 r;
  r.u32[0]=n_s256s1(c.u32[2])+a.u32[0]+t0[0]; r.u32[1]=n_s256s1(c.u32[3])+a.u32[1]+t0[1];
  r.u32[2]=n_s256s1(r.u32[0])+a.u32[2]+t0[2]; r.u32[3]=n_s256s1(r.u32[1])+a.u32[3]+t0[3]; return r;}
static inline uint64_t n_s512(uint64_t x,int a,int b,int c){return n_ror64(x,a)^n_ror64(x,b)^n_ror64(x,c);}
static inline V128 n_sha512h(V128 w,V128 x,V128 y){V128 r; uint64_t hi=((y.u64[1]&x.u64[0])^(~y.u64[1]&x.u64[1]))+n_s512(y.u64[1],14,18,41)+w.u64[1];
  uint64_t t=hi+y.u64[0]; r.u64[1]=hi; r.u64[0]=((t&y.u64[1])^(~t&x.u64[0]))+n_s512(t,14,18,41)+w.u64[0]; return r;}
static inline V128 n_sha512h2(V128 w,V128 x,V128 y){V128 r;
  uint64_t hi=((x.u64[0]&y.u64[1])^(x.u64[0]&y.u64[0])^(y.u64[1]&y.u64[0]))+n_s512(y.u64[0],28,34,39)+w.u64[1];
  r.u64[1]=hi; r.u64[0]=((hi&y.u64[0])^(hi&y.u64[1])^(y.u64[1]&y.u64[0]))+n_s512(hi,28,34,39)+w.u64[0]; return r;}
static inline V128 n_sha512su0(V128 w,V128 x){V128 r;
  r.u64[0]=w.u64[0]+(n_ror64(w.u64[1],1)^n_ror64(w.u64[1],8)^(w.u64[1]>>7));
  r.u64[1]=w.u64[1]+(n_ror64(x.u64[0],1)^n_ror64(x.u64[0],8)^(x.u64[0]>>7)); return r;}
static inline V128 n_sha512su1(V128 w,V128 x,V128 y){V128 r;
  r.u64[1]=w.u64[1]+(n_ror64(x.u64[1],19)^n_ror64(x.u64[1],61)^(x.u64[1]>>6))+y.u64[1];
  r.u64[0]=w.u64[0]+(n_ror64(x.u64[0],19)^n_ror64(x.u64[0],61)^(x.u64[0]>>6))+y.u64[0]; return r;}
static inline V128 n_sm3ss1(V128 n,V128 m,V128 a){V128 r={0}; r.u32[3]=n_rol32(n_rol32(n.u32[3],12)+m.u32[3]+a.u32[3],7); return r;}
static inline V128 n_sm3tt(V128 d,V128 n,uint32_t wj,int op){uint32_t d0=d.u32[0],d1=d.u32[1],d2=d.u32[2],d3=d.u32[3], t; V128 r;
  if(op<2){ uint32_t ss2=n.u32[3]^n_rol32(d3,12); t=op==0?d1^d3^d2:(d3&d1)|(d3&d2)|(d1&d2); t=t+d0+ss2+wj;
    r.u32[0]=d1; r.u32[1]=n_rol32(d2,9); r.u32[2]=d3; r.u32[3]=t; }
  else { t=op==2?d1^d3^d2:(d3&d2)|(~d3&d1); t=t+d0+n.u32[3]+wj;
    r.u32[0]=d1; r.u32[1]=n_rol32(d2,19); r.u32[2]=d3; r.u32[3]=t^n_rol32(t,9)^n_rol32(t,17); } return r;}
static inline V128 n_sm3pw1(V128 d,V128 n,V128 m){V128 r; for(int i=0;i<3;i++) r.u32[i]=d.u32[i]^n.u32[i]^n_rol32(m.u32[i+1],15);
  r.u32[3]=d.u32[3]^n.u32[3]; for(int i=0;i<4;i++){ if(i==3) r.u32[3]=d.u32[3]^n.u32[3]^n_rol32(r.u32[0],15);
    r.u32[i]=r.u32[i]^n_rol32(r.u32[i],15)^n_rol32(r.u32[i],23);} return r;}
static inline V128 n_sm3pw2(V128 d,V128 n,V128 m){V128 t,r; for(int i=0;i<4;i++){ t.u32[i]=n.u32[i]^n_rol32(m.u32[i],7); r.u32[i]=d.u32[i]^t.u32[i]; }
  uint32_t t2=n_rol32(t.u32[0],15); t2=t2^n_rol32(t2,15)^n_rol32(t2,23); r.u32[3]^=t2; return r;}
static const uint8_t n_sm4_sbox[256]={
  0xd6,0x90,0xe9,0xfe,0xcc,0xe1,0x3d,0xb7,0x16,0xb6,0x14,0xc2,0x28,0xfb,0x2c,0x05,0x2b,0x67,0x9a,0x76,0x2a,0xbe,0x04,0xc3,
  0xaa,0x44,0x13,0x26,0x49,0x86,0x06,0x99,0x9c,0x42,0x50,0xf4,0x91,0xef,0x98,0x7a,0x33,0x54,0x0b,0x43,0xed,0xcf,0xac,0x62,
  0xe4,0xb3,0x1c,0xa9,0xc9,0x08,0xe8,0x95,0x80,0xdf,0x94,0xfa,0x75,0x8f,0x3f,0xa6,0x47,0x07,0xa7,0xfc,0xf3,0x73,0x17,0xba,
  0x83,0x59,0x3c,0x19,0xe6,0x85,0x4f,0xa8,0x68,0x6b,0x81,0xb2,0x71,0x64,0xda,0x8b,0xf8,0xeb,0x0f,0x4b,0x70,0x56,0x9d,0x35,
  0x1e,0x24,0x0e,0x5e,0x63,0x58,0xd1,0xa2,0x25,0x22,0x7c,0x3b,0x01,0x21,0x78,0x87,0xd4,0x00,0x46,0x57,0x9f,0xd3,0x27,0x52,
  0x4c,0x36,0x02,0xe7,0xa0,0xc4,0xc8,0x9e,0xea,0xbf,0x8a,0xd2,0x40,0xc7,0x38,0xb5,0xa3,0xf7,0xf2,0xce,0xf9,0x61,0x15,0xa1,
  0xe0,0xae,0x5d,0xa4,0x9b,0x34,0x1a,0x55,0xad,0x93,0x32,0x30,0xf5,0x8c,0xb1,0xe3,0x1d,0xf6,0xe2,0x2e,0x82,0x66,0xca,0x60,
  0xc0,0x29,0x23,0xab,0x0d,0x53,0x4e,0x6f,0xd5,0xdb,0x37,0x45,0xde,0xfd,0x8e,0x2f,0x03,0xff,0x6a,0x72,0x6d,0x6c,0x5b,0x51,
  0x8d,0x1b,0xaf,0x92,0xbb,0xdd,0xbc,0x7f,0x11,0xd9,0x5c,0x41,0x1f,0x10,0x5a,0xd8,0x0a,0xc1,0x31,0x88,0xa5,0xcd,0x7b,0xbd,
  0x2d,0x74,0xd0,0x12,0xb8,0xe5,0xb4,0xb0,0x89,0x69,0x97,0x4a,0x0c,0x96,0x77,0x7e,0x65,0xb9,0xf1,0x09,0xc5,0x6e,0xc6,0x84,
  0x18,0xf0,0x7d,0xec,0x3a,0xdc,0x4d,0x20,0x79,0xee,0x5f,0x3e,0xd7,0xcb,0x39,0x48};
static inline V128 n_sm4(V128 s,V128 k,int key){for(int e=0;e<4;e++){
  uint32_t v=s.u32[3]^s.u32[2]^s.u32[1]^k.u32[e], o=0; for(int i=0;i<4;i++) o|=(uint32_t)n_sm4_sbox[(v>>(8*i))&0xff]<<(8*i);
  o=key?o^n_rol32(o,13)^n_rol32(o,23):o^n_rol32(o,2)^n_rol32(o,10)^n_rol32(o,18)^n_rol32(o,24); o^=s.u32[0];
  s.u32[0]=s.u32[1]; s.u32[1]=s.u32[2]; s.u32[2]=s.u32[3]; s.u32[3]=o;} return s;}
static inline V128 n_eor3(V128 n,V128 m,V128 a){V128 r; for(int i=0;i<2;i++) r.u64[i]=n.u64[i]^m.u64[i]^a.u64[i]; return r;}
static inline V128 n_bcax(V128 n,V128 m,V128 a){V128 r; for(int i=0;i<2;i++) r.u64[i]=n.u64[i]^(m.u64[i]&~a.u64[i]); return r;}
static inline V128 n_rax1(V128 n,V128 m){V128 r; for(int i=0;i<2;i++) r.u64[i]=n.u64[i]^n_ror64(m.u64[i],63); return r;}
static inline V128 n_xar(V128 n,V128 m,int k){V128 r; for(int i=0;i<2;i++) r.u64[i]=n_ror64(n.u64[i]^m.u64[i],k); return r;}
"""                                                                    # static inline C appended to recompile.C_PRELUDE; prefix names n_

###############
# element access layer
###############
def vinfo(ins: object, o: object) -> tuple[str, int, int, int, int]:
    """(kind, index, esize, count, lane) of a register operand; scalars are count 1, lane -1."""
    kind, idx, w = reg_parts(ins.reg_name(o.reg))
    if kind != "v": return (kind, idx, w, 1, -1)
    if o.vas not in VAS:                                               # capstone leaves vas unset on some .d[i] lanes
        lt = re.search(r"\bv%d\.([bhsd])\[%d\]" % (idx, o.vector_index), ins.op_str)
        if lt is None: raise NotImplementedError("neon:vas " + ins.op_str)
        return ("v", idx, {"b": 8, "h": 16, "s": 32, "d": 64}[lt.group(1)], 1, o.vector_index)
    count, esize = VAS[o.vas]
    return ("v", idx, esize, count, o.vector_index)

def el(var: str, e: int, k: int, t: str) -> str:
    """C expression for element k of width e in V128 var: t u=unsigned, s=sign-extended int64, f=float."""
    if t == "s": return "(int64_t)(int%d_t)%s.u%d[%d]" % (e, var, e, k)
    return "%s.%s%d[%d]" % (var, "f" if t == "f" else "u", e, k)

def wbits(d: tuple) -> int:
    """Bits of the destination written by a full-width op; V bits above it are zeroed."""
    return d[2] * d[3] if d[0] == "v" else d[2]

def finish(srcs: list, init: str, body: list, bits: int, dst: int) -> str:
    """Copy sources to locals, build _r, zero above `bits`, store to V[dst]."""
    decl = "".join("V128 _%s=c->V[%d]; " % s for s in srcs)
    return "{ %sV128 _r=%s; %s %s c->V[%d]=_r; }" % (decl, init, " ".join(body), CLEAR[bits], dst)

def third_op(ins: object, ops: list, k: int) -> tuple[tuple | None, int]:
    """(vinfo or None, immediate or 0) for optional operand k."""
    o = ops[k] if len(ops) > k else None
    if o is None: return (None, 0)
    if o.type == ARM64_OP_REG: return (vinfo(ins, o), 0)
    return (None, o.imm if o.type == ARM64_OP_IMM else 0)

###############
# elementwise, widening, narrowing
###############
def lift_elem(ins: object, m: str, ops: list) -> str:
    """Same-arrangement elementwise ops: three-same, by-element, two-misc, shift-by-immediate, compare #0."""
    d, a = vinfo(ins, ops[0]), vinfo(ins, ops[1])
    b, imm = third_op(ins, ops, 2)
    tmpl, rk = ELEM[m]
    if m in REG_ONLY and b is None: raise NotImplementedError("neon:%s #imm" % m)
    e, n = (64, max(1, wbits(d) // 64)) if m in BITWISE else (d[2], d[3])
    half = e == 16 and ("{f" in tmpl or rk == "f")                     # exact via f32: no rounding in these ops
    if (half and m not in HALF_F32) or (not half and ("{f" in tmpl or rk == "f") and e not in (32, 64)):
        raise NotImplementedError("neon:fp16 " + m)
    body, ks = [], []
    for j in range(n):
        bj = b[4] if b and b[4] >= 0 else j
        k = {"a": el("_a", e, j, "u"), "sa": el("_a", e, j, "s"), "fa": el("_a", e, j, "f"),
             "b": el("_b", e, bj, "u") if b else "0", "sb": el("_b", e, bj, "s") if b else "0",
             "fb": el("_b", e, bj, "f") if b else "0.0", "d": el("_d", e, j, "u"), "fd": el("_d", e, j, "f"),
             "E": e, "M": "0x%xULL" % ((1 << e) - 1), "N": imm, "S": e, "SB": "0x%xULL" % (1 << (e - 1)),
             "T": "float" if e == 32 else "double", "P": repr(float(2 ** imm))}
        if half:
            k.update(fa="n_h2f(%s)" % k["a"], fb="n_h2f(%s)" % k["b"], fd="n_h2f(%s)" % k["d"], S=32, T="float")
        body.append("_r.u16[%d]=n_f2h(%s);" % (j, tmpl.format(**k)) if half else "_r.%s%d[%d]=%s;" % (rk, e, j, tmpl.format(**k)))
        ks.append(k)
    if m in FAST and not half:                                         # IEEE vector op; the ARM NaN rules only when a lane is NaN
        vt, lanes = ("vf32", 4) if e == 32 else ("vf64", 2)
        bv = "_b.%s" % vt if not b or b[4] < 0 else "__builtin_shufflevector(_b.%s,_b.%s,%s)" % (vt, vt, ",".join([str(b[4])] * lanes))
        ops_v = {"a": "_a." + vt, "b": bv, "d": "_d." + vt}
        if n < lanes:                                                  # inactive lanes: 1.0 (exact in every FAST op), opaque so -O2 cannot drop them
            ops_v = {k: "n_ones_%s(%s,%d)" % (vt, v, n) for k, v in ops_v.items()}
        fast = ["_r.%s=%s;" % (vt, FAST[m].format(**ops_v)),
                "%s _m=_r.%s!=_r.%s;" % ("gv4i" if e == 32 else "gv2l", vt, vt)]
        any_nan = "__builtin_ia32_movmsk%s((%s)_m) & %d" % ("ps" if e == 32 else "pd", "gv4f" if e == 32 else "gv2d", (1 << n) - 1)   # lane sign bits: one test
        fix = "_r.%s=n_fixv_%s%d(_a.%s,%s,_d.%s,_r.%s,%d);" % (vt, m, e, vt, bv, vt, vt, n)   # the per-lane ARM results, out of line: preserve_all keeps the hot path's registers
        body = fast + ["if (__builtin_expect((%s)!=0, 0)) { %s }" % (any_nan, fix)]
    elif m in VINT and not half and not (b and b[4] >= 0) and (b or "{b}" not in VINT[m]):   # whole-vector integer lanes
        vu = VU[e]
        body = ["_r.%s=%s;" % (vu, "_a.%s^_a.%s" % (vu, vu) if m == "ushr" and imm >= e else VINT[m].format(a="_a." + vu, b="_b." + vu, N=imm))]
    srcs = [("a", a[1])] + ([("b", b[1])] if b else []) + [("d", d[1])]
    return finish(srcs, "{0}", body, wbits(d), d[1])

def lift_long(ins: object, m: str, ops: list) -> str:
    """Widening ops (ushll/sshll/shll, *addl/*subl, *addw/*subw, *mull), '2' forms read the high half."""
    base = m[:-1] if m.endswith("2") else m
    d, a = vinfo(ins, ops[0]), vinfo(ins, ops[1])
    b, imm = third_op(ins, ops, 2)
    ed, n = d[2], d[3]
    es, off, t = ed // 2, (n if base != m else 0), ("s" if base[0] == "s" and base != "shll" else "u")
    body = []
    for j in range(n):
        x = "(uint64_t)%s" % el("_a", es, off + j, t)
        y = "(uint64_t)%s" % el("_b", es, b[4] if b[4] >= 0 else off + j, t) if b else "0"
        body.append("_r.u%d[%d]=%s;" % (ed, j, LONG[base].format(x=x, y=y, w="(uint64_t)" + el("_a", ed, j, "u"), N=imm,
                                                                 d="(uint64_t)" + el("_d", ed, j, "u"))))
    if es in HUT and ed == 2 * es:                                     # whole vectors: widen a half, then wrapping unsigned lanes
        half = lambda v, lane: "__builtin_shufflevector(%s, %s, %s)" % (v, v, ",".join(str(lane if lane >= 0 else off + j) for j in range(n)))
        src = lambda r: "(%s)_%s.%s" % (VST[es], r, VU[es]) if t == "s" else "_%s.%s" % (r, VU[es])
        wide = lambda r, lane: "((%s)__builtin_convertvector(%s, %s))" % (VUT[ed], half(src(r), lane), VST[ed] if t == "s" else VUT[ed])
        body = ["_r.%s=%s;" % (VU[ed], LONG[base].format(x=wide("a", -1), y=wide("b", b[4]) if b else "0", w="_a." + VU[ed],
                                                        d="_d." + VU[ed], N=imm))]
    return finish([("a", a[1])] + ([("b", b[1])] if b else []) + [("d", d[1])], "{0}", body, 128, d[1])

def lift_narrow(ins: object, m: str, ops: list) -> str:
    """Narrowing ops (xtn, shrn, rshrn, fcvtn, sq/uq saturating, addhn/subhn); '2' forms write the high half, keep the low."""
    base = m[:-1] if m.endswith("2") else m
    d, a = vinfo(ins, ops[0]), vinfo(ins, ops[1])
    b, imm = third_op(ins, ops, 2)
    es, ns, hi = a[2], a[3], base != m
    tmpl, rk = ("n_f32to16({f})", "u") if base == "fcvtn" and es == 32 else NARROW[base]
    if ("{y}" in tmpl) != (b is not None): raise NotImplementedError("neon:%s operands" % m)
    body = ["_r.%s%d[%d]=%s;" % (rk, es // 2, (ns if hi else 0) + j, tmpl.format(
        x=el("_a", es, j, "u"), sx=el("_a", es, j, "s"), y=el("_b", es, j, "u") if b else "", f=el("_a", es, j, "f"),
        N=imm, H=es // 2)) for j in range(ns)]
    if base in VNARROW and es // 2 in HUT:                             # whole vector: shift, truncate each lane, place the half
        v = VNARROW[base].format(x="_a." + VU[es], N=imm, R=(1 << (imm - 1)) if imm else 0)
        body = ["{ %s _n=__builtin_convertvector(%s, %s); memcpy(&_r.u64[%d], &_n, 8); }" % (HUT[es // 2], v, HUT[es // 2], int(hi))]
    return finish([("a", a[1]), ("d", d[1])] + ([("b", b[1])] if b else []), "_d" if hi else "{0}", body, 128 if hi else 64, d[1])

def lift_fcvtl(ins: object, m: str, ops: list) -> str:
    """fcvtl/fcvtl2: widen two f32 to f64 or four f16 to f32 (low or high half); NaNs are quieted."""
    d, a = vinfo(ins, ops[0]), vinfo(ins, ops[1])
    n = 128 // d[2]
    off = n if m == "fcvtl2" else 0
    cvt = "_r.f64[%d]=n_f32to64(_a.f32[%d]);" if d[2] == 64 else "_r.f32[%d]=n_h2fq(_a.u16[%d]);"
    return finish([("a", a[1])], "{0}", [cvt % (j, off + j) for j in range(n)], 128, d[1])

def lift_addlp(ins: object, m: str, ops: list) -> str:
    """uaddlp/saddlp (+ uadalp/sadalp accumulate): element j = a[2j] + a[2j+1] widened to twice the width."""
    d, a = vinfo(ins, ops[0]), vinfo(ins, ops[1])
    t, acc = ADDLP[m]
    ed, es = d[2], a[2]
    body = ["_r.u%d[%d]=%s(uint64_t)%s+(uint64_t)%s;" % (ed, j, "(uint64_t)%s+" % el("_d", ed, j, "u") if acc else "",
                                                        el("_a", es, 2 * j, t), el("_a", es, 2 * j + 1, t)) for j in range(d[3])]
    return finish([("a", a[1]), ("d", d[1])], "{0}", body, wbits(d), d[1])

###############
# permutes, table lookup, pairwise, reductions, dot product
###############
def perm_map(m: str, n: int, imm: int) -> list:
    """Source (reg, element) for each destination element of a permute over n elements."""
    cat = [("a", k) for k in range(n)] + [("b", k) for k in range(n)]
    h = n // 2
    if m == "zip1": return [cat[(j % 2) * n + j // 2] for j in range(n)]
    if m == "zip2": return [cat[(j % 2) * n + h + j // 2] for j in range(n)]
    if m == "uzp1": return [cat[2 * j] for j in range(n)]
    if m == "uzp2": return [cat[2 * j + 1] for j in range(n)]
    if m == "trn1": return [cat[(j % 2) * n + j - j % 2] for j in range(n)]
    if m == "trn2": return [cat[(j % 2) * n + j - j % 2 + 1] for j in range(n)]
    return [cat[imm + j] for j in range(n)]

def lift_perm(ins: object, m: str, ops: list) -> str:
    """zip/uzp/trn, ext (bytes), rev16/32/64 (reverse elements within each container)."""
    d, a = vinfo(ins, ops[0]), vinfo(ins, ops[1])
    b, _ = third_op(ins, ops, 2)
    e, n = (8, wbits(d) // 8) if m == "ext" else (d[2], d[3])
    if m.startswith("rev"):
        k = int(m[3:]) // e
        if k < 2: raise NotImplementedError("neon:%s.%d" % (m, e))
        src = [("a", j ^ (k - 1)) for j in range(n)]
    else:
        src = perm_map(m, n, ops[3].imm if m == "ext" else 0)
    body = ["_r.u%d[%d]=_%s.u%d[%d];" % (e, j, s, e, k) for j, (s, k) in enumerate(src)]
    return finish([("a", a[1])] + ([("b", b[1])] if b else []), "{0}", body, wbits(d), d[1])

def lift_tbl(ins: object, m: str, ops: list) -> str:
    """tbl/tbx over a 1-4 register table; out-of-range index gives 0 (tbl) or keeps the lane (tbx)."""
    regs = [vinfo(ins, o) for o in ops]
    d, tabs, x = regs[0], regs[1:-1], regs[-1]
    nb = wbits(d) // 8
    return ("{ V128 _t[%d]={%s}; V128 _x=c->V[%d]; V128 _r=%s; for(int _j=0;_j<%d;_j++){ unsigned _k=_x.u8[_j]; "
            "if(_k<%d) _r.u8[_j]=_t[_k>>4].u8[_k&15]; } %s c->V[%d]=_r; }"
            % (len(tabs), ",".join("c->V[%d]" % t[1] for t in tabs), x[1], "c->V[%d]" % d[1] if m == "tbx" else "{0}",
               nb, 16 * len(tabs), CLEAR[wbits(d)], d[1]))

def lift_pairwise(ins: object, m: str, ops: list) -> str:
    """addp/faddp vector: element j = op(concat(a,b)[2j], concat(a,b)[2j+1])."""
    d, a, b = vinfo(ins, ops[0]), vinfo(ins, ops[1]), vinfo(ins, ops[2])
    e, n = d[2], d[3]
    cat = [("a", k) for k in range(n)] + [("b", k) for k in range(n)]
    body = []
    for j in range(n):
        (s1, k1), (s2, k2) = cat[2 * j], cat[2 * j + 1]
        if m == "faddp":
            body.append("_r.f%d[%d]=n_fadd%d(_%s.f%d[%d],_%s.f%d[%d]);" % (e, j, e, s1, e, k1, s2, e, k2))
        else:
            body.append("_r.u%d[%d]=_%s.u%d[%d]+_%s.u%d[%d];" % (e, j, s1, e, k1, s2, e, k2))
    return finish([("a", a[1]), ("b", b[1])], "{0}", body, wbits(d), d[1])

def lift_reduce(ins: object, m: str, ops: list) -> str:
    """Across-lanes to a scalar: addv, uaddlv, saddlv, u/s max/min v, scalar addp/faddp."""
    d, a = vinfo(ins, ops[0]), vinfo(ins, ops[1])
    if d[0] == "v": return lift_pairwise(ins, m, ops)
    e, n, ed = a[2], a[3], d[2]
    if m in FREDUCE:                                                   # ARM Reduce(): op(reduce(low half), reduce(high half))
        if e not in (32, 64): raise NotImplementedError("neon:%s.%d" % (m, e))
        xs = ["_a.f%d[%d]" % (e, k) for k in range(n)]
        while len(xs) > 1: xs = ["n_%s%d(%s,%s)" % (FREDUCE[m], e, xs[k], xs[k + 1]) for k in range(0, len(xs), 2)]
        return finish([("a", a[1])], "{0}", ["_r.f%d[0]=%s;" % (e, xs[0])], ed, d[1])
    if m == "faddp":
        body = ["_r.f%d[0]=n_fadd%d(_a.f%d[0],_a.f%d[1]);" % (e, e, e, e)]
    else:
        signed = m in ("saddlv", "smaxv", "sminv")
        xs = [el("_a", e, k, "s" if signed else "u") for k in range(n)]
        cmp = ">" if "max" in m else "<"
        step = ["_s+=%s;" % x for x in xs[1:]] if "add" in m else ["if(%s%s_s) _s=%s;" % (x, cmp, x) for x in xs[1:]]
        body = ["%s _s=%s;" % ("int64_t" if signed else "uint64_t", xs[0])] + step + ["_r.u%d[0]=_s;" % ed]
    return finish([("a", a[1])], "{0}", body, ed, d[1])

def lift_dot(ins: object, m: str, ops: list) -> str:
    """udot/sdot by vector or by element: 32-bit lane += sum of four byte products."""
    d, a, b = vinfo(ins, ops[0]), vinfo(ins, ops[1]), vinfo(ins, ops[2])
    t = "s" if m == "sdot" else "u"
    body = []
    for i in range(d[3]):
        bi = b[4] if b[4] >= 0 else i
        terms = "+".join("%s*%s" % (el("_a", 8, 4 * i + k, t), el("_b", 8, 4 * bi + k, t)) for k in range(4))
        body.append("_r.u32[%d]=_d.u32[%d]+(uint32_t)(%s);" % (i, i, terms))
    return finish([("a", a[1]), ("b", b[1]), ("d", d[1])], "{0}", body, wbits(d), d[1])

###############
# immediates and lane moves
###############
def lift_modimm(ins: object, m: str, ops: list) -> str:
    """movi/mvni/fmov #imm and orr/bic #imm (lsl or msl shifted), replicated per element."""
    d, o = vinfo(ins, ops[0]), ops[1]
    e, n = d[2], d[3]
    if o.type == ARM64_OP_FP:
        if e not in (16, 32, 64): raise NotImplementedError("neon:fmov.%d" % e)
        v = int.from_bytes(struct.pack({16: "<e", 32: "<f", 64: "<d"}[e], o.fp), "little")
    else:
        v, sa = o.imm & 0xFFFFFFFFFFFFFFFF, o.shift.value
        if o.shift.type == ARM64_SFT_LSL: v <<= sa
        elif o.shift.type == ARM64_SFT_MSL: v = (v << sa) | ((1 << sa) - 1)
        v = (~v if m == "mvni" else v) & ((1 << e) - 1)
    fmt = {"orr": "_d.u%d[%d]|0x%xULL", "bic": "_d.u%d[%d]&~0x%xULL"}.get(m)
    body = ["_r.u%d[%d]=%s;" % (e, j, fmt % (e, j, v) if fmt else "0x%xULL" % v) for j in range(n)]
    return finish([("d", d[1])], "{0}", body, wbits(d), d[1])

def lift_lane(ins: object, m: str, ops: list) -> str:
    """dup / ins / umov / smov / mov and fmov lane forms, plus whole-register mov (orr alias)."""
    d, s = vinfo(ins, ops[0]), vinfo(ins, ops[1])
    if d[0] in GPR:
        val = "c->V[%d].u%d[%d]" % (s[1], s[2], max(s[4], 0))
        return wr(d[0], d[1], d[2], "(uint64_t)(int64_t)(int%d_t)%s" % (s[2], val) if m == "smov" else val)
    src = rd(s[0], s[1], s[2]) if s[0] in GPR else "_a.u%d[%d]" % (s[2], s[4])
    pre = "" if s[0] in GPR else "V128 _a=c->V[%d]; " % s[1]
    if d[0] == "v" and d[4] >= 0:
        return "{ %sc->V[%d].u%d[%d]=(uint%d_t)(%s); }" % (pre, d[1], d[2], d[4], d[2], src)
    if s[0] == "v" and s[4] < 0:
        return finish([("a", s[1])], "_a", [], wbits(d), d[1])
    body = ["_r.u%d[%d]=(uint%d_t)(%s);" % (d[2], j, d[2], src) for j in range(d[3])]
    return "{ %sV128 _r={0}; %s %s c->V[%d]=_r; }" % (pre, " ".join(body), CLEAR[wbits(d)], d[1])

def lift_imm_or_elem(ins: object, m: str, ops: list) -> str:
    """orr/bic: modified-immediate form or register form."""
    return lift_modimm(ins, m, ops) if ops[1].type == ARM64_OP_IMM else lift_elem(ins, m, ops)

def lift_fmov(ins: object, m: str, ops: list) -> str:
    """fmov vector immediate or fmov to/from a d[1] lane."""
    return lift_modimm(ins, m, ops) if ops[1].type == ARM64_OP_FP else lift_lane(ins, m, ops)

###############
# structure loads and stores
###############
def lift_mem(ins: object, m: str, ops: list) -> str:
    """ld1-4 / st1-4 (multiple, interleaved, single lane) and ld1r-4r, with imm or register post-index."""
    mi = next(k for k, o in enumerate(ops) if o.type == ARM64_OP_MEM)
    vl = [vinfo(ins, o) for o in ops[:mi]]
    bk, bi, _ = reg_parts(ins.reg_name(ops[mi].mem.base))
    store, rep, nst = m.startswith("st"), m.endswith("r"), int(m[2])
    e, n, lane = vl[0][2], vl[0][3], max(v[4] for v in vl)             # capstone puts a list's lane on its last reg
    eb, nb = e // 8, e * n // 8
    body = []
    if lane >= 0 or rep:
        for r, v in enumerate(vl):
            p = "*(uint%d_t*)(_ad+%d)" % (e, r * eb)
            if store: body.append("%s=c->V[%d].u%d[%d];" % (p, v[1], e, lane))
            elif lane >= 0: body.append("c->V[%d].u%d[%d]=%s;" % (v[1], e, lane, p))
            else: body.append("{ uint%d_t _v=%s; V128 _r={0}; for(int _j=0;_j<%d;_j++) _r.u%d[_j]=_v; c->V[%d]=_r; }"
                              % (e, p, n, e, v[1]))
        size = len(vl) * eb
    elif nst == 1:
        body = [(simd_store if store else simd_load)(v[1], nb * 8, "(_ad+%d)" % (r * nb)) for r, v in enumerate(vl)]
        size = len(vl) * nb
    else:
        body = [] if store else ["c->V[%d].u64[1]=0;" % v[1] for v in vl if nb == 8]
        for j in range(n):
            for r, v in enumerate(vl):
                p = "*(uint%d_t*)(_ad+%d)" % (e, (j * nst + r) * eb)
                body.append("%s=c->V[%d].u%d[%d];" % (p, v[1], e, j) if store else "c->V[%d].u%d[%d]=%s;" % (v[1], e, j, p))
        size = nst * n * eb
    post = ops[mi + 1] if len(ops) > mi + 1 else None
    wb = ""
    if ins.writeback:
        inc = rd(*reg_parts(ins.reg_name(post.reg))[:2], 64) if post is not None and post.type == ARM64_OP_REG else \
            "%d" % (post.imm if post is not None else size)
        wb = wr(bk, bi, 64, "_ad + %s" % inc)
    return "{ uint64_t _ad=%s; %s %s }" % (rd(bk, bi, 64), " ".join(body), wb)

###############
# crypto
###############
def lift_aes(ins: object, m: str, ops: list) -> str:
    """aese/aesd (state ^= key, then (Inv)SubBytes+(Inv)ShiftRows) and aesmc/aesimc via AES-NI."""
    d, a, op = vinfo(ins, ops[0]), vinfo(ins, ops[1]), AES_OP[m]
    return "c->V[%d]=n_aes(c->V[%d], c->V[%d], %d);" % (d[1], d[1] if op < 2 else a[1], a[1], op)

def lift_pmull(ins: object, m: str, ops: list) -> str:
    """pmull/pmull2: 64x64->128 carry-less product via PCLMULQDQ, or eight 8x8->16 products; '2' reads the high half."""
    d, a, b = vinfo(ins, ops[0]), vinfo(ins, ops[1]), vinfo(ins, ops[2])
    hi = m == "pmull2"
    if d[2] == 128:
        return "{ V128 _a=c->V[%d], _b=c->V[%d]; c->V[%d]=n_pmull64(_a.u64[%d], _b.u64[%d]); }" % (a[1], b[1], d[1], hi, hi)
    body = ["_r.u16[%d]=(uint16_t)n_clmul8(_a.u8[%d],_b.u8[%d]);" % (j, 8 * hi + j, 8 * hi + j) for j in range(8)]
    return finish([("a", a[1]), ("b", b[1])], "{0}", body, 128, d[1])

def lift_crypto(ins: object, m: str, ops: list) -> str:
    """SHA-1/256/512, SM3, SM4 and SHA-3 (eor3, bcax, rax1, xar) on whole V registers through the n_ helpers."""
    r = [reg_parts(ins.reg_name(o.reg))[1] for o in ops if o.type == ARM64_OP_REG]
    v = ["c->V[%d]" % k for k in r] + ["", ""]
    call = CRYPTO[m].format(d=v[0], n=v[1], m=v[2], a=v[3], ns="%s.u32[0]" % v[1], i=max(ops[-1].vector_index, 0),
                            imm=ops[-1].imm if m == "xar" else 0)
    return "{ V128 _r=%s; c->V[%d]=_r; }" % (call, r[0])

###############
# dispatch
###############
DISPATCH = {**{k: lift_elem for k in ELEM}, "orr": lift_imm_or_elem, "bic": lift_imm_or_elem,
            **{k: lift_long for k in LONG}, **{k + "2": lift_long for k in LONG},
            **{k: lift_narrow for k in NARROW}, **{k + "2": lift_narrow for k in NARROW},
            "fcvtl": lift_fcvtl, "fcvtl2": lift_fcvtl,
            **{k: lift_perm for k in ("zip1", "zip2", "uzp1", "uzp2", "trn1", "trn2", "ext", "rev16", "rev32", "rev64")},
            "tbl": lift_tbl, "tbx": lift_tbl, "addp": lift_reduce, "faddp": lift_reduce,
            **{k: lift_reduce for k in ("addv", "uaddlv", "saddlv", "umaxv", "uminv", "smaxv", "sminv")},
            "udot": lift_dot, "sdot": lift_dot, "movi": lift_modimm, "mvni": lift_modimm, "fmov": lift_fmov,
            **{k: lift_lane for k in ("dup", "mov", "ins", "umov", "smov")},
            **{k: lift_mem for k in ("ld1", "ld2", "ld3", "ld4", "ld1r", "ld2r", "ld3r", "ld4r", "st1", "st2", "st3", "st4")},
            **{k: lift_aes for k in AES_OP}, "pmull": lift_pmull, "pmull2": lift_pmull,
            **{k: lift_addlp for k in ADDLP}, **{k: lift_reduce for k in FREDUCE}, **{k: lift_crypto for k in CRYPTO}}
MNEMONICS: set = set(DISPATCH)

###############
# lifting
###############
def scalar_form(ins: object, m: str) -> bool:
    """True for a scalar-register form lifted here: SCALAR mnemonics, and h forms of the fp ops computed via f32."""
    return m in SCALAR or m in CRYPTO or (m in HALF_F32 and ins.reg_name(ins.operands[0].reg)[0] == "h")

def lift_neon(ins: object, m: str, ops: list) -> str:
    """C statements for one claimed vector instruction."""
    return DISPATCH[m](ins, m, ops)
