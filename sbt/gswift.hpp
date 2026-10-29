/* gswift.hpp: Swift for translated code (included by gbridge.hpp after gobjc.hpp; tables and bridges come from the
   generated swift_gen.hpp, gswift.py).
   - Imports: every Swift import with a signature in gswift's IR database gets a bridge swb_* (guest Apple-arm64 registers:
     x0-x7 / v0-v7, packed stack, x8 indirect result, x20 self, x21 error -> clang swiftcall on the host: rdi.. / xmm0..,
     rax indirect result, r13 self, r12 error; up to four results each way).
   - Guest code the host runtime calls: relative function pointers in the guest's Swift records (metadata accessors, resilient
     witnesses, generic instantiation / completion, witness-table instantiators) are rewritten to trampolines near the image
     (GSW_TRAMP_BASE, within +-2 GB) that jump to typed closures (swe_* entries); absolute ones (value witness tables, heap
     destroyers of classes and boxes) are rewritten in place to closures. The guest calling such an address goes back to
     its own code (dispatch: closure -> rev_find, trampoline -> gsw::tramp_target).
   - Registration: __swift5_protos, __swift5_types, __swift5_proto of every guest image go to the host runtime before the
     initializers (after gobjc has registered the guest classes, Swift ones included, under _TtCs12_SwiftObject).
   - Host value witnesses the guest calls (resilient host types: NWPath, DispatchQoS): typed from the metadata argument. */
#define GSW_SWIFTCC __attribute__((swiftcall))
#define GSW_CONTEXT __attribute__((swift_context))
#define GSW_ERRORRESULT __attribute__((swift_error_result))
#define GSW_INDIRECT __attribute__((swift_indirect_result))
struct GswRel { uint64_t field; const void* entry; const char* what; };   /* int32 relative field -> trampoline -> entry */
struct GswSect { uint64_t types, ntypes, proto, nproto, protos, nprotos; };   /* per image: address, bytes */
struct GswEager { uint64_t accessor; int kind; };              /* non-generic value type: metadata hostified at map time */
struct GswRo { uint64_t ro; int meta; };                       /* class_ro_t in a runtime-built class's pattern: methods -> host IMPs */
struct GswMeth { const void* desc; void (*call)(CPU*, void*); };   /* host method descriptor '...Tq' -> caller of its implementation */
static const uint64_t GSW_TRAMP_BASE = GD_IMPORT_BASE + 0xC000000ULL;   /* below the guest images, above the handles */
/* trampolines: GSW_NREL static ones (Swift records) + room for those made at run time (key path patterns); each is
   `jmp *slot(%rip)` with its slot in a data page after the code, so adding one never writes executable memory */
enum { GSW_TRAMP_SZ = 16, GSW_TRAMP_DYN = 65536, GSW_VWT_ENUM = 0x00200000 };

namespace gsw {
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
/* a closure stub whose slot names guest code g and the typed entry e (one shared table with gbridge's Pool) */
static void* closure(uint64_t g, const void* e) {
  int n = __atomic_load_n(&ncslot, __ATOMIC_ACQUIRE);
  for (int i = 0; i < n && i < GD_MAX_CLOSURES; i++)
    if (__atomic_load_n(&CSLOT[i].guest, __ATOMIC_ACQUIRE) == g && CSLOT[i].entry == e) return CSTUB + i * CSTUB_SZ;
  int i = __atomic_fetch_add(&ncslot, 1, __ATOMIC_ACQ_REL);
  if (i >= GD_MAX_CLOSURES) die("closure table full (GD_MAX_CLOSURES)", g);
  CSLOT[i].entry = const_cast<void*>(e); __atomic_store_n(&CSLOT[i].guest, g, __ATOMIC_RELEASE);
  return CSTUB + i * CSTUB_SZ;
}
/* a Swift function value the guest hands to the host: guest code -> closure; null stays null */
static void* closure_or_host(uint64_t g, void* e) {
  if (!g) return nullptr;
  if (guest_fn_start(g)) return closure(g, e);
  if (int h = handle_index(g); h >= 0) return HND[h].fn;
  if (import_slot(g) >= 0) die_name("a host import passed to the host as a Swift function value (no plain host function)", ENT[import_slot(g)].name);
  return (void*)(uintptr_t)g;
}
static bool patch_fn(uint64_t* slot, const void* e) {         /* guest code in a function-pointer field -> closure, in place */
  uint64_t v = __atomic_load_n(slot, __ATOMIC_ACQUIRE);
  if (!v || !guest_fn_start(v)) return false;
  __atomic_store_n(slot, (uint64_t)(uintptr_t)closure(v, e), __ATOMIC_RELEASE);
  return true;
}
static void* heapmd(void* md);
static void* keypath(void* pattern);
static uint64_t host_method(uint64_t fn, uint64_t desc);
static uint64_t tramp_target(uint64_t a);
static void* blk(void* b) { gobjc_hostify((uint64_t)(uintptr_t)b); return b; }   /* a guest block in a @convention(block) API */
/* a pointer parameter of a @convention(c) API whose callback signature was never derived: a host function or data passes,
   guest code stops (native code would jump into guest memory) */
static void* cfn_raw(uint64_t v) {
  if (guest_fn_start(v)) die("guest code passed to a Swift API's C function pointer parameter (no callback signature derived)", v);
  if (int h = handle_index(v); h >= 0) return HND[h].fn;
  if (int k = import_slot(v); k >= 0) {
    if (!ENT[k].hostfn) die_name("a host import passed to a Swift API's C function pointer parameter (no plain host function)", ENT[k].name);
    return ENT[k].hostfn;
  }
  return (void*)(uintptr_t)v;
}
static bool trace;                                            /* GSW_TRACE=1: every Swift bridge call on stderr */
static void trace_call(const char* name, const CPU* c) {
  fprintf(stderr, "gsw: %s x0=%llx x1=%llx x2=%llx x3=%llx x8=%llx x20=%llx\n", name, (unsigned long long)c->X[0], (unsigned long long)c->X[1],
          (unsigned long long)c->X[2], (unsigned long long)c->X[3], (unsigned long long)c->X[8], (unsigned long long)c->X[20]);
}
}  // namespace gsw

