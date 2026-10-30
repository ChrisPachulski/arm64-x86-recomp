/* gobjc.hpp: Objective-C and blocks for translated code (included by gbridge.hpp, after namespace gd).
   - objc_msgSend family: the IMP comes from the runtime (class_getMethodImplementation: +initialize, resolvers, caches). A
     guest IMP is entered directly on the caller's registers and stack, exactly as the arm64 objc_msgSend jumps to it (so
     variadic, va_list, HFA, array and packed arguments need no marshalling). A host IMP is called through libffi, typed
     from the runtime's type encoding of the method (x86-64 stret is libffi's hidden pointer); arguments are read per
     AAPCS64 (HFAs, indirect structs, Apple stack packing). Variadic host methods are known from the SDK headers (gdyld:
     GD_VMETH): nil-terminated object lists, and format methods whose variadic or va_list arguments are typed from the
     format string and passed natively, so the host formats them (locale, %S, embedded NULs). A forwarded selector runs
     the runtime's own protocol once: forwardingTargetForSelector:, methodSignatureForSelector:, forwardInvocation:.
   - Guest classes are registered in place: their class_t / metaclass become host classes through objc_readClassPair, with
     each method list rebuilt as typed closures that enter the guest IMP (guest categories of guest classes are merged in
     front, newest first, as the runtime's attachCategories orders them); the runtime then slides the ivars and writes the
     guest's own ivar offset variables. Selector refs are uniqued, guest protocols become host protocols (refs and lists
     are rewritten), categories of host classes attach through the runtime API, +load runs per image before that image's
     initializers.
   - Blocks: a guest block that reaches native code gets, in place, a typed invoke closure (from its signature, with
     BLOCK_USE_STRET set by the x86-64 rule) and host-callable copy/dispose helpers (byref keep/destroy likewise through
     _Block_object_assign), so the host's own block runtime copies and releases it. A host block the guest calls is typed
     from its signature in dispatch().
   - ObjC exceptions: a host exception that reaches a guest->host call (gbridge, typed handles) is rethrown inside the guest
     from that call site through the guest libc++abi (objc_exception layout and objc_ehtype_vtable as libobjc builds it), so
     guest @catch / @finally / ARC cleanups run; the guest personality, begin/end catch and rethrow are the guest
     libc++abi's. Every guest stack segment (callback entry, thread and main start) ends in a sentinel frame whose
     personality claims ObjC exceptions: they leave the segment as a host exception (objc_exception_throw), so host frames
     in between get their handlers, and an uncaught one ends in the host's uncaught-exception handler as natively. */
#include <objc/runtime.h>
#include <objc/message.h>
#include <objc/objc-exception.h>
#include <ffi/ffi.h>
#include <Block.h>
#include <mach/mach.h>

extern "C" {                                                  /* exported by libobjc, not in the public headers (gdyld's EXTRA_DECLS
                                                                 repeats the ARC ones so their imports get prototype bridges) */
Class objc_readClassPair(Class, const void*);
id objc_retain(id); void objc_release(id); id objc_autorelease(id); id objc_retainBlock(id);
id objc_retainAutoreleasedReturnValue(id); id objc_autoreleaseReturnValue(id); id objc_retainAutoreleaseReturnValue(id);
id objc_unsafeClaimAutoreleasedReturnValue(id); void* objc_autoreleasePoolPush(void); void objc_autoreleasePoolPop(void*);
}
static uint64_t guest_export(const char* nm, int from, int to);
static void gswift_class_fix(uint64_t cls);                   /* gswift.hpp */

