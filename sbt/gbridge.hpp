/* gdyld host runtime (C++17 without libc++). host.cpp includes it after the SDK headers, the CPU typedef and
   the GD_* constants; the generated bridge.hpp and layout.hpp follow it. Each host import gets an
   Apple-AAPCS64 -> SysV bridge derived at compile time from its real header prototype (Gen<&::name>).
   Function pointers cross in both directions: guest code handed to the host becomes a typed closure (Pool<F>) that
   re-enters translated code and maps back to the guest address when the host returns it; a host function returned
   with a known function-pointer type becomes a typed handle the guest can call (dispatch); an untyped host code
   pointer (dlsym, void(*)(void)) becomes a handle that refuses to be called. Struct and union layouts are read with
   __builtin_dump_struct at compile time (HFA/HVA classification, code-pointer fields, long double fields).
   V8 (C++ imports): non-literal classes are classified at run time, C++ references and non-trivial-for-calls values cross
   as the caller's own object, callbacks inside structs and callback outputs are converted (Fix/After from
   gen/v8_marshal.inc), guest vtables implementing host interfaces are patched to native closures (GD_VTABS) and native
   vtable slots of host objects the guest calls get typed bridges (GD_NSLOTS). A V8 build includes gen/v8_bridges.inc and
   gen/v8_marshal.inc after this file; any other build gets empty tables from gdyld. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <dlfcn.h>
#include <pthread.h>
#include <signal.h>
#include <syslog.h>
#include <xlocale.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <mach-o/loader.h>
#include <mach-o/nlist.h>
#include <mach-o/fat.h>
#include <libkern/OSByteOrder.h>
#include <limits.h>
#include <malloc/malloc.h>
#include <mach/mach.h>

typedef void (*gfn)(CPU*);
#if __OBJC__
using gd_id = id;                                             /* ObjC's id is its own type, not struct objc_object* */
#else
struct objc_object; using gd_id = objc_object*;               /* a plain C++ embedder (no gdyld build) */
#endif
extern "C" void dispatch(CPU* c, uint64_t a);
extern "C" int __cxa_atexit(void (*)(void *), void *, void *);
static void (*gd_die_hook)();                                 /* GDYLD_TRACE_IMPORTS: lists the imports called before a loud stop */
[[noreturn]] static void die(const char* what, uint64_t a) {
  fprintf(stderr, "FATAL: %s 0x%llx\n", what, (unsigned long long)a); fflush(stderr);
  if (gd_die_hook) gd_die_hook();
  _exit(70);
}
[[noreturn]] static void die_name(const char* what, const char* name) {
  fprintf(stderr, "FATAL: %s: %s\n", what, name); fflush(stderr);
  if (gd_die_hook) gd_die_hook();
  _exit(70);
}
extern "C" void gd_die(const char* what, uint64_t a) { die(what, a); }
extern "C" void unsupported(CPU* c, uint64_t a) { (void)c; die("unsupported instruction at", a); }
#include "gvarargs.h"

/* tables emitted by gdyld.py into bridge.hpp / layout.hpp */
/* kind: EK_FN prototype bridge (addr = the host function, null when a weak import is absent), EK_DATA host data,
   EK_DYN undeclared (resolved by name at start), EK_SPECIAL hand-written bridge, EK_QUAL a name that several host
   libraries export: resolved in `lib` alone at start (two-level namespace), EK_QDATA the same for data */
struct Ent { void (*call)(CPU*, int); uint64_t data; void* hostfn; const char* name; int kind; const void* addr; const char* lib; };
enum { EK_FN, EK_DATA, EK_DYN, EK_SPECIAL, EK_QUAL, EK_QDATA };
struct Img { uint64_t lo, size, slide; const char* file; gfn (*lookup)(uint64_t); const char* path;
             uint64_t ehf, ehf_len, cu, cu_len; };                   /* guest __eh_frame / __unwind_info */
struct HBind { uint64_t addr; int k; int64_t addend; int weak; };
struct TlvImg { uint64_t start, init, size, align; };
struct GExp { int img; const char* name; uint64_t addr; };    /* guest export, C name (no leading underscore) */
extern const Ent ENT[]; extern const int NIMP;
extern const Img IMG[]; extern const int NIMG;
extern const HBind HB[]; extern const int NHB;
extern const uint64_t INITS[]; extern const int NINIT;
extern const TlvImg TLVI[]; extern const int NTLV;
extern const uint64_t TLVD[]; extern const int TLVD_IMG[]; extern const int NTLVD;
extern const GExp GEXP[]; extern const int NGEXP;
extern const uint64_t GD_MAIN_ADDR;
extern const int ORDER[]; extern const int NORDER; extern const int INIT_IMG[];   /* image init order; image of INITS[i] */
extern const uint64_t OCI[];                                  /* per image: (address, count) of each gdyld.OBJC_SECTS list */
/* variadic / va_list methods of host classes from the SDK headers, sorted by selector: kind VK_* (gobjc.hpp), fmt and va
   are 1-based parameter indexes; cls "" for a protocol */
struct VMeth { const char* cls; const char* sel; int cmeth, kind, fmt, va; };
extern const VMeth GD_VMETH[]; extern const int GD_NVMETH;
/* guest vtables implementing host interfaces: slot -> closure maker; the image is found by content (slot chk holds the
   unslid guest address chk_target) */
struct VSlot { int slot; uint64_t (*mk)(uint64_t); const char* sig; };
struct VTab { const char* iface; uint64_t vptr; int chk; uint64_t chk_target; int n; const VSlot* s; };
extern const VTab GD_VTABS[]; extern const int GD_NVTAB;
/* native vtable slots of host classes implementing an interface whose objects reach the guest: the slot at `addr` in
   library `lib` (unslid x86-64 vmaddr) holds the function the guest calls through it; `target` is its unslid address
   (a rebase) or 0 for a bind to `sym` */
struct NSlot { const char* lib; const char* anchor; uint64_t anchor_addr, addr, target; const char* sym;
               void (*call)(CPU*, void*); const char* sig; };
extern const NSlot GD_NSLOTS[]; extern const int GD_NNSLOT;
static void** QFN;                                           /* EK_QUAL: host address resolved in its own library */

static __thread CPU* tls_cur;                                 /* innermost guest CPU of this thread (running or in a host call) */
/* A stack address the guest computed (a V8 stack limit: &local - N) handed to native code that compares it with its own
   stack pointer: the same distance below the host sp. A value farther than 1 GB from the guest sp (a constant such as
   0x8000, a host address) is not a guest-stack address and passes unchanged. */
static uint64_t stack_to_host(uint64_t a) {
  const CPU* c = tls_cur;
  const uint64_t span = 1ULL << 30;
  if (!c || a - (c->SP - span) >= 2 * span) return a;
  return (uint64_t)(uintptr_t)__builtin_frame_address(0) - (c->SP - a);
}

/* ---- non-local transfers (C++ exceptions via guest libunwind, longjmp) ----
   The guest's only non-local jump is a host exception carrying the register file to install. Every translated function
   with resume points (landing pads, setjmp return sites) runs its body under gd_eh_run; the innermost such frame whose
   entry SP lies above the target SP (for an extra entry point, which may enter a frame an earlier call allocated, also
   equal to it when the pc is one of its resume points) owns the target: it asserts the pc is one of its resume points, installs the
   registers and re-enters its body there. No cost unless something is thrown. */
struct GuestResume { uint64_t sp, pc; CPU regs; };
extern "C" void gd_eh_run_at(CPU* c, void (*body)(CPU*, int), const uint64_t* rp, int n, int e0);
extern "C" void gd_eh_run(CPU* c, void (*body)(CPU*, int), const uint64_t* rp, int n) { gd_eh_run_at(c, body, rp, n, -1); }
/* e0: the body's entry index (-1 the function start; an extra entry point of a function with resume points sits past rp[n-1]) */
extern "C" void gd_eh_run_at(CPU* c, void (*body)(CPU*, int), const uint64_t* rp, int n, int e0) {
  uint64_t sp0 = c->SP; int e = e0;
  for (;;) {
    try { body(c, e); return; }
    catch (GuestResume& r) {
      /* a function start's frame lies below its entry sp (equal sp: the caller's frame, maybe a recursive caller with the
         same resume points); an extra entry may run in a frame made before it, so equal sp is its own at its own pc */
      if (r.sp > sp0 || (r.sp == sp0 && e0 < 0)) throw;
      e = -1;
      for (int i = 0; i < n; i++) if (rp[i] == r.pc) e = i;
      if (e < 0 && r.sp == sp0) throw;
      if (e < 0) die("non-local transfer: target pc is not a resume point of the frame that owns the target SP", r.pc);
      *c = r.regs;
    }
  }
}
extern "C" void gd_jumpto(CPU* c) {                           /* __libunwind_Registers_arm64_jumpto(Registers_arm64*) */
  const uint64_t* g = (const uint64_t*)(uintptr_t)c->X[0];    /* x0..x28 @0, fp @0xe8, lr @0xf0, sp @0xf8, pc @0x100, d0..d31 @0x110 */
  GuestResume r; r.regs = *c;
  for (int i = 0; i < 30; i++) if (i != 16 && i != 17) r.regs.X[i] = g[i];
  r.regs.X[16] = g[31]; r.regs.X[30] = g[32]; r.regs.SP = g[31];   /* the asm restores sp through x16 and returns to lr=pc */
  for (int i = 0; i < 32; i++) { r.regs.V[i].u64[0] = g[34 + i]; r.regs.V[i].u64[1] = 0; }
  r.sp = g[31]; r.pc = g[32];
  throw r;
}
struct TlsRestore { CPU* p; ~TlsRestore() { tls_cur = p; } };   /* a longjmp leaves through the bridge */

/* guest stacks: mmap with a PROT_NONE guard page below (overflow faults instead of corrupting the heap) and a
   pad above the top (variadic bridges read slots past the last argument) */