#if __has_include("swift_gen.hpp")
#include "swift_gen.hpp"
#endif
#ifndef GSW_HAVE_GEN                                          /* a build without gdyld's Swift pass: nothing to map */
static const GswRel GSW_REL[] = {{0, nullptr, nullptr}}; static const int GSW_NREL = 0;
static const GswSect GSW_SECT[] = {{0, 0, 0, 0, 0, 0}};
static const GswEager GSW_EAGER[] = {{0, 0}}; static const int GSW_NEAGER = 0;
static const uint64_t GSW_VWTS[] = {0}; static const int GSW_NVWT = 0;
static const GswRo GSW_RO[] = {{0, 0}}; static const int GSW_NRO = 0;
static const int GSW_NEED_TRAMP = 0;
static const GswMeth GSW_MDESC[] = {{nullptr, nullptr}}; static const int GSW_NMDESC = 0;
#define GSW_E_HEAPDESTROY nullptr
#endif

namespace gsw {
static uint64_t* TR_GUEST; static uint64_t* TR_SLOT; static int NTR, CAPTR;   /* trampoline i -> its guest code, its jump slot */
static uint64_t tramp_target(uint64_t a) {
  uint64_t o = a - GSW_TRAMP_BASE;
  int n = __atomic_load_n(&NTR, __ATOMIC_ACQUIRE);
  return TR_GUEST && o < (uint64_t)n * GSW_TRAMP_SZ && o % GSW_TRAMP_SZ == 0 ? TR_GUEST[o / GSW_TRAMP_SZ] : 0;
}
/* the int32 relative field at `field` (guest data, maybe unaligned) -> a new trampoline to entry e for its guest target g;
   caller holds mu or runs before any other thread */
static void tramp_field(uint64_t field, uint64_t g, const void* e) {
  int i = NTR;
  if (i >= CAPTR) die("Swift trampoline area full (GSW_TRAMP_DYN)", field);
  uint64_t t = GSW_TRAMP_BASE + (uint64_t)i * GSW_TRAMP_SZ;
  int64_t d = (int64_t)t - (int64_t)field;
  if (d != (int32_t)d) die("Swift relative pointer cannot reach the trampoline area", field);
  TR_GUEST[i] = g; __atomic_store_n(&TR_SLOT[i], (uint64_t)(uintptr_t)closure(g, e), __ATOMIC_RELEASE);
  __atomic_store_n(&NTR, i + 1, __ATOMIC_RELEASE);
  int32_t d32 = (int32_t)d; memcpy((void*)(uintptr_t)field, &d32, 4);
}
/* a relative field the host runtime calls through at run time: guest code -> trampoline; null, host code or an existing
   trampoline stay (so a pattern is converted once however often it is used) */
static void retarget(uint64_t field, const void* e) {
  int32_t off; memcpy(&off, (const void*)(uintptr_t)field, 4);
  uint64_t g = field + (int64_t)off;
  if (off && guest_fn_start(g)) tramp_field(field, g, e);
}
/* the host runtime called a guest witness whose requirement has no signature in gswift's database */
static void loud() {
  uint64_t g = cpop()->guest;
  for (int i = 0; i < GSW_NREL; i++)
    if (TR_GUEST && TR_GUEST[i] == g) die_name("the host Swift runtime called a guest function with no bridged signature", GSW_REL[i].what);
  die("the host Swift runtime called a guest function with no bridged signature", g);
}
#ifdef GSW_HAVE_GEN
static void patch_vwt(uint64_t vwt) {                         /* a guest value witness table: entries -> typed closures */
  if (!vwt || !in_guest(vwt)) return;
  uint64_t* w = (uint64_t*)(uintptr_t)vwt;
  static const void* const E[14] = {GSW_E_VWT0, GSW_E_VWT1, GSW_E_VWT2, GSW_E_VWT3, GSW_E_VWT4, GSW_E_VWT5, GSW_E_VWT6, GSW_E_VWT7,
                                    nullptr, nullptr, nullptr, GSW_E_VWT11, GSW_E_VWT12, GSW_E_VWT13};
  for (int s = 0; s < 8; s++) patch_fn(&w[s], E[s]);
  if (*(const uint32_t*)(uintptr_t)(vwt + 80) & GSW_VWT_ENUM) for (int s = 11; s < 14; s++) patch_fn(&w[s], E[s]);
}
#endif
/* guest metadata about to be used by the host: its value witnesses, or a class's destroy / ivar destroyer */
static void hostify_md(uint64_t md) {
#ifdef GSW_HAVE_GEN
  if (!md || !in_guest(md)) return;
  pthread_mutex_lock(&mu);
  uint64_t kind = *(const uint64_t*)(uintptr_t)md;
  if (kind < 0x800) patch_vwt(*(const uint64_t*)(uintptr_t)(md - 8));   /* value metadata (struct 0x200, enum 0x201, ...) */
  else {                                                      /* class: isa; Swift bits in the rodata word */
    patch_fn((uint64_t*)(uintptr_t)(md - 16), GSW_E_HEAPDESTROY);
    if (*(const uint64_t*)(uintptr_t)(md + 32) & 3) patch_fn((uint64_t*)(uintptr_t)(md + 72), GSW_E_HEAPDESTROY);
  }
  pthread_mutex_unlock(&mu);
#else
  (void)md;
#endif
}
/* swift_allocObject / swift_initStackObject: heap metadata (a class, a closure context or box) whose destroy is guest code */
static void* heapmd(void* m) {
#ifdef GSW_HAVE_GEN
  uint64_t md = (uint64_t)(uintptr_t)m;
  if (md && in_guest(md)) {
    pthread_mutex_lock(&mu); patch_fn((uint64_t*)(uintptr_t)(md - 16), GSW_E_HEAPDESTROY); pthread_mutex_unlock(&mu);
    if (*(const uint64_t*)(uintptr_t)md >= 0x800) hostify_md(md);
  }
#endif
  return m;
}
#ifdef GSW_HAVE_GEN
/* key path patterns (stdlib KeyPath.swift, _walkKeyPathPattern): every guest function the host runtime calls through one */
static uint32_t kw(uint64_t a) { uint32_t v; memcpy(&v, (const void*)(uintptr_t)a, 4); return v; }
static void kp_ref(uint64_t field) {                          /* a metadata reference: '\xff\x09' + relative accessor */
  uint64_t r = field + (int64_t)(int32_t)kw(field);
  if ((r & 1) && in_guest(r - 1) && *(const uint8_t*)(uintptr_t)(r - 1) == 0xFF && *(const uint8_t*)(uintptr_t)r == 9) retarget(r + 1, GSW_E_CPTR1);
}
/* a computed component's body at c (header payload pay): id (a resolver when unresolved by function call), getter,
   setter, then for arguments the layout function, witness table (absolute pointers) and initializer; end of the body */
static uint64_t kp_computed(uint64_t c, uint32_t pay, bool args) {
  if ((pay & 0xF) == 1) retarget(c, GSW_E_CPTR1);
  retarget(c + 4, GSW_E_KPGET); c += 8;
  if (pay & 0x400000) { retarget(c, GSW_E_KPSET); c += 4; }
  if (args && (pay & 0x80000)) {
    retarget(c, GSW_E_KPLAYOUT);
    if (int32_t w = (int32_t)kw(c + 4)) {
      uint64_t* t = (uint64_t*)(uintptr_t)(c + 4 + (int64_t)w);
      patch_fn(&t[0], GSW_E_KPDESTROY); patch_fn(&t[1], GSW_E_KPCOPY); patch_fn(&t[2], GSW_E_KPEQUALS); patch_fn(&t[3], GSW_E_KPHASH);
    }
    retarget(c + 8, GSW_E_KPINIT); c += 12;
  }
  return c;
}
#endif
/* a class method lookup ('...Mu', swift_lookUpClassMethod) returned fn for method descriptor desc: host code becomes a
   handle typed by the method's signature (untyped, so a call stops loudly, when the descriptor is not known); guest
   code (a guest override, a trampoline) stays */
static uint64_t host_method(uint64_t fn, uint64_t desc) {
  if (!fn || !host_code((const void*)(uintptr_t)fn)) return fn;
  for (int i = 0; i < GSW_NMDESC; i++)
    if (GSW_MDESC[i].desc && (uint64_t)(uintptr_t)GSW_MDESC[i].desc == desc) return code_to_guest(fn, GSW_MDESC[i].call);
  return code_to_guest(fn, nullptr);
}
/* swift_getKeyPath(pattern, arguments): a guest pattern's functions -> typed closures before the host instantiates it */
static void* keypath(void* pp) {
#ifdef GSW_HAVE_GEN
  uint64_t p = (uint64_t)(uintptr_t)pp;
  if (!p || !in_guest(p)) return pp;
  pthread_mutex_lock(&mu);
  /* once-token, then the walked pattern: generic environment, root type, leaf type, KVC string, KeyPathBuffer header */
  kp_ref(p + 8); kp_ref(p + 12);
  uint64_t c = p + 24, end = c + (kw(p + 20) & 0xFFFFFF);
  while (c < end) {
    uint32_t h = kw(c), disc = (h >> 24) & 0x7F, pay = h & 0xFFFFFF;
    c += 4;
    if (disc == 1 || disc == 3) c += (pay & 0x7FFFFF) >= 0x7FFFFD ? 4 : 0;   /* stored: an out-of-line / unresolved offset */
    else if (disc == 2) c = kp_computed(c, pay, true);
    else if (disc == 0) {                                     /* external: descriptor, generic args, then the local candidate */
      int32_t v = (int32_t)kw(c);
      uint64_t d = c + (int64_t)(v & ~1);
      if (v & 1) d = *(const uint64_t*)(uintptr_t)d;
      if (v && in_guest(d) && ((kw(d) >> 24) & 0x7F) == 2) kp_computed(d + 4, kw(d) & 0xFFFFFF, false);
      for (uint32_t k = 0; k < pay; k++) kp_ref(c + 4 + 4 * k);
      c += 4 * (1 + (uint64_t)pay);
      continue;                                               /* no component type between it and its candidate */
    }
    if (c < end) { kp_ref(c); c += 4; }                       /* the next component's type */
  }
  pthread_mutex_unlock(&mu);
#endif
  return pp;
}
/* a call of host value witness a, slot s: value witnesses are C functions of pointer / 32-bit arguments; x0 gets 32 bits
   from the two that return unsigned (getEnumTagSinglePayload, getEnumTag) */
static void vwt_run(CPU* c, uint64_t a, int s) {
  TlsRestore g{tls_cur}; tls_cur = c;
  uint64_t r = ((uint64_t (*)(uint64_t, uint64_t, uint64_t, uint64_t))(uintptr_t)a)(c->X[0], c->X[1], c->X[2], c->X[3]);
  c->X[0] = s == 6 || s == 11 ? (uint32_t)r : r;
  if (trace) fprintf(stderr, "gsw: host value witness %d -> %llx\n", s, (unsigned long long)c->X[0]);
}
/* the guest called native code with no bridge (and no ObjC method has it as IMP): a host value witness, recognised from
   the metadata argument it passes (slot s takes the metadata in x[MDREG[s]]) whose witness table is host memory. The
   slot it was called in, else -1 (not called) */
static int host_vwt_call(CPU* c, uint64_t a) {
  static const int MDREG[14] = {2, 1, 2, 2, 2, 2, 2, 3, -1, -1, -1, 1, 1, 2};
  for (int s = 0; s < 14; s++) {
    if (MDREG[s] < 0) continue;
    uint64_t md = c->X[MDREG[s]];
    if (!go::readable(md - 8, 8)) continue;                   /* guest or host metadata; a host VWT either way */
    uint64_t vwt = *(const uint64_t*)(uintptr_t)(md - 8);
    if (!go::readable(vwt + 8 * s, 8) || *(const uint64_t*)(uintptr_t)(vwt + 8 * s) != a) continue;   /* readable(): at most 16 bytes */
    if (s >= 11 && !(*(const uint32_t*)(uintptr_t)(vwt + 80) & GSW_VWT_ENUM)) continue;
    if (in_guest(vwt)) continue;                              /* a host VWT is the host's (image or runtime-instantiated), never guest data */
    if (trace) fprintf(stderr, "gsw: host value witness %d of %llx\n", s, (unsigned long long)md), trace_call("vwt", c);
    vwt_run(c, a, s);
    return s;
  }
  return -1;
}
using RegFn = void (*)(const void*, const void*);
static void reg(const char* fn, uint64_t at, uint64_t len) {
  if (!len) return;
  RegFn f = (RegFn)dlsym(RTLD_DEFAULT, fn);
  if (!f) die_name("the host Swift runtime is not loaded (no registration entry point)", fn);
  f((const void*)(uintptr_t)at, (const void*)(uintptr_t)(at + len));
}
/* dyld's Swift image callbacks for every guest image, after the ObjC classes and before any initializer */
static void map_images() {
  trace = getenv("GSW_TRACE") != nullptr;
  if (GSW_NEED_TRAMP) {                                       /* static record patches, or key path patterns to convert */
    CAPTR = GSW_NREL + GSW_TRAMP_DYN;
    size_t pg = (size_t)getpagesize(), code = ((size_t)CAPTR * GSW_TRAMP_SZ + pg - 1) & ~(pg - 1), data = ((size_t)CAPTR * 8 + pg - 1) & ~(pg - 1);
    unsigned char* t = (unsigned char*)mmap((void*)(uintptr_t)GSW_TRAMP_BASE, code + data, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (t != (unsigned char*)(uintptr_t)GSW_TRAMP_BASE) die("Swift trampoline area is not free at", GSW_TRAMP_BASE);
    TR_GUEST = (uint64_t*)calloc((size_t)CAPTR, 8); TR_SLOT = (uint64_t*)(uintptr_t)(t + code);
    for (int i = 0; i < CAPTR; i++) {                         /* jmp *slot(%rip); int3 padding */
      unsigned char* p = t + (size_t)i * GSW_TRAMP_SZ;
      int32_t d = (int32_t)((int64_t)(uintptr_t)&TR_SLOT[i] - (int64_t)(uintptr_t)(p + 6));
      p[0] = 0xFF; p[1] = 0x25; memcpy(p + 2, &d, 4); memset(p + 6, 0xCC, GSW_TRAMP_SZ - 6);
    }
    if (mprotect(t, code, PROT_READ | PROT_EXEC)) die("Swift trampoline mprotect failed", code);
    for (int i = 0; i < GSW_NREL; i++) {                      /* static records first: trampoline i stands for GSW_REL[i] */
      int32_t off; memcpy(&off, (const void*)(uintptr_t)GSW_REL[i].field, 4);
      tramp_field(GSW_REL[i].field, GSW_REL[i].field + (int64_t)off, GSW_REL[i].entry ? GSW_REL[i].entry : (const void*)&loud);
    }
  }
#ifdef GSW_HAVE_GEN
  for (int i = 0; i < GSW_NRO; i++) {                         /* class_ro_t the Swift runtime hands to libobjc for classes it builds */
    uint64_t ro = GSW_RO[i].ro;
    *(uint64_t*)(uintptr_t)(ro + 32) = go::host_methods(0, GSW_RO[i].meta, *(const uint64_t*)(uintptr_t)(ro + 32), nullptr);
    go::fix_protolist(*(const uint64_t*)(uintptr_t)(ro + 40));
  }
#endif
  for (int k = 0; k < NIMG; k++) {
    const GswSect& s = GSW_SECT[k];
    if (!s.ntypes && !s.nproto && !s.nprotos) continue;
    reg("swift_registerProtocols", s.protos, s.nprotos);
    reg("swift_registerTypeMetadataRecords", s.types, s.ntypes);
    reg("swift_registerProtocolConformances", s.proto, s.nproto);
  }
#ifdef GSW_HAVE_GEN
  for (int i = 0; i < GSW_NVWT; i++) { pthread_mutex_lock(&mu); patch_vwt(GSW_VWTS[i]); pthread_mutex_unlock(&mu); }
#endif
  for (int i = 0; i < GSW_NEAGER; i++) {                     /* non-generic structs and enums only (compiler-made accessors) */
    uint64_t req = 0;
    hostify_md(gd::call_guest<uint64_t, uint64_t>(GSW_EAGER[i].accessor, req));
  }
}
}  // namespace gsw

static void gswift_class_fix(uint64_t cls) { gsw::hostify_md(cls); }   /* gobjc: a guest Swift class was registered */