namespace go {
using gd::Rd; using gd::Wr; using gd::Hfa;

static void* gzalloc(size_t n) { void* p = calloc(1, n ? n : 1); if (!p) die("gobjc: out of memory", n); return p; }
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;        /* inserts into the tables below; signature and closure caches */

/* insert-only open addressing, key 0 = empty; a value is published before its key, so readers need no lock */
enum { TAB_N = 1 << 16 };
struct Tab { uint64_t k[TAB_N], v[TAB_N]; int used; };
static unsigned th(uint64_t a) { return (unsigned)((a * 0x9E3779B97F4A7C15ULL) >> 48) & (TAB_N - 1); }
static uint64_t tget(const Tab& t, uint64_t key) {
  for (unsigned i = th(key);; i = (i + 1) & (TAB_N - 1)) {
    uint64_t k = __atomic_load_n(&t.k[i], __ATOMIC_ACQUIRE);
    if (!k) return 0;
    if (k == key) return __atomic_load_n(&t.v[i], __ATOMIC_ACQUIRE);
  }
}
static void tput(Tab& t, uint64_t key, uint64_t val) {        /* caller holds mu (or runs before any other thread) */
  unsigned i = th(key);
  while (t.k[i] && t.k[i] != key) i = (i + 1) & (TAB_N - 1);
  if (!t.k[i] && ++t.used > TAB_N / 2) die("gobjc: table full", (uint64_t)t.used);
  __atomic_store_n(&t.v[i], val, __ATOMIC_RELEASE); __atomic_store_n(&t.k[i], key, __ATOMIC_RELEASE);
}
static Tab CODE2G, G2C, REG, PMAP, LOADIMP, LOADED, HBLK, VMT, IMPSIG, IMPSEL, FPT, VRT;   /* see their uses */

/* ---- headless guard: a message to (or objc_alloc etc. of) a class defined in AppKit, Metal, MetalKit, MetalFX or
   MetalPerformanceShaders, a subclass of one (guest classes included), CAMetalLayer or CADisplayLink stops loudly before
   the runtime is asked for an IMP, so no +initialize, window-server connection or GPU device ever starts ---- */
static Tab UICLS;                                             /* class -> 1 clean, 2 blocked */
static const char* ui_class_walk(Class k) {
  for (; k; k = class_getSuperclass(k)) {
    const char* n = class_getName(k);
    if (!strcmp(n, "CAMetalLayer") || !strcmp(n, "CADisplayLink") || !strcmp(n, "CAMetalDisplayLink")) return n;
    if (ui_image(class_getImageName(k))) return n;
  }
  return nullptr;
}
static const char* ui_class(id self) {                        /* the blocked ancestor's name, or null */
  if (!GD_UI_GUARD) return nullptr;
  Class k = object_isClass(self) ? (Class)self : object_getClass(self);
  uint64_t v = tget(UICLS, (uint64_t)(uintptr_t)k);
  if (v == 1) return nullptr;
  const char* n = ui_class_walk(k);
  if (!v) { pthread_mutex_lock(&mu); tput(UICLS, (uint64_t)(uintptr_t)k, n ? 2 : 1); pthread_mutex_unlock(&mu); }
  return n;
}
[[noreturn]] static void ui_stop(id self, const char* blocked, const char* what) {
  bool cls = object_isClass(self);
  fprintf(stderr, "FATAL: blocked window-server / AppKit-UI / GPU entry point (headless translation): %s on %s %s (%s)\n", what,
          cls ? "class" : "an instance of", class_getName(cls ? (Class)self : object_getClass(self)), blocked);
  fflush(stderr); if (gd_die_hook) gd_die_hook(); _exit(70);
}
static void ui_check(uint64_t x0, const char* what) {         /* gdyld UI_RECV imports: the receiver/class in x0 */
  if (const char* n = x0 ? ui_class((id)(uintptr_t)x0) : nullptr) ui_stop((id)(uintptr_t)x0, n, what);
}
/* host-side routes a guest send starts: the host then messages another object (a target, an invocation's target, an
   observer, each element of a collection), so that object is checked before the send runs (the receiver already is) */
static id msg_id(id o, const char* sel);
static bool kind_of(id o, const char* cls) {
  Class k = objc_getClass(cls);
  return k && ((BOOL (*)(id, SEL, Class))objc_msgSend)(o, sel_registerName("isKindOfClass:"), k);
}
template<class F> void ui_elements(id coll, const char* what, F&& each) {   /* NSArray, NSSet, NSOrderedSet, NSHashTable... */
  id arr = coll;
  if (!kind_of(coll, "NSArray"))
    arr = class_respondsToSelector(object_getClass(coll), sel_registerName("allObjects")) ? msg_id(coll, "allObjects")
        : class_respondsToSelector(object_getClass(coll), sel_registerName("array")) ? msg_id(coll, "array") : nil;
  if (!arr) die_name("makeObjectsPerformSelector: on a collection whose elements cannot be listed (headless guard)", what);
  unsigned long n = ((unsigned long (*)(id, SEL))objc_msgSend)(arr, sel_registerName("count"));
  for (unsigned long i = 0; i < n; i++) {
    id el = ((id (*)(id, SEL, unsigned long))objc_msgSend)(arr, sel_registerName("objectAtIndex:"), i);
    ui_check((uint64_t)(uintptr_t)el, what);
    each(el);
  }
}

/* ---- type encodings -> size, alignment, AAPCS64 class (HFA), libffi type ----
   T_VAL: the x86-64 va_list parameter of a host method (an array of one __va_list_tag). co: code-pointer fields of a
   record, (offset << 1) | is-block. ldbl: holds a long double (guest 64-bit, host 80-bit x87). */
enum { T_VOID, T_INT, T_F32, T_F64, T_PTR, T_ID, T_BLK, T_FNP, T_REC, T_VAL, T_BAD };
enum { GSIG_MAX = 32, CO_MAX = 32 };
struct GT { int k, size, align; bool sgn, ldbl; Hfa h; ffi_type* ft; const char* why; int nco; const int* co; };
struct Sig { GT ret; int n; GT a[GSIG_MAX]; ffi_type* at[GSIG_MAX]; ffi_cif cif; const char* bad; char* enc; };
static GT tbad(const char* why, bool ldbl = false) { GT t{}; t.k = T_BAD; t.size = t.align = 8; t.ft = &ffi_type_pointer; t.why = why; t.ldbl = ldbl; return t; }
static GT tsc(int k, int size, bool sgn, ffi_type* ft) { GT t{}; t.k = k; t.size = t.align = size; t.sgn = sgn; t.ft = ft; return t; }
static Hfa hfa_of(const GT& t) { return t.k == T_F32 ? Hfa{4, 1} : t.k == T_F64 ? Hfa{8, 1} : t.k == T_REC ? t.h : Hfa{0, 0}; }
static void skip_digits(const char*& p) { while (*p == '-' || (*p >= '0' && *p <= '9')) p++; }
static long num(const char*& p) {                             /* an encoding's offset, LONG_MIN when absent */
  bool neg = *p == '-', any = false; long v = 0;
  if (neg) p++;
  while (*p >= '0' && *p <= '9') { v = v * 10 + (*p++ - '0'); any = true; }
  return any ? (neg ? -v : v) : LONG_MIN;
}
static void skip_quoted(const char*& p) { if (*p == '"') { p++; while (*p && *p != '"') p++; if (*p) p++; } }
static GT ptype(const char*& p);
static GT agg(GT* m, int nm, int reps) {                      /* a struct of nm members, or an array of reps x m[0] */
  int cnt = nm * reps, off = 0, al = 1, hb = 0, hn = 0, co[CO_MAX], nco = 0; bool hfa = true, ld = false, many = false;
  ffi_type** el = (ffi_type**)gzalloc((size_t)(cnt + 1) * sizeof(ffi_type*));
  for (int i = 0; i < cnt; i++) {
    const GT& e = m[i % nm];
    off = (off + e.align - 1) & ~(e.align - 1);
    if (e.k == T_FNP || e.k == T_BLK) { if (nco < CO_MAX) co[nco++] = off * 2 + (e.k == T_BLK); else many = true; }
    for (int j = 0; j < e.nco; j++) { if (nco < CO_MAX) co[nco++] = off * 2 + e.co[j]; else many = true; }
    ld = ld || e.ldbl;
    off += e.size; al = e.align > al ? e.align : al; el[i] = e.ft;
    Hfa h = hfa_of(e);
    if (!h.n || (hb && hb != h.base)) hfa = false; else { hb = h.base; hn += h.n; }
  }
  if (many) return tbad("struct with more than 32 code-pointer fields", ld);
  GT t{}; t.k = T_REC; t.align = al; t.size = (off + al - 1) & ~(al - 1); t.ldbl = ld;
  t.h = hfa && hn <= 4 && t.size == hn * hb ? Hfa{hb, hn} : Hfa{0, 0};
  ffi_type* ft = (ffi_type*)gzalloc(sizeof(ffi_type)); ft->type = FFI_TYPE_STRUCT; ft->elements = el; t.ft = ft;
  if (nco) { int* c = (int*)gzalloc(sizeof(int) * (size_t)nco); memcpy(c, co, sizeof(int) * (size_t)nco); t.co = c; t.nco = nco; }
  return t;
}
static GT trec(const char*& p, char close) {                  /* after '{' or '(' */
  while (*p && *p != '=' && *p != close) p++;
  if (*p != '=') { if (*p) p++; return tbad("opaque struct or union by value"); }
  p++;
  GT m[64]; int nm = 0; const char* why = nullptr; bool ld = false;
  while (*p && *p != close) {
    skip_quoted(p);
    if (!*p || *p == close) break;
    GT e = ptype(p);
    ld = ld || e.ldbl;
    if (e.k == T_BAD) why = e.why;
    if (nm < 64) m[nm++] = e; else why = "struct with more than 64 members";
  }
  if (*p) p++;
  if (close == ')') return tbad("union by value", ld);
  if (why) return tbad(why, ld);
  if (!nm) return tbad("empty struct by value");
  return agg(m, nm, 1);
}
static GT ptype(const char*& p) {
  while (*p && strchr("rnNoORVA+", *p)) p++;                  /* qualifiers: const, in/out, bycopy, oneway, _Atomic */
  char ch = *p ? *p++ : 0;
  switch (ch) {
    case 'c': return tsc(T_INT, 1, true, &ffi_type_sint8);
    case 'C': case 'B': return tsc(T_INT, 1, false, &ffi_type_uint8);
    case 's': return tsc(T_INT, 2, true, &ffi_type_sint16);
    case 'S': return tsc(T_INT, 2, false, &ffi_type_uint16);
    case 'i': case 'l': return tsc(T_INT, 4, true, &ffi_type_sint32);    /* 'l' is a 32-bit long in LP64 encodings */
    case 'I': case 'L': return tsc(T_INT, 4, false, &ffi_type_uint32);
    case 'q': return tsc(T_INT, 8, true, &ffi_type_sint64);
    case 'Q': return tsc(T_INT, 8, false, &ffi_type_uint64);
    case 'f': return tsc(T_F32, 4, false, &ffi_type_float);
    case 'd': return tsc(T_F64, 8, false, &ffi_type_double);
    case 'v': { GT t = tsc(T_VOID, 0, false, &ffi_type_void); t.align = 1; return t; }
    case '*': case ':': case '%': return tsc(T_PTR, 8, false, &ffi_type_pointer);
    case '#': return tsc(T_ID, 8, false, &ffi_type_pointer);
    case '@':
      if (*p == '?') {
        p++;
        if (*p == '<') for (int d = 0; *p; p++) { d += *p == '<'; d -= *p == '>'; if (!d) { p++; break; } }
        return tsc(T_BLK, 8, false, &ffi_type_pointer);
      }
      skip_quoted(p);
      return tsc(T_ID, 8, false, &ffi_type_pointer);
    case '^': {
      if (*p == '?') { p++; return tsc(T_FNP, 8, false, &ffi_type_pointer); }
      GT pt = ptype(p);                                       /* the pointee's layout must agree on both sides */
      if (pt.ldbl) return tbad("pointer to a long double (guest 64-bit, host 80-bit x87)");
      GT t = tsc(T_PTR, 8, false, &ffi_type_pointer);
      if (pt.k == T_REC) { t.nco = pt.nco; t.co = pt.co; }    /* the pointee's code-pointer fields */
      return t;
    }
    case '{': return trec(p, '}');
    case '(': return trec(p, ')');
    case '[': {
      long n = strtol(p, const_cast<char**>(&p), 10);
      GT e = ptype(p);
      if (*p == ']') p++;
      if (e.k == T_BAD) return e;
      if (n <= 0 || n > 4096) return tbad("array of unsupported length");
      return agg(&e, 1, (int)n);
    }
    case 'b': skip_digits(p); return tbad("bit-field");
    case 'D': return tbad("long double (guest 64-bit, host 80-bit x87)", true);
    case 'j': (void)ptype(p); return tbad("_Complex");
    default: return tbad("unknown type encoding");
  }
}
static GT top_arg(const char*& p) {                           /* a parameter: an array is passed as a pointer to it */
  const char* q = p;
  while (*q && strchr("rnNoORVA+", *q)) q++;
  if (*q != '[') return ptype(p);
  bool va = !strncmp(q, "[1{__va_list_tag", 16);              /* x86-64 va_list */
  GT e = ptype(p);
  if (e.ldbl) return tbad("pointer to a long double array (guest 64-bit, host 80-bit x87)");
  return tsc(va ? T_VAL : T_PTR, 8, false, &ffi_type_pointer);
}
static Sig* sig_parse(const char* enc) {
  Sig* s = (Sig*)gzalloc(sizeof(Sig));
  s->enc = strdup(enc);
  const char* p = enc;
  long off[GSIG_MAX + 1];
  s->ret = ptype(p); long total = num(p);
  if (s->ret.k == T_BAD) s->bad = s->ret.why;
  while (*p) {
    if (s->n == GSIG_MAX) { s->bad = "more than 32 arguments"; break; }
    GT t = top_arg(p); off[s->n] = num(p);
    if (t.k == T_BAD || t.k == T_VOID) s->bad = t.k == T_VOID ? "void argument" : t.why;
    s->at[s->n] = t.ft; s->a[s->n++] = t;
  }
  for (int i = 0; i < s->n && !s->bad; i++) {                 /* a by-value record narrower than its natural layout is packed */
    long nx = i + 1 < s->n ? off[i + 1] : total;
    /* a SIMD vector encodes as nothing ("v36@0:816i32"): its offset fuses with the previous one, so offsets stop rising */
    if (off[i] != LONG_MIN && ((total != LONG_MIN && off[i] > total) || (i && off[i - 1] != LONG_MIN && off[i] < off[i - 1])))
      s->bad = "an argument with an empty type encoding (a SIMD vector): no layout to marshal";
    else if (s->a[i].k == T_REC && off[i] != LONG_MIN && nx != LONG_MIN && nx > off[i] && nx - off[i] < s->a[i].size)
      s->bad = "packed struct by value (the type encoding gives no packed layout)";
    /* a record's offsets step by its exact size ("v20@0:8{?=c}16{?=[3c]}17"); a SIMD member encodes as nothing, so a
       record holding one steps further than its encoded members reach ("v48@0:8{?=i}16") */
    else if (s->a[i].k == T_REC && off[i] != LONG_MIN && nx != LONG_MIN && nx - off[i] > s->a[i].size)
      s->bad = "a record holding a SIMD vector by value (its encoding omits the vector: its offsets give more bytes than its members)";
  }
  if (!s->bad && ffi_prep_cif(&s->cif, FFI_DEFAULT_ABI, (unsigned)s->n, s->ret.ft, s->at) != FFI_OK) s->bad = "libffi refused the signature";
  return s;
}
struct SigNode { Sig* s; SigNode* next; };
enum { SIGB_N = 4096 };
static SigNode* SIGB[SIGB_N];
static Sig* sig_of(const char* enc) {                         /* one parsed signature per distinct encoding string */
  unsigned h = 2166136261u;
  for (const char* q = enc; *q; q++) h = (h ^ (unsigned char)*q) * 16777619u;
  pthread_mutex_lock(&mu);                                    /* ponytail: one lock per host send; per-(class, sel) cache if hot */
  SigNode* n = SIGB[h & (SIGB_N - 1)];
  while (n && strcmp(n->s->enc, enc)) n = n->next;
  if (!n) { n = (SigNode*)gzalloc(sizeof(SigNode)); n->s = sig_parse(enc); n->next = SIGB[h & (SIGB_N - 1)]; SIGB[h & (SIGB_N - 1)] = n; }
  pthread_mutex_unlock(&mu);
  return n->s;
}
/* GD_VECREC (gdyld, from the framework and extra host headers): methods whose header type has a record holding a SIMD
   vector. The encoding drops the vector (struct { simd_float4 v; int tag; } is "{?=i}") and a return carries no offset
   that would show it, so these are matched by selector and encoding (both without offsets or qualifiers, as gdyld
   enc_key) and refused loudly */
static void enc_key(const char* e, char* k, size_t n) {
  size_t o = 0;
  for (; *e && o + 1 < n; e++) if (!(*e >= '0' && *e <= '9') && !strchr("rnNoORV+", *e)) k[o++] = *e;
  k[o] = 0;
}
static bool vec_rec(SEL sel, const char* enc) {
  uint64_t i = sel ? tget(VRT, (uint64_t)(uintptr_t)sel) : 0;
  if (!i) return false;
  char k[4096]; enc_key(enc, k, sizeof k);
  for (int j = (int)i - 1; j < GD_NVECREC && sel_registerName(GD_VECREC[j].sel) == sel; j++) if (!strcmp(GD_VECREC[j].key, k)) return true;
  return false;
}
static Sig* sig_sel(SEL sel, const char* enc) {               /* sig_of for method `sel`, refused when GD_VECREC lists it */
  Sig* s = sig_of(enc);
  if (s->bad || !vec_rec(sel, enc)) return s;
  Sig* b = (Sig*)gzalloc(sizeof(Sig)); *b = *s;               /* a refused copy: its cif is never used */
  b->bad = "a record holding a SIMD vector (its header type; the encoding omits the vector, so no layout to marshal)";
  return b;
}

/* ---- values: guest CPU (AAPCS64) <-> host memory in the encoded type ---- */
static uint64_t ext(const GT& t, const void* p) {             /* an integer of t.size bytes, widened to 64 bits */
  switch (t.size) {
    case 1: return t.sgn ? (uint64_t)(int64_t)*(const int8_t*)p : *(const uint8_t*)p;
    case 2: return t.sgn ? (uint64_t)(int64_t)*(const int16_t*)p : *(const uint16_t*)p;
    case 4: return t.sgn ? (uint64_t)(int64_t)*(const int32_t*)p : *(const uint32_t*)p;
    default: return *(const uint64_t*)p;
  }
}
static void rd_arg(Rd& r, const GT& t, void* d) {
  if (t.k == T_INT) {
    if (r.g < 8) memcpy(d, &r.c->X[r.g++], (size_t)t.size);
    else memcpy(d, (const void*)(uintptr_t)gd::rd_stk(r, (uint64_t)t.size, (uint64_t)t.size), (size_t)t.size);
  } else if (t.k == T_F32 || t.k == T_F64) {
    if (r.v < 8) memcpy(d, &r.c->V[r.v++], (size_t)t.size);
    else memcpy(d, (const void*)(uintptr_t)gd::rd_stk(r, (uint64_t)t.size, (uint64_t)t.size), (size_t)t.size);
  } else if (t.k == T_REC) gd::rd_agg(r, d, (unsigned long)t.size, (unsigned long)t.align, t.h);
  else { uint64_t v = gd::rd_x(r); memcpy(d, &v, 8); }
}
static void wr_arg(Wr& w, const GT& t, const void* s) {
  if (t.k == T_INT) {
    uint64_t u = ext(t, s);
    if (w.g < 8) w.c->X[w.g++] = u; else memcpy((void*)(uintptr_t)gd::wr_stk(w, (uint64_t)t.size, (uint64_t)t.size), &u, (size_t)t.size);
  } else if (t.k == T_F32 || t.k == T_F64) {
    if (w.v < 8) { memset(&w.c->V[w.v], 0, 16); memcpy(&w.c->V[w.v++], s, (size_t)t.size); }
    else memcpy((void*)(uintptr_t)gd::wr_stk(w, (uint64_t)t.size, (uint64_t)t.size), s, (size_t)t.size);
  } else if (t.k == T_REC) gd::wr_agg(w, s, (unsigned long)t.size, (unsigned long)t.align, t.h);
  else gd::wr_x(w, t.k == T_PTR ? gd::unshadow(*(const uint64_t*)s) : *(const uint64_t*)s);   /* a struct shadow: the guest's own */
}
static void ret_to_guest(CPU* c, const GT& t, const void* rv) {
  switch (t.k) {
    case T_VOID: break;
    case T_INT: c->X[0] = ext(t, rv); break;
    case T_F32: case T_F64: memset(&c->V[0], 0, 16); memcpy(&c->V[0], rv, (size_t)t.size); break;
    case T_REC: gd::ret_agg(c, rv, (unsigned long)t.size, t.h); break;
    case T_FNP: {                                             /* a closure of guest code: the guest's own function again */
      uint64_t v = *(const uint64_t*)rv, g = rev_find(v);
      if (!g) g = ::gobjc_target(v);
      c->X[0] = g ? g : v; break;
    }
    case T_PTR: c->X[0] = gd::unshadow(*(const uint64_t*)rv); break;
    default: c->X[0] = *(const uint64_t*)rv;
  }
}
static void nil_ret(CPU* c) { c->X[0] = c->X[1] = 0; for (int i = 0; i < 4; i++) memset(&c->V[i], 0, 16); }

/* ---- blocks ---- */
struct Lit { void* isa; int32_t flags, res; uint64_t invoke; uint64_t* desc; };
struct Byref { void* isa; Byref* fwd; int32_t flags; uint32_t size; uint64_t keep, destroy; };
enum { BF_COPY_DISPOSE = 1 << 25, BF_STRET = 1 << 29, BF_SIG = 1 << 30, FIELD_BLOCK = 7, FIELD_BYREF = 8 };
using CopyH = void (*)(void*, const void*);
using DispH = void (*)(const void*);
static void* BLKCLS[3];                                       /* stack, global, malloc block classes */
static bool blk_isa(const void* isa) { return isa && (isa == BLKCLS[0] || isa == BLKCLS[1] || isa == BLKCLS[2]); }
static bool is_blk(uint64_t p) { return p >= 4096 && !(p & 1) && !(p >> 63) && blk_isa(*(void* const*)(uintptr_t)p); }
static const char* blk_sig(const Lit* b) {
  return b->flags & BF_SIG ? (const char*)(uintptr_t)b->desc[b->flags & BF_COPY_DISPOSE ? 4 : 2] : nullptr;
}
static void* clo_get(Sig* s, uint64_t g);
static bool x86_stret(const GT& t) { return t.k == T_REC && t.size > 16; }   /* SysV MEMORY class (packed records are refused) */
static void hostify_blk(uint64_t p) {                         /* in place: typed invoke closure, host-callable helpers */
  if (!is_blk(p)) return;
  Lit* b = (Lit*)(uintptr_t)p;
  uint64_t inv = __atomic_load_n(&b->invoke, __ATOMIC_ACQUIRE);
  if (!in_guest(inv)) return;
  if (b->flags & BF_COPY_DISPOSE) {
    uint64_t* d = b->desc;
    if (in_guest(d[2])) __atomic_store_n(&d[2], (uint64_t)(uintptr_t)gd::to_host_fn<CopyH>(d[2]), __ATOMIC_RELEASE);
    if (in_guest(d[3])) __atomic_store_n(&d[3], (uint64_t)(uintptr_t)gd::to_host_fn<DispH>(d[3]), __ATOMIC_RELEASE);
  }
  const char* sg = blk_sig(b);
  if (!sg) die("a guest block without a signature reaches native code; invoke", inv);
  Sig* s = sig_of(sg);
  if (s->bad) die_name("a guest block whose signature has no AAPCS64 mapping reaches native code", s->enc);
  /* arm64 never sets BLOCK_USE_STRET (x8 carries the result); the host's imp_implementationWithBlock picks its trampoline by it */
  if (x86_stret(s->ret)) __atomic_fetch_or(&b->flags, (int32_t)BF_STRET, __ATOMIC_RELAXED);
  else __atomic_fetch_and(&b->flags, ~(int32_t)BF_STRET, __ATOMIC_RELAXED);
  __atomic_store_n(&b->invoke, (uint64_t)(uintptr_t)clo_get(s, inv), __ATOMIC_RELEASE);
}
static void hostify_byref(uint64_t p) {                       /* __block variable: keep/destroy helpers */
  Byref* r = (Byref*)(uintptr_t)p;
  Byref* both[2] = {r, r ? r->fwd : nullptr};
  for (Byref* x : both)
    if (x && (x->flags & BF_COPY_DISPOSE)) {
      if (in_guest(x->keep)) x->keep = (uint64_t)(uintptr_t)gd::to_host_fn<CopyH>(x->keep);
      if (in_guest(x->destroy)) x->destroy = (uint64_t)(uintptr_t)gd::to_host_fn<DispH>(x->destroy);
    }
}
/* a value about to reach native code: guest blocks (also inside an id, or a record field) become host-callable; guest code
   in a function-pointer field or parameter would be executed natively, so it stops here */
static void to_native(const GT& t, const void* d) {
  if (t.k == T_ID || t.k == T_BLK) hostify_blk(*(const uint64_t*)d);
  else if (t.k == T_FNP && guest_code(*(const uint64_t*)d)) die("guest code passed to native code as an untyped function pointer (^?)", *(const uint64_t*)d);
  else if (t.k == T_REC || (t.k == T_PTR && t.nco && *(const uint64_t*)d))
    for (int j = 0; j < t.nco; j++) {
      const char* base = t.k == T_REC ? (const char*)d : (const char*)(uintptr_t)*(const uint64_t*)d;
      uint64_t v; memcpy(&v, base + (t.co[j] >> 1), 8);
      if (t.co[j] & 1) hostify_blk(v);
      else if (guest_code(v)) die("guest code passed to native code in a struct's untyped function-pointer field (^?)", v);
    }
}

/* ARC return handoff in the guest, libobjc's arm64 rule: objc_autoreleaseReturnValue whose lr holds the `mov x29, x29`
   marker (the caller will claim the result next) leaves the object +1 in tls_handoff instead of autoreleasing it, and the
   caller's objc_retainAutoreleasedReturnValue takes it. Guest methods (entered directly by send) and C functions alike;
   a segment's first frame returns to GD_SENTINEL (no marker), so a host caller always gets an autoreleased object. */
static __thread uint64_t tls_handoff;
enum : uint32_t { ARC_MARKER = 0xaa1d03fdu };                 /* mov x29, x29 */
static bool arc_marker(uint64_t lr) { return in_guest(lr) && *(const uint32_t*)(uintptr_t)lr == ARC_MARKER; }

/* ---- host -> guest: typed closures (methods, block invokes) ---- */
struct Clo { Sig* s; uint64_t g; void* code; };
struct CloNode { Sig* s; void* code; CloNode* next; };
static void clo_handler(ffi_cif*, void* ret, void** args, void* ud) {
  const Clo* k = (const Clo*)ud;
  const Sig* s = k->s;
  const GT& rt = s->ret;
  bool sret = rt.k == T_REC && !rt.h.n && rt.size > 16;       /* the guest builds it at x8: the host's result memory */
  alignas(16) unsigned char tmp[16];
  CPU nc;
  gd::enter_guest_w(nc, sret ? ret : (void*)tmp, k->g, [&](Wr& w) { for (int i = 0; i < s->n; i++) wr_arg(w, s->a[i], args[i]); });
  switch (rt.k) {
    case T_VOID: break;
    case T_INT: { uint64_t v = ext(rt, &nc.X[0]); memcpy(ret, &v, 8); break; }   /* libffi: a full ffi_arg */
    case T_F32: case T_F64: memcpy(ret, &nc.V[0], (size_t)rt.size); break;
    case T_REC:
      if (rt.h.n) for (int i = 0; i < rt.h.n; i++) memcpy((char*)ret + i * rt.h.base, &nc.V[i], (size_t)rt.h.base);
      else if (rt.size <= 16) memcpy(ret, &nc.X[0], (size_t)rt.size);
      to_native(rt, ret);
      break;
    default: to_native(rt, &nc.X[0]); memcpy(ret, &nc.X[0], 8);
  }
}
static void clo_bad(ffi_cif*, void*, void**, void* ud) {      /* host -> guest method with no AAPCS64 mapping */
  const Clo* k = (const Clo*)ud;
  fprintf(stderr, "FATAL: native code called a guest method or block whose type encoding %s has no AAPCS64 mapping: %s\n", k->s->enc, k->s->bad);
  fflush(stderr); if (gd_die_hook) gd_die_hook(); _exit(70);
}
static void* clo_get(Sig* s, uint64_t g) {                    /* one libffi closure per (guest code, signature) */
  static ffi_cif vcif; static bool vready;
  pthread_mutex_lock(&mu);
  if (!vready) { ffi_prep_cif(&vcif, FFI_DEFAULT_ABI, 0, &ffi_type_void, nullptr); vready = true; }
  CloNode* n = (CloNode*)(uintptr_t)tget(G2C, g);
  for (; n; n = n->next) if (n->s == s) break;
  if (!n) {
    void* code = nullptr;
    ffi_closure* cl = (ffi_closure*)ffi_closure_alloc(sizeof(ffi_closure), &code);
    Clo* k = (Clo*)gzalloc(sizeof(Clo)); k->s = s; k->g = g; k->code = code;
    if (!cl || ffi_prep_closure_loc(cl, s->bad ? &vcif : &s->cif, s->bad ? clo_bad : clo_handler, k, code) != FFI_OK)
      die("libffi closure allocation failed", g);
    n = (CloNode*)gzalloc(sizeof(CloNode)); n->s = s; n->code = code; n->next = (CloNode*)(uintptr_t)tget(G2C, g);
    tput(G2C, g, (uint64_t)(uintptr_t)n); tput(CODE2G, (uint64_t)(uintptr_t)code, g);
  }
  pthread_mutex_unlock(&mu);
  return n->code;
}
static uint64_t clo_target(uint64_t a) { return tget(CODE2G, a); }   /* closure code -> its guest code, 0 if not ours */

/* GD_FPARAM (gdyld, from the SDK headers): a method parameter the encoding calls ^? has a function type in its header, so
   guest code there becomes a closure of that type (sortedArrayUsingFunction:context:); without a row it stays a loud stop */
static const FParam* fparam(Class cls, SEL sel, int arg) {
  uint64_t i = cls && sel ? tget(FPT, (uint64_t)(uintptr_t)sel) : 0;
  for (int j = (int)i - 1; i && j < GD_NFPARAM && sel_registerName(GD_FPARAM[j].sel) == sel; j++) {
    const FParam& f = GD_FPARAM[j];
    if (f.arg != arg || f.cmeth != (int)class_isMetaClass(cls)) continue;
    if (!*f.cls) return &f;                                   /* declared by a protocol */
    for (Class k = cls; k; k = class_getSuperclass(k)) if (!strcmp(class_getName(k), f.cls)) return &f;
  }
  return nullptr;
}
static void fn_arg(const GT& t, void* d, Class cls, SEL sel, int i) {   /* i: encoding index (self, _cmd, then parameters) */
  uint64_t v;
  if (t.k != T_FNP || i < 2) return;
  memcpy(&v, d, 8);
  if (!guest_code(v)) return;
  if (const FParam* f = fparam(cls, sel, i - 2)) { v = f->mk(v); memcpy(d, &v, 8); }
}

/* ---- guest -> host: one typed call through libffi (cls, sel: the method, when known) ---- */
static void host_call(CPU* c, void* fn, const Sig* s, const char* what, Class cls = Nil, SEL sel = nullptr) {
  if (s->bad) { fprintf(stderr, "FATAL: %s: type encoding %s: %s\n", what, s->enc, s->bad); fflush(stderr); if (gd_die_hook) gd_die_hook(); _exit(70); }
  Rd r{c, 0, 0, c->SP, -1};
  alignas(16) unsigned char store[GSIG_MAX][32];
  void* av[GSIG_MAX];
  for (int i = 0; i < s->n; i++) {
    const GT& t = s->a[i];
    if (t.k == T_VAL) die_name("a va_list parameter of a method that is not a known format method (no conversion)", what);
    void* d = t.size <= 32 ? (void*)store[i] : __builtin_alloca(((size_t)t.size + 15) & ~(size_t)15);
    rd_arg(r, t, d); av[i] = d;
    fn_arg(t, d, cls, sel, i);
    to_native(t, d);
  }
  alignas(16) unsigned char rbuf[64];
  void* rv = s->ret.size > 48 ? __builtin_alloca(((size_t)s->ret.size + 15) & ~(size_t)15) : (void*)rbuf;
  ffi_call(const_cast<ffi_cif*>(&s->cif), FFI_FN(fn), rv, av);
  ret_to_guest(c, s->ret, rv);
}
/* the guest branched to native code with no bridge: if x0 is a block whose invoke is that address, call it typed */
static bool host_block_call(CPU* c, uint64_t a) {
  const char* sg = (const char*)(uintptr_t)tget(HBLK, a);
  if (!sg) {
    Lit b; vm_size_t got = 0;
    if (vm_read_overwrite(mach_task_self(), (vm_address_t)c->X[0], sizeof b, (vm_address_t)&b, &got) != KERN_SUCCESS || got != sizeof b) return false;
    if (!blk_isa(b.isa) || b.invoke != a) return false;
    if (!(sg = blk_sig(&b))) die("the guest calls a host block without a signature; invoke", a);
    pthread_mutex_lock(&mu); tput(HBLK, a, (uint64_t)(uintptr_t)sg); pthread_mutex_unlock(&mu);
  }
  TlsRestore g{tls_cur}; tls_cur = c;
  host_call(c, (void*)(uintptr_t)a, sig_of(sg), "host block called by the guest");
  return true;
}

/* ---- variadic host arguments: typed by a format string, passed natively ----
   Apple arm64 gives every variadic argument its own 8-byte stack slot (long double is a double), so argument N is slot N-1
   whatever its type; the format names the type the host callee will va_arg. */
enum { FA_I32 = 1, FA_I64, FA_DBL, FA_LDBL, FA_PTR, FA_MAX = 128 };
struct FArgs { int n; unsigned char ty[FA_MAX]; uint64_t v[FA_MAX]; };
static void fa_set(FArgs& a, int pos, int ty, const char* f) {
  if (pos < 0 || pos >= FA_MAX) die_name("format: argument position out of range", f);
  if (a.ty[pos] && a.ty[pos] != ty) die_name("format: one argument position with two types", f);
  a.ty[pos] = (unsigned char)ty;
  if (pos + 1 > a.n) a.n = pos + 1;
}
static int fa_pos(const char*& f) {                           /* "N$" -> N-1, else -1 (f unchanged) */
  const char* q = f; int v = 0;
  while (*q >= '0' && *q <= '9') v = v * 10 + (*q++ - '0');
  if (*q == '$' && q > f && v) { f = q + 1; return v - 1; }
  return -1;
}
/* NSString / CFString / NSPredicate format conversions -> argument types; the values come from the guest slots */
static void fmt_args(const char* fmt, const uint64_t* va, FArgs& a) {
  memset(&a, 0, sizeof a);
  int next = 0;
  for (const char* f = fmt; f && *f;) {
    if (*f++ != '%') continue;
    if (*f == '%') { f++; continue; }
    int pos = fa_pos(f);
    while (*f && strchr("-+ #0'", *f)) f++;
    for (int wp = 0; wp < 2; wp++) {                          /* width, then precision */
      if (wp) { if (*f != '.') break; f++; }
      if (*f == '*') { f++; int p = fa_pos(f); fa_set(a, p >= 0 ? p : next++, FA_I32, fmt); }
      else while (*f >= '0' && *f <= '9') f++;
    }
    int l = 0; bool L = false;
    while (*f && strchr("hlLqjzt", *f)) { l += *f != 'h'; L = L || *f == 'L'; f++; }
    char cv = *f;
    if (!cv) die_name("format: truncated conversion", fmt);
    f++;
    int ty = strchr("diouxXDOUcC", cv) ? (l && !strchr("cC", cv) ? FA_I64 : FA_I32)
           : strchr("eEfFgGaA", cv) ? (L ? FA_LDBL : FA_DBL)
           : strchr("sSp@Kn", cv) ? FA_PTR : 0;
    if (!ty) die_name("format: unsupported conversion", fmt);
    fa_set(a, pos >= 0 ? pos : next++, ty, fmt);
  }
  for (int i = 0; i < a.n; i++) { if (!a.ty[i]) a.ty[i] = FA_I64; a.v[i] = va[i]; }
}
static ffi_type* fa_ffi(int ty) {
  return ty == FA_I32 ? &ffi_type_sint32 : ty == FA_I64 ? &ffi_type_sint64 : ty == FA_DBL ? &ffi_type_double
       : ty == FA_LDBL ? &ffi_type_longdouble : &ffi_type_pointer;
}
union FaVal { int32_t i; int64_t q; double d; long double ld; void* p; };
static void fa_val(const FArgs& a, int i, FaVal& v) {
  double d; memcpy(&d, &a.v[i], 8);
  switch (a.ty[i]) {
    case FA_I32: v.i = (int32_t)a.v[i]; break;
    case FA_DBL: v.d = d; break;
    case FA_LDBL: v.ld = (long double)d; break;
    default: v.q = (int64_t)a.v[i];
  }
}
/* an x86-64 va_list whose every argument is in the overflow area (gp_offset 48, fp_offset 176: registers used up) */
struct NVa { unsigned gp, fp; void* ovf; void* reg; };
struct NVaBuf { NVa tag; alignas(16) uint64_t area[2 * FA_MAX]; };
static gd::VaPtr fa_valist(const FArgs& a, NVaBuf& b) {
  size_t o = 0;
  for (int i = 0; i < a.n; i++) {
    FaVal v; fa_val(a, i, v);
    if (a.ty[i] == FA_LDBL) { o = (o + 1) & ~(size_t)1; memcpy(&b.area[o], &v.ld, 16); o += 2; }
    else { uint64_t u = a.ty[i] == FA_I32 ? (uint64_t)(int64_t)v.i : (uint64_t)v.q; b.area[o++] = u; }
  }
  b.tag = NVa{48, 176, b.area, b.area};
  return reinterpret_cast<gd::VaPtr>(&b.tag);
}

/* ---- message sends ---- */
static id msg_id(id o, const char* sel) { return ((id (*)(id, SEL))objc_msgSend)(o, sel_registerName(sel)); }
static const char* utf8(id s) { return s ? ((const char* (*)(id, SEL))objc_msgSend)(s, sel_registerName("UTF8String")) : nullptr; }
/* GD_VMETH (gdyld, from the SDK headers): variadic and va_list methods of host classes, sorted by selector */
enum { VK_NIL = 1, VK_FMT, VK_VAL, VK_UNK };
static const VMeth* vmeth(Class cls, SEL sel) {
  uint64_t i = tget(VMT, (uint64_t)(uintptr_t)sel);
  if (!i) return nullptr;
  for (int j = (int)i - 1; j < GD_NVMETH && sel_registerName(GD_VMETH[j].sel) == sel; j++) {
    const VMeth& v = GD_VMETH[j];
    if (v.cmeth != (int)class_isMetaClass(cls)) continue;
    if (!*v.cls) return &v;                                   /* declared by a protocol */
    for (Class k = cls; k; k = class_getSuperclass(k)) if (!strcmp(class_getName(k), v.cls)) return &v;
  }
  return nullptr;
}
static void var_send(CPU* c, void* fn, const Sig* s, const VMeth* v, const char* name, Class cls, SEL sel) {
  if (s->bad) { fprintf(stderr, "FATAL: %s: type encoding %s: %s\n", name, s->enc, s->bad); fflush(stderr); if (gd_die_hook) gd_die_hook(); _exit(70); }
  if (v->kind == VK_UNK) die_name("variadic host method whose argument types are unknown (no format or nil terminator)", name);
  Rd r{c, 0, 0, c->SP, -1};
  alignas(16) unsigned char store[GSIG_MAX][32];
  void* av[GSIG_MAX + FA_MAX]; ffi_type* at[GSIG_MAX + FA_MAX];
  for (int i = 0; i < s->n; i++) {
    if (s->a[i].size > 32) die_name("variadic host method with a large struct argument", name);
    rd_arg(r, s->a[i], store[i]); av[i] = store[i]; at[i] = s->at[i];
    fn_arg(s->a[i], store[i], cls, sel, i);
    if (s->a[i].k != T_VAL) to_native(s->a[i], store[i]);
  }
  const uint64_t* va = (const uint64_t*)(uintptr_t)((r.sa + 7) & ~7ULL);
  FArgs fa; fa.n = 0;
  int fi = v->kind == VK_NIL ? -1 : v->fmt + 1;               /* encoding index: self, _cmd, then the parameters */
  if (fi >= s->n || (fi >= 0 && s->a[fi].k != T_ID)) die_name("variadic host method: the format parameter is not an object", name);
  const char* fmt = fi >= 0 ? utf8(*(id*)store[fi]) : nullptr;
  if (v->kind == VK_VAL) {
    int vi = v->va + 1;
    if (vi >= s->n || s->a[vi].k != T_VAL) die_name("va_list host method: unexpected signature", name);
    fmt_args(fmt, (const uint64_t*)(uintptr_t)*(const uint64_t*)store[vi], fa);
    NVaBuf b;
    gd::VaPtr p = fa_valist(fa, b);
    memcpy(store[vi], &p, 8);
    alignas(16) unsigned char rbuf[64];
    void* rv = s->ret.size > 48 ? __builtin_alloca(((size_t)s->ret.size + 15) & ~(size_t)15) : (void*)rbuf;
    ffi_call(const_cast<ffi_cif*>(&s->cif), FFI_FN(fn), rv, av);
    ret_to_guest(c, s->ret, rv);
    return;
  }
  if (v->kind == VK_NIL) {                                    /* object list up to and including the nil */
    if (*(const uint64_t*)store[s->n - 1])
      for (int i = 0;; i++) {
        if (i == FA_MAX) die_name("nil-terminated list longer than 128 objects", name);
        fa.ty[i] = FA_PTR; fa.v[i] = va[i]; fa.n = i + 1; hostify_blk(va[i]);
        if (!va[i]) break;
      }
  } else fmt_args(fmt, va, fa);
  FaVal vals[FA_MAX];
  for (int i = 0; i < fa.n; i++) { fa_val(fa, i, vals[i]); av[s->n + i] = &vals[i]; at[s->n + i] = fa_ffi(fa.ty[i]); }
  ffi_cif cif;
  if (ffi_prep_cif_var(&cif, FFI_DEFAULT_ABI, (unsigned)s->n, (unsigned)(s->n + fa.n), s->ret.ft, at) != FFI_OK)
    die_name("libffi refused a variadic signature", s->enc);
  alignas(16) unsigned char rbuf[64];
  void* rv = s->ret.size > 48 ? __builtin_alloca(((size_t)s->ret.size + 15) & ~(size_t)15) : (void*)rbuf;
  ffi_call(&cif, FFI_FN(fn), rv, av);
  ret_to_guest(c, s->ret, rv);
}
static Sig* ms_sig(id ms) {                                   /* an NSMethodSignature -> its Sig (types without offsets) */
  char buf[2048]; size_t o = 0;
  auto add = [&](const char* t) { size_t n = strlen(t); if (o + n + 1 > sizeof buf) die("forwarding signature too long", n); memcpy(buf + o, t, n); o += n; };
  add(((const char* (*)(id, SEL))objc_msgSend)(ms, sel_registerName("methodReturnType")));
  unsigned long na = ((unsigned long (*)(id, SEL))objc_msgSend)(ms, sel_registerName("numberOfArguments"));
  for (unsigned long i = 0; i < na; i++) add(((const char* (*)(id, SEL, unsigned long))objc_msgSend)(ms, sel_registerName("getArgumentTypeAtIndex:"), i));
  buf[o] = 0;
  return sig_of(buf);
}
struct MIc;
static void send(CPU* c, int sup, MIc* ic = nullptr);
/* a selector the class does not implement: the runtime's forwarding (CoreFoundation ___forwarding___), each hook once */
static void fwd_send(CPU* c, id self, SEL sel) {
  Class rc = object_getClass(self);
  SEL ft = sel_registerName("forwardingTargetForSelector:"), msfs = sel_registerName("methodSignatureForSelector:");
  if (class_respondsToSelector(rc, ft)) {
    id t = ((id (*)(id, SEL, SEL))objc_msgSend)(self, ft, sel);
    if (t && t != self) { c->X[0] = (uint64_t)(uintptr_t)t; send(c, 0); return; }
  }
  id ms = class_respondsToSelector(rc, msfs) ? ((id (*)(id, SEL, SEL))objc_msgSend)(self, msfs, sel) : nil;
  if (!ms) {
    ((void (*)(id, SEL, SEL))objc_msgSend)(self, sel_registerName("doesNotRecognizeSelector:"), sel);   /* raises */
    nil_ret(c); return;
  }
  Sig* s = ms_sig(ms);
  if (s->bad || s->n < 2) { fprintf(stderr, "FATAL: forwarded %s: type encoding %s: %s\n", sel_getName(sel), s->enc, s->bad ? s->bad : "no receiver"); fflush(stderr); if (gd_die_hook) gd_die_hook(); _exit(70); }
  if (!class_respondsToSelector(rc, sel_registerName("forwardInvocation:"))) { nil_ret(c); return; }   /* the runtime drops it */
  id inv = ((id (*)(id, SEL, id))objc_msgSend)((id)objc_getClass("NSInvocation"), sel_registerName("invocationWithMethodSignature:"), ms);
  ((void (*)(id, SEL, id))objc_msgSend)(inv, sel_registerName("setTarget:"), self);
  ((void (*)(id, SEL, SEL))objc_msgSend)(inv, sel_registerName("setSelector:"), sel);
  Rd r{c, 0, 0, c->SP, -1};
  SEL setarg = sel_registerName("setArgument:atIndex:");
  for (int i = 0; i < s->n; i++) {
    const GT& t = s->a[i];
    if (t.k == T_VAL) die_name("forwarded message with a va_list parameter", sel_getName(sel));
    void* d = __builtin_alloca(((size_t)t.size + 15) & ~(size_t)15);
    rd_arg(r, t, d);
    if (i >= 2) { fn_arg(t, d, rc, sel, i); to_native(t, d); ((void (*)(id, SEL, void*, long))objc_msgSend)(inv, setarg, d, i); }
  }
  ((void (*)(id, SEL, id))objc_msgSend)(self, sel_registerName("forwardInvocation:"), inv);
  if (s->ret.k == T_VOID) return;
  void* rv = __builtin_alloca(((size_t)s->ret.size + 15) & ~(size_t)15);
  ((void (*)(id, SEL, void*))objc_msgSend)(inv, sel_registerName("getReturnValue:"), rv);
  ret_to_guest(c, s->ret, rv);
}
/* argument i (encoding index: self, _cmd, then parameters) of a send the guard looks into, raw when it is an object or a
   selector, else 0: read per AAPCS64 from the guest's registers and stack (a host method about to run), from an
   NSInvocation, or from a list (the withObject: arguments a performSelector: passes on) */
struct UiArgs { CPU* c; const Sig* s; id inv; const uint64_t* v; int nv; };
static uint64_t ui_arg(const UiArgs& a, int i) {
  if (a.c) {
    if (i >= a.s->n) return 0;
    Rd r{a.c, 0, 0, a.c->SP, -1};
    uint64_t v = 0;
    for (int j = 0; j <= i; j++) {
      void* d = __builtin_alloca(((size_t)a.s->a[j].size + 15) & ~(size_t)15);
      rd_arg(r, a.s->a[j], d);
      if (j == i) memcpy(&v, d, 8);
    }
    return a.s->a[i].k == T_ID || a.s->a[i].k == T_PTR ? v : 0;
  }
  if (a.inv) {
    id ms = msg_id(a.inv, "methodSignature");
    if (!ms || (unsigned long)i >= ((unsigned long (*)(id, SEL))objc_msgSend)(ms, sel_registerName("numberOfArguments"))) return 0;
    const char* t = ((const char* (*)(id, SEL, unsigned long))objc_msgSend)(ms, sel_registerName("getArgumentTypeAtIndex:"), (unsigned long)i);
    while (*t && strchr("rnNoORV", *t)) t++;
    if (*t != '@' && *t != ':' && *t != '#') return 0;
    uint64_t v = 0;
    ((void (*)(id, SEL, void*, long))objc_msgSend)(a.inv, sel_registerName("getArgument:atIndex:"), &v, i);
    return v;
  }
  return i >= 2 && i - 2 < a.nv ? a.v[i - 2] : 0;
}
static bool kw_is(const char* k, size_t n, const char* w) { return n == strlen(w) && !strncmp(k, w, n); }
static bool kw_ends(const char* k, size_t n, const char* w) { size_t m = strlen(w); return n >= m && !strncmp(k + n - m, w, m); }
/* host-side routes a guest send starts: the host method then messages another object (a target, an invocation's target, an
   observer, each element of a collection) or its receiver again (the performSelector: family), so that object is checked
   and the send it will get is routed the same way, before the host method runs */
static void ui_route(id self, SEL sel, const UiArgs& a, int depth) {
  if (!GD_UI_GUARD || !self || !sel) return;
  if (depth > 8) die_name("host-side sends nested more than 8 deep (headless guard)", sel_getName(sel));
  const char* nm = sel_getName(sel);
  if (!strcmp(nm, "setTarget:")) return;                      /* storing a target runs nothing (an NSControl receiver is checked) */
  if ((!strcmp(nm, "invoke") || !strcmp(nm, "invokeWithTarget:")) && kind_of(self, "NSInvocation")) {
    id t = nm[6] ? (id)(uintptr_t)ui_arg(a, 2) : msg_id(self, "target");
    ui_check((uint64_t)(uintptr_t)t, nm);
    ui_route(t, ((SEL (*)(id, SEL))objc_msgSend)(self, sel_registerName("selector")), UiArgs{nullptr, nullptr, self, nullptr, 0}, depth + 1);
    return;
  }
  bool perform = !strncmp(nm, "performSelector", 15), each = !strncmp(nm, "makeObjectsPerformSelector:", 27);
  uint64_t with[4] = {0, 0, 0, 0}, tgt = 0; int nw = 0; SEL inner = nullptr;
  int i = 2;
  for (const char* k = nm; const char* e = strchr(k, ':'); k = e + 1, i++) {   /* keyword i - 2 names encoding argument i */
    size_t n = (size_t)(e - k);
    if ((perform || each) && i == 2) inner = (SEL)(uintptr_t)ui_arg(a, i);
    else if (kw_is(k, n, "withObject")) { if (nw < 4) with[nw++] = ui_arg(a, i); }
    else if (kw_ends(k, n, "target") || kw_ends(k, n, "Target") || kw_is(k, n, "addObserver")) ui_check(tgt = ui_arg(a, i), nm);
    else if (kw_ends(k, n, "selector") || kw_ends(k, n, "Selector") || kw_is(k, n, "action")) inner = (SEL)(uintptr_t)ui_arg(a, i);
  }
  const UiArgs ia{nullptr, nullptr, nil, with, nw};
  if (each) ui_elements(self, nm, [&](id el) { ui_route(el, inner, ia, depth + 1); });
  else if (perform) ui_route(self, inner, ia, depth + 1);
  else if (tgt) ui_route((id)(uintptr_t)tgt, inner, ia, depth + 1);
}
/* ---- per-call-site send cache (recompile GD_MSGSEND -> gbridge gd_msgsend) ----
   The runtime is still asked for the IMP on every send (class_getMethodImplementation: swizzled methods, methods and
   categories added later, KVO's isa-swizzled subclasses, +initialize and resolvers stay exact), but only for a class this
   site already sent to (vetted by the UI guard and the registration check). A site caches the work after the lookup, per
   (class, selector, IMP): the translated function of a guest IMP (entered as arm64 objc_msgSend jumps to it), or a typed
   direct call of a host IMP whose arguments all travel in registers and need only widening (blocks made host-callable).
   Forwarding, variadic methods, records, ^? pointers and stack arguments stay on send(). Entries are interned, never freed.
   The encoding a host entry was typed from can change under the same (class, selector, IMP): a class disposed and its
   address reused, a method added that shadows an inherited one with the same IMP. Every guest-side runtime change of
   that kind (sp_objc_disposeClassPair, sp_class_addMethod, sp_class_replaceMethod, sp_method_setImplementation,
   guest class and category registration) bumps M_EP, and an entry hits only in the epoch it was looked up in.
   ponytail: host-side disposal or method addition (a host framework's, not the guest's) does not bump it. */
enum { MS_GUEST = 1, MS_HOST = 2, MS_GPR = 6, MS_FPR = 8, MEB_N = 4096 };
typedef double MX __attribute__((vector_size(16)));           /* one xmm register: a float or double argument / result */
struct MEnt { Class cls; SEL sel; IMP imp; unsigned long ep; int kind, ngp, nfp, rk; bool route; unsigned char ext[MS_GPR], blk[MS_GPR]; gfn f; const Sig* s; MEnt* next; };
struct MIc { const MEnt* e; };                                /* recompile GMsgIC */
static MEnt* MEB[MEB_N];
static unsigned long M_EP;                                    /* send cache epoch (above) */
static void m_flush() { __atomic_add_fetch(&M_EP, 1, __ATOMIC_ACQ_REL); }
/* the IMP objc_msgSend / objc_msgSendSuper2 would jump to for (receiver, sel): libobjc's objc_msgLookup* entry points run
   the same method-cache probe (and on a miss the same lookUpImpOrForward, +initialize and resolvers included) and return
   the IMP in r11 (forwarding: _objc_msgForward_impcache, never a cached entry's IMP); these local thunks give it the C ABI.
   Cheaper than class_getMethodImplementation's three calls deep; tests/m7b/run_msglookup.py checks the two agree. */
extern "C" IMP gd_msglookup(id self, SEL sel);
extern "C" IMP gd_msglookup_super2(const objc_super* sup, SEL sel);
__asm__(".text\n.p2align 4\n"
        "_gd_msglookup:\n  pushq %rbp\n  movq %rsp, %rbp\n  callq _objc_msgLookup\n  movq %r11, %rax\n  popq %rbp\n  retq\n"
        ".p2align 4\n"
        "_gd_msglookup_super2:\n  pushq %rbp\n  movq %rsp, %rbp\n  callq _objc_msgLookupSuper2\n  movq %r11, %rax\n  popq %rbp\n  retq\n");
static int m_extk(const GT& t) { return t.k != T_INT || t.size == 8 ? 0 : (t.size == 1 ? 1 : t.size == 2 ? 3 : 5) + !t.sgn; }
static uint64_t m_ext(uint64_t v, int k) {                    /* m_extk codes: AAPCS64 leaves a narrow argument's upper bits unspecified */
  switch (k) {
    case 1: return (uint64_t)(int64_t)(int8_t)v;  case 2: return (uint8_t)v;
    case 3: return (uint64_t)(int64_t)(int16_t)v; case 4: return (uint16_t)v;
    case 5: return (uint64_t)(int64_t)(int32_t)v; case 6: return (uint32_t)v;
    default: return v;
  }
}
static bool ui_route_acts(SEL sel) {                          /* ui_route may look into a send of this selector (by name alone) */
  if (!GD_UI_GUARD) return false;                             /* ui_route returns at once with the guard off */
  const char* nm = sel_getName(sel);
  if (!strcmp(nm, "invoke") || !strncmp(nm, "invokeWithTarget:", 17) || !strncmp(nm, "performSelector", 15) ||
      !strncmp(nm, "makeObjectsPerformSelector:", 27)) return true;
  for (const char* k = nm; const char* e = strchr(k, ':'); k = e + 1) {
    size_t n = (size_t)(e - k);
    if (kw_is(k, n, "withObject") || kw_ends(k, n, "target") || kw_ends(k, n, "Target") || kw_is(k, n, "addObserver") ||
        kw_ends(k, n, "selector") || kw_ends(k, n, "Selector") || kw_is(k, n, "action")) return true;
  }
  return false;
}
static bool m_typed(MEnt& e) {                                /* e.s as a typed direct call: true when it fits MS_GPR / MS_FPR registers */
  const Sig* s = e.s;
  if (s->bad) return false;
  switch (s->ret.k) {
    case T_VOID: e.rk = 0; break;
    case T_INT: case T_ID: case T_BLK: case T_PTR: e.rk = 1; break;
    case T_F32: case T_F64: e.rk = 2; break;
    default: return false;
  }
  for (int i = 0; i < s->n; i++) {
    const GT& t = s->a[i];
    if (t.k == T_INT || t.k == T_ID || t.k == T_BLK || (t.k == T_PTR && !t.nco)) {
      if (e.ngp == MS_GPR) return false;
      e.ext[e.ngp] = (unsigned char)m_extk(t); e.blk[e.ngp++] = t.k == T_ID || t.k == T_BLK;
    } else if (t.k == T_F32 || t.k == T_F64) { if (e.nfp++ == MS_FPR) return false; }
    else return false;
  }
  return true;
}
static void m_fill(MIc* ic, Class cls, SEL sel, IMP imp, unsigned long ep, int kind, gfn f, const Sig* s) {   /* intern and publish the site's entry (ep: M_EP before the lookup) */
  unsigned h = (unsigned)((((uint64_t)(uintptr_t)cls * 0x9E3779B97F4A7C15ULL) ^ (uint64_t)(uintptr_t)sel ^ ((uint64_t)(uintptr_t)imp >> 4)) >> 20) & (MEB_N - 1);
  pthread_mutex_lock(&mu);
  MEnt* e = MEB[h];
  while (e && !(e->cls == cls && e->sel == sel && e->imp == imp && e->ep == ep)) e = e->next;
  if (!e) {
    MEnt n{}; n.cls = cls; n.sel = sel; n.imp = imp; n.ep = ep; n.kind = kind; n.f = f; n.s = s;
    if (kind == MS_HOST) { if (!m_typed(n)) n.kind = 0; else n.route = ui_route_acts(sel); }
    e = (MEnt*)gzalloc(sizeof(MEnt)); *e = n; e->next = MEB[h]; MEB[h] = e;
  }
  pthread_mutex_unlock(&mu);
  if (e->kind) __atomic_store_n(&ic->e, e, __ATOMIC_RELEASE);
}
static void m_host(CPU* c, const MEnt* e) {                   /* the typed direct call (host_call's effect for these encodings) */
  uint64_t a[MS_GPR] = {0, 0, 0, 0, 0, 0};
  for (int i = 0; i < e->ngp; i++) { a[i] = m_ext(c->X[i], e->ext[i]); if (e->blk[i]) hostify_blk(a[i]); }
  void* fn = (void*)e->imp;
  uint64_t r = 0; MX v = {0, 0};
  if (!e->nfp) {
    if (e->rk == 2) v = ((MX (*)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t))fn)(a[0], a[1], a[2], a[3], a[4], a[5]);
    else r = ((uint64_t (*)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t))fn)(a[0], a[1], a[2], a[3], a[4], a[5]);
  } else {
    MX f[MS_FPR];
    memcpy(f, c->V, sizeof f);
    typedef MX (*FF)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, MX, MX, MX, MX, MX, MX, MX, MX);
    typedef uint64_t (*FI)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, MX, MX, MX, MX, MX, MX, MX, MX);
    if (e->rk == 2) v = ((FF)fn)(a[0], a[1], a[2], a[3], a[4], a[5], f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7]);
    else r = ((FI)fn)(a[0], a[1], a[2], a[3], a[4], a[5], f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7]);
  }
  if (e->rk == 1) c->X[0] = e->s->ret.k == T_INT ? ext(e->s->ret, &r) : e->s->ret.k == T_PTR ? gd::unshadow(r) : r;
  else if (e->rk == 2) { memset(&c->V[0], 0, 16); memcpy(&c->V[0], &v, (size_t)e->s->ret.size); }
}
static gfn guest_fn(uint64_t g) {                             /* the translated function at guest address g, or null */
  for (int k = 0; k < NIMG; k++) if (g - IMG[k].lo < IMG[k].size) return IMG[k].lookup(g - IMG[k].slide);
  return nullptr;
}
static void send(CPU* c, int sup, MIc* ic) {                  /* sup: 0 objc_msgSend, 1 objc_msgSendSuper, 2 objc_msgSendSuper2; ic: a site cache to fill */
  uint64_t x0 = c->X[0];
  SEL sel = (SEL)(uintptr_t)c->X[1];
  id self; Class cls;
  if (sup) {
    const objc_super* sp = (const objc_super*)(uintptr_t)x0;
    self = sp->receiver;
    cls = sup == 2 ? class_getSuperclass(sp->super_class) : sp->super_class;
  } else { self = (id)(uintptr_t)x0; cls = self ? object_getClass(self) : Nil; }
  if (!self) { nil_ret(c); return; }
  if (const char* n = ui_class(self)) ui_stop(self, n, sel_getName(sel));
  if (!sup && in_guest((uint64_t)(uintptr_t)cls) && !tget(REG, (uint64_t)(uintptr_t)cls))
    die_name("message to an object whose guest class is not registered with the host runtime (a Swift class?)", sel_getName(sel));
  unsigned long ep = __atomic_load_n(&M_EP, __ATOMIC_ACQUIRE);   /* before the lookup: a change during it makes the entry stale */
  IMP imp = class_getMethodImplementation(cls, sel);          /* +initialize, +resolveInstanceMethod:, the method cache */
  c->X[0] = (uint64_t)(uintptr_t)self;                        /* the IMP's receiver (a super send passes the objc_super) */
  if (uint64_t g = clo_target((uint64_t)(uintptr_t)imp)) {    /* a guest method: as arm64 objc_msgSend */
    if (gfn f = ic ? guest_fn(g) : nullptr) m_fill(ic, cls, sel, imp, ep, MS_GUEST, f, nullptr);
    dispatch(c, g); return;
  }
  if (imp == (IMP)_objc_msgForward) { fwd_send(c, self, sel); return; }
  Method m = class_getInstanceMethod(cls, sel);
  if (!m) die_name("message send: the runtime has an implementation but no method", sel_getName(sel));
  Sig* s = sig_sel(sel, method_getTypeEncoding(m));
  if (!s->bad) ui_route(self, sel, UiArgs{c, s, nil, nullptr, 0}, 0);
  if (const VMeth* v = vmeth(cls, sel)) var_send(c, (void*)imp, s, v, sel_getName(sel), cls, sel);
  else {
    if (ic) m_fill(ic, cls, sel, imp, ep, MS_HOST, nullptr, s);
    host_call(c, (void*)imp, s, sel_getName(sel), cls, sel);
  }
}

