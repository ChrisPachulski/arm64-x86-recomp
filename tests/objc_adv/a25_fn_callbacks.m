// Guest C functions handed to host code as function pointers, each typed from its header prototype: qsort, CFArraySortValues,
// pthread_once, atexit, dispatch_*_f, CFRunLoopTimer / CFRunLoopObserver callbacks whose contexts carry guest retain /
// release / copyDescription functions (struct fields), CFRunLoopTimerGetContext handing them back, NSMutableArray
// sortUsingFunction:context: and the NSPointerFunctions function-pointer properties (^? in the runtime's encodings).
#import <Foundation/Foundation.h>
#include <pthread.h>
#include <stdatomic.h>

static int cmp_int(const void* a, const void* b) { return *(const int*)a - *(const int*)b; }
static CFComparisonResult cf_cmp(const void* a, const void* b, void* ctx) {
  long x, y; CFNumberGetValue((CFNumberRef)a, kCFNumberLongType, &x); CFNumberGetValue((CFNumberRef)b, kCFNumberLongType, &y);
  long d = *(int*)ctx * (x - y);
  return d < 0 ? kCFCompareLessThan : d > 0 ? kCFCompareGreaterThan : kCFCompareEqualTo;
}
static pthread_once_t once = PTHREAD_ONCE_INIT;
static int once_count;
static void once_fn(void) { once_count++; }
static void at_exit_fn(void) { printf("atexit ran\n"); fflush(stdout); }
static void add5(void* ctx) { *(int*)ctx += 5; }
static atomic_long apply_sum;
static void apply_fn(void* ctx, size_t i) { atomic_fetch_add(&apply_sum, (long)i * *(int*)ctx); }
static int retains, releases, descs;
static const void* ctx_retain(const void* info) { retains++; return info; }
static void ctx_release(const void* info) { releases++; }
static CFStringRef ctx_desc(const void* info) { descs++; return CFSTR("guest context"); }
static void timer_cb(CFRunLoopTimerRef t, void* info) { (*(int*)info)++; CFRunLoopStop(CFRunLoopGetCurrent()); }
static void obs_cb(CFRunLoopObserverRef o, CFRunLoopActivity act, void* info) { (*(int*)info)++; }
static NSInteger ns_cmp(id a, id b, void* ctx) { return *(int*)ctx * [a compare:b]; }
static NSUInteger hash7(const void* item, NSUInteger (*size)(const void* item)) { return 7; }
static BOOL same_len(const void* a, const void* b, NSUInteger (*size)(const void* item)) { return strlen(a) == strlen(b); }

int main(void) {
  @autoreleasepool {
    int v[] = {5, 3, 9, 1, 7};
    qsort(v, 5, sizeof v[0], cmp_int);
    printf("qsort %d %d %d %d %d\n", v[0], v[1], v[2], v[3], v[4]);

    CFMutableArrayRef arr = CFArrayCreateMutable(NULL, 0, &kCFTypeArrayCallBacks);
    for (long i = 0; i < 5; i++) { long n = (i * 7) % 5; CFNumberRef x = CFNumberCreate(NULL, kCFNumberLongType, &n); CFArrayAppendValue(arr, x); CFRelease(x); }
    int dir = -1;
    CFArraySortValues(arr, CFRangeMake(0, CFArrayGetCount(arr)), cf_cmp, &dir);
    printf("CFArraySortValues %s\n", [(__bridge NSArray*)arr componentsJoinedByString:@","].UTF8String);
    CFRelease(arr);

    pthread_once(&once, once_fn); pthread_once(&once, once_fn);
    printf("pthread_once %d\n", once_count);
    atexit(at_exit_fn);

    int x = 1;
    dispatch_sync_f(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), &x, add5);
    dispatch_group_t g = dispatch_group_create();
    dispatch_group_async_f(g, dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), &x, add5);
    dispatch_group_wait(g, DISPATCH_TIME_FOREVER);
    int mul = 3;
    dispatch_apply_f(10, dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), &mul, apply_fn);
    printf("dispatch %d %ld\n", x, (long)atomic_load(&apply_sum));

    int fired = 0, seen = 0;
    CFRunLoopTimerContext tc = {0, &fired, ctx_retain, ctx_release, ctx_desc};
    CFRunLoopObserverContext oc = {0, &seen, ctx_retain, ctx_release, NULL};
    CFRunLoopTimerRef t = CFRunLoopTimerCreate(NULL, CFAbsoluteTimeGetCurrent() + 0.02, 0, 0, 0, timer_cb, &tc);
    CFRunLoopObserverRef o = CFRunLoopObserverCreate(NULL, kCFRunLoopBeforeTimers, true, 0, obs_cb, &oc);
    CFRunLoopTimerContext back; memset(&back, 0, sizeof back);
    CFRunLoopTimerGetContext(t, &back);
    printf("context fields back: %d %d %d %d, input intact %d\n", back.info == &fired, back.retain == ctx_retain, back.release == ctx_release,
           back.copyDescription == ctx_desc, tc.retain == ctx_retain && tc.release == ctx_release);
    CFStringRef d = CFCopyDescription(t);
    printf("description mentions the guest's: %d\n", CFStringFind(d, CFSTR("guest context"), 0).location != kCFNotFound);
    CFRelease(d);
    CFRunLoopAddTimer(CFRunLoopGetCurrent(), t, kCFRunLoopDefaultMode);
    CFRunLoopAddObserver(CFRunLoopGetCurrent(), o, kCFRunLoopDefaultMode);
    CFRunLoopRunInMode(kCFRunLoopDefaultMode, 5, false);
    CFRunLoopRemoveObserver(CFRunLoopGetCurrent(), o, kCFRunLoopDefaultMode);
    CFRunLoopObserverInvalidate(o); CFRelease(o);
    CFRunLoopTimerInvalidate(t); CFRelease(t);
    printf("runloop fired %d observed %d retains==releases %d descs %d\n", fired, seen > 0, retains == releases && retains > 0, descs > 0);

    NSMutableArray* m = [@[@4, @2, @8, @6] mutableCopy];
    int up = 1;
    [m sortUsingFunction:ns_cmp context:&up];
    printf("sortUsingFunction %s\n", [m componentsJoinedByString:@","].UTF8String);

    NSPointerFunctions* pf = [NSPointerFunctions pointerFunctionsWithOptions:NSPointerFunctionsCStringPersonality | NSPointerFunctionsOpaqueMemory];
    pf.hashFunction = hash7;
    pf.isEqualFunction = same_len;
    printf("getters give back our functions: hash %d isEqual %d\n", pf.hashFunction == hash7, pf.isEqualFunction == same_len);
    NSHashTable* h = [[NSHashTable alloc] initWithPointerFunctions:pf capacity:4];
    NSHashInsert(h, "abc"); NSHashInsert(h, "xyz"); NSHashInsert(h, "four");
    printf("NSHashTable with guest hash/equality: count %lu\n", (unsigned long)NSCountHashTable(h));
  }
  return 0;
}