struct GStack { void* base; size_t len; uint64_t top; int busy; };
static GStack gstack(size_t sz) {
  size_t pg = (size_t)getpagesize(); sz = (sz + pg - 1) & ~(pg - 1);
  size_t len = pg + sz + GD_STACK_PAD;
  void* b = mmap(nullptr, len, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
  if (b == MAP_FAILED) die("guest stack mmap failed", sz);
  mprotect(b, pg, PROT_NONE);
  return GStack{b, len, ((uint64_t)(uintptr_t)b + pg + sz) & ~15ULL, 0};
}
static void gstack_free(GStack s) { if (s.base) munmap(s.base, s.len); }
static pthread_key_t cb_key; static pthread_once_t cb_once = PTHREAD_ONCE_INIT;
static void cb_dtor(void* p) { gstack_free(*(GStack*)p); free(p); }
static void cb_make_key() { pthread_key_create(&cb_key, cb_dtor); }
static GStack* cb_stack() {                                  /* per-thread callback stack for host-owned threads */
  pthread_once(&cb_once, cb_make_key);
  GStack* s = (GStack*)pthread_getspecific(cb_key);
  if (!s) { s = (GStack*)calloc(1, sizeof(GStack)); *s = gstack(GD_CB_STACK); pthread_setspecific(cb_key, s); }
  return s;
}

/* ---- headless UI guard by image: AppKit, Metal, MetalKit, MetalFX, MetalPerformanceShaders (gobjc's class guard and
   gdyld's UI_LIB_RE name the same frameworks) ---- */
#define GD_UI_MARK "blocked window-server / AppKit-UI / GPU entry point (headless translation)"
#ifdef GD_NO_UI_GUARD                                         /* gdyld translate(ui_guard=False): a windowed/GPU test run only */
static const bool GD_UI_GUARD = false;
#else
static const bool GD_UI_GUARD = true;
#endif
static bool ui_image(const char* im) {
  return GD_UI_GUARD && im && (strstr(im, "/AppKit.framework/") || strstr(im, "/Metal.framework/") || strstr(im, "/MetalKit.framework/")
                || strstr(im, "/MetalFX.framework/") || strstr(im, "/MetalPerformanceShaders"));
}
static const char* ui_code(const void* p) {                   /* the UI framework image holding host code p, else null */
  Dl_info di;
  return p && dladdr(p, &di) && ui_image(di.dli_fname) ? di.dli_fname : nullptr;
}

/* ---- address classes the guest can hold as a function pointer ---- */
struct Hnd { void* fn; void (*call)(CPU*, void*); const char* ui; };   /* ui: a UI framework's code: never called, never handed on */
static Hnd HND[GD_MAX_HANDLES]; static int nhnd;              /* handle i lives at GD_HANDLE_BASE + i*GD_HANDLE_SLOT */
static pthread_mutex_t reg_mu = PTHREAD_MUTEX_INITIALIZER;

/* closures: guest code handed to native code as a typed function pointer. Closure i is a machine-code stub made at
   start (movabs r11, &CSLOT[i]; movabs r10, gd_ctramp; jmp r10); gd_ctramp keeps every argument register, pushes the slot
   on a per-thread LIFO and jumps to the slot's typed entry (Pool<F>::entry), which pops it before anything else runs. A
   signal handler running a closure in between pushes and pops its own slot, so the LIFO stays matched. The table is
   shared by every signature: no per-signature cap. Lock-free: a signal handler converts its own handler again
   (signal/sigaction) while it may have interrupted a conversion. */
struct CSlot { void* entry; uint64_t guest; };
static CSlot CSLOT[GD_MAX_CLOSURES]; static int ncslot;
static unsigned char* CSTUB;                                  /* GD_MAX_CLOSURES stubs of CSTUB_SZ bytes, read+execute */
enum { CSTUB_SZ = 32, CLIFO_N = 16 };
static __thread const CSlot* clifo[CLIFO_N]; static __thread int nclifo;
extern "C" void gd_ctramp();
extern "C" void gd_cpush(const CSlot* s) {                    /* reserve, then fill: a nested push lands above */
  int i = nclifo; nclifo = i + 1; __atomic_signal_fence(__ATOMIC_SEQ_CST);
  if (i >= CLIFO_N) die("closure entries nested too deeply on one thread", s->guest);
  clifo[i] = s;
}
static const CSlot* cpop() {
  int i = nclifo - 1; const CSlot* s = clifo[i]; __atomic_signal_fence(__ATOMIC_SEQ_CST); nclifo = i; return s;
}
/* entry rsp = 8 mod 16; 8 pushes + 136 bytes of xmm0-7 -> 0 mod 16 at the call */
asm(R"(
  .text
  .globl _gd_ctramp
  .p2align 4
_gd_ctramp:
  pushq %rdi
  pushq %rsi
  pushq %rdx
  pushq %rcx
  pushq %r8
  pushq %r9
  pushq %rax
  pushq %r11
  subq $136, %rsp
  movaps %xmm0, 0(%rsp)
  movaps %xmm1, 16(%rsp)
  movaps %xmm2, 32(%rsp)
  movaps %xmm3, 48(%rsp)
  movaps %xmm4, 64(%rsp)
  movaps %xmm5, 80(%rsp)
  movaps %xmm6, 96(%rsp)
  movaps %xmm7, 112(%rsp)
  movq %r11, %rdi
  callq _gd_cpush
  movaps 0(%rsp), %xmm0
  movaps 16(%rsp), %xmm1
  movaps 32(%rsp), %xmm2
  movaps 48(%rsp), %xmm3
  movaps 64(%rsp), %xmm4
  movaps 80(%rsp), %xmm5
  movaps 96(%rsp), %xmm6
  movaps 112(%rsp), %xmm7
  addq $136, %rsp
  popq %r11
  popq %rax
  popq %r9
  popq %r8
  popq %rcx
  popq %rdx
  popq %rsi
  popq %rdi
  jmpq *(%r11)
)");
__attribute__((constructor)) static void cstubs_init() {   /* before main and before any embedder of this runtime */
  size_t len = (size_t)GD_MAX_CLOSURES * CSTUB_SZ;
  void* m = mmap(nullptr, len, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
  if (m == MAP_FAILED) die("closure stub mmap failed", len);
  unsigned char* p = (unsigned char*)m;
  for (int i = 0; i < GD_MAX_CLOSURES; i++, p += CSTUB_SZ) {
    uint64_t s = (uint64_t)(uintptr_t)&CSLOT[i], t = (uint64_t)(uintptr_t)&gd_ctramp;
    p[0] = 0x49; p[1] = 0xBB; memcpy(p + 2, &s, 8);           /* movabs r11, slot */
    p[10] = 0x49; p[11] = 0xBA; memcpy(p + 12, &t, 8);        /* movabs r10, gd_ctramp */
    p[20] = 0x41; p[21] = 0xFF; p[22] = 0xE2;                 /* jmp r10 */
    memset(p + 23, 0xCC, CSTUB_SZ - 23);
  }
  if (mprotect(m, len, PROT_READ | PROT_EXEC)) die("closure stub mprotect failed", len);
  CSTUB = (unsigned char*)m;
}
static uint64_t rev_find(uint64_t host) {                     /* closure stub -> its guest target, 0 if not a stub */
  uint64_t o = host - (uint64_t)(uintptr_t)CSTUB;
  if (!CSTUB || o >= (uint64_t)GD_MAX_CLOSURES * CSTUB_SZ || o % CSTUB_SZ) return 0;
  return __atomic_load_n(&CSLOT[o / CSTUB_SZ].guest, __ATOMIC_ACQUIRE);
}
static bool in_guest(uint64_t a) {
  for (int k = 0; k < NIMG; k++) if (a - IMG[k].lo < IMG[k].size) return true;
  return false;
}
static bool guest_fn_start(uint64_t a) {
  for (int k = 0; k < NIMG; k++) if (a - IMG[k].lo < IMG[k].size) return IMG[k].lookup(a - IMG[k].slide) != nullptr;
  return false;
}
static int import_slot(uint64_t a) {                          /* import index or -1 */
  return a >= GD_IMPORT_BASE && a < GD_IMPORT_BASE + (uint64_t)NIMP * GD_IMP_SLOT && (a - GD_IMPORT_BASE) % GD_IMP_SLOT == 0
         ? (int)((a - GD_IMPORT_BASE) / GD_IMP_SLOT) : -1;
}
static int handle_index(uint64_t a) {                         /* handle index or -1 */
  uint64_t i = (a - GD_HANDLE_BASE) / GD_HANDLE_SLOT;
  return a >= GD_HANDLE_BASE && (a - GD_HANDLE_BASE) % GD_HANDLE_SLOT == 0 && i < (uint64_t)__atomic_load_n(&nhnd, __ATOMIC_ACQUIRE)
         ? (int)i : -1;
}
static bool guest_code(uint64_t a) { return guest_fn_start(a) || import_slot(a) >= 0 || handle_index(a) >= 0; }
static void gobjc_hostify(uint64_t blk);                      /* gobjc.hpp: a guest block made callable by native code */
static bool gobjc_guest_block(uint64_t b);                    /* gobjc.hpp: b is a block whose invoke is guest code */
static uint64_t gobjc_target(uint64_t code);                  /* gobjc.hpp: libffi closure -> its guest code, else 0 */
[[noreturn]] static void gobjc_boundary_throw();              /* gobjc.hpp: a sentinel-claimed exception leaves as a host one */
/* Every guest stack segment (callback, thread, main) starts with lr = GD_SENTINEL, a pc with synthetic unwind info
   (gobjc.hpp sent_init): CFA and return address come from a record at entry sp + GD_ARGS + GD_COPY, so a C++ exception
   walks on into the guest caller's frames, while its personality claims ObjC exceptions for the host side. */
static const uint64_t GD_SENTINEL = GD_HANDLE_BASE - 64;
static void seg_start(CPU* c, uint64_t top, uint64_t cfa, uint64_t ra) {   /* sp below the record, lr = sentinel */
  c->SP = (top - GD_ARGS - GD_COPY) & ~15ULL;
  uint64_t* r = (uint64_t*)(uintptr_t)(c->SP + GD_ARGS + GD_COPY);
  r[0] = cfa ? cfa : c->SP + GD_ARGS + GD_COPY + 16; r[1] = ra;
  c->X[30] = GD_SENTINEL;
}
/* After a segment's guest code returns: c->unw (recompile GD_RC) is a return the guest made past its host call sites; at
   a segment boundary only a return to the segment's own lr (the sentinel) is one. Anything else has no host frame left. */
static void guest_returned(CPU* c) {
  if (c->unw && c->unw != GD_SENTINEL) die("guest returned to an address that is no pending call site on this thread", c->unw);
  c->unw = 0;
}
static uint64_t handle_of(void* fn, void (*call)(CPU*, void*)) {   /* call == nullptr: untyped (refuses to be called) */
  pthread_mutex_lock(&reg_mu);
  int n = nhnd, i = 0;
  while (i < n && !(HND[i].fn == fn && (!call || !HND[i].call || HND[i].call == call))) i++;
  if (i == n) {
    if (n == GD_MAX_HANDLES) die("host function handle table full", (uint64_t)(uintptr_t)fn);
    HND[n].fn = fn; HND[n].ui = ui_code(fn);
    __atomic_store_n(&HND[n].call, call, __ATOMIC_RELEASE); __atomic_store_n(&nhnd, n + 1, __ATOMIC_RELEASE);
  } else if (call && !HND[i].call) __atomic_store_n(&HND[i].call, call, __ATOMIC_RELEASE);   /* typed after an untyped dlsym */
  pthread_mutex_unlock(&reg_mu);
  return GD_HANDLE_BASE + (uint64_t)i * GD_HANDLE_SLOT;
}
static uint64_t code_to_guest(uint64_t v, void (*call)(CPU*, void*)) {   /* host code address -> guest-held value */
  if (v < 4096 || v > ~4095ULL) return v;                     /* NULL, SIG_DFL/SIG_IGN/SIG_HOLD/SIG_ERR sentinels */
  if (uint64_t g = rev_find(v)) return g;                     /* one of our closures: the original guest address */
  if (uint64_t g = gobjc_target(v)) return g;                 /* a typed ObjC method or block closure */
  for (int k = 0; k < NIMP; k++)                              /* an import: the guest's own pointer to it */
    if (ENT[k].hostfn && (uint64_t)(uintptr_t)ENT[k].hostfn == v) return GD_IMPORT_BASE + (uint64_t)k * GD_IMP_SLOT;
  return handle_of((void*)(uintptr_t)v, call);
}
/* 1 if p lies in an instruction section of a loaded image. By section, not segment: an executable __TEXT segment also
   holds data (__const, __cstring, Swift descriptors such as protocol requirements bases '...TL'). */
static int host_code(const void* p) {
  Dl_info di;
  if (!p || !dladdr(p, &di) || !di.dli_fbase) return 0;
  const mach_header_64* mh = (const mach_header_64*)di.dli_fbase;
  uint64_t slide = 0; const uint8_t* lc = (const uint8_t*)(mh + 1); int code = 0;
  for (uint32_t i = 0; i < mh->ncmds; i++, lc += ((const load_command*)lc)->cmdsize) {
    const segment_command_64* s = (const segment_command_64*)lc;
    if (s->cmd == LC_SEGMENT_64 && !strcmp(s->segname, "__TEXT")) slide = (uint64_t)(uintptr_t)mh - s->vmaddr;
  }
  lc = (const uint8_t*)(mh + 1);
  for (uint32_t i = 0; i < mh->ncmds; i++, lc += ((const load_command*)lc)->cmdsize) {
    const segment_command_64* s = (const segment_command_64*)lc;
    if (s->cmd != LC_SEGMENT_64 || !(s->initprot & VM_PROT_EXECUTE) || (uint64_t)(uintptr_t)p - (s->vmaddr + slide) >= s->vmsize) continue;
    const section_64* sc = (const section_64*)(s + 1);
    for (uint32_t j = 0; j < s->nsects; j++)
      if ((uint64_t)(uintptr_t)p - (sc[j].addr + slide) < sc[j].size)
        code = (sc[j].flags & (S_ATTR_PURE_INSTRUCTIONS | S_ATTR_SOME_INSTRUCTIONS)) != 0;
  }
  return code;
}

namespace gd {
template<class T> T&& declval();
template<int... I> struct Seq {};
template<class T, T... I> struct ISeq { using type = Seq<(int)I...>; };
template<int N> using MakeSeq = typename __make_integer_seq<ISeq, int, N>::type;
template<class T> struct rcv { using t = T; };
template<class T> struct rcv<const T> { using t = T; };
template<class T> struct rcv<volatile T> { using t = T; };
template<class T> struct rcv<const volatile T> { using t = T; };
template<class T> struct rmp { using t = void; };
template<class T> struct rmp<T*> { using t = typename rcv<T>::t; };
template<class T> struct decay_arr { using t = T; };
template<class T, unsigned long N> struct decay_arr<T[N]> { using t = T*; };
using VaPtr = decay_arr<__builtin_va_list>::t;                /* x86-64 va_list as a parameter: never a guest va_list */

template<class F> struct fnp { static constexpr bool v = false, plain = false; };
template<class R, class... A> struct fnp<R (*)(A...)> { static constexpr bool v = true, plain = true; };
template<class R, class... A> struct fnp<R (*)(A...) noexcept> { static constexpr bool v = true, plain = false; };
template<class R, class... A> struct fnp<R (*)(A..., ...)> { static constexpr bool v = true, plain = false; };
template<class R, class... A> struct fnp<R (*)(A..., ...) noexcept> { static constexpr bool v = true, plain = false; };
template<class R, class... A> struct fnp<__attribute__((noreturn)) R (*)(A...)> { static constexpr bool v = true, plain = true; };
template<class R, class... A> struct fnp<__attribute__((noreturn)) R (*)(A..., ...)> { static constexpr bool v = true, plain = false; };
/* fx<T>::t: T without a function effect. Core Audio's CA_REALTIME_API marks render callbacks (AURenderCallback) and realtime
   functions (AudioUnitSetParameter) [[clang::nonblocking]], a distinct function-pointer type that the patterns above miss:
   such a field would reach native code as raw guest code, such an import would refuse to decompose. The effect changes
   no calling convention, so they are bridged as their plain type and cast back. */
template<class T> struct fx { using t = T; };
#if __has_attribute(nonblocking)
template<class R, class... A> struct fx<R (*)(A...) [[clang::nonblocking]]> { using t = R (*)(A...); };
template<class R, class... A> struct fnp<R (*)(A...) [[clang::nonblocking]]> { static constexpr bool v = true, plain = true; };
#endif
template<class T> struct blk { static constexpr bool v = false; };
#if __has_extension(blocks)
template<class R, class... A> struct blk<R (^)(A...)> { static constexpr bool v = true; };
#endif
template<class T> struct arr { static constexpr bool v = false; };
template<class U, unsigned long N> struct arr<U[N]> { static constexpr bool v = true; using e = U; static constexpr int n = (int)N; };
template<class T> struct arrp { static constexpr bool v = false; };    /* dump_struct hands array fields over as E (*)[N] */
template<class E, unsigned long N> struct arrp<E (*)[N]> { static constexpr bool v = true; using e = E; static constexpr int n = (int)N; };
template<class T> struct bptr { static constexpr bool v = false; };    /* and block fields as their address, B* */
template<class B> struct bptr<B*> { static constexpr bool v = blk<typename rcv<B>::t>::v; };
template<class T, class = void> struct subscr { static constexpr bool v = false; };
template<class T> struct subscr<T, decltype((void)declval<T&>()[0])> { static constexpr bool v = true; };
template<class T> constexpr bool is_vec() { return !__is_class(T) && !__is_union(T) && !__is_pointer(T) && !__is_array(T) && subscr<T>::v; }
template<class T, class = void> struct complete { static constexpr bool v = false; };
template<class T> struct complete<T, decltype((void)sizeof(T))> { static constexpr bool v = true; };
template<class T> constexpr bool is_rec() { return __is_class(T) || __is_union(T); }

/* ---- record layout, read through __builtin_dump_struct during constant evaluation ----
   Rec: HFA/HVA base size and member count (vectors flagged), not-homogeneous, holds a code pointer, holds a long
   double. Members add up in a struct and take the maximum in a union; a block is a union when its second member
   starts at its first member's address. A member count that does not fill sizeof(T) means padding: not an HFA. */
struct Rec { int base, n; bool vec, bad, code, ldbl; };
constexpr Rec RBAD{0, 0, false, true, false, false};
constexpr bool streq(const char* a, const char* b) { while (*a && *a == *b) { a++; b++; } return *a == *b; }
template<class T> constexpr const void* addr_of(const T& a) { if constexpr (arrp<T>::v) return (const void*)a; else return (const void*)&a; }
template<class T> constexpr const T& lastv(const T& t) { return t; }
template<class T, class... R> constexpr decltype(auto) lastv(const T&, const R&... r) { return lastv(r...); }
template<class T> constexpr Rec rec_calc();
template<class T> inline constexpr Rec REC = rec_calc<T>();
template<class T> constexpr Rec leaf();
template<class T> constexpr bool ct_rec();
template<class T> Rec rec_rt();
template<class E> constexpr Rec elem() {                      /* one array element: a record, a nested array or a leaf */
  if constexpr (arr<E>::v) { Rec e = elem<typename rcv<typename arr<E>::e>::t>(); e.n *= arr<E>::n; return e; }
  else if constexpr (is_rec<E>() && ct_rec<E>()) return REC<E>;
  else if constexpr (is_rec<E>()) {                           /* non-literal element: only the run-time walk can list it */
    if (__builtin_is_constant_evaluated()) return RBAD;
    return rec_rt<E>();
  } else return leaf<E>();
}
template<class T> constexpr Rec leaf() {
  if constexpr (__is_same(T, float)) return Rec{4, 1, false, false, false, false};
  else if constexpr (__is_same(T, double)) return Rec{8, 1, false, false, false, false};
  else if constexpr (__is_same(T, long double)) return Rec{0, 0, false, true, false, true};
  else if constexpr (fnp<T>::v || blk<T>::v || bptr<T>::v) return Rec{0, 0, false, true, true, false};
  else if constexpr (is_vec<T>()) return sizeof(T) == 8 || sizeof(T) == 16 ? Rec{(int)sizeof(T), 1, true, false, false, false} : RBAD;
  else if constexpr (arrp<T>::v) {
    Rec e = elem<typename rcv<typename arrp<T>::e>::t>(); e.n *= arrp<T>::n; e.bad = e.bad || arrp<T>::n == 0; return e;
  } else return RBAD;
}
struct Fr { const void* start; int n, kids; bool uni; Rec r; };
struct Walk {
  Fr st[32]; int d = 0; Rec top = RBAD;
  constexpr void add(Rec r, const void* s) {
    Fr& f = st[d - 1];
    f.r.code = f.r.code || r.code; f.r.ldbl = f.r.ldbl || r.ldbl; f.r.bad = f.r.bad || r.bad;
    if (r.n > 0 && !f.r.base) { f.r.base = r.base; f.r.vec = r.vec; }
    else if (r.n > 0 && (f.r.base != r.base || f.r.vec != r.vec)) f.r.bad = true;
    if (!s) return;                                           /* bit-field or member without storage */
    if (f.kids == 0) { f.start = s; f.n = r.n; }
    else if (f.kids == 1 && s == f.start) { f.uni = true; f.n = f.n > r.n ? f.n : r.n; }
    else f.n = f.uni ? (f.n > r.n ? f.n : r.n) : f.n + r.n;
    f.kids++;
  }
  template<class... A> constexpr int operator()(const char* fmt, const A&... a) {
    if (streq(fmt, " {\n")) { st[d++] = Fr{nullptr, 0, 0, false, Rec{0, 0, false, false, false, false}}; return 0; }
    if (streq(fmt, "%s}\n") || streq(fmt, "}\n")) {
      Fr f = st[--d]; Rec r = f.r; r.n = f.n;
      if (d) add(r, f.start); else top = r;
      return 0;
    }
    if constexpr (sizeof...(A) == 4) add(leaf<typename rcv<__type_pack_element<3, A...>>::t>(), addr_of(lastv(a...)));
    else if constexpr (sizeof...(A) == 5) add(RBAD, nullptr);   /* bit-field: name, width, value */
    return 0;
  }
};
/* a record whose layout can be walked at compile time (`T x{}` in a constant expression); any other one is KCLS */
template<class T> constexpr bool ct_rec() {
  return __is_literal_type(T) && !__is_polymorphic(T) && __is_constructible(T) && __is_destructible(T);
}
template<class T> constexpr Rec rec_calc() {
  if constexpr (!ct_rec<T>()) return RBAD;
  else {
    T x{}; Walk w{};
    __builtin_dump_struct(&x, w);
    Rec r = w.top;
    r.bad = r.bad || r.n < 1 || r.n > 4 || !r.base || (int)sizeof(T) != r.n * r.base;
    return r;
  }
}
/* the same walk at run time for a class that is not a literal type (constructors, e.g. v8::Local): AAPCS64 HFA-ness
   ignores constructors and access, so the fields of raw storage are listed (no constructor runs). Computed once. */
template<class T> Rec rec_rt() {
  static const Rec r = [] {
    alignas(T) unsigned char b[sizeof(T)] = {};
    Walk w{};
    __builtin_dump_struct(reinterpret_cast<T*>(b), w);
    Rec x = w.top;
    x.bad = x.bad || x.n < 1 || x.n > 4 || !x.base || (int)sizeof(T) != x.n * x.base;
    return x;
  }();
  return r;
}

struct Hfa { int base, n; };
template<class T> constexpr Hfa hfa() {
  if constexpr (is_vec<T>()) return Hfa{(int)sizeof(T), 1};
  else return Hfa{REC<T>.base, REC<T>.n};
}

/* Itanium "non-trivial for the purpose of calls" (unique_ptr, shared_ptr): passed as a pointer to a caller-owned
   temporary, returned through x8 / the hidden pointer, on both arches. Trivial for calls: a trivial destructor, every
   callable copy/move constructor trivial, at least one callable (all deleted: non-trivial). ponytail: "callable" is
   overload resolution, so an inaccessible constructor counts as deleted outside -fno-access-control builds. */
template<class T> constexpr bool trivial_for_calls() {
  constexpr bool cc = __is_constructible(T, const T&), mc = __is_constructible(T, T&&);
  return __is_trivially_destructible(T) && (cc || mc) && (!cc || __is_trivially_constructible(T, const T&))
         && (!mc || __is_trivially_constructible(T, T&&));
}
/* KEMPTY: an empty record, which Apple arm64 ignores as a parameter and as a return value (no register, no slot).
   KCLS: a trivially copyable record that is not a literal type, classified at run time (rec_rt). KNTRIV: non-trivial
   for calls, crosses as the address of the caller's object. */
enum { KVOID, KINT, KF32, KF64, KF80, KHFA, KSMALL, KBIG, KFNPTR, KPTR, KEMPTY, KCLS, KNTRIV, KBLK, KBAD };
template<class T> constexpr int kind() {
  if constexpr (__is_same(T, void)) return KVOID;
  else if constexpr (blk<T>::v) return KBLK;                  /* block pointer: a guest block is made host-callable */
  else if constexpr (__is_same(T, float)) return KF32;
  else if constexpr (__is_same(T, double)) return KF64;
  else if constexpr (__is_same(T, long double)) return KF80;
  else if constexpr (__is_same(T, VaPtr)) return KBAD;
  else if constexpr (fnp<T>::v) return KFNPTR;
  else if constexpr (__is_pointer(T) || __is_same(T, decltype(nullptr))) return KPTR;
  else if constexpr ((__is_integral(T) || __is_enum(T)) && sizeof(T) <= 8) return KINT;
  else if constexpr (is_vec<T>()) return sizeof(T) == 8 || sizeof(T) == 16 ? KHFA : KBAD;   /* short vector: one V register */
  else if constexpr (is_rec<T>() && !trivial_for_calls<T>()) return KNTRIV;
  else if constexpr (is_rec<T>() && __is_empty(T)) return KEMPTY;
  else if constexpr (is_rec<T>() && !ct_rec<T>()) return KCLS;
  else if constexpr (is_rec<T>()) return REC<T>.ldbl ? KBAD : !REC<T>.bad ? KHFA : sizeof(T) <= 16 ? KSMALL : KBIG;
  else return KBAD;                                           /* block pointers, long vectors, __int128, _Complex */
}

template<class T> struct is_ref { static constexpr bool v = false; };
template<class T> struct is_ref<T&> { static constexpr bool v = true; };
template<class T> struct is_ref<T&&> { static constexpr bool v = true; };
template<class T> struct deref { using t = T; };
template<class T> struct deref<T&> { using t = T; };
template<class T> struct deref<T&&> { using t = T; };
template<bool B, class X, class Y> struct cond { using t = X; };
template<class X, class Y> struct cond<false, X, Y> { using t = Y; };
/* link-time check: long double reached through memory (a pointer or a C++ reference) has two layouts (guest 8-byte
   double, host 80-bit x87), also inside the signature of a callback parameter (the host would hand the guest an x87
   value, or read one back). Non-literal classes have no compile-time walk: ldbl_rt checks them on first use. */
template<class F> struct LdSig;
template<class T> constexpr bool ldbl_mem() {
  if constexpr (is_ref<T>::v) return ldbl_mem<typename deref<T>::t*>();   /* a reference is the object's address */
  else {
  using U = typename rcv<T>::t;
  using P = typename rmp<U>::t;
  if constexpr (fnp<U>::v) return LdSig<U>::v;
  else if constexpr (__is_pointer(U) && __is_same(P, long double)) return true;
  else if constexpr (__is_pointer(U) && is_rec<P>() && complete<P>::v) return REC<P>.ldbl;
  else if constexpr (is_rec<U>()) return REC<U>.ldbl;
  else return false;
  }
}
template<class F> struct LdSig { static constexpr bool v = false; };
template<class R, class... A> struct LdSig<R (*)(A...)> { static constexpr bool v = (ldbl_mem<R>() || ... || ldbl_mem<A>()); };
template<class R, class... A> struct LdSig<R (*)(A..., ...)> : LdSig<R (*)(A...)> {};
template<class R, class... A> struct LdSig<R (*)(A...) noexcept> : LdSig<R (*)(A...)> {};
template<class R, class... A> struct LdSig<R (*)(A..., ...) noexcept> : LdSig<R (*)(A...)> {};
template<class R, class... A> struct LdSig<__attribute__((noreturn)) R (*)(A...)> : LdSig<R (*)(A...)> {};
template<class R, class... A> struct LdSig<__attribute__((noreturn)) R (*)(A..., ...)> : LdSig<R (*)(A...)> {};
#if __has_attribute(nonblocking)
template<class R, class... A> struct LdSig<R (*)(A...) [[clang::nonblocking]]> : LdSig<R (*)(A...)> {};
#endif

template<class T> uint64_t to_u64(T v) {
  if constexpr (__is_enum(T)) return to_u64<__underlying_type(T)>((__underlying_type(T))v);
  else if constexpr (__is_same(T, decltype(nullptr))) return 0;
  else if constexpr (__is_pointer(T) || fnp<T>::v) return (uint64_t)reinterpret_cast<uintptr_t>(v);
  else if constexpr (__is_signed(T)) return (uint64_t)(int64_t)v;
  else return (uint64_t)v;
}

/* ---- structs with code-pointer fields handed to the host (CFArrayCallBacks, CFRunLoopTimerContext, FTS, FILE) ----
   Native code cannot run guest code, and the guest's own storage is never converted for it: it may be read-only, shared
   by other threads, or freed by the call. A struct passed by pointer whose code fields hold guest code reaches the host as
   its shadow: a copy with those fields as typed closures of their declared types, one shadow per guest address and type,
   from an arena that is never freed (native free() refuses it loudly). Shadow and guest struct are synchronized at every
   boundary crossing of the calling thread (the call, each guest callback it makes, that callback's return): guest edits
   reach the shadow, and only bytes native code changed in the shadow reach the guest, code fields as the guest's own
   values (a guest address stays one). Any other struct is passed as is (FTS, FILE: host objects); after the call, code
   fields native code changed read as guest values only in memory the call cannot free and the host does not own: a guest
   image or the calling thread's guest stack. A by-value struct is converted in its own copy. A code field sharing storage
   with another member (a union) that holds guest code stops loudly: no single type to convert it with. */
template<class T> T to_host_fn(uint64_t g);
template<class T> uint64_t to_guest_fn(T p);
static const char* imp_name(int k) { return k >= 0 ? ENT[k].name : "(host function pointer)"; }
enum { CODE_MAX = 64, LEAF_MAX = 1024 };
struct CodeF { unsigned off; bool blk, shared; uint64_t (*mk)(uint64_t); uint64_t (*back)(uint64_t); };
struct CodeLay { unsigned size; int n; CodeF f[CODE_MAX]; signed char* cm; };   /* cm[i]: the code field starting at byte i, or -1 */
template<class U> uint64_t mk_fn(uint64_t g) { return to_u64(to_host_fn<U>(g)); }
template<class U> uint64_t back_fn(uint64_t h) { return to_guest_fn<U>(reinterpret_cast<U>((uintptr_t)h)); }
template<class V> constexpr bool code_rec() { if constexpr (is_rec<V>()) return REC<V>.code; else return false; }
template<class V> constexpr bool has_code() {                 /* a code pointer, block, or a record or array holding one */
  if constexpr (arr<V>::v) return has_code<typename rcv<typename arr<V>::e>::t>();
  else return fnp<V>::v || blk<V>::v || code_rec<V>();
}
struct LayW {                                                 /* the leaves of a record, as dump_struct lists them */
  const char* base; CodeLay* lay; unsigned size, lo[LEAF_MAX], hi[LEAF_MAX]; int nl = 0;
  void leaf(const void* p, unsigned sz) {
    if ((const char*)p < base || (const char*)p >= base + size) return;   /* a value dump_struct copied (a vector...): no storage */
    if (nl == LEAF_MAX) die("a struct with code-pointer fields and more than 1024 members reaches the host", sz);
    lo[nl] = (unsigned)((const char*)p - base); hi[nl++] = (unsigned)((const char*)p - base) + sz;
  }
  template<class E> void el(const E& e) {
    using U = typename rcv<E>::t;
    if constexpr (arr<U>::v) {                                /* elements holding code one by one, any other array one leaf */
      if constexpr (has_code<U>()) { for (int i = 0; i < arr<U>::n; i++) el(e[i]); }
      else leaf(&e, sizeof(U));
    }
    else if constexpr (code_rec<U>()) __builtin_dump_struct(&e, *this);
    else if constexpr (fnp<U>::v || blk<U>::v) {
      if (lay->n == CODE_MAX) die("a struct with more than 64 code-pointer fields reaches the host", sizeof(U));
      CodeF& f = lay->f[lay->n++];
      f.off = (unsigned)((const char*)&e - base); f.blk = blk<U>::v; f.shared = false;
      if constexpr (fnp<U>::v) { f.mk = &mk_fn<U>; f.back = &back_fn<U>; } else { f.mk = nullptr; f.back = nullptr; }
      leaf(&e, 8);
    } else leaf(&e, sizeof(U));
  }
  template<class... A> int operator()(const char*, const A&... a) {
    if constexpr (sizeof...(A) == 4) {
      using L = typename rcv<__type_pack_element<3, A...>>::t;
      if constexpr (arrp<L>::v || bptr<L>::v) el(*lastv(a...)); else el(lastv(a...));
    }
    return 0;
  }
};
/* the code fields of Q, walked once over zeroed storage; a code field is shared when any other member overlaps it */
template<class Q> const CodeLay& code_lay() {
  static const CodeLay* lay = [] {
    alignas(Q) static unsigned char raw[sizeof(Q)];
    CodeLay* L = (CodeLay*)calloc(1, sizeof(CodeLay));
    LayW* w = (LayW*)calloc(1, sizeof(LayW));
    w->base = (const char*)raw; w->lay = L; w->size = sizeof(Q);
    __builtin_dump_struct(reinterpret_cast<const Q*>(raw), *w);
    L->size = sizeof(Q);
    L->cm = (signed char*)malloc(sizeof(Q));
    memset(L->cm, -1, sizeof(Q));
    for (int i = L->n - 1; i >= 0; i--) {
      L->cm[L->f[i].off] = (signed char)i;
      int over = 0;
      for (int j = 0; j < w->nl; j++) over += w->lo[j] < L->f[i].off + 8 && L->f[i].off < w->hi[j];
      L->f[i].shared = over > 1;                              /* its own leaf is one */
    }
    free(w);
    return L;
  }();
  return *lay;
}
static uint64_t rd8(const void* p) { uint64_t v; memcpy(&v, p, 8); return v; }
static void wr8(void* p, uint64_t v) { memcpy(p, &v, 8); }  /* one 8-byte store: a racing reader sees the old or the new value */
[[noreturn]] static void union_stop(int k) {
  die_name("a struct handed to the host holds guest code in a function pointer that shares storage (a union): no single type "
           "to convert it with", imp_name(k));
}
static uint64_t code_in(const CodeF& f, uint64_t v, int k) {  /* a guest code-field value as native code may see it */
  if (f.shared) { if (guest_code(v) || (f.blk && gobjc_guest_block(v))) union_stop(k); return v; }
  if (f.blk) { if (v) gobjc_hostify(v); return v; }
  return guest_code(v) ? f.mk(v) : v;
}
static uint64_t code_out(const CodeF& f, uint64_t v) {        /* native's code-field value as the guest's own */
  return f.blk || v < 4096 || in_guest(v) || guest_code(v) ? v : f.back(v);
}
template<class T> void conv_local(T* v, int k) {              /* a by-value struct: its own copy is converted */
  if constexpr (is_rec<T>() && complete<T>::v) {
    if constexpr (__is_literal_type(T) && REC<T>.code) {
      const CodeLay& L = code_lay<T>();
      for (int i = 0; i < L.n; i++) wr8((char*)v + L.f[i].off, code_in(L.f[i], rd8((const char*)v + L.f[i].off), k));
    }
  }
}
struct Shadow { uint64_t g; const CodeLay* lay; unsigned char *s, *r; Shadow* next; };   /* s: native's copy, r: guest bytes last synced */
struct Bind { Shadow* sh; unsigned char* bl; bool out; int k; Bind* next; };   /* a shadow argument of a host call in flight; bl: the
                                                                                 shadow as last synced, a difference is native's write */
static pthread_mutex_t sh_mu = PTHREAD_MUTEX_INITIALIZER;   /* ponytail: one lock for every shadow; per-shadow locks if callbacks contend */
static Shadow* sh_tab[4096];
static unsigned char *sh_next, *sh_end;
static uint64_t sh_lo[256], sh_hi[256]; static int nsh_chunk;   /* the arena's chunks, for unshadow */
static __thread Bind* tls_binds;
static __thread bool tls_bsync;                               /* sh_mu is held on this thread: a signal handler's closure skips the sync */
static __thread uint64_t tls_stk_lo, tls_stk_hi;              /* the calling thread's guest stack */
static unsigned char* sh_alloc(size_t n) {                    /* sh_mu held */
  n = (n + 15) & ~(size_t)15;
  if (!sh_next || sh_next + n > sh_end) {
    size_t len = n > (1u << 20) ? n : (1u << 20);
    void* m = mmap(nullptr, len, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (m == MAP_FAILED || nsh_chunk == 256) die("struct shadow arena exhausted", len);
    sh_next = (unsigned char*)m; sh_end = sh_next + len;
    sh_lo[nsh_chunk] = (uint64_t)(uintptr_t)m; sh_hi[nsh_chunk] = sh_lo[nsh_chunk] + len;
    __atomic_store_n(&nsh_chunk, nsh_chunk + 1, __ATOMIC_RELEASE);
  }
  unsigned char* p = sh_next; sh_next += n; return p;
}
/* units: a code field (8 bytes, converted) or one byte */
static void sync_in(Shadow* sh, unsigned char* bl, bool fresh, int k) {   /* guest -> shadow; sh_mu held */
  const CodeLay& L = *sh->lay; const unsigned char* g = (const unsigned char*)(uintptr_t)sh->g;
  for (unsigned i = 0; i < L.size;) {
    int c = L.cm[i]; unsigned w = c >= 0 ? 8 : 1;
    if (fresh || memcmp(g + i, sh->r + i, w)) {
      memcpy(sh->r + i, g + i, w);
      if (c >= 0) { uint64_t v = code_in(L.f[c], rd8(g + i), k); if (rd8(sh->s + i) != v) wr8(sh->s + i, v); }
      else sh->s[i] = g[i];
      if (bl) memcpy(bl + i, sh->s + i, w);
    }
    i += w;
  }
}
static void write_back(Bind* b) {                             /* shadow -> guest: native's writes only; sh_mu held */
  Shadow* sh = b->sh; const CodeLay& L = *sh->lay; unsigned char* g = (unsigned char*)(uintptr_t)sh->g;
  for (unsigned i = 0; i < L.size;) {
    int c = L.cm[i]; unsigned w = c >= 0 ? 8 : 1;
    if (memcmp(sh->s + i, b->bl + i, w)) {
      memcpy(b->bl + i, sh->s + i, w);
      if (c >= 0) wr8(g + i, code_out(L.f[c], rd8(sh->s + i))); else g[i] = sh->s[i];
      memcpy(sh->r + i, g + i, w);
    }
    i += w;
  }
}
static Shadow* shadow_of(uint64_t g, const CodeLay* lay, bool* fresh) {   /* sh_mu held */
  unsigned h = (unsigned)((g * 0x9E3779B97F4A7C15ULL) >> 52) & 4095;
  for (Shadow* s = sh_tab[h]; s; s = s->next) if (s->g == g && s->lay == lay) { *fresh = false; return s; }
  Shadow* s = (Shadow*)sh_alloc(sizeof(Shadow) + 2 * (size_t)lay->size + 16);
  s->s = (unsigned char*)s + ((sizeof(Shadow) + 15) & ~(size_t)15); s->r = s->s + lay->size;
  s->g = g; s->lay = lay; s->next = sh_tab[h]; sh_tab[h] = s; *fresh = true;
  return s;
}
/* a shadow address native code hands to guest code (a callback's argument, a result) -> the guest's own struct */
static uint64_t unshadow(uint64_t v) {
  for (int i = 0, n = __atomic_load_n(&nsh_chunk, __ATOMIC_ACQUIRE); i < n; i++)
    if (v - sh_lo[i] < sh_hi[i] - sh_lo[i]) {
      pthread_mutex_lock(&sh_mu);
      uint64_t g = v;
      for (int h = 0; h < 4096 && g == v; h++)
        for (Shadow* s = sh_tab[h]; s; s = s->next) if (v - (uint64_t)(uintptr_t)s->s < s->lay->size) { g = s->g + (v - (uint64_t)(uintptr_t)s->s); break; }
      pthread_mutex_unlock(&sh_mu);                           /* ponytail: a table walk per shadow pointer; index by address if hot */
      return g;
    }
  return v;
}
struct ShLock {                                               /* sh_mu for one sync on this thread */
  ShLock() { pthread_mutex_lock(&sh_mu); tls_bsync = true; }
  ~ShLock() { tls_bsync = false; pthread_mutex_unlock(&sh_mu); }
};
static void binds_out() {                                     /* host -> guest crossing: native's writes so far reach the guest */
  if (!tls_binds || tls_bsync) return;
  ShLock l;
  for (Bind* b = tls_binds; b; b = b->next) if (b->out) write_back(b);
}
/* guest -> host crossing: the guest's edits reach the shadows. ponytail: a guest struct the guest itself frees in a callback
   of the very call it was passed to is read once more here; hook the guest's free() if that ever happens */
static void binds_in() {
  if (!tls_binds || tls_bsync) return;
  ShLock l;
  for (Bind* b = tls_binds; b; b = b->next) sync_in(b->sh, b->bl, false, b->k);
}
static bool guest_owned(uint64_t p, unsigned n) {             /* memory a host call cannot free and the host does not own */
  return in_guest(p) || (p >= tls_stk_lo && p + n <= tls_stk_hi);
}
/* ---- guest (AAPCS64, Apple stack packing) -> host: read arguments, write the return value ----
   Apple arm64: a 16-byte-aligned aggregate may start in an odd x register (standard AAPCS64 rounds up to even);
   on the stack it is 16-byte aligned. HFA/HVA records (structs and unions) and short vectors go in v registers. */
struct Rd { CPU* c; int g, v; uint64_t sa; int k; };
static inline uint64_t rd_stk(Rd& r, uint64_t size, uint64_t align) {
  r.sa = (r.sa + align - 1) & ~(align - 1); uint64_t a = r.sa; r.sa += size; return a;
}
static uint64_t rd_x(Rd& r) {
  uint64_t v;
  if (r.g < 8) v = r.c->X[r.g++]; else memcpy(&v, (void*)(uintptr_t)rd_stk(r, 8, 8), 8);
  return v;
}
/* one aggregate: an HFA/HVA (h.n > 0) in v registers, up to 16 bytes in x registers, larger ones by reference */
static void rd_agg(Rd& r, void* d, unsigned long sz, unsigned long al, Hfa h) {
  if (h.n > 0) {
    if (r.v + h.n <= 8) { for (int i = 0; i < h.n; i++) memcpy((char*)d + i * h.base, &r.c->V[r.v + i], h.base); r.v += h.n; }
    else { r.v = 8; memcpy(d, (void*)(uintptr_t)rd_stk(r, sz, al), sz); }
  } else if (sz <= 16) {
    int n = (int)((sz + 7) / 8);
    if (r.g + n <= 8) { memcpy(d, &r.c->X[r.g], sz); r.g += n; }
    else { r.g = 8; memcpy(d, (void*)(uintptr_t)rd_stk(r, n * 8, al > 8 ? 16 : 8), sz); }
  } else memcpy(d, (void*)(uintptr_t)rd_x(r), sz);
}
static Hfa hfa_rt(const Rec& r, unsigned long sz) {          /* run-time class (KCLS) */
  if (r.ldbl) die("a C++ class holding a long double crosses the boundary (guest 64-bit, host 80-bit x87); size", sz);
  return r.bad ? Hfa{0, 0} : Hfa{r.base, r.n};
}
/* run-time half of the long double check (LdSig): a non-literal class reached by address (pointer, reference,
   non-trivial value) is walked once, on its bridge's first call or its closure's creation */
template<class T> void ldbl_rt() {
  using U = typename rcv<typename deref<T>::t>::t;
  using P = typename cond<__is_pointer(U), typename rmp<U>::t, U>::t;
  if constexpr (is_rec<P>() && complete<P>::v)                /* nested: an incomplete P never reaches the traits */
    if constexpr (!ct_rec<P>() && (is_ref<T>::v || __is_pointer(U) || kind<U>() == KNTRIV))
      if (rec_rt<P>().ldbl) die("a C++ class holding a long double crosses the boundary by address (guest 64-bit, host 80-bit x87); size", sizeof(P));
}
/* a guest object of an abstract class (a host interface) handed to native code must already carry a patched vtable
   (GD_VTABS): an unpatched one would make native code jump to a guest address, so stop here instead */
static void chk_vptr(uint64_t o) {
  if (!o) return;
  uint64_t vp = *(const uint64_t*)(uintptr_t)o;
  if (!in_guest(vp)) return;                                  /* native object */
  uint64_t s0 = *(const uint64_t*)(uintptr_t)vp;
  if (in_guest(s0) || s0 - GD_IMPORT_BASE < (uint64_t)NIMP * GD_IMP_SLOT) die("guest object with an unpatched vtable passed to native code; vptr", vp);
}
template<class T, class = void> struct abs_ptr { static constexpr bool v = false; };
template<class T> struct abs_ptr<T*, decltype((void)sizeof(T))> { static constexpr bool v = __is_abstract(T); };
template<class T> T to_host_fn(uint64_t g);
template<class T> uint64_t to_guest_fn(T p);
template<class T> T get(Rd& r) {
  constexpr int k = kind<T>();
  if constexpr (k == KCLS) {                                  /* fill raw storage (no constructor), copy out (trivial) */
    alignas(T) unsigned char b[sizeof(T)];
    rd_agg(r, b, sizeof(T), alignof(T), hfa_rt(rec_rt<T>(), sizeof(T)));
    return *reinterpret_cast<T*>(b);
  } else {
    static_assert(k != KNTRIV, "a non-trivial-for-calls value is read through hold()");
    T v{};
    if constexpr (k == KINT || k == KPTR) {
      if (r.g < 8) memcpy(&v, &r.c->X[r.g++], sizeof(T));
      else memcpy(&v, (void*)(uintptr_t)rd_stk(r, sizeof(T), sizeof(T)), sizeof(T));
      if constexpr (__is_same(T, gd_id)) gobjc_hostify((uint64_t)(uintptr_t)v);   /* a guest block passed as an object */
      if constexpr (abs_ptr<T>::v) chk_vptr((uint64_t)(uintptr_t)v);
    } else if constexpr (k == KF32) {
      if (r.v < 8) v = r.c->V[r.v++].f32[0]; else memcpy(&v, (void*)(uintptr_t)rd_stk(r, 4, 4), 4);
    } else if constexpr (k == KF64) {
      if (r.v < 8) v = r.c->V[r.v++].f64[0]; else memcpy(&v, (void*)(uintptr_t)rd_stk(r, 8, 8), 8);
    } else if constexpr (k == KF80) {
      v = (long double)get<double>(r);
    } else if constexpr (k == KHFA) {
      rd_agg(r, &v, sizeof(T), alignof(T), hfa<T>());
    } else if constexpr (k == KSMALL || k == KBIG) {
      rd_agg(r, &v, sizeof(T), alignof(T), Hfa{0, 0});
      conv_local<T>(&v, r.k);
    } else if constexpr (k == KFNPTR) {
      v = to_host_fn<T>(rd_x(r));
    } else if constexpr (k == KBLK) {
      uint64_t b = rd_x(r); gobjc_hostify(b); memcpy((void*)&v, &b, 8);
    } else if constexpr (k == KEMPTY) {
    } else die("import parameter type has no AAPCS64 mapping (long vector, va_list, int128, complex)", sizeof(T));
    return v;
  }
}
static void ret_agg(CPU* c, const void* s, unsigned long sz, Hfa h) {
  if (h.n > 0) for (int i = 0; i < h.n; i++) { memset(&c->V[i], 0, 16); memcpy(&c->V[i], (const char*)s + i * h.base, h.base); }
  else if (sz <= 16) { uint64_t t[2] = {0, 0}; memcpy(t, s, sz); c->X[0] = t[0]; c->X[1] = t[1]; }
  else memcpy((void*)(uintptr_t)c->X[8], s, sz);
}
template<class T> void put_ret(CPU* c, T v) {
  constexpr int k = kind<T>();
  if constexpr (k == KINT) c->X[0] = to_u64(v);
  else if constexpr (k == KPTR) c->X[0] = unshadow(to_u64(v));   /* a shadow handed back is the guest's own struct */
  else if constexpr (k == KBLK) memcpy(&c->X[0], (const void*)&v, 8);   /* a host block: the guest calls it via dispatch */
  else if constexpr (k == KFNPTR) c->X[0] = to_guest_fn<T>(v);
  else if constexpr (k == KF32) { memset(&c->V[0], 0, 16); c->V[0].f32[0] = v; }
  else if constexpr (k == KF64 || k == KF80) { memset(&c->V[0], 0, 16); c->V[0].f64[0] = (double)v; }
  else if constexpr (k == KHFA) ret_agg(c, &v, sizeof(T), hfa<T>());
  else if constexpr (k == KSMALL || k == KBIG) ret_agg(c, &v, sizeof(T), Hfa{0, 0});
  else if constexpr (k == KCLS) ret_agg(c, &v, sizeof(T), hfa_rt(rec_rt<T>(), sizeof(T)));
  else if constexpr (k == KEMPTY) (void)v;
  else die("import return type has no AAPCS64 mapping", sizeof(T));
}

/* ---- host -> guest (closures): write arguments, read the return value ---- */
struct Wr { CPU* c; int g, v; uint64_t sa, lim, copy, copy_lim; };
static inline uint64_t wr_stk(Wr& w, uint64_t size, uint64_t align) {
  w.sa = (w.sa + align - 1) & ~(align - 1); uint64_t a = w.sa; w.sa += size;
  if (w.sa > w.lim) die("closure: stack arguments exceed the reserved area", w.sa);
  return a;
}
static void wr_x(Wr& w, uint64_t x) { if (w.g < 8) w.c->X[w.g++] = x; else memcpy((void*)(uintptr_t)wr_stk(w, 8, 8), &x, 8); }
static void wr_agg(Wr& w, const void* s, unsigned long sz, unsigned long al, Hfa h) {
  if (h.n > 0) {
    if (w.v + h.n <= 8) {
      for (int i = 0; i < h.n; i++) { memset(&w.c->V[w.v + i], 0, 16); memcpy(&w.c->V[w.v + i], (const char*)s + i * h.base, h.base); }
      w.v += h.n;
    } else { w.v = 8; memcpy((void*)(uintptr_t)wr_stk(w, sz, al), s, sz); }
  } else if (sz <= 16) {
    int n = (int)((sz + 7) / 8);
    uint64_t t[2] = {0, 0}; memcpy(t, s, sz);
    if (w.g + n <= 8) { for (int i = 0; i < n; i++) w.c->X[w.g + i] = t[i]; w.g += n; }
    else { w.g = 8; memcpy((void*)(uintptr_t)wr_stk(w, n * 8, al > 8 ? 16 : 8), t, n * 8); }
  } else {                                                    /* a copy the callee owns, passed by address */
    w.copy = (w.copy + 15) & ~15ULL;
    if (w.copy + sz > w.copy_lim) die("closure: by-reference copies exceed the reserved area", sz);
    memcpy((void*)(uintptr_t)w.copy, s, sz); uint64_t p = w.copy; w.copy += sz;
    wr_x(w, p);
  }
}
template<class T> void put(Wr& w, T v) {
  constexpr int k = kind<T>();
  if constexpr (k == KINT || k == KPTR || k == KFNPTR) {
    uint64_t u = 0;
    if constexpr (k == KFNPTR) u = to_guest_fn<T>(v); else if constexpr (k == KPTR) u = unshadow(to_u64(v)); else u = to_u64(v);
    if (w.g < 8) w.c->X[w.g++] = u; else memcpy((void*)(uintptr_t)wr_stk(w, sizeof(T), sizeof(T)), &u, sizeof(T));
  } else if constexpr (k == KBLK) {
    uint64_t u; memcpy(&u, (const void*)&v, 8); wr_x(w, u);
  } else if constexpr (k == KF32) {
    if (w.v < 8) { memset(&w.c->V[w.v], 0, 16); w.c->V[w.v++].f32[0] = v; }
    else memcpy((void*)(uintptr_t)wr_stk(w, 4, 4), &v, 4);
  } else if constexpr (k == KF64) {
    if (w.v < 8) { memset(&w.c->V[w.v], 0, 16); w.c->V[w.v++].f64[0] = v; }
    else memcpy((void*)(uintptr_t)wr_stk(w, 8, 8), &v, 8);
  } else if constexpr (k == KF80) {
    put<double>(w, (double)v);
  } else if constexpr (k == KHFA) {
    wr_agg(w, &v, sizeof(T), alignof(T), hfa<T>());
  } else if constexpr (k == KSMALL || k == KBIG) {
    wr_agg(w, &v, sizeof(T), alignof(T), Hfa{0, 0});
  } else if constexpr (k == KCLS) {
    wr_agg(w, &v, sizeof(T), alignof(T), hfa_rt(rec_rt<T>(), sizeof(T)));
  } else if constexpr (k == KEMPTY) {
  } else die("closure parameter type has no AAPCS64 mapping", sizeof(T));
}
template<class T> void put_arg(Wr& w, T& v) {                 /* references and non-trivial values go by address */
  if constexpr (is_ref<T>::v) wr_x(w, (uint64_t)(uintptr_t)&v);
  else if constexpr (kind<T>() == KNTRIV) wr_x(w, (uint64_t)(uintptr_t)&v);
  else put<typename rcv<T>::t>(w, v);
}
template<class T> T get_ret(CPU* c, const void* sret) {
  constexpr int k = kind<T>();
  if constexpr (k == KCLS) {
    alignas(T) unsigned char b[sizeof(T)];
    Hfa h = hfa_rt(rec_rt<T>(), sizeof(T));
    if (h.n > 0) for (int i = 0; i < h.n; i++) memcpy(b + i * h.base, &c->V[i], h.base);
    else memcpy(b, sizeof(T) <= 16 ? (const void*)&c->X[0] : sret, sizeof(T));
    return *reinterpret_cast<T*>(b);
  } else {
    T v{};
    if constexpr (k == KINT || k == KPTR || k == KSMALL) {
      if constexpr (__is_same(T, gd_id)) gobjc_hostify(c->X[0]);   /* a guest block returned as an object */
      memcpy(&v, &c->X[0], sizeof(T));
    }
    else if constexpr (k == KFNPTR) v = to_host_fn<T>(c->X[0]);
    else if constexpr (k == KBLK) { gobjc_hostify(c->X[0]); memcpy((void*)&v, &c->X[0], 8); }
    else if constexpr (k == KF32) v = c->V[0].f32[0];
    else if constexpr (k == KF64) v = c->V[0].f64[0];
    else if constexpr (k == KF80) v = (long double)c->V[0].f64[0];
    else if constexpr (k == KHFA) { constexpr Hfa h = hfa<T>(); for (int i = 0; i < h.n; i++) memcpy((char*)&v + i * h.base, &c->V[i], h.base); }
    else if constexpr (k == KBIG) memcpy(&v, sret, sizeof(T));
    else if constexpr (k == KEMPTY) {}
    else die("closure return type has no AAPCS64 mapping", sizeof(T));
    return v;
  }
}
template<class T> constexpr unsigned long sret_size() { if constexpr (kind<T>() == KBIG || kind<T>() == KCLS) return sizeof(T); else return 1; }
/* structs carrying function pointers (gen/v8_marshal.inc specializes these): Fix<T>::in turns the guest callback
   addresses of a host-side copy into closures before native code sees them; After<T>::run converts guest callbacks the
   guest wrote into a native argument object during a closure (WeakCallbackInfo::SetSecondPassCallback) */
template<class T> struct Fix { static constexpr bool on = false; static void in(T&) {} };
template<class T> struct After { static void run(const T&) {} };
template<class F> void fix_fn(F& f) { f = to_host_fn<F>((uint64_t)(uintptr_t)f); }
struct CbScope {                                              /* undone on every exit, a C++ exception or longjmp included */
  CPU* prev; GStack st; GStack* own; uint64_t lo = tls_stk_lo, hi = tls_stk_hi;
  ~CbScope() { tls_cur = prev; tls_stk_lo = lo; tls_stk_hi = hi; if (own) own->busy = 0; gstack_free(st); }
};
static void stk_enter(const GStack& s) { tls_stk_lo = (uint64_t)(uintptr_t)s.base; tls_stk_hi = tls_stk_lo + s.len; }
/* run guest code at g on a fresh frame: x8 = indirect result address, `write` places the arguments */
template<class W> void enter_guest_w(CPU& nc, void* x8, uint64_t g, W&& write) {
  memset(&nc, 0, sizeof nc);
  {
    CbScope s{tls_cur, GStack{nullptr, 0, 0, 0}, nullptr};
    CPU* prev = s.prev;
    if (!prev) {                                              /* host-owned thread: cached stack, fresh one if busy */
      s.own = cb_stack();
      if (s.own->busy) { s.own = nullptr; s.st = gstack(GD_CB_STACK); } else s.own->busy = 1;
      stk_enter(s.own ? *s.own : s.st);
    }
    uint64_t top = prev ? ((prev->SP - GD_REDZONE) & ~15ULL) : s.own ? s.own->top : s.st.top;
    /* To the guest the host frames are one call: callee-saved registers and fp continue from the guest caller, and the
       sentinel frame returns to the caller's lr at its sp, so the guest unwinder walks from the callback on into the
       caller's frames (a C++ exception crosses qsort and the like; an ObjC one goes to the host frames first). */
    if (prev) {
      for (int i = 19; i <= 29; i++) nc.X[i] = prev->X[i];
      for (int i = 8; i < 16; i++) nc.V[i].u64[0] = prev->V[i].u64[0];
    }
    seg_start(&nc, top, prev ? prev->SP : 0, prev ? prev->X[30] : 0);
    const uint64_t entry_sp = nc.SP;
    Wr w{&nc, 0, 0, nc.SP, nc.SP + GD_ARGS, nc.SP + GD_ARGS, nc.SP + GD_ARGS + GD_COPY};
    nc.X[8] = (uint64_t)(uintptr_t)x8;
    write(w);
    tls_cur = &nc;
    binds_out();                                              /* struct shadows of host calls in flight on this thread */
    try { dispatch(&nc, g); guest_returned(&nc); }
    catch (GuestResume& r) {
      if (r.pc == GD_SENTINEL && r.sp == entry_sp) gobjc_boundary_throw();
      throw;
    }
    binds_in();
  }
}
/* the same with typed arguments in order, then After<> on each one */
template<class... A> void enter_guest(CPU& nc, void* x8, uint64_t g, A&... a) {
  enter_guest_w(nc, x8, g, [&](Wr& w) { int order[] = {0, (put_arg<A>(w, a), 0)...}; (void)order; });   /* left-to-right */
  int post[] = {0, (After<typename rcv<typename deref<A>::t>::t>::run(a), 0)...};
  (void)post;
}
template<class R, class... A> R call_guest(uint64_t g, A&... a) {
  using RT = typename rcv<R>::t;
  CPU nc;
  alignas(16) unsigned char sret[sret_size<RT>()];
  enter_guest<A...>(nc, sret, g, a...);
  if constexpr (!__is_same(RT, void)) return get_ret<RT>(&nc, sret);
}

struct Direct { template<class R, class... A> static R run(uint64_t g, A&... a) { return call_guest<R, A...>(g, a...); } };
/* Pool<F, How>: the typed entry of closures of type F (one shared stub table, see CSLOT) */
template<class F, class How = Direct> struct Pool;
template<class R, class... A, class How> struct Pool<R (*)(A...), How> {
  using P = R (*)(A...);
  using RT = typename rcv<R>::t;
  static R entry(A... a) { uint64_t g = cpop()->guest; return How::template run<R, A...>(g, a...); }
  /* a non-trivial result is built by the guest straight into the native caller's result object. SysV: hidden pointer in
     rdi, returned in rax, i.e. the machine signature of RT* (RT*, A...). */
  static RT* entry_sret(RT* ret, A... a) { uint64_t g = cpop()->guest; CPU nc; enter_guest<A...>(nc, ret, g, a...); return ret; }
  static P get(uint64_t g) {
    void* e;
    if constexpr (kind<RT>() == KNTRIV) e = reinterpret_cast<void*>(&entry_sret); else e = reinterpret_cast<void*>(&entry);
    int n = __atomic_load_n(&ncslot, __ATOMIC_ACQUIRE);
    for (int i = 0; i < n && i < GD_MAX_CLOSURES; i++)        /* ponytail: linear scan per conversion; index (entry, guest) if hot */
      if (__atomic_load_n(&CSLOT[i].guest, __ATOMIC_ACQUIRE) == g && CSLOT[i].entry == e) return reinterpret_cast<P>(CSTUB + i * CSTUB_SZ);
    int ld[] = {0, (ldbl_rt<A>(), 0)...}; (void)ld; ldbl_rt<R>();
    int i = __atomic_fetch_add(&ncslot, 1, __ATOMIC_ACQ_REL); /* a racing twin may take a second slot: both are correct */
    if (i >= GD_MAX_CLOSURES) die("closure table full (GD_MAX_CLOSURES)", g);
    CSLOT[i].entry = e; __atomic_store_n(&CSLOT[i].guest, g, __ATOMIC_RELEASE);
    return reinterpret_cast<P>(CSTUB + i * CSTUB_SZ);
  }
};
template<class T> T to_host_fn(uint64_t g) {
  if (!g) return nullptr;
  /* An import without a host function of the guest's type (long double math as double, specials, per-library and
     undeclared names) becomes a closure that calls the import through its own bridge. */
  if (int k = import_slot(g); k >= 0) {
    if (ENT[k].hostfn) return reinterpret_cast<T>(ENT[k].hostfn);
    if constexpr (fnp<T>::plain) return reinterpret_cast<T>(Pool<typename fx<T>::t>::get(g));   /* a function effect (fx) is not part of the closure */
    else die_name("import passed as a variadic or noexcept callback has no plain host function", ENT[k].name);
  }
  if (int h = handle_index(g); h >= 0) {
    if (HND[h].ui) die_name(GD_UI_MARK ": a host function pointer into this framework handed to native code", HND[h].ui);
    return reinterpret_cast<T>(HND[h].fn);
  }
  if (in_guest(g)) {
    if constexpr (fnp<T>::plain) return reinterpret_cast<T>(Pool<typename fx<T>::t>::get(g));   /* a function effect (fx) is not part of the closure */
    else die("guest callback with a variadic or noexcept signature", g);
  }
  return reinterpret_cast<T>((uintptr_t)g);                   /* SIG_IGN-style constant or raw host pointer */
}
/* host code address -> the guest-side address it stands for: a closure -> its guest function, an import's host function
   -> its import slot (patched vtable slots and callbacks that native code hands back); 0 if neither */
static uint64_t host_target(uint64_t a) {
  if (uint64_t g = rev_find(a)) return g;
  for (int k = 0; k < NIMP; k++) if (ENT[k].hostfn && (uint64_t)(uintptr_t)ENT[k].hostfn == a) return GD_IMPORT_BASE + (uint64_t)k * GD_IMP_SLOT;
  return 0;
}

/* C++ parameters. T& / T&& and a non-trivial-for-calls T arrive as a pointer in the next x slot. References bind to the
   guest's own object. A non-trivial by-value T is the guest caller's object itself (Itanium: the caller constructs and
   destroys it): the host function is called through an ABI-identical type with T* in that position (SysV passes such a
   T as an INTEGER-class pointer), so no move or destructor is added. */
template<class T> struct Hold { T v; T&& take() { return static_cast<T&&>(v); } };
template<class T> struct HoldP { T* p; T&& take() { return static_cast<T&&>(*p); } };
template<class T> struct HoldN { T* p; T* take() { return p; } };
template<class T> struct HoldR { T* p; T& take() { return *p; } };
template<class T> struct HoldC { alignas(T) unsigned char b[sizeof(T)]; T& take() { return *reinterpret_cast<T*>(b); } };
template<class T> constexpr bool code_rec_ptr() {             /* a pointer to a struct with code-pointer fields */
  if constexpr (__is_pointer(T)) {
    using Q = typename rmp<T>::t;
    if constexpr (is_rec<Q>() && complete<Q>::v) { if constexpr (__is_literal_type(Q)) return REC<Q>.code; }
  }
  return false;
}
template<class T> struct cptr { static constexpr bool v = false; };
template<class Q> struct cptr<const Q*> { static constexpr bool v = true; };
template<class Q> struct cptr<const volatile Q*> { static constexpr bool v = true; };
/* a pointer to a struct with code fields (see code_lay): st 1, the shadow is what native code gets (bound to this thread
   while the call runs, synced back when it ends); st 2, the guest's own pointer, whose changed code fields read as guest
   values after the call (guest_owned memory); st 0, the guest's own pointer, nothing after the call */
template<class T> struct HoldS {
  using Q = typename rmp<T>::t;
  T v; Bind b; unsigned char st; bool taken;
  uint64_t pre[CODE_MAX];
  alignas(16) unsigned char bl[sizeof(Q)];
  T take() {                                                  /* the call starts: this object no longer moves */
    taken = true;
    if (st == 1) { b.bl = bl; b.next = tls_binds; tls_binds = &b; }
    return v;
  }
  ~HoldS() {
    if (!taken) return;
    if (st == 1) {
      ShLock l;
      if (b.out) write_back(&b);
      for (Bind** p = &tls_binds; *p; p = &(*p)->next) if (*p == &b) { *p = b.next; break; }
    } else if (st == 2) {
      const CodeLay& L = code_lay<Q>();
      unsigned char* g = (unsigned char*)(uintptr_t)to_u64(v);
      for (int i = 0; i < L.n; i++)
        if (uint64_t x = rd8(g + L.f[i].off); x != pre[i])
          if (uint64_t o = code_out(L.f[i], x); o != x) wr8(g + L.f[i].off, o);
    }
  }
};
template<class T> void hold_s(HoldS<T>& h, Rd& r) {
  using Q = typename rmp<T>::t;
  h.st = 0; h.taken = false; h.v = get<T>(r);
  if (!h.v) return;
  const CodeLay& L = code_lay<Q>();
  uint64_t p = to_u64(h.v);
  bool need = false;
  for (int i = 0; i < L.n; i++) {
    uint64_t x = rd8((const char*)(uintptr_t)p + L.f[i].off);
    h.pre[i] = x;
    if (L.f[i].shared || L.f[i].blk) code_in(L.f[i], x, r.k);   /* a union with guest code stops; a block becomes host-callable */
    else need = need || guest_code(x);
  }
  if (need) {
    ShLock l;
    bool fresh;
    Shadow* sh = shadow_of(p, &L, &fresh);
    sync_in(sh, nullptr, fresh, r.k);
    memcpy(h.bl, sh->s, sizeof(Q));
    h.b = Bind{sh, nullptr, !cptr<T>::v, r.k, nullptr};
    h.v = reinterpret_cast<T>((uintptr_t)sh->s); h.st = 1;
  } else if (!cptr<T>::v && guest_owned(p, sizeof(Q))) h.st = 2;
}
template<class T> struct HoldOf {
  using t = typename cond<kind<T>() == KNTRIV, HoldN<T>, typename cond<code_rec_ptr<T>(), HoldS<T>, Hold<T>>::t>::t;
};
template<class T> struct HoldOf<T&> { using t = typename cond<Fix<typename rcv<T>::t>::on, HoldC<typename rcv<T>::t>, HoldR<T>>::t; };
template<class T> struct HoldOf<T&&> { using t = HoldP<T>; };
template<class A, bool = !is_ref<A>::v && kind<A>() == KNTRIV> struct AbiP { using t = A; };  /* as the host call passes it */
template<class A> struct AbiP<A, true> { using t = A*; };
template<class T> typename HoldOf<T>::t hold(Rd& r) {
  using H = typename HoldOf<T>::t;
  using D = typename rcv<typename deref<T>::t>::t;
  if constexpr (Fix<D>::on) {
    static_assert(!is_ref<T>::v || __is_same(typename deref<T>::t, const D), "callback struct by non-const reference");
    static_assert(kind<D>() != KNTRIV || is_ref<T>::v, "callback struct as a non-trivial value");
  }
  if constexpr (is_ref<T>::v && Fix<D>::on) {                 /* byte view of the guest object; no host ctor/dtor runs */
    H h; memcpy(h.b, (const void*)(uintptr_t)rd_x(r), sizeof(D)); Fix<D>::in(h.take()); return h;
  } else if constexpr (is_ref<T>::v || kind<T>() == KNTRIV) return H{(typename deref<T>::t*)(uintptr_t)rd_x(r)};
  else if constexpr (code_rec_ptr<T>()) { H h; hold_s<T>(h, r); return h; }
  else { H h{get<T>(r)}; Fix<D>::in(h.v); return h; }
}

/* ---- generic bridge: decode in order into a tuple, call the host function, encode the result ---- */
template<int I, class T> struct Leaf { T v; };
template<class S, class... A> struct Tup;
template<int... I, class... A> struct Tup<Seq<I...>, A...> : Leaf<I, A>... {};
template<class R, class... A> struct InvImpl {
  template<int... I> static void go(CPU* c, int k, R (*f)(A...), Seq<I...>) {
    int ld[] = {0, (ldbl_rt<A>(), 0)...}; (void)ld; ldbl_rt<R>();
    Rd r{c, 0, 0, c->SP, k};
    Tup<Seq<I...>, typename HoldOf<typename rcv<A>::t>::t...> t{{hold<typename rcv<A>::t>(r)}...};
    using RT = typename rcv<R>::t;
    using FP = R (*)(typename AbiP<A>::t...);
    FP fp = reinterpret_cast<FP>(f);
    /* a struct shadow (HoldS) syncs back when t goes out of scope, after the result is written */
    if constexpr (__is_same(R, void)) fp(static_cast<Leaf<I, typename HoldOf<typename rcv<A>::t>::t>&>(t).v.take()...);
    else if constexpr (is_ref<R>::v) {                        /* a reference result is its address */
      auto&& x = fp(static_cast<Leaf<I, typename HoldOf<typename rcv<A>::t>::t>&>(t).v.take()...);
      c->X[0] = unshadow((uint64_t)(uintptr_t)&x);
    }
    else if constexpr (kind<RT>() == KNTRIV) {                /* built in the guest's x8 buffer. SysV: hidden result */
      using FS = RT* (*)(RT*, typename AbiP<A>::t...);        /* pointer first, returned in rax (RT may be incomplete) */
      reinterpret_cast<FS>(f)((RT*)(uintptr_t)c->X[8], static_cast<Leaf<I, typename HoldOf<typename rcv<A>::t>::t>&>(t).v.take()...);
    }
    else { RT rv = fp(static_cast<Leaf<I, typename HoldOf<typename rcv<A>::t>::t>&>(t).v.take()...); put_ret<RT>(c, rv); }
  }
  template<auto F> static void call(CPU* c, int k) { go(c, k, (R (*)(A...))F, MakeSeq<(int)sizeof...(A)>{}); }
  static void call_rt(CPU* c, void* f) { go(c, -1, reinterpret_cast<R (*)(A...)>(f), MakeSeq<(int)sizeof...(A)>{}); }
};
struct InvVariadic {
  template<auto F> static void call(CPU*, int k) { die_name("variadic import has no bridge", ENT[k].name); }
  static void call_rt(CPU*, void* f) { die("call through a variadic host function pointer (no bridge)", (uint64_t)(uintptr_t)f); }
};
template<class F> struct Inv;
template<class R, class... A> struct Inv<R (*)(A...)> : InvImpl<R, A...> {};
template<class R, class... A> struct Inv<R (*)(A...) noexcept> : InvImpl<R, A...> {};
template<class R, class... A> struct Inv<R (*)(A..., ...)> : InvVariadic {};
template<class R, class... A> struct Inv<R (*)(A..., ...) noexcept> : InvVariadic {};
template<class R, class... A> struct Inv<__attribute__((noreturn)) R (*)(A...)> : InvImpl<R, A...> {};  /* __dead2: exit, abort */
template<class R, class... A> struct Inv<__attribute__((noreturn)) R (*)(A..., ...)> : InvVariadic {};
#if __has_attribute(nonblocking)
template<class R, class... A> struct Inv<R (*)(A...) [[clang::nonblocking]]> : InvImpl<R, A...> {};   /* CA_REALTIME_API imports */
#endif

template<class T> uint64_t to_guest_fn(T p) {                 /* void(*)(void) is the generic code pointer (IMP): untyped */
  if constexpr (!__is_same(typename fx<T>::t, T)) return to_guest_fn<typename fx<T>::t>(reinterpret_cast<typename fx<T>::t>(p));
  else if constexpr (__is_same(T, void (*)(void))) return code_to_guest(to_u64(p), nullptr);
  else return code_to_guest(to_u64(p), &Inv<T>::call_rt);
}

/* guest classes implementing host interfaces (GD_VTABS): each interface slot of the guest vtable is rewritten in place,
   once, to a native closure of that slot's signature, so native code can call through it; the guest's own virtual calls
   then reach the closure address and dispatch() maps it back (host_target). The image is found by content. */
template<class P> uint64_t vmk(uint64_t g) { return (uint64_t)(uintptr_t)to_host_fn<P>(g); }
static void vpatch_all() {
  for (int i = 0; i < GD_NVTAB; i++) {
    const VTab& t = GD_VTABS[i]; uint64_t* hit = nullptr;
    for (int k = 0; k < NIMG; k++) {
      uint64_t a = t.vptr + IMG[k].slide, s = a + 8 * (uint64_t)t.chk;
      if (s - IMG[k].lo < IMG[k].size && *(const uint64_t*)(uintptr_t)s == t.chk_target + IMG[k].slide) {
        if (hit) die_name("vtable patch: more than one guest image matches", t.iface);
        hit = (uint64_t*)(uintptr_t)a;
      }
    }
    if (!hit) die_name("vtable patch: no guest image holds the catalogued vtable", t.iface);
    for (int j = 0; j < t.n; j++) hit[t.s[j].slot] = t.s[j].mk(hit[t.s[j].slot]);
  }
}
/* native vtable slots the guest may call (GD_NSLOTS): native function address -> typed bridge, filled once at start from
   the host libraries' own vtables. A slot that differs from the build-time catalog means another library build: stop. */
enum { NMAP_N = 1 << 15 };
static uint64_t nmap_k[NMAP_N];
static const NSlot* nmap_v[NMAP_N];
static unsigned nmap_h(uint64_t a) { return (unsigned)((a * 0x9E3779B97F4A7C15ULL) >> 49) & (NMAP_N - 1); }
static const NSlot* native_slot(uint64_t a) {                 /* acquire the key, then its value (nslot_add publishes at run time) */
  for (unsigned i = nmap_h(a);; i = (i + 1) & (NMAP_N - 1)) {
    uint64_t k = __atomic_load_n(&nmap_k[i], __ATOMIC_ACQUIRE);
    if (!k) return nullptr;
    if (k == a) return __atomic_load_n(&nmap_v[i], __ATOMIC_RELAXED);
  }
}
static void nslots_resolve() {
  if (GD_NNSLOT > NMAP_N / 2) die("native vtable slot table too large", (uint64_t)GD_NNSLOT);
  const char* hold = getenv("GDYLD_TEST_WITHHOLD_NSLOT");    /* test hook: slots whose signature contains it stay unbridged */
  for (int i = 0; i < GD_NNSLOT; i++) {
    const NSlot& s = GD_NSLOTS[i];
    if (hold && *hold && strstr(s.sig, hold)) continue;
    void* h = dlopen(s.lib, RTLD_LAZY | RTLD_NOLOAD);
    void* an = h ? dlsym(h, s.anchor) : nullptr;
    if (!an) die_name("native vtable catalog: host library or its anchor symbol not loaded", s.lib);
    uint64_t slide = (uint64_t)(uintptr_t)an - s.anchor_addr;
    uint64_t fn = *(const uint64_t*)(uintptr_t)(s.addr + slide);
    uint64_t want = s.target ? s.target + slide : (uint64_t)(uintptr_t)dlsym(RTLD_DEFAULT, s.sym + 1);
    if (fn != want) die_name("native vtable slot differs from the build-time catalog (another host library build)", s.sig);
    unsigned j = nmap_h(fn);
    while (nmap_k[j] && nmap_k[j] != fn) j = (j + 1) & (NMAP_N - 1);
    if (!nmap_k[j]) { nmap_k[j] = fn; nmap_v[j] = &s; }       /* identical-code-folded twins: the first signature wins */
  }
}
/* a native slot learnt at run time (gmedia.hpp: a host library's object the guest got); readers stay lock-free: the value
   is published before its key. The same address with another bridge stops loudly, unless keep: then the first bridge stays. */
static pthread_mutex_t nmap_mu = PTHREAD_MUTEX_INITIALIZER;
static int nmap_used;
static void nslot_add(uint64_t fn, const NSlot* s, bool keep = false) {
  pthread_mutex_lock(&nmap_mu);
  unsigned j = nmap_h(fn);
  while (nmap_k[j] && nmap_k[j] != fn) j = (j + 1) & (NMAP_N - 1);
  if (nmap_k[j] && nmap_v[j]->call != s->call && !keep) die_name("native slot learnt twice with two different bridges", s->sig);
  if (!nmap_k[j]) {
    if (GD_NNSLOT + ++nmap_used > NMAP_N / 2) die("native vtable slot table full", (uint64_t)nmap_used);
    __atomic_store_n(&nmap_v[j], s, __ATOMIC_RELEASE); __atomic_store_n(&nmap_k[j], fn, __ATOMIC_RELEASE);
  }
  pthread_mutex_unlock(&nmap_mu);
}
/* malloc zone function slots (malloc/malloc.h; a zone has the same layout in the arm64 guest and the x86-64 host): the guest
   calls them through a zone pointer the host gave it (SQLite's mem1: malloc_default_zone()->size). The first call through a
   slot of a live zone bridges every slot that zone's version has; one function in two slots keeps its first bridge. */
struct ZSlot { size_t off; unsigned ver; NSlot s; };
#define GD_ZSLOT(f, v) {offsetof(malloc_zone_t, f), v, \
                        {nullptr, nullptr, 0, 0, 0, nullptr, &Inv<decltype(malloc_zone_t::f)>::call_rt, "malloc_zone_t::" #f}}
static const ZSlot ZSLOTS[] = {
  GD_ZSLOT(size, 0), GD_ZSLOT(malloc, 0), GD_ZSLOT(calloc, 0), GD_ZSLOT(valloc, 0), GD_ZSLOT(free, 0), GD_ZSLOT(realloc, 0),
  GD_ZSLOT(destroy, 0), GD_ZSLOT(batch_malloc, 0), GD_ZSLOT(batch_free, 0), GD_ZSLOT(memalign, 5),
  GD_ZSLOT(free_definite_size, 6), GD_ZSLOT(pressure_relief, 8), GD_ZSLOT(claimed_address, 10),
  GD_ZSLOT(try_free_default, 13), GD_ZSLOT(malloc_with_options, 15), GD_ZSLOT(malloc_type_malloc, 16),
  GD_ZSLOT(malloc_type_calloc, 16), GD_ZSLOT(malloc_type_realloc, 16), GD_ZSLOT(malloc_type_memalign, 16),
  GD_ZSLOT(malloc_type_malloc_with_options, 16),
};
#undef GD_ZSLOT
static uint64_t zslot_fn(const malloc_zone_t* z, const ZSlot& s) {
  return z->version >= s.ver ? *(const uint64_t*)((const char*)z + s.off) : 0;
}
/* a is a slot of z: bridge all of z's slots */
static bool zone_bridge(const malloc_zone_t* z, uint64_t a) {
  bool hit = false;
  for (const ZSlot& s : ZSLOTS) hit = hit || zslot_fn(z, s) == a;
  if (hit)
    for (const ZSlot& s : ZSLOTS)
      if (uint64_t fn = zslot_fn(z, s)) nslot_add(fn, &s.s, true);
  return hit;
}
static bool zone_slot(uint64_t a) {                           /* a: a slot of a live zone, now bridged */
  if (!a) return false;                                       /* an absent slot reads 0 too */
  if (zone_bridge(malloc_default_zone(), a)) return true;     /* libmalloc's virtual default zone is not in the zone list */
  vm_address_t* zs = nullptr;
  unsigned n = 0;
  if (malloc_get_all_zones(mach_task_self(), nullptr, &zs, &n) != KERN_SUCCESS) return false;
  for (unsigned i = 0; i < n; i++)
    if (zone_bridge((const malloc_zone_t*)(uintptr_t)zs[i], a)) return true;
  return false;
}
}  // namespace gd

#define GD_LDBL_MSG "GDYLD_LINK_ERROR: host import passes long double through memory (long double*, long double& or a struct holding " \
                    "one, also in a callback's signature): the guest's long double is a 64-bit double, the host's is 80-bit x87"
template<class PT> constexpr bool is_fn_ptr = gd::fnp<PT>::v || (__is_pointer(PT) && __is_function(typename gd::rmp<PT>::t));
template<class PT> void undecomposable(int k) {
  if constexpr (is_fn_ptr<PT>) die_name("host import's function type has parameter attributes the bridge cannot decompose "
                                        "(e.g. a noescape block)", ENT[k].name);
  else die_name("branch to a data import", ENT[k].name);
}
template<auto P> struct Gen {
  using PT = decltype(P);
  static constexpr bool isfn = is_fn_ptr<PT>;
  static_assert(!gd::LdSig<PT>::v, GD_LDBL_MSG);
  static void call(CPU* c, int k) { if constexpr (gd::fnp<PT>::v) gd::Inv<PT>::template call<P>(c, k); else undecomposable<PT>(k); }
  static uint64_t data() { if constexpr (isfn) return 0; else return (uint64_t)(uintptr_t)P; }
  static void* fnp() { if constexpr (gd::fnp<PT>::plain) return reinterpret_cast<void*>(P); else return nullptr; }
  static const void* addr() { if constexpr (isfn) return reinterpret_cast<const void*>(P); else return nullptr; }
};
template<class PT> struct GenQ {                             /* EK_QUAL: same bridge, host address from QFN at run time */
  static_assert(!gd::LdSig<PT>::v, GD_LDBL_MSG);
  static void call(CPU* c, int k) { if constexpr (gd::fnp<PT>::v) gd::Inv<PT>::call_rt(c, QFN[k]); else undecomposable<PT>(k); }
};
template<class PT> struct GenH {                             /* GD_EH: a function whose type the templates cannot match */
  static_assert(!gd::LdSig<PT>::v, GD_LDBL_MSG);
  static void call(CPU* c, int k) { gd::Inv<PT>::call_rt(c, const_cast<void*>(ENT[k].addr)); }
};
/* GD_EH: called through its type with the noescape parameter attribute dropped (gdyld's libclang spelling) */
#define GD_EH(t, n, nm) {&GenH<t*>::call, 0, reinterpret_cast<void*>(&::n), nm, EK_FN, reinterpret_cast<const void*>(&::n), nullptr}
/* GD_E prototype, GD_L long double math as its double twin (no host function of the guest's type), GD_Q per-library,
   GD_S special, GD_U undeclared */
#define GD_E(n, nm) {&Gen<&::n>::call, Gen<&::n>::data(), Gen<&::n>::fnp(), nm, Gen<&::n>::isfn ? EK_FN : EK_DATA, Gen<&::n>::addr(), nullptr}
#define GD_L(n, nm) {&Gen<&::n>::call, 0, nullptr, nm, EK_FN, Gen<&::n>::addr(), nullptr}
#define GD_Q(n, nm, lib) {&GenQ<decltype(&::n)>::call, 0, nullptr, nm, EK_QUAL, nullptr, lib}
#define GD_S(h, nm) {&h, 0, nullptr, nm, EK_SPECIAL, nullptr, nullptr}
/* GD_ER (gdyld HEAP_ROUTE): the guest's calls go through route r; dlsym, dladdr and callbacks see the real function.
   GD_ERP: the same with the route given as a function pointer expression (gdyld ABI_ROUTE's Abi* conversions). */
#define GD_ER(r, real, nm) {&Gen<&::r>::call, 0, reinterpret_cast<void*>(&::real), nm, EK_FN, reinterpret_cast<const void*>(&::real), nullptr}
#define GD_ERP(p, real, nm) {&Gen<p>::call, 0, reinterpret_cast<void*>(&::real), nm, EK_FN, reinterpret_cast<const void*>(&::real), nullptr}
/* gdyld ABI_ROUTE: a type the SDK declares narrower for an arm64 build than for x86_64 (SSLCipherSuite: uint16_t vs
   uint32_t, CipherSuite.h). The guest's arrays hold G; the host function reads or writes H. AbiNarrowGet: the host fills
   a temporary of the guest's capacity, narrowed back (count in/out). AbiWidenSet: the guest's array widened for the call.
   AbiNarrowOne: one value out. The real function is called unchanged. */
template<class G, auto F> struct AbiNarrowGet;
template<class G, class R, class C, class H, class N, R (*F)(C, H*, N*)> struct AbiNarrowGet<G, F> {
  static R fn(C c, G* out, N* n) {
    if (!out || !n) return F(c, reinterpret_cast<H*>(out), n);
    N cap = *n, m = cap;
    H* t = static_cast<H*>(calloc(cap ? cap : 1, sizeof(H)));
    R r = F(c, t, &m);
    for (N i = 0; i < (m < cap ? m : cap); i++) out[i] = static_cast<G>(t[i]);
    *n = m; free(t);
    return r;
  }
};
template<class G, auto F> struct AbiWidenSet;
template<class G, class R, class C, class H, class N, R (*F)(C, const H*, N)> struct AbiWidenSet<G, F> {
  static R fn(C c, const G* in, N n) {
    if (!in) return F(c, nullptr, n);
    H* t = static_cast<H*>(calloc(n ? n : 1, sizeof(H)));
    for (N i = 0; i < n; i++) t[i] = static_cast<H>(in[i]);
    R r = F(c, t, n); free(t);
    return r;
  }
};
template<class G, auto F> struct AbiNarrowOne;
template<class G, class R, class C, class H, R (*F)(C, H*)> struct AbiNarrowOne<G, F> {
  static R fn(C c, G* out) {                                  /* starts from the guest's value: unwritten stays unchanged */
    if (!out) return F(c, nullptr);
    H t = static_cast<H>(*out); R r = F(c, &t); *out = static_cast<G>(t);
    return r;
  }
};
#define GD_U(nm) {&sp_undeclared, 0, nullptr, nm, EK_DYN, nullptr, nullptr}
#define GD_UIU(nm) {&sp_ui_stop, 0, nullptr, nm, EK_DYN, nullptr, nullptr}   /* gdyld ui-guard: data resolves, code stops */
/* V8 builds (libc++ overloads some C names): GD_EP / GD_LP take the C function as a pointer expression cast to its C type,
   GD_QT the C type itself */
#define GD_EP(p, nm) {&Gen<p>::call, Gen<p>::data(), Gen<p>::fnp(), nm, Gen<p>::isfn ? EK_FN : EK_DATA, Gen<p>::addr(), nullptr}
#define GD_LP(p, nm) {&Gen<p>::call, 0, nullptr, nm, EK_FN, Gen<p>::addr(), nullptr}
#define GD_QT(t, nm, lib) {&GenQ<t*>::call, 0, nullptr, nm, EK_QUAL, nullptr, lib}
/* GD_V8: a libv8* import through its generated wrapper v8b::b_k (gen/v8_bridges.inc) */
#define GD_V8(k, nm) {&Gen<v8b::b_##k>::call, 0, Gen<v8b::b_##k>::fnp(), nm, EK_FN, Gen<v8b::b_##k>::addr(), nullptr}

/* ---- special imports: Apple varargs, threads, TLV, signals, dlsym, stack probes, traps ---- */
#define VA(x) ((const uint64_t*)(uintptr_t)(x))
#define S(x) ((const char*)(uintptr_t)(x))
#define RET(x) (c->X[0] = (uint64_t)(int64_t)(x))
/* per-build tables from gdyld (gdyld_gen.hpp; a build without one gets empty ones):
   GD_DLI: per guest image its install name, its LC_RPATHs as written ('\n'-separated), what dlsym searches through its
   handle (dyld's order: itself, then its dependencies depth first; `first` for RTLD_FIRST: itself and what it re-exports;
   k >= 0 a guest image, k < 0 the host library GD_DLHOST[-1 - k]) and its guest dependencies in order (an upward link as
   ~k) for running initializers on dlopen; GD_FPARAM: ObjC methods (sorted by selector) with a function-pointer parameter
   `arg` (0 = the first after _cmd), mk turning guest code into a closure of the header's type; GD_VECREC: ObjC methods
   (sorted by selector, encoding as gobjc enc_key) whose header type has a record holding a SIMD vector */
struct DlImg { const char* id; const char* rpaths; const int* deps; int ndeps; const int* first; int nfirst; const int* idep; int nidep; };
struct FParam { const char* cls; const char* sel; int cmeth, arg; uint64_t (*mk)(uint64_t); };
struct VecRec { const char* sel; const char* key; };
#if __has_include("gdyld_gen.hpp")
#include "gdyld_gen.hpp"
#endif
#ifndef GD_HAVE_GEN
static const DlImg GD_DLI[] = {{nullptr, "", nullptr, 0, nullptr, 0, nullptr, 0}}; static const int GD_NDLI = 0;
static const char* const GD_DLHOST[] = {nullptr}; static const int GD_NDLHOST = 0;
static const FParam GD_FPARAM[] = {{nullptr, nullptr, 0, 0, nullptr}}; static const int GD_NFPARAM = 0;
static const VecRec GD_VECREC[] = {{nullptr, nullptr}}; static const int GD_NVECREC = 0;
#endif
#include "gobjc.hpp"
#include "gswift.hpp"
#if __has_include("gmedia.hpp")                              /* optional: typed bridges for one host media library */
#include "gmedia.hpp"
#define GD_TYPED(nm, p) gmd::typed(nm, p)
#else
#define GD_TYPED(nm, p) nullptr
#endif
static void sp_undeclared(CPU*, int k) { die_name("call to a host import with no header prototype (no bridge)", ENT[k].name); }
static void sp_ui_stop(CPU*, int k) { die_name("blocked window-server / AppKit-UI / GPU entry point (headless translation)", ENT[k].name); }
static void sp_trap(CPU*, int k) { die_name("unsupported control transfer (ucontext, vfork, or C++ EH without the guest runtime)", ENT[k].name); }

/* setjmp family: the guest jmp_buf (192 bytes) holds x19..x29, the return address, sp, d8..d15, the signal mask and
   whether it was saved; longjmp throws a GuestResume to the frame that called setjmp (its return site is a resume point). */
enum { JB_X19 = 0, JB_PC = 11, JB_SP = 12, JB_D8 = 13, JB_MASK = 21, JB_SAVED = 22 };
static void jb_save(CPU* c, int save_mask) {
  uint64_t* jb = (uint64_t*)(uintptr_t)c->X[0];
  for (int i = 0; i < 11; i++) jb[JB_X19 + i] = c->X[19 + i];
  jb[JB_PC] = c->X[30]; jb[JB_SP] = c->SP;
  for (int i = 0; i < 8; i++) jb[JB_D8 + i] = c->V[8 + i].u64[0];
  sigset_t m = 0;
  if (save_mask) sigprocmask(SIG_BLOCK, nullptr, &m);
  jb[JB_MASK] = m; jb[JB_SAVED] = (uint64_t)save_mask;
  c->X[0] = 0;
}
[[noreturn]] static void jb_jump(CPU* c, int restore_mask) {
  const uint64_t* jb = (const uint64_t*)(uintptr_t)c->X[0];
  int v = (int)c->X[1];
  if (restore_mask && jb[JB_SAVED]) { sigset_t m = (sigset_t)jb[JB_MASK]; sigprocmask(SIG_SETMASK, &m, nullptr); }
  GuestResume r; r.regs = *c;
  for (int i = 0; i < 11; i++) r.regs.X[19 + i] = jb[JB_X19 + i];
  for (int i = 0; i < 8; i++) { r.regs.V[8 + i].u64[0] = jb[JB_D8 + i]; r.regs.V[8 + i].u64[1] = 0; }
  r.regs.X[30] = jb[JB_PC]; r.regs.SP = jb[JB_SP]; r.regs.X[0] = (uint64_t)(uint32_t)(v ? v : 1);
  r.sp = jb[JB_SP]; r.pc = jb[JB_PC];
  throw r;
}
static void sp_setjmp(CPU* c, int) { jb_save(c, 1); }
static void sp__setjmp(CPU* c, int) { jb_save(c, 0); }
static void sp_sigsetjmp(CPU* c, int) { jb_save(c, (int)c->X[1] != 0); }
static void sp_longjmp(CPU* c, int) { jb_jump(c, 1); }
static void sp__longjmp(CPU* c, int) { jb_jump(c, 0); }
static void sp_siglongjmp(CPU* c, int) { jb_jump(c, 1); }

/* dyld services the guest unwinder needs, answered with guest addresses */
struct GdUnwindSections { uint64_t mh, dwarf, dwarf_len, cu, cu_len; };   /* struct dyld_unwind_sections */
static void sp_find_unwind(CPU* c, int) {
  GdUnwindSections* o = (GdUnwindSections*)(uintptr_t)c->X[1];
  if (c->X[0] - (GD_SENTINEL - 16) < 32) {                    /* the sentinel frame: synthetic __eh_frame */
    *o = GdUnwindSections{GD_SENTINEL - 16, (uint64_t)(uintptr_t)go::EHF, go::EHF_LEN, 0, 0}; RET(1); return;
  }
  for (int k = 0; k < NIMG; k++)
    if (c->X[0] - IMG[k].lo < IMG[k].size) { *o = GdUnwindSections{IMG[k].lo, IMG[k].ehf, IMG[k].ehf_len, IMG[k].cu, IMG[k].cu_len}; RET(1); return; }
  RET(0);
}
/* a guest address, as dyld answers (APIs::dladdr, MachOLoaded::findClosestSymbol) from the image as mapped: the header is
   __dso_handle; else the closest symbol at or below it among the image's global and local (non-debug) symbols of the
   section that holds it; none (a stripped image, a string literal) leaves the name null rather than naming a neighbour */
static void guest_dladdr(int k, uint64_t a, Dl_info* o) {
  const uint64_t lo = IMG[k].lo, slide = IMG[k].slide, ua = a - slide;
  *o = Dl_info{IMG[k].path, (void*)(uintptr_t)lo, nullptr, nullptr};
  if (a == lo) { o->dli_sname = "__dso_handle"; o->dli_saddr = (void*)(uintptr_t)lo; return; }
  const mach_header_64* mh = (const mach_header_64*)(uintptr_t)lo;
  if (mh->magic != MH_MAGIC_64) return;
  const symtab_command* st = nullptr; const dysymtab_command* ds = nullptr;
  uint64_t le_vm = 0, le_off = 0; uint32_t sect = 0; bool hit = false;
  const uint8_t* lc = (const uint8_t*)(mh + 1);
  for (uint32_t i = 0; i < mh->ncmds; i++, lc += ((const load_command*)lc)->cmdsize) {
    const load_command* l = (const load_command*)lc;
    if (l->cmd == LC_SYMTAB) st = (const symtab_command*)lc;
    else if (l->cmd == LC_DYSYMTAB) ds = (const dysymtab_command*)lc;
    else if (l->cmd == LC_SEGMENT_64) {
      const segment_command_64* s = (const segment_command_64*)lc;
      if (!strcmp(s->segname, "__LINKEDIT")) { le_vm = s->vmaddr; le_off = s->fileoff; }
      const section_64* sc = (const section_64*)(s + 1);
      for (uint32_t j = 0; j < s->nsects && !hit; j++) { sect++; hit = ua - sc[j].addr < sc[j].size; }   /* dyld: 1-based, last if none */
    }
  }
  if (!st || !ds || !le_vm) return;
  uint64_t syms = slide + le_vm + st->symoff - le_off, pool = slide + le_vm + st->stroff - le_off;
  if (syms - lo + (uint64_t)st->nsyms * sizeof(nlist_64) > IMG[k].size || pool - lo + st->strsize > IMG[k].size) return;
  const nlist_64* sy = (const nlist_64*)(uintptr_t)syms;
  const nlist_64* best = nullptr;
  const uint32_t from[2] = {ds->iextdefsym, ds->ilocalsym}, cnt[2] = {ds->nextdefsym, ds->nlocalsym};
  for (int pass = 0; pass < 2; pass++)                        /* globals, then locals (debug entries skipped) */
    for (uint32_t i = from[pass]; i < from[pass] + cnt[pass] && i < st->nsyms; i++)
      if ((sy[i].n_type & N_TYPE) == N_SECT && !(pass && (sy[i].n_type & N_STAB)) && sy[i].n_value <= ua && sy[i].n_sect == sect
          && (!best || best->n_value < sy[i].n_value)) best = &sy[i];
  if (!best || best->n_value + slide == lo) return;           /* never the mach header's own symbol */
  const char* n = best->n_un.n_strx < st->strsize ? (const char*)(uintptr_t)pool + best->n_un.n_strx : nullptr;
  o->dli_sname = n && *n == '_' ? n + 1 : n;
  o->dli_saddr = (void*)(uintptr_t)(best->n_value + slide);
}
/* dladdr: a guest address as above; an import slot or host-function handle the guest holds: the host function it stands for,
   with dli_saddr given back as the guest's own pointer when it is that function's start */
static void sp_dladdr(CPU* c, int) {
  Dl_info* o = (Dl_info*)(uintptr_t)c->X[1];
  uint64_t a = c->X[0];
  if (!o) { RET(0); return; }
  for (int k = 0; k < NIMG; k++)
    if (a - IMG[k].lo < IMG[k].size) { guest_dladdr(k, a, o); RET(1); return; }
  const void* h = nullptr;
  if (int k = import_slot(a); k >= 0) h = ENT[k].hostfn ? ENT[k].hostfn : ENT[k].addr;
  else if (int j = handle_index(a); j >= 0) h = HND[j].fn;
  int r = dladdr(h ? h : (const void*)(uintptr_t)a, o);
  if (r && h && o->dli_saddr == h) o->dli_saddr = (void*)(uintptr_t)a;
  RET(r);
}

/* thread_local destructors (_tlv_atexit): per-thread LIFO list run by a key destructor at thread exit, and by exit() on
   the calling thread before atexit handlers and static destructors (Darwin's exit runs _tlv_exit first) */
struct TlvDtor { uint64_t fn, obj; TlvDtor* next; };
static pthread_key_t tlvd_key; static pthread_once_t tlvd_once = PTHREAD_ONCE_INIT;
static void tlvd_drain() {
  for (TlvDtor* d; (d = (TlvDtor*)pthread_getspecific(tlvd_key)); free(d)) {
    pthread_setspecific(tlvd_key, d->next);
    gd::call_guest<void, uint64_t>(d->fn, d->obj);
  }
}
static void tlvd_run(void* p) { pthread_setspecific(tlvd_key, p); tlvd_drain(); }
static void tlvd_make() { pthread_key_create(&tlvd_key, tlvd_run); }
static void sp_tlv_atexit(CPU* c, int) {
  pthread_once(&tlvd_once, tlvd_make);
  TlvDtor* d = (TlvDtor*)malloc(sizeof *d);
  *d = TlvDtor{c->X[0], c->X[1], (TlvDtor*)pthread_getspecific(tlvd_key)};
  pthread_setspecific(tlvd_key, d);
}
static void atexit_thunk(void* p) { TlvDtor* d = (TlvDtor*)p; gd::call_guest<void, uint64_t>(d->fn, d->obj); }
static void sp_cxa_atexit(CPU* c, int) {                      /* one host thunk for every guest dtor: no closure slot each */
  TlvDtor* d = (TlvDtor*)malloc(sizeof *d);                   /* lives until exit */
  *d = TlvDtor{c->X[0], c->X[1], nullptr};
  RET(__cxa_atexit(atexit_thunk, d, (void*)(uintptr_t)c->X[2]));
}
static void sp_exit(CPU* c, int) { pthread_once(&tlvd_once, tlvd_make); tlvd_drain(); exit((int)c->X[0]); }
/* *_l: the varargs core runs under the given locale (NULL is the C locale, LC_GLOBAL_LOCALE the global one) */
struct UseLocale {
  locale_t old;
  explicit UseLocale(uint64_t g) {
    static locale_t c_loc = newlocale(LC_ALL_MASK, "C", (locale_t)0);
    old = uselocale(g ? (locale_t)(uintptr_t)g : c_loc);
  }
  ~UseLocale() { uselocale(old); }
};
static void sp_snprintf_l(CPU* c, int) { UseLocale u(c->X[2]); RET((int)gfmt((char*)c->X[0], (size_t)c->X[1], S(c->X[3]), VA(c->SP))); }
static void sp_asprintf_l(CPU* c, int) { UseLocale u(c->X[1]); RET(gvasprintf((char**)c->X[0], S(c->X[2]), VA(c->SP))); }
static void sp_sscanf_l(CPU* c, int) { UseLocale u(c->X[1]); RET(gscan(S(c->X[0]), nullptr, S(c->X[2]), VA(c->SP))); }
static void sp_nop(CPU*, int) {}
static void sp_chkstk(CPU* c, int) {  // x9 = frame size in bytes (clang darwin arm64): touch every 4 KB page top-down as native
  const volatile char* p = (const char*)(uintptr_t)c->SP;
  uint64_t n = c->X[9];
  for (uint64_t o = 4096; o < n; o += 4096) (void)p[-(int64_t)o];
  if (n) (void)p[-(int64_t)n];
}
/* compiler-rt 128-bit division (no header declares it): AAPCS64 passes each __int128 in an even x pair, returns x0:x1 */
static unsigned __int128 u128(const CPU* c, int i) { return (unsigned __int128)c->X[i + 1] << 64 | c->X[i]; }
static void ret128(CPU* c, unsigned __int128 v) { c->X[0] = (uint64_t)v; c->X[1] = (uint64_t)(v >> 64); }
static void sp_udivti3(CPU* c, int) { ret128(c, u128(c, 0) / u128(c, 2)); }
static void sp_umodti3(CPU* c, int) { ret128(c, u128(c, 0) % u128(c, 2)); }
static void sp_divti3(CPU* c, int) { ret128(c, (unsigned __int128)((__int128)u128(c, 0) / (__int128)u128(c, 2))); }
static void sp_modti3(CPU* c, int) { ret128(c, (unsigned __int128)((__int128)u128(c, 0) % (__int128)u128(c, 2))); }
static void sp_stub_binder(CPU*, int) { die("dyld_stub_binder reached: gdyld binds lazy pointers eagerly", 0); }
static void sp_stack_chk_fail(CPU*, int) { die("guest stack smashing detected (__stack_chk_fail)", 0); }
static void sp_printf(CPU* c, int) { RET(gvfprintf(stdout, S(c->X[0]), VA(c->SP))); }
static void sp_fprintf(CPU* c, int) { RET(gvfprintf((FILE*)c->X[0], S(c->X[1]), VA(c->SP))); }
static void sp_vprintf(CPU* c, int) { RET(gvfprintf(stdout, S(c->X[0]), VA(c->X[1]))); }
static void sp_vfprintf(CPU* c, int) { RET(gvfprintf((FILE*)c->X[0], S(c->X[1]), VA(c->X[2]))); }
static void sp_sprintf(CPU* c, int) { RET((int)gfmt((char*)c->X[0], (size_t)-1 >> 1, S(c->X[1]), VA(c->SP))); }
static void sp_vsprintf(CPU* c, int) { RET((int)gfmt((char*)c->X[0], (size_t)-1 >> 1, S(c->X[1]), VA(c->X[2]))); }
static void sp_snprintf(CPU* c, int) { RET((int)gfmt((char*)c->X[0], (size_t)c->X[1], S(c->X[2]), VA(c->SP))); }
static void sp_vsnprintf(CPU* c, int) { RET((int)gfmt((char*)c->X[0], (size_t)c->X[1], S(c->X[2]), VA(c->X[3]))); }
/* fortified variants: (buf, flag, objsize, fmt, ...) and (buf, maxlen, flag, objsize, fmt, ...). Libc's checks: objsize
   below maxlen, or an output that does not fit objsize, ends in libc's own overflow report (reproduced by a failing host
   __snprintf_chk call). */
extern "C" int __snprintf_chk(char*, size_t, int, size_t, const char*, ...);
[[noreturn]] static void chk_fail() {
  char b[1];
  __snprintf_chk(b, 2, 0, 1, "%s", "");                       /* maxlen 2 > objsize 1: libc's __chk_fail_overflow */
  __builtin_trap();
}
static int sprintf_chk(char* d, size_t os, const char* f, const uint64_t* va) {
  if (!os) chk_fail();
  size_t n = gfmt(d, os, f, va);
  if (n >= os) chk_fail();
  return (int)n;
}
static int snprintf_chk(char* d, size_t mx, size_t os, const char* f, const uint64_t* va) {
  if (mx > os) chk_fail();
  return (int)gfmt(d, mx, f, va);
}
static void sp_sprintf_chk(CPU* c, int) { RET(sprintf_chk((char*)c->X[0], (size_t)c->X[2], S(c->X[3]), VA(c->SP))); }
static void sp_vsprintf_chk(CPU* c, int) { RET(sprintf_chk((char*)c->X[0], (size_t)c->X[2], S(c->X[3]), VA(c->X[4]))); }
static void sp_snprintf_chk(CPU* c, int) { RET(snprintf_chk((char*)c->X[0], (size_t)c->X[1], (size_t)c->X[3], S(c->X[4]), VA(c->SP))); }
static void sp_vsnprintf_chk(CPU* c, int) { RET(snprintf_chk((char*)c->X[0], (size_t)c->X[1], (size_t)c->X[3], S(c->X[4]), VA(c->X[5]))); }
static void sp_NSGetExecutablePath(CPU* c, int) {            /* the guest executable's path, not the translator's */
  uint32_t* size = (uint32_t*)(uintptr_t)c->X[1];
  size_t n = strlen(IMG[0].path) + 1;
  if (n > *size) { *size = (uint32_t)n; RET(-1); return; }
  memcpy((void*)(uintptr_t)c->X[0], IMG[0].path, n); RET(0);
}
static void sp_asprintf(CPU* c, int) { RET(gvasprintf((char**)c->X[0], S(c->X[1]), VA(c->SP))); }
static void sp_vasprintf(CPU* c, int) { RET(gvasprintf((char**)c->X[0], S(c->X[1]), VA(c->X[2]))); }
static int gvdprintf(int fd, const char* f, const uint64_t* va) {
  char* b = nullptr; int n = gvasprintf(&b, f, va);
  if (n > 0 && write(fd, b, (size_t)n) != n) n = -1;
  free(b); return n;
}
static void sp_dprintf(CPU* c, int) { RET(gvdprintf((int)c->X[0], S(c->X[1]), VA(c->SP))); }
static void sp_vdprintf(CPU* c, int) { RET(gvdprintf((int)c->X[0], S(c->X[1]), VA(c->X[2]))); }
static void sp_syslog(CPU* c, int) { char* b = nullptr; gvasprintf(&b, S(c->X[1]), VA(c->SP)); syslog((int)c->X[0], "%s", b ? b : ""); free(b); }
static void sp_sscanf(CPU* c, int) { RET(gscan(S(c->X[0]), nullptr, S(c->X[1]), VA(c->SP))); }
static void sp_vsscanf(CPU* c, int) { RET(gscan(S(c->X[0]), nullptr, S(c->X[1]), VA(c->X[2]))); }
static void sp_fscanf(CPU* c, int) { RET(gscan(nullptr, (FILE*)c->X[0], S(c->X[1]), VA(c->SP))); }
static void sp_vfscanf(CPU* c, int) { RET(gscan(nullptr, (FILE*)c->X[0], S(c->X[1]), VA(c->X[2]))); }
static void sp_scanf(CPU* c, int) { RET(gscan(nullptr, stdin, S(c->X[0]), VA(c->SP))); }
static void sp_vscanf(CPU* c, int) { RET(gscan(nullptr, stdin, S(c->X[0]), VA(c->X[1]))); }
static void sp_open(CPU* c, int) { RET(open(S(c->X[0]), (int)c->X[1], (int)VA(c->SP)[0])); }
static void sp_openat(CPU* c, int) { RET(openat((int)c->X[0], S(c->X[1]), (int)c->X[2], (int)VA(c->SP)[0])); }
static void sp_fcntl(CPU* c, int) { RET(fcntl((int)c->X[0], (int)c->X[1], (long)VA(c->SP)[0])); }
static void sp_ioctl(CPU* c, int) { RET(ioctl((int)c->X[0], (unsigned long)c->X[1], (void*)(uintptr_t)VA(c->SP)[0])); }
static int guest_image(uint64_t a) {
  for (int k = 0; k < NIMG; k++) if (a - IMG[k].lo < IMG[k].size) return k;
  return -1;
}
/* first export of nm by guest images [from, to), in load order */
static uint64_t guest_export(const char* nm, int from, int to) {
  for (int i = 0; i < NGEXP; i++)                             /* ponytail: linear scan; index it if dlsym gets hot */
    if (GEXP[i].img >= from && GEXP[i].img < to && !strcmp(GEXP[i].name, nm)) return GEXP[i].addr;
  return 0;
}
/* ---- guest dlopen: a guest image of this translation, by path, install name, @rpath / @loader_path / @executable_path
   (expanded against the calling guest image and the guest executable, as dyld does), gets a guest handle; anything else
   goes to the host's dlopen, with the @-prefix already expanded. An arm64-only image outside the load graph was never
   translated: NULL, and dlerror says so. dlopen(NULL) is RTLD_DEFAULT, or RTLD_MAIN_ONLY with RTLD_FIRST, as dyld returns.
   Every dlopen / dlsym starts with no pending error, as dyld's do. ---- */
static const uint64_t GD_DLH = GD_HANDLE_BASE - 4096;          /* image k's handle: GD_DLH + 16k, +1 with RTLD_FIRST (a reserved
                                                                  PROT_NONE page) */
static int dl_image(uint64_t h) {
  uint64_t o = h - GD_DLH;
  return o < (uint64_t)NIMG * 16 && o % 16 <= 1 && o < 4096 - 64 ? (int)(o / 16) : -1;
}
static __thread char dl_msg[PATH_MAX + 160]; static __thread bool dl_msg_set;
static void dl_clear() { dl_msg_set = false; (void)dlerror(); }   /* ours and the host's */
static void dl_fail(const char* h, const char* nm) {            /* dyld's message for a symbol not found, the only pending one */
  dl_clear(); snprintf(dl_msg, sizeof dl_msg, "dlsym(%s, %s): symbol not found", h, nm); dl_msg_set = true;
}

/* ---- initializers: dyld's runInitializersBottomUpPlusUpwardLinks, at start from the main executable and on dlopen from the
   opened image: an image is marked when first reached (one already started, or a cycle back into it, is skipped), its
   dependencies run first and its upward links after the rest, then its +load methods and initializers ---- */
static unsigned char* istate;                                  /* per image: 1 once its initialization has started */
static int g_argc; static char** g_argv; static char** g_envp;
static const char* g_apple[] = {"executable_path=", nullptr};
static bool g_init_only;                                       /* GDYLD_INIT_ONLY: report each image's +load and initializers */
static void run_image(int k, CPU* c, uint64_t top) {          /* c: the main CPU at start (top: its stack), else a nested call */
  if (g_init_only) { fprintf(stderr, "gdyld-init: image %d %s: +load\n", k, IMG[k].path); fflush(stderr); }
  if (c) { seg_start(c, top, 0, 0); c->X[29] = 0; }           /* +load runs on the main guest stack */
  go::objc_load_image(k);
  int n = 0;
  for (int i = 0; i < NINIT; i++) {
    if (INIT_IMG[i] != k) continue;
    if (g_init_only) { fprintf(stderr, "gdyld-init: image %d initializer %d at 0x%llx\n", k, n, (unsigned long long)INITS[i]); fflush(stderr); }
    uint64_t argc = (uint64_t)g_argc, argv = (uint64_t)(uintptr_t)g_argv, envp = (uint64_t)(uintptr_t)g_envp, apple = (uint64_t)(uintptr_t)g_apple, z = 0;
    if (c) {
      seg_start(c, top, 0, 0); c->X[0] = argc; c->X[1] = argv; c->X[2] = envp; c->X[3] = apple; c->X[4] = 0; c->X[29] = 0;
      dispatch(c, INITS[i]); guest_returned(c);
    } else gd::call_guest<void, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t>(INITS[i], argc, argv, envp, apple, z);
    n++;
  }
  if (g_init_only) { fprintf(stderr, "gdyld-init: image %d %s: %d initializers ran\n", k, IMG[k].path, n); fflush(stderr); }
}
enum { DANGLE_MAX = 256 };
static void init_up(int k, CPU* c, uint64_t top, int* dang, int& nd) {
  if (__atomic_exchange_n(&istate[k], (unsigned char)1, __ATOMIC_ACQ_REL)) return;   /* dyld's beginInitializers */
  for (int i = 0; i < GD_DLI[k].nidep; i++) {
    int j = GD_DLI[k].idep[i];
    if (j >= 0) { init_up(j, c, top, dang, nd); continue; }
    bool have = false;
    for (int x = 0; x < nd; x++) have = have || dang[x] == ~j;
    if (!have && nd == DANGLE_MAX) die("more than 256 upward-linked images", (uint64_t)k);
    if (!have) dang[nd++] = ~j;
  }
  run_image(k, c, top);
}
static void init_from(int k, CPU* c, uint64_t top) {
  if (GD_NDLI != NIMG) {                                      /* a build without gdyld's tables: load order */
    for (int o = 0; o < NORDER; o++) if (!__atomic_exchange_n(&istate[ORDER[o]], (unsigned char)1, __ATOMIC_ACQ_REL)) run_image(ORDER[o], c, top);
    return;
  }
  int d1[DANGLE_MAX], d2[DANGLE_MAX], d3[DANGLE_MAX], n1 = 0, n2 = 0, n3 = 0;
  init_up(k, c, top, d1, n1);
  for (int i = 0; i < n1; i++) init_up(d1[i], c, top, d2, n2);
  for (int i = 0; i < n2; i++) init_up(d2[i], c, top, d3, n3);
}
static void dir_of(const char* p, char* out) {                /* out: PATH_MAX bytes */
  strlcpy(out, p, PATH_MAX);
  char* s = strrchr(out, '/');
  if (s) *s = 0; else strlcpy(out, ".", PATH_MAX);
}
static void dl_expand(const char* p, int img, char* out) {    /* @loader_path of guest image img, @executable_path of the guest */
  char d[PATH_MAX];
  if (!strncmp(p, "@loader_path", 12)) { dir_of(IMG[img].path, d); snprintf(out, PATH_MAX, "%s%s", d, p + 12); }
  else if (!strncmp(p, "@executable_path", 16)) { dir_of(IMG[0].path, d); snprintf(out, PATH_MAX, "%s%s", d, p + 16); }
  else strlcpy(out, p, PATH_MAX);
}
static int dl_try(const char* cand, char* first) {            /* guest image at this path, else -1; first: the first file that exists */
  char r[PATH_MAX];
  if (!realpath(cand, r)) return -1;
  for (int k = 0; k < NIMG; k++) if (!strcmp(r, IMG[k].path)) return k;
  if (!first[0]) strlcpy(first, r, PATH_MAX);
  return -1;
}
/* image k for a load name requested by guest image me: an install name first, then the candidate paths (@rpath: the
   LC_RPATHs of the caller, then of the main executable, each expanded against the image that declares it) */
static const char* leaf_of(const char* p) { const char* s = strrchr(p, '/'); return s ? s + 1 : p; }
static int dl_find(const char* nm, int me, char* first) {
  for (int k = 0; k < GD_NDLI; k++) if (GD_DLI[k].id && !strcmp(GD_DLI[k].id, nm)) return k;
  if (!strchr(nm, '/'))                                       /* a leaf name: an image already loaded under it, as dyld matches */
    for (int k = 0; k < NIMG; k++)
      if (!strcmp(leaf_of(IMG[k].path), nm) || (k < GD_NDLI && GD_DLI[k].id && !strcmp(leaf_of(GD_DLI[k].id), nm))) return k;
  char cand[PATH_MAX];
  if (strncmp(nm, "@rpath/", 7)) { dl_expand(nm, me, cand); return dl_try(cand, first); }
  const int imgs[2] = {me, 0};
  for (int img : imgs) {
    if (img >= GD_NDLI) continue;
    for (const char* r = GD_DLI[img].rpaths; *r;) {
      size_t n = strcspn(r, "\n");
      char rp[PATH_MAX]; snprintf(rp, sizeof rp, "%.*s", (int)n, r);
      char x[PATH_MAX]; dl_expand(rp, img, x);
      snprintf(cand, sizeof cand, "%s/%s", x, nm + 7);
      if (int k = dl_try(cand, first); k >= 0) return k;
      r += n + (r[n] == '\n');
    }
  }
  return -1;
}
static bool arm64_only(const char* p) {                       /* a thin arm64 Mach-O, or a universal one without x86_64 */
  uint32_t h[64] = {0};
  FILE* f = fopen(p, "rb");
  if (!f) return false;
  size_t n = fread(h, 4, 64, f); fclose(f);
  if (n >= 2 && h[0] == MH_MAGIC_64) return h[1] == CPU_TYPE_ARM64;
  if (n < 2 || (h[0] != OSSwapHostToBigInt32(FAT_MAGIC) && h[0] != OSSwapHostToBigInt32(FAT_MAGIC_64))) return false;
  uint32_t cnt = OSSwapBigToHostInt32(h[1]), step = h[0] == OSSwapHostToBigInt32(FAT_MAGIC) ? 5 : 8;
  bool arm = false;
  for (uint32_t i = 0; i < cnt && 2 + i * step < n; i++) {
    uint32_t cpu = OSSwapBigToHostInt32(h[2 + i * step]);
    if (cpu == CPU_TYPE_X86_64) return false;
    arm = arm || cpu == CPU_TYPE_ARM64;
  }
  return arm;
}
static void sp_dlopen(CPU* c, int) {
  const char* nm = S(c->X[0]);
  int mode = (int)c->X[1], me = guest_image(c->X[30]);
  if (me < 0) me = 0;                                          /* called back from host code: the executable's view */
  dl_clear();
  if (!nm) { c->X[0] = (uint64_t)(uintptr_t)(mode & RTLD_FIRST ? RTLD_MAIN_ONLY : RTLD_DEFAULT); return; }
  char first[PATH_MAX] = "";
  if (int k = dl_find(nm, me, first); k >= 0) {
    init_from(k, nullptr, 0);                                 /* its pending initializers run before dlopen returns */
    c->X[0] = GD_DLH + 16 * (uint64_t)k + (mode & RTLD_FIRST ? 1 : 0);
    return;
  }
  if (first[0] && arm64_only(first)) {
    snprintf(dl_msg, sizeof dl_msg, "gdyld: %s is an arm64 image that is not part of this translation (only the load graph "
             "is translated)", first);
    dl_msg_set = true; c->X[0] = 0; return;
  }
  c->X[0] = (uint64_t)(uintptr_t)dlopen(first[0] ? first : nm, mode);
}
static void sp_dlclose(CPU* c, int) {                         /* guest images are never unloaded */
  if (dl_image(c->X[0]) >= 0) { dl_clear(); RET(0); return; }
  RET(dlclose((void*)(uintptr_t)c->X[0]));
}
static void sp_dlerror(CPU* c, int) {
  if (dl_msg_set) { dl_msg_set = false; c->X[0] = (uint64_t)(uintptr_t)dl_msg; return; }
  c->X[0] = (uint64_t)(uintptr_t)dlerror();
}
static uint64_t host_sym(void* p, const char* nm) {           /* host code -> import slot, typed handle (GD_TYPED) or untyped handle */
  return p && host_code(p) ? code_to_guest((uint64_t)(uintptr_t)p, GD_TYPED(nm, p)) : (uint64_t)(uintptr_t)p;
}
static void* dl_host(int j, bool first) {                     /* host library j of GD_DLHOST, loaded with the program */
  return dlopen(GD_DLHOST[j], RTLD_LAZY | RTLD_NOLOAD | (first ? RTLD_FIRST : 0));   /* ponytail: one dlopen per lookup */
}
/* nm through a GD_DLI search list from position `from`: guest exports, host libraries through the host's own dlsym */
static uint64_t dl_search(const int* l, int n, int from, const char* nm, bool first) {
  for (int i = from; i < n; i++) {
    if (l[i] >= 0) { if (uint64_t g = guest_export(nm, l[i], l[i] + 1)) return g; continue; }
    if (void* h = dl_host(-1 - l[i], first))
      if (void* p = dlsym(h, nm)) return host_sym(p, nm);
  }
  return 0;
}
/* dlsym, with dyld's scopes: a guest handle searches its image and its dependencies depth first (RTLD_FIRST: the image and
   what it re-exports); RTLD_SELF / RTLD_NEXT the calling image's list from itself / after it; RTLD_MAIN_ONLY the guest
   executable; RTLD_DEFAULT every guest image in load order, then the host libraries after the translated executable (never
   the translator's own symbols); a host dlopen handle is the host's. A guest address comes back as is (a function becomes
   a typed closure wherever it reaches native code); host code -> import slot or untyped handle. */
static void sp_dlsym(CPU* c, int) {
  void* h = (void*)(uintptr_t)c->X[0];
  const char* nm = S(c->X[1]);
  int me = guest_image(c->X[30]), k = dl_image(c->X[0]);
  if (me < 0) me = 0;
  dl_clear();
  uint64_t r = 0;
  char hs[32]; snprintf(hs, sizeof hs, "%p", h);
  const char* hn = h == RTLD_DEFAULT ? "RTLD_DEFAULT" : h == RTLD_MAIN_ONLY ? "RTLD_MAIN_ONLY" : h == RTLD_NEXT ? "RTLD_NEXT"
                 : h == RTLD_SELF ? "RTLD_SELF" : hs;
  if (k >= 0 && k < GD_NDLI) {
    bool f = (c->X[0] - GD_DLH) % 16 == 1;
    r = f ? dl_search(GD_DLI[k].first, GD_DLI[k].nfirst, 0, nm, true) : dl_search(GD_DLI[k].deps, GD_DLI[k].ndeps, 0, nm, false);
  } else if ((h == RTLD_SELF || h == RTLD_NEXT) && me < GD_NDLI) r = dl_search(GD_DLI[me].deps, GD_DLI[me].ndeps, h == RTLD_NEXT, nm, false);
  else if (h == RTLD_MAIN_ONLY && GD_NDLI) r = dl_search(GD_DLI[0].first, GD_DLI[0].nfirst, 0, nm, true);
  else if (h == RTLD_DEFAULT || h == RTLD_SELF || h == RTLD_NEXT || h == RTLD_MAIN_ONLY) {
    r = guest_export(nm, 0, h == RTLD_MAIN_ONLY ? 1 : NIMG);
    if (!r && h != RTLD_MAIN_ONLY) r = host_sym(dlsym(RTLD_NEXT, nm), nm);
  } else { c->X[0] = host_sym(dlsym(h, nm), nm); return; }        /* a host handle: the host's own error on a miss */
  if (r) (void)dlerror();                                     /* misses on the way (host libraries) leave no error */
  else dl_fail(hn, nm);
  c->X[0] = r;
}
using SigH = void (*)(int);
using SigA = void (*)(int, siginfo_t*, void*);
/* SA_SIGINFO: the guest handler reads an Apple arm64 ucontext (mach/arm/_structs.h), not the host's x86 one. It holds
   the registers of the thread's innermost guest CPU (pc = its lr: the translated pc is not tracked) and the fault
   address. sp is never above the interrupted code's sp (translated code stores it to the CPU whenever it may go down,
   recompile.localize); x0-x30, NZCV and the V registers are as of the interrupted function's last call or return (they
   live in C locals in between). An edit to it cannot be applied to translated code, so a changed context stops loudly. */
struct GMctx { uint64_t far; uint32_t esr, exc; uint64_t x[29], fp, lr, sp, pc; uint32_t cpsr, pad; __uint128_t v[32]; uint32_t fpsr, fpcr; };
static_assert(__builtin_offsetof(GMctx, pc) == 272 && sizeof(GMctx) == 816, "Apple arm64 __darwin_mcontext64 layout");
struct GUctx { ucontext_t uc; GMctx mc; };                    /* __darwin_ucontext has one layout on both arches */
struct SigCtx {
  template<class R, class... A> static void run(uint64_t g, int s, siginfo_t* si, void* hu) {
    const ucontext_t* hc = (const ucontext_t*)hu;
    GUctx gc, before;
    memset(&gc, 0, sizeof gc);
    if (hc) { gc.uc.uc_onstack = hc->uc_onstack; gc.uc.uc_sigmask = hc->uc_sigmask; gc.uc.uc_stack = hc->uc_stack; }
    gc.uc.uc_mcsize = sizeof(GMctx); gc.uc.uc_mcontext = (mcontext_t)&gc.mc;
    if (si) gc.mc.far = (uint64_t)(uintptr_t)si->si_addr;
    if (const CPU* c = tls_cur) {
      for (int i = 0; i < 29; i++) gc.mc.x[i] = c->X[i];
      gc.mc.fp = c->X[29]; gc.mc.lr = c->X[30]; gc.mc.sp = c->SP; gc.mc.pc = c->X[30];
      gc.mc.cpsr = c->NF << 31 | c->ZF << 30 | c->CF << 29 | c->VF << 28;
      for (int i = 0; i < 32; i++) memcpy(&gc.mc.v[i], &c->V[i], 16);
    }
    memcpy(&before, &gc, sizeof gc);
    void* up = &gc.uc;
    gd::call_guest<void, int, siginfo_t*, void*>(g, s, si, up);
    if (memcmp(&before, &gc, sizeof gc)) die("SA_SIGINFO handler changed the machine context (an edit cannot be applied to translated code)", g);
  }
};
static SigA sig_host_fn(uint64_t g) { return in_guest(g) ? gd::Pool<SigA, SigCtx>::get(g) : gd::to_host_fn<SigA>(g); }
static void sp_sigaction(CPU* c, int) {                       /* the handler sits in the struct: bridged on a host copy */
  const struct sigaction* ga = (const struct sigaction*)(uintptr_t)c->X[1];
  struct sigaction* go = (struct sigaction*)(uintptr_t)c->X[2];
  struct sigaction ha, ho;
  memset(&ho, 0, sizeof ho);
  if (ga) {
    ha = *ga;
    uint64_t g = (uint64_t)(uintptr_t)ga->__sigaction_u.__sa_handler;
    if (ga->sa_flags & SA_SIGINFO) ha.__sigaction_u.__sa_sigaction = sig_host_fn(g);
    else ha.__sigaction_u.__sa_handler = gd::to_host_fn<SigH>(g);
  }
  int r = sigaction((int)c->X[0], ga ? &ha : nullptr, go ? &ho : nullptr);
  if (go && r == 0) {
    uint64_t g = ho.sa_flags & SA_SIGINFO ? gd::to_guest_fn<SigA>(ho.__sigaction_u.__sa_sigaction)
                                          : gd::to_guest_fn<SigH>(ho.__sigaction_u.__sa_handler);
    *go = ho; go->__sigaction_u.__sa_handler = reinterpret_cast<SigH>((uintptr_t)g);
  }
  RET(r);
}

struct Tramp { uint64_t fn, arg; size_t gsz; };
static void* tramp(void* p) {                                 /* host thread running a translated start routine */
  Tramp t = *(Tramp*)p; free(p);
  GStack st = gstack(t.gsz);
  gd::stk_enter(st);
  CPU* c = (CPU*)calloc(1, sizeof(CPU));
  seg_start(c, st.top, 0, 0); c->X[0] = t.arg;                /* x29 = 0, the sentinel returns to 0: end of stack */
  tls_cur = c;                                                /* a signal handler runs below the live guest sp */
  try { dispatch(c, t.fn); guest_returned(c); }
  catch (GuestResume& r) {
    if (r.pc == GD_SENTINEL) gobjc_boundary_throw();          /* an uncaught ObjC exception: the host's handler */
    die("non-local transfer found no owning frame on this thread", r.pc);
  }
  tls_cur = nullptr;                                          /* thread_local dtors at exit get a callback stack */
  uint64_t r = c->X[0];
  free(c); gstack_free(st); gd::tls_stk_lo = gd::tls_stk_hi = 0;
  return (void*)(uintptr_t)r;
}
static void sp_pthread_create(CPU* c, int) {                  /* guest stack size follows the guest's attr */
  const pthread_attr_t* ga = (const pthread_attr_t*)c->X[1];
  size_t gsz = GD_THREAD_STACK; int det = PTHREAD_CREATE_JOINABLE;
  if (ga) { pthread_attr_getstacksize(ga, &gsz); pthread_attr_getdetachstate(ga, &det); }
  size_t pg = (size_t)getpagesize(), hsz = 2 * gsz < GD_MIN_HOST_STACK ? GD_MIN_HOST_STACK : 2 * gsz;
  pthread_attr_t ha; pthread_attr_init(&ha);
  pthread_attr_setdetachstate(&ha, det);
  pthread_attr_setstacksize(&ha, (hsz + pg - 1) & ~(pg - 1));  /* translated frames live on the host stack too */
  Tramp* t = (Tramp*)malloc(sizeof *t);
  t->fn = c->X[2]; t->arg = c->X[3]; t->gsz = gsz;
  int rc = pthread_create((pthread_t*)c->X[0], &ha, tramp, t);
  pthread_attr_destroy(&ha);
  if (rc) free(t);
  RET(rc);
}
static pthread_key_t* TLVK;
enum { TLV_HDR = 16 };                                        /* block header: owning TLV image index */
static void tlv_free(void* p) {                               /* key destructor: thread_local dtors run while every block lives */
  int t = *(int*)p;
  pthread_setspecific(TLVK[t], p);
  pthread_once(&tlvd_once, tlvd_make); tlvd_drain();
  pthread_setspecific(TLVK[t], nullptr); free(p);
}
/* data offset in a block allocated at the template's alignment: past the header and congruent to the template start,
   so every variable keeps its declared alignment */
static uint64_t tlv_off(int t) {
  uint64_t a = TLVI[t].align;
  return ((TLV_HDR + a - 1) & ~(a - 1)) + (TLVI[t].start & (a - 1));
}
static void sp_tlv(CPU* c, int) {                             /* __tlv_bootstrap: x0 = descriptor, returns the variable */
  uint64_t* d = (uint64_t*)(uintptr_t)c->X[0];
  int t = (int)d[1];
  char* b = (char*)pthread_getspecific(TLVK[t]);
  if (!b) {
    size_t len = (size_t)(tlv_off(t) + (TLVI[t].size ? TLVI[t].size : 1));
    void* m = nullptr;
    if (posix_memalign(&m, (size_t)TLVI[t].align, len)) die("TLV block allocation failed", TLVI[t].size);
    b = (char*)m; memset(b, 0, len);
    *(int*)b = t;
    memcpy(b + tlv_off(t), (const void*)(uintptr_t)TLVI[t].start, TLVI[t].init);
    pthread_setspecific(TLVK[t], b);
  }
  c->X[0] = (uint64_t)(uintptr_t)b + tlv_off(t) + d[2];
}

/* ---- dispatch, loader, entry ---- */
static unsigned* gd_trace;                                    /* GDYLD_TRACE_IMPORTS=1: calls per import, listed at exit */
static unsigned* gd_first; static unsigned gd_seq;            /* the order of each import's first call (1, 2, ...) */
static void gd_trace_hit(int k) {
  if (__atomic_fetch_add(&gd_trace[k], 1u, __ATOMIC_RELAXED) == 0) __atomic_store_n(&gd_first[k], __atomic_add_fetch(&gd_seq, 1u, __ATOMIC_RELAXED), __ATOMIC_RELAXED);
}
static void gd_trace_dump_as(const char* tag) {
  for (int k = 0; k < NIMP; k++) if (gd_trace[k]) fprintf(stderr, "%s %s %u first %u\n", tag, ENT[k].name, gd_trace[k], gd_first[k]);
  fflush(stderr);
}
static void gd_trace_dump() { gd_trace_dump_as("import-trace"); }
/* GDYLD_STOP_AT_IMPORT=name[,name...] (a runner option, unset by default): a guest call of a named import stops loudly before
   the host call happens, whichever route reaches it (direct, inline cache, dispatch, a dlsym'd pointer, objc_msgSend) */
static unsigned char* gd_stop;
[[noreturn]] static void gd_stop_at(int k) {
  die_name("GDYLD_STOP_AT_IMPORT: the guest called this import; stopped before the host call", ENT[k].name);
}
static void gd_stop_arm(const char* list) {
  gd_stop = (unsigned char*)calloc((size_t)NIMP + 1, 1);
  for (const char* p = list; *p;) {
    size_t n = strcspn(p, ",");
    int hit = 0;
    for (int k = 0; k < NIMP; k++)                              /* with or without the C symbol's leading underscore */
      if ((strlen(ENT[k].name) == n && !strncmp(ENT[k].name, p, n)) || (strlen(ENT[k].name) == n + 1 && !strncmp(ENT[k].name + 1, p, n))) gd_stop[k] = 1, hit = 1;
    fprintf(stderr, "gdyld: GDYLD_STOP_AT_IMPORT %.*s: %s\n", (int)n, p, hit ? "armed" : "not an import of this program");
    p += n + (p[n] == ',');
  }
  fflush(stderr);
}
extern "C" void gbridge(CPU* c, int k) {
  if (__builtin_expect(gd_stop != nullptr, 0) && gd_stop[k]) gd_stop_at(k);
  if (gd_trace) gd_trace_hit(k);
  TlsRestore g{tls_cur}; tls_cur = c;
  go::host_side(c, [&] { ENT[k].call(c, k); });
}
/* gbridge for an import gdyld lists in LEAF_IMPORTS (libc memory, string and math functions bridged by prototype): it
   never calls back into guest code, never raises an ObjC exception and never reads tls_cur, and tls_cur already is c
   while translated code runs on c (set before every entry: main, thread start, callbacks), so gbridge's TlsRestore and
   host_side are no-ops for it */
extern "C" void gbridge_leaf(CPU* c, int k) {
  if (__builtin_expect(gd_stop != nullptr, 0) && gd_stop[k]) gd_stop_at(k);
  if (gd_trace) gd_trace_hit(k);
  ENT[k].call(c, k);
}
/* recompile GD_MSGSEND: a send through import slot s, which gdyld bound to objc_msgSend (sup 0), objc_msgSendSuper (1) or
   objc_msgSendSuper2 (2), with the call site's cache (gobjc.hpp msg_fast); a slot bridged otherwise goes through gbridge */
extern "C" void gd_msgsend(CPU* c, go::MIc* ic, int sup, uint64_t s) {
  int k = (int)((s - GD_IMPORT_BASE) / GD_IMP_SLOT);
  if (ENT[k].call != (sup == 0 ? &sp_objc_msgSend : sup == 1 ? &sp_objc_msgSendSuper : &sp_objc_msgSendSuper2)) { dispatch(c, s); return; }
  if (__builtin_expect(gd_stop != nullptr, 0) && gd_stop[k]) gd_stop_at(k);
  if (gd_trace) gd_trace_hit(k);
  if (go::msg_fast(c, ic, sup)) return;
  TlsRestore g{tls_cur}; tls_cur = c;
  go::host_side(c, [&] { go::send(c, sup, ic); });
}
extern "C" void dispatch(CPU* c, uint64_t a) {
  for (int k = 0; k < NIMG; k++)
    if (a - IMG[k].lo < IMG[k].size) {
      gfn f = IMG[k].lookup(a - IMG[k].slide);
      if (!f) die("indirect branch to a non-function", a);
      f(c); return;
    }
  if (int k = import_slot(a); k >= 0) { gbridge(c, k); return; }
  if (int h = handle_index(a); h >= 0) {
    if (HND[h].ui) die_name(GD_UI_MARK ": the guest called a host function pointer into this framework", HND[h].ui);
    void (*call)(CPU*, void*) = __atomic_load_n(&HND[h].call, __ATOMIC_ACQUIRE);
    Dl_info di;
    bool imp = false;
    if (!call) go::host_side(c, [&] { imp = go::host_imp_call(c, (uint64_t)(uintptr_t)HND[h].fn); });
    if (imp) return;                                          /* an IMP: typed from its method */
    if (!call) die_name("call through an untyped host code pointer (dlsym result or void(*)(void)): no signature to bridge",
                        dladdr(HND[h].fn, &di) && di.dli_sname ? di.dli_sname : "?");
    TlsRestore g{tls_cur}; tls_cur = c;
    go::host_side(c, [&] { call(c, HND[h].fn); });
    return;
  }
  if (uint64_t g = gd::host_target(a)) { dispatch(c, g); return; }   /* closure or import host function: patched vtables */
  if (uint64_t g = go::clo_target(a)) { dispatch(c, g); return; }    /* a typed ObjC/block closure: its guest code */
  if (uint64_t g = gsw::tramp_target(a)) { dispatch(c, g); return; } /* a Swift record trampoline: its guest code */
  if (const NSlot* s = gd::native_slot(a)) { TlsRestore g{tls_cur}; tls_cur = c; go::host_side(c, [&] { s->call(c, (void*)(uintptr_t)a); }); return; }
  if (const char* ui = ui_code((const void*)(uintptr_t)a)) die_name(GD_UI_MARK ": the guest branched into this framework's code", ui);
  bool done = false;
  go::host_side(c, [&] { done = go::host_block_call(c, a) || go::host_imp_call(c, a) || gsw::host_vwt_call(c, a) || go::eh_call(c, a); });
  if (done) return;                                           /* a host block's invoke, a host IMP (exact method match), a host value witness, libobjc's EH vtable */
  if (gd::zone_slot(a)) { dispatch(c, a); return; }           /* a malloc zone's function slot, bridged by its type */
  if (host_code((const void*)(uintptr_t)a)) {                 /* native code with no typed bridge: name it */
    Dl_info di;
    bool ok = dladdr((const void*)(uintptr_t)a, &di) && di.dli_sname;
    fprintf(stderr, "FATAL: indirect branch to native code 0x%llx with no typed bridge (nearest host symbol %s+0x%llx in %s)\n",
            (unsigned long long)a, ok ? di.dli_sname : "?", ok ? (unsigned long long)(a - (uint64_t)(uintptr_t)di.dli_saddr) : 0ULL,
            ok && di.dli_fname ? di.dli_fname : "?");
    fflush(stderr); if (gd_die_hook) gd_die_hook(); _exit(70);
  }
  die("indirect branch to an unmapped target", a);
}
static void* map_at(uint64_t addr, size_t len, int prot) {    /* exact address or die; never MAP_FIXED over the host */
  void* p = mmap((void*)(uintptr_t)addr, len, prot, MAP_PRIVATE | MAP_ANON, -1, 0);
  if (p != (void*)(uintptr_t)addr) die("guest region is not free at", addr);
  return p;
}
static uint64_t dyn_resolve(const char* nm, int* code) {     /* undeclared host symbol: code or data, from its segment */
  void* p = dlsym(RTLD_DEFAULT, nm);
  *code = host_code(p);
  return (uint64_t)(uintptr_t)p;
}
extern "C" int backtrace(void**, int); extern "C" void backtrace_symbols_fd(void* const*, int, int);

/* GDYLD_HEAP_GUARD=lo-hi (a diagnostic runner option, unset by default): the guest's malloc, calloc, aligned_alloc and
   default-zone malloc_zone_malloc of lo..hi bytes each get a page of their own that ends at an inaccessible page, and
   free makes the page inaccessible and keeps it out of reuse for the next QCAP frees. A write past a block's end or into
   a freed block then faults at the writing instruction: GDYLD_CRASH_TRACE prints the writer's host backtrace and gh::note
   the block's size and its allocation and free backtraces. The blocks form a registered malloc zone, so free, realloc
   and malloc_size from host or guest code find them. Unset, the gd_heap_* routes (gdyld.py HEAP_ROUTE) are the plain
   system calls. GDYLD_HEAP_GUARD=lo-hi,host also guards host allocations: the zone becomes the default zone (moved to
   the front of the zone list, as Mozilla's allocator does) and hands every other size to the system zone it displaced. */
#include <malloc/malloc.h>
#include <mach/mach.h>
namespace gh {
enum { BT = 10 };
struct Meta { uint32_t size, state; uint64_t user; void* abt[BT]; void* fbt[BT]; };   /* state 0 unused, 1 live, 2 freed */
static bool on;
static size_t lo, hi, pg, slot, nslots, qcap;
static char* arena;                                           /* slot i: [data page][inaccessible page] */
static Meta* meta;
static uint32_t *reuse, *quar;                                /* slots back from quarantine; ring of freed slots */
static size_t next, nreuse, qhead, qlen;
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static malloc_zone_t zone;
static malloc_introspection_t intro;
static malloc_zone_t* sys;                                    /* the system zone every other size and pointer goes to */
static bool in_arena(const void* p) { return on && (const char*)p >= arena && (const char*)p < arena + nslots * slot; }
static void* map_rw(size_t n) {
  void* p = mmap(nullptr, n, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
  if (p == MAP_FAILED) die("GDYLD_HEAP_GUARD: mmap of the guard tables failed; bytes", (uint64_t)n);
  return p;
}
static void* alloc(size_t n, size_t al) {
  pthread_mutex_lock(&mu);
  size_t i = nreuse ? reuse[--nreuse] : next < nslots ? next++ : nslots;
  pthread_mutex_unlock(&mu);
  if (i == nslots) die("GDYLD_HEAP_GUARD: every guarded slot is live or in quarantine; slots", (uint64_t)nslots);
  char* base = arena + i * slot;
  if (mprotect(base, pg, PROT_READ | PROT_WRITE) != 0) die("GDYLD_HEAP_GUARD: mprotect failed; slot", (uint64_t)i);
  size_t r = n ? (n + 15) & ~(size_t)15 : 16;
  Meta& m = meta[i];
  m.size = (uint32_t)n; m.user = (uint64_t)(uintptr_t)(base + pg - r) & ~(uint64_t)(al - 1);
  memset(m.abt, 0, sizeof m.abt); memset(m.fbt, 0, sizeof m.fbt);
  backtrace(m.abt, BT);
  __atomic_store_n(&m.state, 1u, __ATOMIC_RELEASE);
  return (void*)(uintptr_t)m.user;
}
static void say(const char* s) { if (write(2, s, strlen(s)) < 0) {} }
static void bt_out(const char* what, void* const* f) {
  int n = 0; while (n < BT && f[n]) n++;
  say(what); backtrace_symbols_fd(f, n, 2);
}
[[noreturn]] static void misuse(const char* what, const void* p) {
  char b[200]; snprintf(b, sizeof b, "FATAL: GDYLD_HEAP_GUARD: %s: %p\n", what, p); say(b);
  void* f[BT + 1] = {}; backtrace(f, BT); bt_out("called from:\n", f);
  if (in_arena(p)) { const Meta& m = meta[((const char*)p - arena) / slot]; bt_out("block allocated at:\n", m.abt); if (m.state == 2) bt_out("block freed at:\n", m.fbt); }
  _exit(72);
}
static size_t live_index(const void* p) {
  size_t i = (size_t)((const char*)p - arena) / slot;
  const Meta& m = meta[i];
  if (m.user != (uint64_t)(uintptr_t)p) misuse("pointer inside a guarded slot that is not a block start", p);
  if (__atomic_load_n(&m.state, __ATOMIC_ACQUIRE) != 1) misuse("pointer to a guarded block that is already freed (double free or use after free)", p);
  return i;
}
static void release(void* p) {
  size_t i = live_index(p);
  Meta& m = meta[i];
  backtrace(m.fbt, BT);
  __atomic_store_n(&m.state, 2u, __ATOMIC_RELEASE);
  char* base = arena + i * slot;
  if (mmap(base, pg, PROT_NONE, MAP_FIXED | MAP_ANON | MAP_PRIVATE, -1, 0) == MAP_FAILED) die("GDYLD_HEAP_GUARD: page release failed; slot", (uint64_t)i);
  pthread_mutex_lock(&mu);
  if (qlen == qcap) { reuse[nreuse++] = quar[qhead]; qhead = (qhead + 1) % qcap; qlen--; }
  quar[(qhead + qlen) % qcap] = (uint32_t)i; qlen++;
  pthread_mutex_unlock(&mu);
}
static size_t z_size(malloc_zone_t*, const void* p) {        /* 0 for an interior pointer, as malloc_size wants */
  if (!in_arena(p)) return 0;
  const Meta& m = meta[(size_t)((const char*)p - arena) / slot];
  if (m.user != (uint64_t)(uintptr_t)p) return 0;
  return __atomic_load_n(&m.state, __ATOMIC_ACQUIRE) == 1 ? m.size : (misuse("size or free of a guarded block that is already freed", p), 0);
}
static void* z_malloc(malloc_zone_t*, size_t n) { return n >= lo && n <= hi ? alloc(n, 16) : malloc_zone_malloc(sys, n); }
static void* z_calloc(malloc_zone_t*, size_t c, size_t n) {
  size_t t; if (__builtin_mul_overflow(c, n, &t)) return nullptr;
  if (t < lo || t > hi) return malloc_zone_calloc(sys, c, n);
  void* p = alloc(t, 16); memset(p, 0, t); return p;
}
static void* z_valloc(malloc_zone_t*, size_t n) { return malloc_zone_valloc(sys, n); }
static malloc_zone_t* owner(void* p) { malloc_zone_t* o = malloc_zone_from_ptr(p); return o ? o : sys; }
static void z_free(malloc_zone_t*, void* p) {                 /* as the default zone it also gets other zones' pointers */
  if (!p) return;
  if (in_arena(p)) release(p); else malloc_zone_free(owner(p), p);
}
static void* z_realloc(malloc_zone_t*, void* p, size_t n) {
  if (!p) return z_malloc(nullptr, n);
  if (!in_arena(p)) return malloc_zone_realloc(owner(p), p, n);
  size_t old = meta[live_index(p)].size;
  void* q = z_malloc(nullptr, n ? n : 1);
  if (q) { memcpy(q, p, old < n ? old : n); release(p); }
  return q;
}
static void* z_memalign(malloc_zone_t*, size_t a, size_t n) {
  if (n >= lo && n <= hi && a && !(a & (a - 1)) && a <= pg) return alloc(n, a < 16 ? 16 : a);
  return malloc_zone_memalign(sys, a, n);
}
static void z_free_size(malloc_zone_t*, void* p, size_t) { z_free(nullptr, p); }
static void z_destroy(malloc_zone_t*) {}
static unsigned z_batch_malloc(malloc_zone_t*, size_t n, void** v, unsigned k) { return malloc_zone_batch_malloc(sys, n, v, k); }
static void z_batch_free(malloc_zone_t*, void** v, unsigned n) { for (unsigned i = 0; i < n; i++) z_free(nullptr, v[i]); }
static size_t z_pressure(malloc_zone_t*, size_t goal) { return malloc_zone_pressure_relief(sys, goal); }
static boolean_t z_claimed(malloc_zone_t*, void* p) { return in_arena(p); }
static kern_return_t i_enum(task_t, void*, unsigned, vm_address_t, memory_reader_t, vm_range_recorder_t) { return KERN_SUCCESS; }
static size_t i_good(malloc_zone_t*, size_t n) { return n; }
static boolean_t i_check(malloc_zone_t*) { return 1; }
static void i_print(malloc_zone_t*, boolean_t) {}
static void i_log(malloc_zone_t*, void*) {}
static void i_lock(malloc_zone_t*) { pthread_mutex_lock(&mu); }
static void i_unlock(malloc_zone_t*) { pthread_mutex_unlock(&mu); }
static void i_stats(malloc_zone_t*, malloc_statistics_t* s) { memset(s, 0, sizeof *s); }
static boolean_t i_locked(malloc_zone_t*) { return 0; }
static void i_reinit(malloc_zone_t*) { pthread_mutex_init(&mu, nullptr); }
/* the fault report's addition: which guarded block an address hits */
static void note(const void* a) {
  if (!in_arena(a)) return;
  size_t i = (size_t)((const char*)a - arena) / slot;
  const Meta& m = meta[i];
  bool guard = (const char*)a >= arena + i * slot + pg;
  static const char* const st[] = {"never used", "live", "freed"};
  char b[300];
  snprintf(b, sizeof b, "GDYLD_HEAP_GUARD: the fault address %p is %s of guarded slot %zu (%s): block %p, size %u, offset %+lld from the block\n",
           a, guard ? "in the inaccessible page after the data page (a write or read past the end)" : "in the data page", i,
           st[m.state < 3 ? m.state : 0], (void*)(uintptr_t)m.user, m.size, (long long)((const char*)a - (const char*)(uintptr_t)m.user));
  say(b);
  if (m.state) bt_out("block allocated at:\n", m.abt);
  if (m.state == 2) bt_out("block freed at:\n", m.fbt);
}
static malloc_zone_t* front_zone() {
  vm_address_t* zs = nullptr; unsigned nz = 0;
  return malloc_get_all_zones(mach_task_self(), nullptr, &zs, &nz) == KERN_SUCCESS && nz ? (malloc_zone_t*)zs[0] : nullptr;
}
static void init(const char* s) {
  if (!s || !*s) return;
  char mode[16] = "";
  int got = sscanf(s, "%zu-%zu,%15s", &lo, &hi, mode);
  if (got < 2 || lo > hi || hi > 3072 || (got == 3 && strcmp(mode, "host")))
    die_name("GDYLD_HEAP_GUARD wants lo-hi or lo-hi,host in bytes, hi at most 3072", s);
  bool host = got == 3;
  sys = host ? front_zone() : malloc_default_zone();
  if (!sys) die("GDYLD_HEAP_GUARD: no system zone to hand other sizes to", 0);
  malloc_zone_t* purge = host ? malloc_default_purgeable_zone() : nullptr;   /* made before the move, kept behind ours */
  pg = (size_t)getpagesize(); slot = 2 * pg; nslots = (size_t)1 << 22; qcap = (size_t)1 << 20;
  void* a = mmap((void*)(uintptr_t)0x200000000000ULL, nslots * slot, PROT_NONE, MAP_ANON | MAP_PRIVATE, -1, 0);
  if (a == MAP_FAILED) die("GDYLD_HEAP_GUARD: arena reservation failed; bytes", (uint64_t)(nslots * slot));
  arena = (char*)a;
  meta = (Meta*)map_rw(nslots * sizeof(Meta)); reuse = (uint32_t*)map_rw(nslots * 4); quar = (uint32_t*)map_rw(qcap * 4);
  intro.enumerator = i_enum; intro.good_size = i_good; intro.check = i_check; intro.print = i_print; intro.log = i_log;
  intro.force_lock = i_lock; intro.force_unlock = i_unlock; intro.statistics = i_stats; intro.zone_locked = i_locked;
  intro.reinit_lock = i_reinit;
  zone.size = z_size; zone.malloc = z_malloc; zone.calloc = z_calloc; zone.valloc = z_valloc; zone.free = z_free;
  zone.realloc = z_realloc; zone.destroy = z_destroy; zone.zone_name = "GDYLD_HEAP_GUARD"; zone.batch_malloc = z_batch_malloc;
  zone.batch_free = z_batch_free; zone.introspect = &intro; zone.version = 10; zone.memalign = z_memalign;
  zone.free_definite_size = z_free_size; zone.pressure_relief = z_pressure; zone.claimed_address = z_claimed;
  on = true;
  malloc_zone_register(&zone);
  for (int t = 0; host && front_zone() != &zone; t++) {       /* unregister + register moves a zone to the back */
    if (t == 8) die("GDYLD_HEAP_GUARD host: the guard zone did not become the default zone; tries", (uint64_t)t);
    malloc_zone_unregister(sys); malloc_zone_register(sys);
    malloc_zone_unregister(purge); malloc_zone_register(purge);
  }
  fprintf(stderr, "gdyld: GDYLD_HEAP_GUARD %zu-%zu%s: %s blocks of that size are guarded (arena %p, %zu slots, quarantine %zu)\n",
          lo, hi, host ? ",host" : "", host ? "guest and host" : "guest", a, nslots, qcap);
  fflush(stderr);
}
static bool want(size_t n) { return on && n >= lo && n <= hi; }
}  // namespace gh
extern "C" void* gd_heap_malloc(size_t n) { return gh::want(n) ? gh::alloc(n, 16) : malloc(n); }
extern "C" void* gd_heap_calloc(size_t c, size_t n) {
  size_t t;
  return gh::on && !__builtin_mul_overflow(c, n, &t) && gh::want(t) ? gh::z_calloc(nullptr, c, n) : calloc(c, n);
}
extern "C" void* gd_heap_aligned_alloc(size_t a, size_t n) {
  return gh::want(n) && a && !(a & (a - 1)) && a <= gh::pg ? gh::alloc(n, a < 16 ? 16 : a) : aligned_alloc(a, n);
}
extern "C" void* gd_heap_zone_malloc(malloc_zone_t* z, size_t n) {
  return gh::want(n) && z == malloc_default_zone() ? gh::alloc(n, 16) : malloc_zone_malloc(z, n);
}
extern "C" void gd_heap_zone_free(malloc_zone_t* z, void* p) { if (gh::in_arena(p)) gh::release(p); else malloc_zone_free(z, p); }
extern "C" void* gd_heap_zone_realloc(malloc_zone_t* z, void* p, size_t n) {
  return gh::in_arena(p) ? gh::z_realloc(nullptr, p, n) : malloc_zone_realloc(z, p, n);
}

/* GDYLD_PROFILE=path[,hz] (a diagnostic runner option, unset by default): a sampler thread reads the instruction pointer
   of every running thread hz times a second (default 200): thread_suspend, thread_get_state, thread_resume, and nothing
   else while a thread is stopped. Every 4th tick it also records where each waiting thread waits: its stack's return
   addresses (read with vm_read_overwrite, so a bad frame pointer cannot fault), credited at dump time to the first frame
   outside libsystem and libdispatch (usually the import bridge Gen<&fn>::call, which names the blocking call). Every 10 s
   and at exit the counts go to path: the main thread's CPU, other threads' CPU, and the waits, grouped by image and
   symbol. Translated functions (symbols that carry a guest address) count as one group, "translated guest code", with
   the spread over the hottest of them; their names are never written. */
#include <ctype.h>
#include <sys/time.h>
#include <mach-o/dyld.h>
namespace gp {
enum : uint32_t { CAP = 1u << 20, GCAP = 1u << 14, FCAP = 1u << 16, NAMEW = 112, DEPTH = 8 };
struct Grp { char name[NAMEW]; uint64_t n; };
struct Tab { uint64_t* keys; uint32_t* cnt; int32_t* grp; uint64_t (*chain)[DEPTH]; uint64_t total, lost; };   /* grp: -1 until resolved */
static const char* path;
static unsigned hz = 200;
static uint64_t *fkeys, t0, ticks;
static uint32_t* fcnt;
static Tab tabs[4];                                           /* main thread CPU, other threads CPU, waits, CPU in libsystem by caller */
static uint64_t sys_lo[4], sys_hi[4]; static int nsys;        /* __TEXT of libsystem_kernel / libsystem_pthread / libsystem_platform */
struct Last { bool run; uint64_t rip; uint64_t ch[DEPTH]; };
static Last main_last;                                        /* the main thread at the latest sample */
static thread_act_t main_port;
static const void* self_base;                                 /* this image (runtime and translated code): not dyld image 0 under DYLD_INSERT_LIBRARIES */
static Grp* grps; static int32_t* gidx; static uint32_t ngrp;
static pthread_mutex_t dmu = PTHREAD_MUTEX_INITIALIZER;
static uint64_t now_ms() { struct timeval tv; gettimeofday(&tv, nullptr); return (uint64_t)tv.tv_sec * 1000 + (uint64_t)tv.tv_usec / 1000; }
static void add(Tab& t, uint64_t key, const uint64_t* chain) {
  uint32_t h = (uint32_t)((key * 0x9E3779B97F4A7C15ULL) >> 44);
  t.total++;
  for (uint32_t probe = 0; probe < 64; probe++, h = (h + 1) & (CAP - 1)) {
    if (t.keys[h] == key) { t.cnt[h]++; return; }
    if (!t.keys[h]) { t.keys[h] = key; t.cnt[h] = 1; if (chain) memcpy(t.chain[h], chain, sizeof t.chain[h]); return; }
  }
  t.lost++;
}
static uint64_t peek(uint64_t a) {                            /* 8 bytes of our own memory, 0 if unreadable */
  uint64_t v = 0; vm_size_t got = 0;
  if (!a || (a & 7) || vm_read_overwrite(mach_task_self(), (vm_address_t)a, 8, (vm_address_t)&v, &got) != KERN_SUCCESS || got != 8) return 0;
  return v;
}
static bool hexrun(const char* s) { int r = 0; for (; s && *s; s++) { r = isxdigit((unsigned char)*s) ? r + 1 : 0; if (r >= 8) return true; } return false; }
static int32_t group(const char* name) {                     /* name -> group index, made on first use */
  uint32_t h = 2166136261u; for (const char* p = name; *p; p++) h = (h ^ (uint8_t)*p) * 16777619u;
  for (uint32_t i = h & (GCAP - 1);; i = (i + 1) & (GCAP - 1)) {
    if (gidx[i] < 0) {
      if (ngrp + 1 >= GCAP / 2) return 0;                     /* group 0 is the overflow group */
      gidx[i] = (int32_t)ngrp; snprintf(grps[ngrp].name, NAMEW, "%s", name); return (int32_t)ngrp++;
    }
    if (!strcmp(grps[gidx[i]].name, name)) return gidx[i];
  }
}
static void fadd(uint64_t fn, uint32_t n) {                   /* per translated function, for the spread only */
  uint32_t h = (uint32_t)((fn * 0x9E3779B97F4A7C15ULL) >> 48);
  for (uint32_t probe = 0; probe < 64; probe++, h = (h + 1) & (FCAP - 1)) {
    if (fkeys[h] == fn) { fcnt[h] += n; return; }
    if (!fkeys[h]) { fkeys[h] = fn; fcnt[h] = n; return; }
  }
}
static int32_t resolve(uint64_t pc) {
  Dl_info di; char b[NAMEW];
  if (!dladdr((void*)(uintptr_t)pc, &di) || !di.dli_fname) return group("(no image)");
  const char* img = strrchr(di.dli_fname, '/'); img = img ? img + 1 : di.dli_fname;
  if ((const void*)di.dli_fbase == self_base && (!di.dli_sname || hexrun(di.dli_sname)))
    return group("translated guest code");
  snprintf(b, sizeof b, "%s: %s", img, di.dli_sname ? di.dli_sname : "?");
  return group(b);
}
static bool system_image(const char* img) {
  return !strncmp(img, "libsystem_", 10) || !strcmp(img, "libdispatch.dylib") || !strcmp(img, "libc++.1.dylib") ||
         !strcmp(img, "libc++abi.dylib") || !strcmp(img, "libdyld.dylib");
}
static int32_t wait_resolve(const uint64_t* ch, const char* pre) {   /* return addresses -> the first frame outside libsystem */
  char b[NAMEW]; Dl_info di;
  for (uint32_t k = 0; k < DEPTH && ch[k]; k++) {
    if (!dladdr((void*)(uintptr_t)(ch[k] - 1), &di) || !di.dli_fname) continue;
    const char* img = strrchr(di.dli_fname, '/'); img = img ? img + 1 : di.dli_fname;
    if (system_image(img)) continue;
    if ((const void*)di.dli_fbase == self_base && (!di.dli_sname || hexrun(di.dli_sname)))
      { snprintf(b, sizeof b, "%s in translated guest code", pre); return group(b); }
    snprintf(b, sizeof b, "%s %s: %s", pre, img, di.dli_sname ? di.dli_sname : "?");
    return group(b);
  }
  if (ch[0] && dladdr((void*)(uintptr_t)(ch[0] - 1), &di) && di.dli_sname) { snprintf(b, sizeof b, "%s (system frames only) %s", pre, di.dli_sname); return group(b); }
  snprintf(b, sizeof b, "%s (no frames)", pre); return group(b);
}
static void section(FILE* f, Tab& t, const char* title, const char* pre) {   /* pre: null for CPU samples, else a chain label */
  bool waits = pre != nullptr;
  for (uint32_t i = 0; i < ngrp; i++) grps[i].n = 0;
  memset(fcnt, 0, FCAP * sizeof *fcnt); memset(fkeys, 0, FCAP * sizeof *fkeys);
  for (uint32_t h = 0; h < CAP; h++) {
    if (!t.keys[h]) continue;
    if (t.grp[h] < 0) t.grp[h] = waits ? wait_resolve(t.chain[h], pre) : resolve(t.keys[h]);
    grps[t.grp[h]].n += t.cnt[h];
    if (!waits && !strcmp(grps[t.grp[h]].name, "translated guest code")) {
      Dl_info di; if (dladdr((void*)(uintptr_t)t.keys[h], &di)) fadd((uint64_t)(uintptr_t)di.dli_saddr, t.cnt[h]);
    }
  }
  static uint32_t ord[GCAP / 2]; uint32_t m = 0;
  for (uint32_t i = 0; i < ngrp; i++) if (grps[i].n) ord[m++] = i;
  for (uint32_t i = 1; i < m; i++) for (uint32_t j = i; j > 0 && grps[ord[j]].n > grps[ord[j - 1]].n; j--) { uint32_t s = ord[j]; ord[j] = ord[j - 1]; ord[j - 1] = s; }
  uint32_t top[10] = {}; uint32_t nf = 0;                     /* the ten hottest translated functions' counts */
  for (uint32_t h = 0; h < FCAP; h++) {
    if (!fkeys[h] || !fcnt[h]) continue;
    nf++;
    for (int k = 0; k < 10; k++) if (fcnt[h] > top[k]) { memmove(&top[k + 1], &top[k], (9 - k) * sizeof *top); top[k] = fcnt[h]; break; }
  }
  double tot = t.total ? (double)t.total : 1.0;
  fprintf(f, "\n== %s: %llu samples (%llu not counted: table full)\n", title, (unsigned long long)t.total, (unsigned long long)t.lost);
  for (uint32_t i = 0; i < m && i < 45; i++) {
    fprintf(f, "%6.2f%%  %s", 100.0 * grps[ord[i]].n / tot, grps[ord[i]].name);
    if (!strcmp(grps[ord[i]].name, "translated guest code")) {
      fprintf(f, "  (%u functions hit; the hottest ten:", nf);
      for (int k = 0; k < 10 && top[k]; k++) fprintf(f, " %.2f%%", 100.0 * top[k] / tot);
      fprintf(f, ")");
    }
    fprintf(f, "\n");
  }
}
static void dump() {
  pthread_mutex_lock(&dmu);
  char tmp[PATH_MAX]; snprintf(tmp, sizeof tmp, "%s.tmp", path);
  if (FILE* f = fopen(tmp, "w")) {
    fprintf(f, "GDYLD_PROFILE: %.1f s, %llu ticks at %u Hz (waits every 4th tick)\n", (now_ms() - t0) / 1000.0, (unsigned long long)ticks, hz);
    Last ml = main_last;
    if (ml.run) fprintf(f, "\nmain thread at the latest sample: running in %s\n", grps[resolve(ml.rip)].name);
    else {
      fprintf(f, "\nmain thread at the latest sample: waiting; frames:");
      for (uint32_t k = 0; k < DEPTH && ml.ch[k]; k++) fprintf(f, "  [%s]", grps[resolve(ml.ch[k] - 1)].name);
      fprintf(f, "\n");
    }
    section(f, tabs[0], "main thread, running", nullptr);
    section(f, tabs[1], "other threads, running", nullptr);
    section(f, tabs[3], "running inside libsystem (locks, yields, syscalls), by first caller outside it", "in libsystem, called from");
    section(f, tabs[2], "waiting threads (all), by wait site", "wait:");
    fclose(f);
    rename(tmp, path);
  }
  pthread_mutex_unlock(&dmu);
}
static void sample(thread_act_t th, bool waits) {
  thread_basic_info_data_t bi; mach_msg_type_number_t bc = THREAD_BASIC_INFO_COUNT;
  if (thread_info(th, THREAD_BASIC_INFO, (thread_info_t)&bi, &bc) != KERN_SUCCESS || (bi.flags & TH_FLAGS_IDLE)) return;
  bool run = bi.run_state == TH_STATE_RUNNING;
  if (!run && !(waits && (bi.run_state == TH_STATE_WAITING || bi.run_state == TH_STATE_UNINTERRUPTIBLE))) return;
  if (thread_suspend(th) != KERN_SUCCESS) return;
  x86_thread_state64_t st; mach_msg_type_number_t sc = x86_THREAD_STATE64_COUNT;
  bool ok = thread_get_state(th, x86_THREAD_STATE64, (thread_state_t)&st, &sc) == KERN_SUCCESS;
  uint64_t ch[DEPTH] = {}, key = 0;
  bool in_sys = false;
  for (int i = 0; ok && run && i < nsys; i++) in_sys |= st.__rip >= sys_lo[i] && st.__rip < sys_hi[i];
  if (ok && (!run || in_sys || th == main_port)) {            /* [rsp]: a leaf stub's return; then the rbp chain */
    ch[0] = peek(st.__rsp);
    uint64_t bp = st.__rbp;
    for (uint32_t k = 1; k < DEPTH && bp; k++) {
      ch[k] = peek(bp + 8);
      uint64_t up = peek(bp);
      if (!ch[k] || up <= bp) break;
      bp = up;
    }
    for (uint32_t k = 0; k < DEPTH; k++) key = (key ^ ch[k]) * 0x100000001B3ULL;
  }
  thread_resume(th);
  if (!ok) return;
  if (th == main_port) { Last l = {run, st.__rip, {}}; memcpy(l.ch, ch, sizeof ch); main_last = l; }
  if (run) add(tabs[th == main_port ? 0 : 1], st.__rip, nullptr);
  if (run && in_sys) add(tabs[3], key ? key : 1, ch);
  if (!run) add(tabs[2], key ? key : 1, ch);
}
static void* sampler(void*) {
  thread_act_t self = mach_thread_self();
  uint64_t next = now_ms() + 10000;
  for (;;) {
    thread_act_array_t th; mach_msg_type_number_t n;
    if (task_threads(mach_task_self(), &th, &n) == KERN_SUCCESS) {
      for (mach_msg_type_number_t i = 0; i < n; i++) {
        if (th[i] != self) sample(th[i], ticks % 4 == 0);
        mach_port_deallocate(mach_task_self(), th[i]);
      }
      vm_deallocate(mach_task_self(), (vm_address_t)th, n * sizeof(thread_act_t));
    }
    ticks++;
    usleep(1000000 / hz);
    if (now_ms() >= next) { dump(); next += 10000; }
  }
  return nullptr;
}
static void at_exit() { if (path) dump(); }
static Tab table(bool chains) {
  Tab t = {};
  t.keys = (uint64_t*)gh::map_rw(CAP * 8); t.cnt = (uint32_t*)gh::map_rw(CAP * 4); t.grp = (int32_t*)gh::map_rw(CAP * 4);
  for (uint32_t i = 0; i < CAP; i++) t.grp[i] = -1;
  if (chains) t.chain = (uint64_t (*)[DEPTH])gh::map_rw((size_t)CAP * DEPTH * 8);
  return t;
}
static void init(const char* s) {
  if (!s || !*s) return;
  static char p[PATH_MAX]; snprintf(p, sizeof p, "%s", s);
  if (char* c = strrchr(p, ',')) { *c = 0; hz = (unsigned)atoi(c + 1); if (hz < 1 || hz > 2000) die_name("GDYLD_PROFILE wants path[,hz] with hz 1..2000", s); }
  path = p; t0 = now_ms();
  main_port = pthread_mach_thread_np(pthread_self());         /* init runs on the main thread */
  Dl_info me; if (dladdr((const void*)&init, &me)) self_base = me.dli_fbase;
  if (!self_base) die("GDYLD_PROFILE: cannot find the runtime's own image", 0);
  tabs[0] = table(false); tabs[1] = table(false); tabs[2] = table(true); tabs[3] = table(true);
  for (uint32_t i = 0; i < _dyld_image_count() && nsys < 4; i++) {   /* the system images whose running samples get callers */
    const char* nm = _dyld_get_image_name(i);
    if (!nm || !(strstr(nm, "/libsystem_kernel.dylib") || strstr(nm, "/libsystem_pthread.dylib") || strstr(nm, "/libsystem_platform.dylib"))) continue;
    const mach_header_64* h = (const mach_header_64*)_dyld_get_image_header(i);
    const load_command* lc = (const load_command*)(h + 1);
    for (uint32_t c = 0; c < h->ncmds; c++, lc = (const load_command*)((const char*)lc + lc->cmdsize)) {
      const segment_command_64* sg = (const segment_command_64*)lc;
      if (lc->cmd == LC_SEGMENT_64 && !strcmp(sg->segname, "__TEXT")) {
        sys_lo[nsys] = sg->vmaddr + (uint64_t)_dyld_get_image_vmaddr_slide(i); sys_hi[nsys] = sys_lo[nsys] + sg->vmsize; nsys++; break;
      }
    }
  }
  fkeys = (uint64_t*)gh::map_rw(FCAP * 8); fcnt = (uint32_t*)gh::map_rw(FCAP * 4);
  grps = (Grp*)gh::map_rw(GCAP / 2 * sizeof(Grp)); gidx = (int32_t*)gh::map_rw(GCAP * 4);
  for (uint32_t i = 0; i < GCAP; i++) gidx[i] = -1;
  group("(overflow: too many groups)");
  pthread_t t;
  if (pthread_create(&t, nullptr, sampler, nullptr) != 0) die("GDYLD_PROFILE: sampler thread failed", 0);
  pthread_detach(t);
  atexit(at_exit);
  fprintf(stderr, "gdyld: GDYLD_PROFILE %s at %u Hz\n", path, hz); fflush(stderr);
}
}  // namespace gp

static void crash_trace(int s, siginfo_t* si, void* uc) {     /* GDYLD_CRASH_TRACE=1: host backtrace of a fault, then die */
  void* f[64]; int n = backtrace(f, 64);
  const ucontext_t* u = (const ucontext_t*)uc;
  char m[256]; int k = snprintf(m, sizeof m, "FATAL: signal %d at %p (rip %p rsp %p rdi %p rsi %p), host backtrace:\n", s, si ? si->si_addr : nullptr,
                                u ? (void*)u->uc_mcontext->__ss.__rip : nullptr, u ? (void*)u->uc_mcontext->__ss.__rsp : nullptr,
                                u ? (void*)u->uc_mcontext->__ss.__rdi : nullptr, u ? (void*)u->uc_mcontext->__ss.__rsi : nullptr);
  if (write(2, m, (size_t)k) < 0) {}
  backtrace_symbols_fd(f, n, 2);
  gh::note(si ? si->si_addr : nullptr);                       /* GDYLD_HEAP_GUARD: the guarded block it hit, if any */
  if (gd_trace) gd_trace_dump();                              /* GDYLD_TRACE_IMPORTS: what ran before the fault (not async-signal-safe; dying anyway) */
  _exit(71);
}
int main(int argc, char** argv, char** envp) {
  size_t pg = (size_t)getpagesize();
  if (!GD_UI_GUARD) { fprintf(stderr, "gdyld: UI guard OFF (built with ui_guard=False): window, AppKit and GPU calls run\n"); fflush(stderr); }
  if (getenv("GDYLD_CRASH_TRACE")) {
    struct sigaction sa; memset(&sa, 0, sizeof sa); sa.sa_sigaction = crash_trace; sa.sa_flags = SA_SIGINFO;
    sigaction(SIGSEGV, &sa, nullptr); sigaction(SIGBUS, &sa, nullptr);
  }
  if (getenv("GDYLD_TRACE_IMPORTS")) {
    gd_trace = (unsigned*)calloc((size_t)NIMP + 1, sizeof(unsigned)); gd_first = (unsigned*)calloc((size_t)NIMP + 1, sizeof(unsigned));
    atexit(gd_trace_dump); gd_die_hook = gd_trace_dump;
  }
  map_at(GD_IMPORT_BASE, ((size_t)NIMP * GD_IMP_SLOT + pg) & ~(pg - 1), PROT_READ | PROT_WRITE);
  map_at(GD_DLH, 4096 + (((size_t)GD_MAX_HANDLES * GD_HANDLE_SLOT + pg - 1) & ~(pg - 1)), PROT_NONE);   /* dlopen handles, sentinel,
                                                                                                          handles: reserved, never read */
  for (int k = 0; k < NIMG; k++) {
    void* b = map_at(IMG[k].lo, (size_t)IMG[k].size, PROT_READ | PROT_WRITE);
    FILE* f = fopen(IMG[k].file, "rb");
    if (!f) die_name("cannot open guest image", IMG[k].file);
    size_t got = fread(b, 1, (size_t)IMG[k].size, f); fclose(f);
    if (got != IMG[k].size) die_name("short guest image", IMG[k].file);
  }
  uint64_t* impv = (uint64_t*)calloc((size_t)NIMP + 1, 8);
  QFN = (void**)calloc((size_t)NIMP + 1, sizeof(void*));
  for (int k = 0; k < NIMP; k++) {
    int code = 1;
    uint64_t slot = GD_IMPORT_BASE + (uint64_t)k * GD_IMP_SLOT;
    if (ENT[k].kind == EK_DATA) impv[k] = ENT[k].data;
    else if (ENT[k].kind == EK_FN) impv[k] = ENT[k].addr ? slot : 0;   /* an absent weak host function reads as NULL */
    else if (ENT[k].kind == EK_SPECIAL) impv[k] = slot;
    else {                                                    /* EK_DYN / EK_QUAL / EK_QDATA: code -> slot, data -> host address */
      void* lib = ENT[k].kind != EK_DYN ? dlopen(ENT[k].lib, RTLD_LAZY | RTLD_LOCAL) : nullptr;
      if (ENT[k].kind != EK_DYN && !lib) die_name("host library not loadable", ENT[k].lib);
      uint64_t p = lib ? (uint64_t)(uintptr_t)dlsym(lib, ENT[k].name + 1) : dyn_resolve(ENT[k].name + 1, &code);
      if (lib) { code = ENT[k].kind == EK_QUAL && host_code((const void*)(uintptr_t)p); QFN[k] = (void*)(uintptr_t)p; }
      impv[k] = !p ? 0 : code ? slot : p;
      if (ENT[k].kind == EK_DYN && code && p && ENT[k].call == &sp_undeclared && getenv("GDYLD_INIT_ONLY"))
        fprintf(stderr, "gdyld-init: dynamic import resolved as code (loud if called): %s\n", ENT[k].name);
    }
  }
  for (int i = 0; i < NHB; i++) {
    uint64_t v = impv[HB[i].k];
    if (!v && !HB[i].weak) die_name("symbol not found in the host", ENT[HB[i].k].name);
    *(uint64_t*)(uintptr_t)HB[i].addr = v ? v + (uint64_t)HB[i].addend : 0;
  }
  if (const char* s = getenv("GDYLD_STOP_AT_IMPORT")) if (*s) gd_stop_arm(s);   /* before any guest code runs */
  gh::init(getenv("GDYLD_HEAP_GUARD"));                       /* likewise: guest allocations are routed from the first */
  gp::init(getenv("GDYLD_PROFILE"));                          /* sampling profile of every running thread */
  gd::vpatch_all();                                           /* once, after the binds: slots may hold import slots */
  gd::nslots_resolve();
  go::objc_map_images();                                      /* selectors, protocols, guest classes, categories */
  go::sent_init();
  gsw::map_images();                                          /* Swift records to the host runtime (needs sent_init's frame) */
  TLVK = (pthread_key_t*)calloc((size_t)NTLV + 1, sizeof(pthread_key_t));
  for (int t = 0; t < NTLV; t++) pthread_key_create(&TLVK[t], tlv_free);
  for (int i = 0; i < NTLVD; i++) ((uint64_t*)(uintptr_t)TLVD[i])[1] = (uint64_t)TLVD_IMG[i];
  GStack st = gstack(GD_MAIN_STACK);
  gd::stk_enter(st);
  CPU* c = (CPU*)calloc(1, sizeof(CPU));
  tls_cur = c;                                                /* a signal handler runs below the live guest sp */
  g_init_only = getenv("GDYLD_INIT_ONLY") != nullptr;         /* run every image's +load and initializers, exit before main */
  g_argc = argc; g_argv = argv; g_envp = envp;
  istate = (unsigned char*)calloc((size_t)NIMG + 1, 1);
  try {
    init_from(0, c, st.top);                                  /* dependency order: +load methods, then initializers */
    if (g_init_only) {                                        /* no atexit / static destructors: they belong to a finished run */
      fprintf(stderr, "gdyld-init: all %d initializers of %d images ran; exiting before main (GDYLD_INIT_ONLY)\n", NINIT, NORDER);
      fflush(stdout); fflush(stderr); _exit(0);
    }
    if (gd_trace) { fprintf(stderr, "gdyld-trace: initializers done, entering main at first-call order %u\n", gd_seq); gd_trace_dump_as("import-trace-init"); }
    seg_start(c, st.top, 0, 0); c->X[0] = (uint64_t)argc; c->X[1] = (uint64_t)(uintptr_t)argv;
    c->X[2] = (uint64_t)(uintptr_t)envp; c->X[3] = (uint64_t)(uintptr_t)g_apple; c->X[29] = 0;
    dispatch(c, GD_MAIN_ADDR); guest_returned(c);
  } catch (GuestResume& r) {
    if (r.pc == GD_SENTINEL) gobjc_boundary_throw();          /* an uncaught ObjC exception: the host's handler */
    die("non-local transfer found no owning frame on the main thread", r.pc);
  }
  sp_exit(c, -1);                                             /* LC_MAIN: thread_local dtors, then libSystem's exit */
}