/* ---- Objective-C exceptions (see the header comment) ---- */
static uint64_t G_ALLOC, G_THROW, G_BEGIN, G_END, G_RETHROW, G_PERS;   /* guest libc++abi */
static void** EHVT;                                           /* libobjc's objc_ehtype_vtable */
static uint64_t EH_DTOR;                                      /* guest-callable handle of exc_dtor */
static __thread uint64_t tls_bexc;                            /* the exception a sentinel frame claimed */
enum { UA_SEARCH = 1, UA_FORCE = 8, URC_HANDLER_FOUND = 6, URC_INSTALL = 7, URC_CONTINUE = 8, UE_SIZE = 32, CXA_TYPE = -80 };
static void exc_dtor(void* thrown) { objc_release(*(id*)thrown); }   /* objc's _objc_exception_destructor */
static bool objc_exc(uint64_t ue) {                           /* a guest libc++abi exception thrown with an ObjC typeinfo */
  if (!ue || !EHVT || (*(const uint64_t*)(uintptr_t)ue >> 8) != (0x434C4E47432B2B00ULL >> 8)) return false;   /* CLNGC++ */
  uint64_t ti = *(const uint64_t*)(uintptr_t)(ue + CXA_TYPE);
  return ti && *(const uint64_t*)(uintptr_t)ti == (uint64_t)(uintptr_t)(EHVT + 2);
}
[[noreturn]] static void guest_objc_throw(CPU* c, id obj) {  /* objc_exception_throw, inside the guest, from c's call site */
  uint64_t sz = 32, exc = gd::call_guest<uint64_t, uint64_t>(G_ALLOC, sz);
  uint64_t* e = (uint64_t*)(uintptr_t)exc;
  e[0] = (uint64_t)(uintptr_t)obj; e[1] = (uint64_t)(uintptr_t)(EHVT + 2);
  e[2] = (uint64_t)(uintptr_t)object_getClassName(obj); e[3] = (uint64_t)(uintptr_t)object_getClass(obj);
  c->X[0] = exc; c->X[1] = exc + 8; c->X[2] = EH_DTOR;
  dispatch(c, G_THROW);
  die("guest __cxa_throw returned", exc);
}
/* a guest->host call: a host ObjC exception escaping it continues inside the guest (no guest runtime: it stays native) */
template<class F> static void host_side(CPU* c, F&& f) {
#if __OBJC__
  id ex = nil;
  @try { f(); }
  @catch (id e) { if (!G_THROW) @throw; ex = objc_retain(e); }
  if (ex) guest_objc_throw(c, ex);
#else                                                         /* a plain C++ embedder (no gdyld build): no ObjC exceptions */
  (void)c; f();
#endif
}
extern "C" const uintptr_t objc_debug_isa_class_mask;  /* libobjc: the isa bits object_getClass reads for a non-tagged object */
/* gbridge gd_msgsend's first try at an objc_msgSend site: the site's entry when it is a guest method, the receiver (not nil, not a
   tagged pointer) is of its class, selector and epoch match, and libobjc still sends the pair to the entry's IMP (the check for
   host-side changes, which bump no epoch); else null, and gd_msgsend takes its full path */
