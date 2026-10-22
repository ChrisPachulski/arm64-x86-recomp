// Guest callbacks the host calls: libc (funopen, qsort_r, heapsort, mergesort, bsearch, scandir, fts), CoreFoundation
// structs of callbacks (CFAllocator, CFBinaryHeap, CFDictionary key callbacks, CFTree, CFRunLoopSource), Foundation C
// tables (NSHashTable / NSMapTable callbacks), and callbacks stored by the host and called later on another thread
// (pthread key destructor, dispatch finalizer / queue-specific destructor, CFNotificationCenter, signal handler).
#import <Foundation/Foundation.h>
#include <CoreFoundation/CoreFoundation.h>
#include <dispatch/dispatch.h>
#include <fts.h>
#include <dirent.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

// ---- funopen: a memory FILE whose read/write/seek/close are guest code ----
typedef struct { char buf[256]; long len, pos; int closed; } Mem;
static int m_read(void* c, char* b, int n) { Mem* m = c; int k = (int)(m->len - m->pos < n ? m->len - m->pos : n); memcpy(b, m->buf + m->pos, k); m->pos += k; return k; }
static int m_write(void* c, const char* b, int n) { Mem* m = c; memcpy(m->buf + m->pos, b, n); m->pos += n; if (m->pos > m->len) m->len = m->pos; return n; }
static fpos_t m_seek(void* c, fpos_t off, int wh) { Mem* m = c; m->pos = (wh == SEEK_SET ? 0 : wh == SEEK_CUR ? m->pos : m->len) + off; return m->pos; }
static int m_close(void* c) { ((Mem*)c)->closed = 1; return 0; }

// ---- sorting ----
static int by_ctx(void* ctx, const void* a, const void* b) { int s = *(int*)ctx; return s * (*(const int*)a - *(const int*)b); }
static int cmp_d(const void* a, const void* b) { double x = *(const double*)a, y = *(const double*)b; return x < y ? -1 : x > y; }
typedef struct { int k; double w; char tag[12]; } Rec;              // 24 bytes: sorted by the host as opaque memory
static int cmp_rec(const void* a, const void* b) { const Rec *x = a, *y = b; return x->w < y->w ? -1 : x->w > y->w ? 1 : x->k - y->k; }

// ---- directory walks ----
static int sel_txt(const struct dirent* d) { return strstr(d->d_name, ".txt") != NULL; }
static int cmp_dirent(const struct dirent** a, const struct dirent** b) { return -strcmp((*a)->d_name, (*b)->d_name); }
static int cmp_fts(const FTSENT** a, const FTSENT** b) { return strcmp((*a)->fts_name, (*b)->fts_name); }

// ---- CoreFoundation callback structs ----
static int n_alloc, n_free, n_realloc;
static void* a_alloc(CFIndex sz, CFOptionFlags h, void* info) { n_alloc++; (*(int*)info)++; return malloc(sz); }
static void a_free(void* p, void* info) { n_free++; free(p); }
static void* a_realloc(void* p, CFIndex sz, CFOptionFlags h, void* info) { n_realloc++; return realloc(p, sz); }
static CFStringRef a_desc(const void* info) { return CFSTR("guest allocator"); }
static CFComparisonResult heap_cmp(const void* a, const void* b, void* info) {
  long d = ((long)a - (long)b) * *(long*)info; return d < 0 ? kCFCompareLessThan : d > 0 ? kCFCompareGreaterThan : kCFCompareEqualTo;
}
static int n_kret, n_krel;
static const void* k_ret(CFAllocatorRef al, const void* v) { n_kret++; return v; }
static void k_rel(CFAllocatorRef al, const void* v) { n_krel++; }
static CFStringRef k_desc(const void* v) { return CFStringCreateWithFormat(NULL, NULL, CFSTR("<key %ld>"), (long)v); }
static Boolean k_eq(const void* a, const void* b) { return ((long)a % 100) == ((long)b % 100); }   // keys equal modulo 100
static CFHashCode k_hash(const void* v) { return (CFHashCode)((long)v % 100); }
static const void* t_ret(const void* info) { return info; }
static void t_rel(const void* info) {}
static CFStringRef t_desc(const void* info) { return CFStringCreateWithCString(NULL, (const char*)info, kCFStringEncodingUTF8); }

// ---- NSHashTable / NSMapTable C callbacks ----
static NSUInteger h_hash(NSHashTable* t, const void* p) { return strlen((const char*)p); }
static BOOL h_eq(NSHashTable* t, const void* a, const void* b) { return strlen((const char*)a) == strlen((const char*)b); }
static NSString* h_desc(NSHashTable* t, const void* p) { return [NSString stringWithFormat:@"s:%s", (const char*)p]; }
static NSUInteger mk_hash(NSMapTable* t, const void* p) { return (NSUInteger)(uintptr_t)p & 7; }
static BOOL mk_eq(NSMapTable* t, const void* a, const void* b) { return ((uintptr_t)a & 7) == ((uintptr_t)b & 7); }

