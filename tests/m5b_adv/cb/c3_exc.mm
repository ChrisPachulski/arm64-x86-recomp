// Exceptions and longjmp leaving guest callbacks through host frames (libc, CoreFoundation, libdispatch, Foundation),
// nested host frames, and a throw caught inside a callback on a host-owned thread. argv[1] "uncaught" lets a C++
// exception escape a qsort comparator to terminate().
#import <Foundation/Foundation.h>
#include <CoreFoundation/CoreFoundation.h>
#include <dispatch/dispatch.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdexcept>

struct Boom { int code; };
static int calls;
static int cmp_throw(const void* a, const void* b) { if (++calls == 3) throw Boom{*(const int*)a * 0 + 7}; return *(const int*)a - *(const int*)b; }
static int cmp_throw_std(const void* a, const void* b) { if (++calls == 2) throw std::runtime_error("from bsearch"); return *(const int*)a - *(const int*)b; }
static int cmp_objc(const void* a, const void* b) { if (++calls == 2) @throw [NSException exceptionWithName:@"Cmp" reason:@"objc from qsort" userInfo:nil]; return 0; }
static void apply_throw(const void* v, void* ctx) { if ((long)v == 3) throw Boom{(int)(long)v}; ++*(int*)ctx; }
static void apply_objc(const void* v, void* ctx) { if ((long)v == 2) @throw [NSException exceptionWithName:@"App" reason:@"objc from applier" userInfo:nil]; }
static void sync_throw(void* ctx) { throw std::logic_error((const char*)ctx); }
static int n_inner;
static int inner_cmp(const void* a, const void* b) { if (++n_inner == 2) throw Boom{99}; return 0; }
static int outer_cmp(const void* a, const void* b) {           // qsort inside a qsort comparator; the inner throw is caught here
  int w[4] = {4, 3, 2, 1};
  try { qsort(w, 4, sizeof w[0], inner_cmp); } catch (Boom& e) { return e.code == 99 ? *(const int*)a - *(const int*)b : 0; }
  return *(const int*)a - *(const int*)b;
}
static jmp_buf jb;
static int cmp_jump(const void* a, const void* b) { if (++calls == 4) longjmp(jb, 5); return 0; }
static int mem_read(void* c, char* b, int n) { throw Boom{(int)n > 0 ? 13 : 0}; }
static void worker(void* ctx) {                                 // on a libdispatch thread
  int* out = (int*)ctx;
  int v[6] = {6, 5, 4, 3, 2, 1};
  try { calls = 0; qsort(v, 6, sizeof v[0], cmp_throw); *out = -1; } catch (Boom& e) { *out = e.code; }
}

int main(int argc, char** argv) {
  @autoreleasepool {
    setvbuf(stdout, NULL, _IOLBF, 0);
    int v[8] = {8, 7, 6, 5, 4, 3, 2, 1};
    if (argc > 1 && !strcmp(argv[1], "uncaught")) { printf("uncaught: before\n"); qsort(v, 8, sizeof v[0], cmp_throw); printf("not reached\n"); return 1; }
    try { calls = 0; qsort(v, 8, sizeof v[0], cmp_throw); printf("qsort: no throw\n"); } catch (Boom& e) { printf("C++ through qsort: %d after %d calls\n", e.code, calls); }
    int s[5] = {1, 3, 5, 7, 9}, key = 7;
    try { calls = 0; bsearch(&key, s, 5, sizeof s[0], cmp_throw_std); printf("bsearch: no throw\n"); }
    catch (std::exception& e) { printf("C++ through bsearch: %s\n", e.what()); }
    @try { calls = 0; qsort(v, 8, sizeof v[0], cmp_objc); printf("qsort objc: no throw\n"); }
    @catch (NSException* e) { printf("ObjC through qsort: %s / %s\n", e.name.UTF8String, e.reason.UTF8String); }
    const void* vals[5] = {(void*)1, (void*)2, (void*)3, (void*)4, (void*)5};
    CFArrayRef arr = CFArrayCreate(NULL, vals, 5, NULL);
    int seen = 0;
    try { CFArrayApplyFunction(arr, CFRangeMake(0, 5), apply_throw, &seen); printf("CFArrayApplyFunction: no throw\n"); }
    catch (Boom& e) { printf("C++ through CFArrayApplyFunction: %d seen %d\n", e.code, seen); }
    @try { CFArrayApplyFunction(arr, CFRangeMake(0, 5), apply_objc, NULL); printf("CFArrayApplyFunction objc: no throw\n"); }
    @catch (NSException* e) { printf("ObjC through CFArrayApplyFunction: %s\n", e.reason.UTF8String); }
    CFRelease(arr);
    (void)sync_throw;                                           // a throw through dispatch_sync_f crashes natively (SIGSEGV): not tested
    try { [@[@1, @2, @3] enumerateObjectsUsingBlock:^(id o, NSUInteger i, BOOL* stop) { if (i == 1) throw Boom{(int)[o intValue] * 10}; }];
          printf("enumerate: no throw\n"); }
    catch (Boom& e) { printf("C++ through enumerateObjectsUsingBlock: %d\n", e.code); }
    try { [@[@"b", @"a", @"c"] sortedArrayUsingComparator:^NSComparisonResult(id x, id y) { throw std::out_of_range("comparator block"); }];
          printf("sortedArrayUsingComparator: no throw\n"); }
    catch (std::out_of_range& e) { printf("C++ through sortedArrayUsingComparator: %s\n", e.what()); }
    int w[4] = {4, 1, 3, 2};
    n_inner = 0; qsort(w, 4, sizeof w[0], outer_cmp);
    printf("nested qsort, inner throw caught in outer comparator: %d %d %d %d (inner calls %d)\n", w[0], w[1], w[2], w[3], n_inner);
    calls = 0;
    int jv = setjmp(jb);
    if (!jv) { qsort(v, 8, sizeof v[0], cmp_jump); printf("longjmp: not taken\n"); }
    else printf("longjmp out of qsort comparator: %d after %d calls\n", jv, calls);
    (void)mem_read;                                             // a throw through fread terminates natively: not tested
    int res = 0;
    dispatch_sync_f(dispatch_get_global_queue(0, 0), &res, worker);
    printf("caught inside a callback on a dispatch thread: %d\n", res);
    dispatch_group_t g = dispatch_group_create(); int res2 = 0;
    dispatch_group_async_f(g, dispatch_get_global_queue(0, 0), &res2, worker);
    dispatch_group_wait(g, dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC));
    printf("caught inside an async callback on a worker thread: %d\n", res2);
  }
  return 0;
}