static inline const MEnt* msg_guest(CPU* c, MIc* ic) {
  const MEnt* e = __atomic_load_n(&ic->e, __ATOMIC_ACQUIRE);
  uintptr_t x0 = (uintptr_t)c->X[0];
  if (!e || !x0 || (x0 & 1) || e->kind != MS_GUEST || (Class)(*(const uintptr_t*)x0 & objc_debug_isa_class_mask) != e->cls ||
      e->sel != (SEL)(uintptr_t)c->X[1] || e->ep != __atomic_load_n(&M_EP, __ATOMIC_ACQUIRE) || gd_msglookup((id)x0, e->sel) != e->imp)
    return nullptr;
  return e;
}
/* a cached send (per-call-site send cache above): true when done here (nil receiver, or the site's entry matches);
   else gbridge's gd_msgsend runs send(c, sup, ic) */
static inline bool msg_fast(CPU* c, MIc* ic, int sup) {
  uint64_t x0 = c->X[0];
  id self; Class cls;
  if (sup) {
    const objc_super* sp = (const objc_super*)(uintptr_t)x0;
    self = sp->receiver;
    cls = sup == 2 ? class_getSuperclass(sp->super_class) : sp->super_class;
  } else { self = (id)(uintptr_t)x0; cls = self ? object_getClass(self) : Nil; }
  if (!self) { nil_ret(c); return true; }
  SEL sel = (SEL)(uintptr_t)c->X[1];
  const MEnt* e = __atomic_load_n(&ic->e, __ATOMIC_ACQUIRE);
  if (!e || e->cls != cls || e->sel != sel || e->ep != __atomic_load_n(&M_EP, __ATOMIC_ACQUIRE)) return false;
  IMP imp = sup == 0 ? gd_msglookup(self, sel) : sup == 2 ? gd_msglookup_super2((const objc_super*)(uintptr_t)x0, sel)
                     : class_getMethodImplementation(cls, sel);
  if (imp != e->imp) return false;
  c->X[0] = (uint64_t)(uintptr_t)self;
  if (e->kind == MS_GUEST) { e->f(c); return true; }
  TlsRestore g{tls_cur}; tls_cur = c;
  host_side(c, [&] {
    if (e->route) ui_route(self, sel, UiArgs{c, e->s, nil, nullptr, 0}, 0);
    m_host(c, e);
  });
  return true;
}
static int sent_pers(int, int actions, uint64_t, uint64_t ue, uint64_t) {   /* the sentinel frame's personality */
  if (!objc_exc(ue) || (actions & UA_FORCE)) return URC_CONTINUE;   /* C++ exceptions walk on into the caller's frames */
  if (actions & UA_SEARCH) return URC_HANDLER_FOUND;
  tls_bexc = ue;
  return URC_INSTALL;                                         /* resumes at GD_SENTINEL: the host side rethrows it */
}
[[noreturn]] static void boundary_throw() {                   /* a guest ObjC exception leaves its segment as a host one */
  uint64_t ue = tls_bexc; tls_bexc = 0;
  if (!ue) die("sentinel frame reached without a claimed exception", 0);
  id obj = objc_retain(*(id*)(uintptr_t)(ue + UE_SIZE));
  gd::call_guest<uint64_t, uint64_t>(G_BEGIN, ue); gd::call_guest<void>(G_END);   /* the guest exception is done */
  struct Rel { id o; ~Rel() { objc_release(o); } } rel{obj};
  objc_exception_throw(obj);
}
/* the guest called through libobjc's objc_ehtype_vtable (its personality matching an @catch type) */
static bool eh_call(CPU* c, uint64_t a) {
  if (!EHVT) return false;
  if (a == (uint64_t)(uintptr_t)EHVT[6]) {                    /* _objc_exception_do_catch(catch, throw, void** obj, outer) */
    c->X[0] = ((bool (*)(void*, void*, void**, unsigned))(uintptr_t)a)((void*)(uintptr_t)c->X[0], (void*)(uintptr_t)c->X[1],
                                                                       (void**)(uintptr_t)c->X[2], (unsigned)c->X[3]);
    return true;
  }
  if (a == (uint64_t)(uintptr_t)EHVT[7]) { c->X[0] = 0; return true; }   /* _objc_exception_false */
  if (a == (uint64_t)(uintptr_t)EHVT[2]) return true;                    /* _objc_exception_noop */
  return false;
}
static unsigned char EHF[160]; static uint64_t EHF_LEN;       /* the sentinel frame's __eh_frame (one CIE, one FDE) */
static void leb(unsigned char* b, size_t& o, int64_t v, bool sgn) {
  for (bool more = true; more;) {
    unsigned char x = v & 0x7f; v = sgn ? v >> 7 : (int64_t)((uint64_t)v >> 7);
    more = sgn ? !((v == 0 && !(x & 0x40)) || (v == -1 && (x & 0x40))) : v != 0;
    b[o++] = x | (more ? 0x80 : 0);
  }
}
/* CFA = *(sp + K), return address at sp + K + 8 (K = GD_ARGS + GD_COPY: the record each segment start writes) */
static void sent_init() {
  uint64_t pers = handle_of((void*)&sent_pers, &gd::Inv<int (*)(int, int, uint64_t, uint64_t, uint64_t)>::call_rt);
  const int64_t K = GD_ARGS + GD_COPY;
  unsigned char* b = EHF; size_t o = 4;
  auto u32 = [&](size_t at, uint32_t v) { memcpy(b + at, &v, 4); };
  auto u64 = [&](uint64_t v) { memcpy(b + o, &v, 8); o += 8; };
  u32(o, 0); o += 4;                                          /* CIE id */
  b[o++] = 1; memcpy(b + o, "zPR", 4); o += 4;
  leb(b, o, 1, false); leb(b, o, -8, true); b[o++] = 30;      /* code align, data align, return address column */
  leb(b, o, 10, false); b[o++] = 0; u64(pers); b[o++] = 0;    /* augmentation: absptr personality, absptr FDE pointers */
  b[o++] = 0x0c; b[o++] = 31; b[o++] = 0;                     /* DW_CFA_def_cfa sp, 0 */
  while ((o - 4) % 8) b[o++] = 0;
  u32(0, (uint32_t)(o - 4));
  size_t f = o; o += 4; u32(o, (uint32_t)(o)); o += 4;        /* FDE: CIE pointer = distance back to the CIE */
  u64(GD_SENTINEL - 16); u64(32); leb(b, o, 0, false);
  unsigned char e[16]; size_t n = 0;
  e[n++] = 0x8f; leb(e, n, K, true); e[n++] = 0x06;           /* DW_OP_breg31 K; DW_OP_deref */
  b[o++] = 0x0f; leb(b, o, (int64_t)n, false); memcpy(b + o, e, n); o += n;
  n = 0; e[n++] = 0x8f; leb(e, n, K + 8, true);
  b[o++] = 0x10; b[o++] = 30; leb(b, o, (int64_t)n, false); memcpy(b + o, e, n); o += n;
  while ((o - f - 4) % 8) b[o++] = 0;
  u32(f, (uint32_t)(o - f - 4));
  u32(o, 0); o += 4;                                          /* terminator */
  EHF_LEN = o;
}
static void eh_init() {
  EHVT = (void**)dlsym(RTLD_DEFAULT, "objc_ehtype_vtable");
  G_ALLOC = guest_export("__cxa_allocate_exception", 0, NIMG); G_THROW = guest_export("__cxa_throw", 0, NIMG);
  G_BEGIN = guest_export("__cxa_begin_catch", 0, NIMG); G_END = guest_export("__cxa_end_catch", 0, NIMG);
  G_RETHROW = guest_export("__cxa_rethrow", 0, NIMG); G_PERS = guest_export("__gxx_personality_v0", 0, NIMG);
  if (!(EHVT && G_ALLOC && G_THROW && G_BEGIN && G_END && G_RETHROW && G_PERS)) G_THROW = 0;
  else EH_DTOR = handle_of((void*)&exc_dtor, &gd::Inv<void (*)(void*)>::call_rt);
}
static uint64_t eh_need(uint64_t g, const char* what) { if (!g || !G_THROW) die_name("Objective-C exceptions need the guest C++ runtime", what); return g; }