// ---- stored callbacks run later, elsewhere ----
static pthread_key_t key;
static volatile int key_dtor_ran, key_dtor_main;
static void key_dtor(void* v) { key_dtor_ran = (int)(long)v; key_dtor_main = pthread_main_np(); }
static void* key_thread(void* p) { pthread_setspecific(key, (void*)77); return NULL; }
static volatile int fin_ran, spec_dtor;
static void q_fin(void* ctx) { fin_ran = *(int*)ctx; }
static void spec_free(void* ctx) { spec_dtor += (int)(long)ctx; }
static int notes, note_main;
static void note_cb(CFNotificationCenterRef c, void* obs, CFNotificationName name, const void* obj, CFDictionaryRef info) {
  notes += (int)CFDictionaryGetCount(info) + *(int*)obs; note_main = pthread_main_np();
}
static void* poster(void* p) {
  const void* k[] = {CFSTR("a"), CFSTR("b")}; const void* v[] = {CFSTR("1"), CFSTR("2")};
  CFDictionaryRef d = CFDictionaryCreate(NULL, k, v, 2, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
  CFNotificationCenterPostNotification(CFNotificationCenterGetLocalCenter(), CFSTR("gd.note"), NULL, d, true);
  CFRelease(d); return NULL;
}
static volatile sig_atomic_t got_sig, sig_main;
static void on_usr1(int s) { got_sig = s; sig_main = pthread_main_np(); }
static void* raiser(void* p) { pthread_kill(*(pthread_t*)p, SIGUSR1); return NULL; }
// CFRunLoopSource version 0 on a background thread's run loop, signalled from the main thread
static CFRunLoopRef bg_rl; static int src_sched, src_perf, src_cancel; static dispatch_semaphore_t ready, done;
static void s_sched(void* info, CFRunLoopRef rl, CFStringRef mode) { src_sched++; }
static void s_cancel(void* info, CFRunLoopRef rl, CFStringRef mode) { src_cancel++; }
static void s_perform(void* info) { src_perf += *(int*)info; CFRunLoopStop(CFRunLoopGetCurrent()); }
static void* bg_loop(void* src) {
  bg_rl = CFRunLoopGetCurrent();
  CFRunLoopAddSource(bg_rl, (CFRunLoopSourceRef)src, kCFRunLoopDefaultMode);
  dispatch_semaphore_signal(ready);
  CFRunLoopRunInMode(kCFRunLoopDefaultMode, 10, false);
  CFRunLoopRemoveSource(bg_rl, (CFRunLoopSourceRef)src, kCFRunLoopDefaultMode);
  dispatch_semaphore_signal(done);
  return NULL;
}

int main(void) {
  @autoreleasepool {
    setvbuf(stdout, NULL, _IOLBF, 0);
    // funopen
    Mem m = {{0}, 0, 0, 0};
    FILE* f = funopen(&m, m_read, m_write, m_seek, m_close);
    fprintf(f, "alpha %d beta %.3f\n", 42, 2.5); fflush(f);
    fseek(f, 6, SEEK_SET);
    int x = 0; fscanf(f, "%d", &x);
    long at = ftell(f);
    fseeko(f, -4, SEEK_END); char tail[8] = {0}; fread(tail, 1, 4, f);
    fclose(f);
    printf("funopen: len %ld x %d at %ld tail '%s' closed %d\n", m.len, x, at, tail, m.closed);
    // sorting with context, heapsort / mergesort, bsearch, doubles and 24-byte records
    int v[8] = {5, 3, 9, 1, 7, 2, 8, 4}, desc = -1;
    qsort_r(v, 8, sizeof v[0], &desc, by_ctx);
    printf("qsort_r desc: %d %d %d %d %d %d %d %d\n", v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]);
    double dv[6] = {2.5, -1.25, 9.0, 0.5, 3.75, -7.0};
    heapsort(dv, 6, sizeof dv[0], cmp_d);
    printf("heapsort doubles: %g %g %g %g %g %g\n", dv[0], dv[1], dv[2], dv[3], dv[4], dv[5]);
    Rec r[5] = {{1, 2.5, "a"}, {2, 0.5, "b"}, {3, 2.5, "c"}, {4, -1, "d"}, {5, 0.5, "e"}};
    mergesort(r, 5, sizeof r[0], cmp_rec);
    printf("mergesort records: %s%s%s%s%s\n", r[0].tag, r[1].tag, r[2].tag, r[3].tag, r[4].tag);
    double key9 = 3.75; double* hit = bsearch(&key9, dv, 6, sizeof dv[0], cmp_d);
    printf("bsearch: index %ld\n", hit ? (long)(hit - dv) : -1L);
    // scandir / fts with guest select and comparators
    char dir[] = "/tmp/gdyld_cbXXXXXX"; mkdtemp(dir);
    const char* names[] = {"b.txt", "a.txt", "c.dat", "d.txt"};
    for (int i = 0; i < 4; i++) { char p[256]; snprintf(p, sizeof p, "%s/%s", dir, names[i]); fclose(fopen(p, "w")); }
    struct dirent** list = NULL;
    int nd = scandir(dir, &list, sel_txt, cmp_dirent);
    printf("scandir:"); for (int i = 0; i < nd; i++) { printf(" %s", list[i]->d_name); free(list[i]); } printf(" (%d)\n", nd); free(list);
    char* roots[] = {dir, NULL};
    FTS* fts = fts_open(roots, FTS_PHYSICAL | FTS_NOCHDIR, cmp_fts);
    printf("fts:"); for (FTSENT* e; (e = fts_read(fts));) if (e->fts_info == FTS_F) printf(" %s", e->fts_name); printf("\n");
    fts_close(fts);
    for (int i = 0; i < 4; i++) { char p[256]; snprintf(p, sizeof p, "%s/%s", dir, names[i]); unlink(p); } rmdir(dir);
    // CFAllocator with guest callbacks
    int info_count = 0;
    CFAllocatorContext ac = {0, &info_count, NULL, NULL, a_desc, a_alloc, a_realloc, a_free, NULL};
    CFAllocatorRef al = CFAllocatorCreate(NULL, &ac);
    CFMutableStringRef s = CFStringCreateMutable(al, 0);
    for (int i = 0; i < 40; i++) CFStringAppendCString(s, "abcdefghij", kCFStringEncodingASCII);
    CFIndex slen = CFStringGetLength(s);
    CFRelease(s);
    CFAllocatorContext back; CFAllocatorGetContext(al, &back);
    CFStringRef ad = back.copyDescription ? back.copyDescription(back.info) : NULL;
    printf("allocator: len %ld allocs>0 %d frees>0 %d info-counted %d ctx-roundtrip %d desc '%s'\n", (long)slen, n_alloc > 0, n_free > 0,
           info_count == n_alloc, back.allocate == a_alloc && back.info == &info_count, ad ? CFStringGetCStringPtr(ad, kCFStringEncodingASCII) : "(none)");
    CFRelease(al);
    // CFBinaryHeap: compare with a guest context
    long sign = -1;
    CFBinaryHeapCallBacks hcb = {0, NULL, NULL, NULL, heap_cmp};
    CFBinaryHeapCompareContext hctx = {0, &sign, NULL, NULL, NULL};
    CFBinaryHeapRef heap = CFBinaryHeapCreate(NULL, 0, &hcb, &hctx);
    for (long i = 1; i <= 9; i++) CFBinaryHeapAddValue(heap, (const void*)((i * 7) % 10));
    printf("binary heap (max first):"); while (CFBinaryHeapGetCount(heap)) { printf(" %ld", (long)CFBinaryHeapGetMinimum(heap)); CFBinaryHeapRemoveMinimumValue(heap); } printf("\n");
    CFRelease(heap);
    // CFDictionary with guest key callbacks
    CFDictionaryKeyCallBacks kcb = {0, k_ret, k_rel, k_desc, k_eq, k_hash};
    CFMutableDictionaryRef dct = CFDictionaryCreateMutable(NULL, 0, &kcb, NULL);
    for (long i = 1; i <= 5; i++) CFDictionarySetValue(dct, (const void*)(i * 100 + i), (const void*)i);
    long got = (long)CFDictionaryGetValue(dct, (const void*)(903));   // equal to 303 modulo 100
    CFStringRef dd = CFCopyDescription(dct);
    printf("dictionary: count %ld lookup %ld retains %d desc-has-key %d\n", (long)CFDictionaryGetCount(dct), got, n_kret,
           CFStringFind(dd, CFSTR("<key 303>"), 0).location != kCFNotFound);
    CFRelease(dd); CFRelease(dct);
    printf("dictionary released: releases %d\n", n_krel);
    // CFTree with a guest context
    CFTreeContext tc = {0, (void*)"root-info", t_ret, t_rel, t_desc};
    CFTreeRef root = CFTreeCreate(NULL, &tc);
    CFTreeContext tc2 = {0, (void*)"child-info", t_ret, t_rel, t_desc};
    CFTreeRef ch = CFTreeCreate(NULL, &tc2); CFTreeAppendChild(root, ch);
    CFTreeContext out = {0}; CFTreeGetContext(CFTreeGetFirstChild(root), &out);
    CFStringRef tdsc = CFCopyDescription(root);
    printf("tree: children %ld child info '%s' desc-has-info %d\n", (long)CFTreeGetChildCount(root), (const char*)out.info,
           CFStringFind(tdsc, CFSTR("root-info"), 0).location != kCFNotFound);
    CFRelease(tdsc); CFRelease(ch); CFRelease(root);
    // NSHashTable / NSMapTable with C callbacks
    NSHashTableCallBacks hc = {h_hash, h_eq, NULL, NULL, h_desc};
    NSHashTable* ht = NSCreateHashTable(hc, 0);
    const char* words[] = {"one", "two", "three", "four", "seven"};
    for (int i = 0; i < 5; i++) NSHashInsert(ht, words[i]);
    printf("NSHashTable: count %lu get(six) %s\n", (unsigned long)NSCountHashTable(ht), (const char*)NSHashGet(ht, "six") ?: "(nil)");
    NSString* hd = NSStringFromHashTable(ht);
    printf("NSHashTable describe: has s:three %d\n", [hd containsString:@"s:three"]);
    NSFreeHashTable(ht);
    NSMapTableKeyCallBacks mk = {mk_hash, mk_eq, NULL, NULL, NULL, NULL};
    NSMapTable* mt = NSCreateMapTable(mk, NSIntegerMapValueCallBacks, 0);
    for (uintptr_t i = 1; i <= 12; i++) NSMapInsert(mt, (void*)i, (void*)(i * 10));
    printf("NSMapTable: count %lu get(15) %ld\n", (unsigned long)NSCountMapTable(mt), (long)NSMapGet(mt, (void*)15));
    NSFreeMapTable(mt);
    // stored callbacks: pthread key destructor on the exiting thread
    pthread_key_create(&key, key_dtor);
    pthread_t t; pthread_create(&t, NULL, key_thread, NULL); pthread_join(t, NULL);
    printf("pthread key destructor: value %d on main %d\n", key_dtor_ran, key_dtor_main);
    // dispatch finalizer and queue-specific destructor, called when the queue goes away
    int fin_val = 31;
    dispatch_queue_t q = dispatch_queue_create("gd.q", NULL);
    dispatch_set_context(q, &fin_val); dispatch_set_finalizer_f(q, q_fin);
    static char spec_key;
    dispatch_queue_set_specific(q, &spec_key, (void*)5, spec_free);
    dispatch_queue_set_specific(q, &spec_key, (void*)6, spec_free);     // replacing runs the first destructor
    dispatch_sync(q, ^{ printf("queue specific in queue: %ld\n", (long)dispatch_get_specific(&spec_key)); });
    q = nil;
    for (int i = 0; i < 200 && !fin_ran; i++) usleep(5000);
    printf("dispatch finalizer %d, specific destructors %d\n", fin_ran, spec_dtor);
    // CFNotificationCenter observer called on the posting thread
    int add = 1000;
    CFNotificationCenterAddObserver(CFNotificationCenterGetLocalCenter(), &add, note_cb, CFSTR("gd.note"), NULL,
                                    CFNotificationSuspensionBehaviorDeliverImmediately);
    pthread_create(&t, NULL, poster, NULL); pthread_join(t, NULL);
    printf("CF notification: %d on main %d\n", notes, note_main);
    CFNotificationCenterRemoveEveryObserver(CFNotificationCenterGetLocalCenter(), &add);
    // signal handler, signal sent from another thread to the main thread
    signal(SIGUSR1, on_usr1);
    pthread_t self = pthread_self();
    pthread_create(&t, NULL, raiser, &self); pthread_join(t, NULL);
    for (int i = 0; i < 200 && !got_sig; i++) usleep(5000);
    void (*old)(int) = signal(SIGUSR1, SIG_DFL);
    printf("signal: %d on main %d, old handler round trip %d\n", (int)got_sig, (int)sig_main, old == on_usr1);
    // CFRunLoopSource on a background run loop
    int inc = 3;
    CFRunLoopSourceContext sc = {0, &inc, NULL, NULL, NULL, NULL, NULL, s_sched, s_cancel, s_perform};
    CFRunLoopSourceRef src = CFRunLoopSourceCreate(NULL, 0, &sc);
    ready = dispatch_semaphore_create(0); done = dispatch_semaphore_create(0);
    pthread_create(&t, NULL, bg_loop, (void*)src);
    dispatch_semaphore_wait(ready, dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC));
    CFRunLoopSourceSignal(src); CFRunLoopWakeUp(bg_rl);
    dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC));
    pthread_join(t, NULL);
    printf("run loop source: schedule %d perform %d cancel %d\n", src_sched, src_perf, src_cancel);
    CFRelease(src);
  }
  return 0;
}