/* ---- guest images: selectors, protocols, classes (in place), categories, +load ---- */
enum { OC_CLS, OC_CAT, OC_PROTO, OC_SEL, OC_NLCLS, OC_NLCAT, OC_PREF, NOCS };   /* gdyld.OBJC_SECTS order */
static uint64_t Q(uint64_t a) { return *(const uint64_t*)(uintptr_t)a; }
static uint32_t W(uint64_t a) { return *(const uint32_t*)(uintptr_t)a; }
static int64_t SW(uint64_t a) { return *(const int32_t*)(uintptr_t)a; }
static const char* CS(uint64_t a) { return (const char*)(uintptr_t)a; }
static uint64_t oci_addr(int k, int s) { return OCI[(k * NOCS + s) * 2]; }
static uint64_t oci_n(int k, int s) { return OCI[(k * NOCS + s) * 2 + 1]; }
static SEL sel_load_() { static SEL s = sel_registerName("load"); return s; }
/* method_list_t, big (name, types, imp) or small (relative offsets; the name refers to a selector ref unless uniqued) */
template<class F> static void each_method(uint64_t ml, F&& f) {
  if (!ml) return;
  uint32_t ef = W(ml), n = W(ml + 4), es = ef & 0xfffcu;
  for (uint32_t i = 0; i < n; i++) {
    uint64_t e = ml + 8 + (uint64_t)i * es;
    if (ef & 0x80000000u) {
      uint64_t nref = e + (uint64_t)SW(e);
      f(sel_registerName(ef & 0x40000000u ? CS(nref) : CS(Q(nref))), CS(e + 4 + (uint64_t)SW(e + 4)), SW(e + 8) ? e + 8 + (uint64_t)SW(e + 8) : 0);
    } else f(sel_registerName(CS(Q(e))), CS(Q(e + 8)), Q(e + 16));
  }
}
static IMP meth_imp(uint64_t g, const char* types, SEL sel) { return (IMP)clo_get(sig_sel(sel, types), g); }   /* a bad one dies when called */
struct HMeth { const char* name; const char* types; IMP imp; };
struct HML { uint32_t es, n; HMeth m[]; };
static uint64_t* GCATS; static int NGCATS;                    /* (guest class, category) pairs in load order */
/* a big method list of typed closures for the runtime: the class's guest categories first (newest first), then its own */
static uint64_t host_methods(uint64_t cls, bool meta, uint64_t ml, uint64_t* load) {
  uint32_t n = ml ? W(ml + 4) : 0;
  for (int i = 0; i < NGCATS; i++) if (GCATS[2 * i] == cls && Q(GCATS[2 * i + 1] + (meta ? 24 : 16))) n += W(Q(GCATS[2 * i + 1] + (meta ? 24 : 16)) + 4);
  if (!n) return ml;
  HML* h = (HML*)gzalloc(8 + sizeof(HMeth) * n);
  h->es = sizeof(HMeth);
  for (int i = NGCATS - 1; i >= 0; i--)
    if (GCATS[2 * i] == cls)
      each_method(Q(GCATS[2 * i + 1] + (meta ? 24 : 16)), [&](SEL s, const char* t, uint64_t imp) { h->m[h->n++] = HMeth{sel_getName(s), t, meth_imp(imp, t, s)}; });
  each_method(ml, [&](SEL s, const char* t, uint64_t imp) {
    if (load && s == sel_load_()) *load = imp;
    h->m[h->n++] = HMeth{sel_getName(s), t, meth_imp(imp, t, s)};
  });
  return (uint64_t)(uintptr_t)h;
}
struct PropAttrs { objc_property_attribute_t a[16]; unsigned n; };
static PropAttrs prop_attrs(const char* s) {                  /* "T@\"NSString\",C,N,V_name" -> runtime attributes */
  PropAttrs r{}; char* b = strdup(s); char* p = b;
  while (*p && r.n < 16) {
    char* start = p; bool q = false;
    while (*p && (q || *p != ',')) { q ^= *p == '"'; p++; }
    if (*p) *p++ = 0;
    char* nm = (char*)gzalloc(2); nm[0] = start[0];
    r.a[r.n++] = objc_property_attribute_t{nm, start + 1};
  }
  return r;
}
template<class F> static void each_prop(uint64_t pl, F&& f) {
  if (!pl) return;
  for (uint32_t i = 0, es = W(pl), n = W(pl + 4); i < n; i++) f(CS(Q(pl + 8 + (uint64_t)i * es)), CS(Q(pl + 16 + (uint64_t)i * es)));
}
static Protocol* proto_host(uint64_t g) {                     /* guest protocol_t -> the host protocol of that name */
  if (uint64_t h = tget(PMAP, g)) return (Protocol*)(uintptr_t)h;
  const char* name = CS(Q(g + 8));
  Protocol* p = objc_getProtocol(name);
  if (!p) {
    p = objc_allocateProtocol(name);
    if (!p) die_name("cannot allocate the guest protocol", name);
    if (uint64_t pl = Q(g + 16)) for (uint64_t k = 0; k < Q(pl); k++) protocol_addProtocol(p, proto_host(Q(pl + 8 + 8 * k)));
    static const int off[4] = {24, 32, 40, 48}; static const bool req[4] = {true, true, false, false}, inst[4] = {true, false, true, false};
    for (int j = 0; j < 4; j++)
      each_method(Q(g + off[j]), [&](SEL s, const char* t, uint64_t) { protocol_addMethodDescription(p, s, t, req[j], inst[j]); });
    each_prop(Q(g + 56), [&](const char* n, const char* a) { PropAttrs r = prop_attrs(a); protocol_addProperty(p, n, r.a, r.n, true, true); });
    if (W(g + 64) >= 96)                                      /* protocol_t::_classProperties, when the record has it */
      each_prop(Q(g + 88), [&](const char* n, const char* a) { PropAttrs r = prop_attrs(a); protocol_addProperty(p, n, r.a, r.n, true, false); });
    objc_registerProtocol(p);
  }
  tput(PMAP, g, (uint64_t)(uintptr_t)p);
  return p;
}
static void fix_protolist(uint64_t pl) {                      /* protocol_list_t entries -> host protocols, in place */
  if (pl) for (uint64_t k = 0; k < Q(pl); k++) {
    uint64_t* e = (uint64_t*)(uintptr_t)(pl + 8 + 8 * k);
    if (in_guest(*e)) *e = (uint64_t)(uintptr_t)proto_host(*e);
  }
}
static int nswift;                                            /* guest Swift classes registered (FAST_IS_SWIFT_* bits) */
static void reg_class(uint64_t g, int depth) {
  if (tget(REG, g) || depth > 64) return;
  uint64_t bits = Q(g + 32), sup = Q(g + 8), meta = Q(g);
  if (sup && in_guest(sup)) { reg_class(sup, depth + 1); if (!tget(REG, sup)) return; }
  uint64_t ro = bits & ~7ULL, mro = Q(meta + 32) & ~7ULL, load = 0;
  if (!in_guest(meta) || !ro || !mro) die("malformed guest class", g);
  *(uint64_t*)(uintptr_t)(ro + 32) = host_methods(g, false, Q(ro + 32), nullptr);
  *(uint64_t*)(uintptr_t)(mro + 32) = host_methods(g, true, Q(mro + 32), &load);
  fix_protolist(Q(ro + 40)); fix_protolist(Q(mro + 40));
  static const uint32_t info[2] = {0, 0};
  if ((uint64_t)(uintptr_t)objc_readClassPair((Class)(uintptr_t)g, info) != g) die_name("objc_readClassPair refused a guest class", CS(Q(ro + 24)));
  tput(REG, g, 1); tput(REG, meta, 1); m_flush();
  if (load) tput(LOADIMP, g, load);
  if (bits & 3) { nswift++; gswift_class_fix(g); }            /* Swift metadata: heap destroy, ivar destroyer (gswift.hpp) */
}
/* category_t: name, cls, instance methods, class methods, protocols, instance properties, class properties */
static void attach_cat(uint64_t cat) {
  uint64_t cls = Q(cat + 8);
  if (!cls || (in_guest(cls) && !tget(REG, cls))) return;     /* a weak-linked missing class, or an unregistered one */
  Class c = (Class)(uintptr_t)cls, m = object_getClass((id)c);
  if (!in_guest(cls)) {                                       /* host class: methods through the runtime API (merged for guest ones) */
    /* ponytail: a category overriding a host class's own method replaces that entry (the runtime keeps both lists);
       private class_rw_t surgery would be needed to keep the original enumerable */
    each_method(Q(cat + 16), [&](SEL s, const char* t, uint64_t imp) { class_replaceMethod(c, s, meth_imp(imp, t, s), t); });
    each_method(Q(cat + 24), [&](SEL s, const char* t, uint64_t imp) { class_replaceMethod(m, s, meth_imp(imp, t, s), t); });
  }
  fix_protolist(Q(cat + 32));
  if (uint64_t pl = Q(cat + 32)) for (uint64_t k = 0; k < Q(pl); k++) class_addProtocol(c, (Protocol*)(uintptr_t)Q(pl + 8 + 8 * k));
  each_prop(Q(cat + 40), [&](const char* n, const char* a) { PropAttrs r = prop_attrs(a); class_addProperty(c, n, r.a, r.n); });
  each_prop(Q(cat + 48), [&](const char* n, const char* a) { PropAttrs r = prop_attrs(a); class_addProperty(m, n, r.a, r.n); });
  m_flush();
}
static void objc_map_images() {                               /* dyld's map_images for every guest image, before +load */
  BLKCLS[0] = (void*)_NSConcreteStackBlock; BLKCLS[1] = (void*)_NSConcreteGlobalBlock;
  BLKCLS[2] = dlsym(RTLD_DEFAULT, "_NSConcreteMallocBlock");
  eh_init();
  for (int i = 0; i < GD_NVMETH; i++) {
    SEL s = sel_registerName(GD_VMETH[i].sel);
    if (!tget(VMT, (uint64_t)(uintptr_t)s)) tput(VMT, (uint64_t)(uintptr_t)s, (uint64_t)i + 1);
  }
  for (int i = 0; i < GD_NFPARAM; i++) {                      /* sorted by selector: the first row of each */
    SEL s = sel_registerName(GD_FPARAM[i].sel);
    if (!tget(FPT, (uint64_t)(uintptr_t)s)) tput(FPT, (uint64_t)(uintptr_t)s, (uint64_t)i + 1);
  }
  for (int i = 0; i < GD_NVECREC; i++) {                      /* sorted by selector: the first row of each */
    SEL s = sel_registerName(GD_VECREC[i].sel);
    if (!tget(VRT, (uint64_t)(uintptr_t)s)) tput(VRT, (uint64_t)(uintptr_t)s, (uint64_t)i + 1);
  }
  for (int k = 0; k < NIMG; k++)
    for (uint64_t i = 0, a = oci_addr(k, OC_SEL); i < oci_n(k, OC_SEL); i++)
      *(SEL*)(uintptr_t)(a + 8 * i) = sel_registerName(CS(Q(a + 8 * i)));
  for (int k = 0; k < NIMG; k++) {
    for (uint64_t i = 0, a = oci_addr(k, OC_PROTO); i < oci_n(k, OC_PROTO); i++) proto_host(Q(a + 8 * i));
    for (uint64_t i = 0, a = oci_addr(k, OC_PREF); i < oci_n(k, OC_PREF); i++) {
      uint64_t* e = (uint64_t*)(uintptr_t)(a + 8 * i);
      if (in_guest(*e)) *e = (uint64_t)(uintptr_t)proto_host(*e);
    }
  }
  int ncat = 0;
  for (int k = 0; k < NIMG; k++) ncat += (int)oci_n(k, OC_CAT);
  GCATS = (uint64_t*)gzalloc(16 * (size_t)ncat);
  for (int k = 0; k < NIMG; k++)
    for (uint64_t i = 0, a = oci_addr(k, OC_CAT); i < oci_n(k, OC_CAT); i++)
      if (uint64_t cat = Q(a + 8 * i), cls = Q(cat + 8); cls && in_guest(cls)) { GCATS[2 * NGCATS] = cls; GCATS[2 * NGCATS++ + 1] = cat; }
  for (int k = 0; k < NIMG; k++)
    for (uint64_t i = 0, a = oci_addr(k, OC_CLS); i < oci_n(k, OC_CLS); i++) reg_class(Q(a + 8 * i), 0);
  for (int k = 0; k < NIMG; k++)
    for (uint64_t i = 0, a = oci_addr(k, OC_CAT); i < oci_n(k, OC_CAT); i++) attach_cat(Q(a + 8 * i));
  if (nswift && getenv("GDYLD_VERBOSE")) fprintf(stderr, "gobjc: %d guest Swift classes registered\n", nswift);
}
static void call_load(uint64_t cls, uint64_t imp) {
  uint64_t sel = (uint64_t)(uintptr_t)sel_load_();
  gd::call_guest<void, uint64_t, uint64_t>(imp, cls, sel);
}
static void load_class(uint64_t g) {                          /* superclass first, each class once */
  if (!g || !in_guest(g) || tget(LOADED, g)) return;
  pthread_mutex_lock(&mu); tput(LOADED, g, 1); pthread_mutex_unlock(&mu);   /* an earlier image's initializer may run threads */
  load_class(Q(g + 8));
  if (uint64_t imp = tget(LOADIMP, g)) call_load(g, imp);
}
static void objc_load_image(int k) {                          /* load_images: class +load methods, then categories' */
  if (!oci_n(k, OC_NLCLS) && !oci_n(k, OC_NLCAT)) return;
  void* pool = objc_autoreleasePoolPush();
  for (uint64_t i = 0, a = oci_addr(k, OC_NLCLS); i < oci_n(k, OC_NLCLS); i++) load_class(Q(a + 8 * i));
  for (uint64_t i = 0, a = oci_addr(k, OC_NLCAT); i < oci_n(k, OC_NLCAT); i++) {
    uint64_t cat = Q(a + 8 * i), cls = Q(cat + 8), imp = 0;
    each_method(Q(cat + 24), [&](SEL s, const char*, uint64_t p) { if (s == sel_load_()) imp = p; });
    if (cls && imp && (!in_guest(cls) || tget(REG, cls))) call_load(cls, imp);
  }
  objc_autoreleasePoolPop(pool);
}
/* the guest branched to a host IMP (methodForSelector:, method_getImplementation): typed from the method of the receiver's
   class (or a superclass) that has this implementation; x0 and x1 are checked to be a readable object and a selector */
static bool readable(uint64_t a, size_t n) {
  unsigned char b[16]; vm_size_t got = 0;
  return a >= 4096 && vm_read_overwrite(mach_task_self(), (vm_address_t)a, n, (vm_address_t)b, &got) == KERN_SUCCESS && got == n;
}
static bool host_imp_call(CPU* c, uint64_t a) {
  if (uint64_t s = tget(IMPSIG, a)) {                         /* an IMP the runtime API handed back from a typed method */
    if (!(c->X[0] & 1) && readable(c->X[0], 8)) {             /* the receiver, and the route of the method it implemented */
      ui_check(c->X[0], "saved host method implementation");
      if (const Sig* sg = (const Sig*)(uintptr_t)s; !sg->bad)
        ui_route((id)(uintptr_t)c->X[0], (SEL)(uintptr_t)tget(IMPSEL, a), UiArgs{c, sg, nil, nullptr, 0}, 0);
    }
    TlsRestore g{tls_cur}; tls_cur = c;
    host_call(c, (void*)(uintptr_t)a, (const Sig*)(uintptr_t)s, "saved host method implementation");
    return true;
  }
  uint64_t self = c->X[0], sel = c->X[1];
  if ((self & 1) || !readable(self, 8) || !readable(sel, 1) || !sel_isMapped((SEL)(uintptr_t)sel)) return false;
  for (Class k = object_getClass((id)(uintptr_t)self); k; k = class_getSuperclass(k))
    if (Method m = class_getInstanceMethod(k, (SEL)(uintptr_t)sel))
      if ((uint64_t)(uintptr_t)method_getImplementation(m) == a) {
        ui_check(self, sel_getName((SEL)(uintptr_t)sel));   /* an IMP fetched by the guest, called on an AppKit / Metal object */
        TlsRestore g{tls_cur}; tls_cur = c;
        Sig* s = sig_sel((SEL)(uintptr_t)sel, method_getTypeEncoding(m));
        if (!s->bad) ui_route((id)(uintptr_t)self, (SEL)(uintptr_t)sel, UiArgs{c, s, nil, nullptr, 0}, 0);
        host_call(c, (void*)(uintptr_t)a, s, sel_getName((SEL)(uintptr_t)sel), k, (SEL)(uintptr_t)sel);
        return true;
      }
  return false;
}
static IMP imp_in(uint64_t imp, const char* types, SEL sel) { return in_guest(imp) ? meth_imp(imp, types, sel) : gd::to_host_fn<IMP>(imp); }
static void nslogv(uint64_t fmt, const uint64_t* va) {        /* NSLog with the guest's slots as a native va_list */
  using F = void (*)(id, gd::VaPtr);
  static F f = (F)dlsym(RTLD_DEFAULT, "NSLogv");
  if (!f) die("NSLogv: Foundation is not loaded", 0);
  FArgs fa; fmt_args(utf8((id)(uintptr_t)fmt), va, fa);
  NVaBuf b;
  f((id)(uintptr_t)fmt, fa_valist(fa, b));
}
}  // namespace go

static void gobjc_hostify(uint64_t blk) { go::hostify_blk(blk); }
static bool gobjc_guest_block(uint64_t b) {                   /* any value: read only when mapped */
  return go::readable(b, 8) && go::is_blk(b) && go::readable(b + 16, 8) && in_guest(((const go::Lit*)(uintptr_t)b)->invoke);
}
static uint64_t gobjc_target(uint64_t code) { return go::clo_target(code); }
static void gobjc_boundary_throw() { go::boundary_throw(); }
/* runtime API taking an IMP: a guest one becomes a typed closure; an old IMP handed back maps to the guest's own address,
   or (a host one) is remembered with the method's encoding and selector so the guest can call it after it was replaced
   (and the headless guard routes it as that method) */
static uint64_t imp_out(IMP p, const char* types, SEL sel) {
  uint64_t a = (uint64_t)(uintptr_t)p;
  if (p && types && !go::clo_target(a) && !go::tget(go::IMPSIG, a)) {
    go::Sig* s = go::sig_sel(sel, types);
    pthread_mutex_lock(&go::mu);
    if (sel) go::tput(go::IMPSEL, a, (uint64_t)(uintptr_t)sel);
    go::tput(go::IMPSIG, a, (uint64_t)(uintptr_t)s);
    pthread_mutex_unlock(&go::mu);
  }
  return code_to_guest(a, nullptr);
}
/* runtime changes that can retype a cached (class, selector, IMP): the send cache epoch moves after each (go::m_flush) */
static void sp_class_addMethod(CPU* c, int) {
  RET(class_addMethod((Class)(uintptr_t)c->X[0], (SEL)(uintptr_t)c->X[1], go::imp_in(c->X[2], S(c->X[3]), (SEL)(uintptr_t)c->X[1]), S(c->X[3])));
  go::m_flush();
}
static void sp_class_replaceMethod(CPU* c, int) {
  SEL sel = (SEL)(uintptr_t)c->X[1];
  Method m = class_getInstanceMethod((Class)(uintptr_t)c->X[0], sel);
  const char* t = m ? method_getTypeEncoding(m) : S(c->X[3]);
  c->X[0] = imp_out(class_replaceMethod((Class)(uintptr_t)c->X[0], sel, go::imp_in(c->X[2], S(c->X[3]), sel), S(c->X[3])), t, sel);
  go::m_flush();
}
static void sp_method_setImplementation(CPU* c, int) {
  Method m = (Method)(uintptr_t)c->X[0];
  c->X[0] = imp_out(method_setImplementation(m, go::imp_in(c->X[1], method_getTypeEncoding(m), method_getName(m))), method_getTypeEncoding(m), method_getName(m));
  go::m_flush();
}
static void sp_objc_disposeClassPair(CPU* c, int) { objc_disposeClassPair((Class)(uintptr_t)c->X[0]); go::m_flush(); }
static void sp_imp_implementationWithBlock(CPU* c, int) {
  go::hostify_blk(c->X[0]);
  c->X[0] = imp_out(imp_implementationWithBlock((id)(uintptr_t)c->X[0]), nullptr, nullptr);
}
static void sp_objc_msgSend(CPU* c, int) { go::send(c, 0); }
static void sp_objc_msgSendSuper(CPU* c, int) { go::send(c, 1); }
static void sp_objc_msgSendSuper2(CPU* c, int) { go::send(c, 2); }
static void sp_objc_retainBlock(CPU* c, int) { go::hostify_blk(c->X[0]); c->X[0] = (uint64_t)(uintptr_t)objc_retainBlock((id)(uintptr_t)c->X[0]); }
static void sp_Block_copy(CPU* c, int) { go::hostify_blk(c->X[0]); c->X[0] = (uint64_t)(uintptr_t)_Block_copy((const void*)(uintptr_t)c->X[0]); }
static void sp_Block_object_assign(CPU* c, int) {             /* the guest copy helper copying a captured block / __block var */
  int fl = (int)c->X[2];
  if (fl & go::FIELD_BYREF) go::hostify_byref(c->X[1]);
  else if ((fl & go::FIELD_BLOCK) == go::FIELD_BLOCK) go::hostify_blk(c->X[1]);
  _Block_object_assign((void*)(uintptr_t)c->X[0], (const void*)(uintptr_t)c->X[1], fl);
}
/* ObjC exception entry points: the guest libc++abi's, entered on the caller's registers (a tail call) or nested */
static void sp_objc_personality(CPU* c, int) { dispatch(c, go::eh_need(go::G_PERS, "__objc_personality_v0")); }
static void sp_objc_exception_rethrow(CPU* c, int) { dispatch(c, go::eh_need(go::G_RETHROW, "objc_exception_rethrow")); }
static void sp_objc_begin_catch(CPU* c, int) {               /* libobjc: (id)__cxa_begin_catch(exc): do_catch adjusted it */
  uint64_t ue = c->X[0];
  c->X[0] = gd::call_guest<uint64_t, uint64_t>(go::eh_need(go::G_BEGIN, "objc_begin_catch"), ue);
}
static void sp_objc_end_catch(CPU*, int) { gd::call_guest<void>(go::eh_need(go::G_END, "objc_end_catch")); }
static bool handoff_ok(CPU* c) { return go::arc_marker(c->X[30]); }   /* the caller claims the result next */
static void handoff_flush() {                                 /* an unclaimed handoff goes to the pool as it would have */
  if (uint64_t o = go::tls_handoff) { go::tls_handoff = 0; objc_autorelease((id)(uintptr_t)o); }
}
static void sp_objc_autoreleaseReturnValue(CPU* c, int) {
  handoff_flush();
  if (c->X[0] && handoff_ok(c)) { go::tls_handoff = c->X[0]; return; }
  c->X[0] = (uint64_t)(uintptr_t)objc_autoreleaseReturnValue((id)(uintptr_t)c->X[0]);
}
static void sp_objc_retainAutoreleaseReturnValue(CPU* c, int) {
  handoff_flush();
  if (c->X[0] && handoff_ok(c)) { objc_retain((id)(uintptr_t)c->X[0]); go::tls_handoff = c->X[0]; return; }
  c->X[0] = (uint64_t)(uintptr_t)objc_retainAutoreleaseReturnValue((id)(uintptr_t)c->X[0]);
}
static void sp_objc_retainAutoreleasedReturnValue(CPU* c, int) {   /* also objc_claimAutoreleasedReturnValue: +1 result */
  if (c->X[0] && go::tls_handoff == c->X[0]) { go::tls_handoff = 0; return; }
  handoff_flush();
  c->X[0] = (uint64_t)(uintptr_t)objc_retainAutoreleasedReturnValue((id)(uintptr_t)c->X[0]);
}
static void sp_objc_unsafeClaimAutoreleasedReturnValue(CPU* c, int) {   /* +0 result: a handed-off object is released here */
  if (c->X[0] && go::tls_handoff == c->X[0]) { go::tls_handoff = 0; objc_release((id)(uintptr_t)c->X[0]); return; }
  handoff_flush();
  c->X[0] = (uint64_t)(uintptr_t)objc_unsafeClaimAutoreleasedReturnValue((id)(uintptr_t)c->X[0]);
}
static void sp_NSLog(CPU* c, int) { go::nslogv(c->X[0], VA(c->SP)); }
static void sp_NSLogv(CPU* c, int) { go::nslogv(c->X[0], VA(c->X[1])); }
static void sp_swprintf(CPU* c, int) { RET(gswfmt((wchar_t*)(uintptr_t)c->X[0], (size_t)c->X[1], (const wchar_t*)(uintptr_t)c->X[2], VA(c->SP))); }
static void sp_vswprintf(CPU* c, int) { RET(gswfmt((wchar_t*)(uintptr_t)c->X[0], (size_t)c->X[1], (const wchar_t*)(uintptr_t)c->X[2], VA(c->X[3]))); }
