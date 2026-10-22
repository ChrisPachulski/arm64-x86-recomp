/* Per-call-site send cache semantics: every probe runs ONE call site (a loop or a helper) many times while the runtime
   changes under it; native x86_64 is the oracle. Prints results only (no addresses). */
#include "perf.h"
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <pthread.h>

typedef struct { double x, y, w, h; } Box;                    /* 32 bytes: x86-64 stret, AAPCS64 x8 */
typedef struct { long a, b; } Pair;                           /* 16 bytes: two registers on both */

@interface Base : NSObject { @public long n; }
- (long)val;
- (long)twice:(long)x;
- (Box)box:(double)s;
- (Pair)pair:(long)a;
- (BOOL)isOdd:(int)x;
- (double)mix:(int)a d:(double)b f:(float)c l:(long)d;
@end
@implementation Base
- (long)val { return 1; }
- (long)twice:(long)x { return 2 * x; }
- (Box)box:(double)s { Box b = {s, s + 1, s + 2, s + 3}; return b; }
- (Pair)pair:(long)a { Pair p = {a, -a}; return p; }
- (BOOL)isOdd:(int)x { return x & 1; }
- (double)mix:(int)a d:(double)b f:(float)c l:(long)d { return a + b * 2 + c * 4 + d * 8; }
@end
@interface Sub : Base
@end
@implementation Sub
- (long)val { return 10 + [super val]; }                      /* objc_msgSendSuper2 */
@end
@interface Other : NSObject
- (long)val;
@end
@implementation Other
- (long)val { return 100; }
@end
@interface Fwd : NSObject
@end
@implementation Fwd
- (id)forwardingTargetForSelector:(SEL)s { static Base* b; if (!b) b = [Base new]; return s == @selector(val) ? b : nil; }
@end
@interface Obs : NSObject
@property long count;
@end
@implementation Obs
- (void)observeValueForKeyPath:(NSString*)k ofObject:(id)o change:(NSDictionary*)c context:(void*)x { self.count++; }
@end
@interface Kv : NSObject
@property long level;
@end
@implementation Kv
@end

static long alt_val(id self, SEL _cmd) { return 7; }
static long add_late(id self, SEL _cmd) { return 42; }

__attribute__((noinline)) static long site_val(id o) { return [(Base*)o val]; }       /* one call site, many receivers */
__attribute__((noinline)) static long site_late(id o) { return [(id)o performSelector:@selector(lateMethod)] ? 1 : 0; }

static void* hammer(void* arg) {                              /* the same site from two threads, alternating classes */
  NSArray* objs = (__bridge NSArray*)arg;
  long s = 0;
  for (int i = 0; i < 200000; i++) s += site_val(objs[i & 1]);
  return (void*)s;
}

int main(void) {
  @autoreleasepool {
    uint64_t t0 = perf_ns();
    Base* b = [Base new]; Sub* sb = [Sub new]; Other* ot = [Other new];
    long s = 0;
    for (int i = 0; i < 1000; i++) s += site_val(b);
    printf("plain %ld\n", s);
    s = 0;
    for (int i = 0; i < 1000; i++) s += site_val(i % 3 == 0 ? (id)b : i % 3 == 1 ? (id)sb : (id)ot);
    printf("polymorphic %ld\n", s);
    s = 0;
    for (int i = 0; i < 1000; i++) s += site_val(i & 1 ? nil : b);
    printf("nil receivers %ld\n", s);
    Method m = class_getInstanceMethod([Base class], @selector(val));
    IMP old = method_setImplementation(m, (IMP)alt_val);
    printf("swizzled base %ld sub %ld\n", site_val(b), site_val(sb));
    method_setImplementation(m, old);
    printf("restored base %ld sub %ld\n", site_val(b), site_val(sb));
    Method m1 = class_getInstanceMethod([Base class], @selector(val)), m2 = class_getInstanceMethod([Base class], @selector(twice:));
    long before = site_val(b);
    method_exchangeImplementations(m1, m2);
    long during = site_val(b) != before;
    method_exchangeImplementations(m1, m2);
    printf("exchanged changed %ld back %ld\n", during, site_val(b));
    printf("added late before %ld\n", (long)[b respondsToSelector:@selector(lateMethod)]);
    class_addMethod([Base class], @selector(lateMethod), (IMP)add_late, "l@:");
    printf("added late after %ld %ld\n", site_late(b), site_late(sb));
    class_addMethod([Sub class], @selector(val), (IMP)alt_val, "l@:");   /* already defined there: no change */
    class_replaceMethod([Other class], @selector(val), (IMP)alt_val, "l@:");
    printf("replaced other %ld\n", site_val(ot));
    Fwd* fw = [Fwd new];
    s = 0;
    for (int i = 0; i < 100; i++) s += site_val(fw);
    printf("forwarded %ld\n", s);
    Kv* kv = [Kv new]; Obs* ob = [Obs new];
    for (int i = 0; i < 10; i++) kv.level = i;
    [kv addObserver:ob forKeyPath:@"level" options:0 context:NULL];
    for (int i = 0; i < 10; i++) kv.level = i;
    [kv removeObserver:ob forKeyPath:@"level"];
    for (int i = 0; i < 10; i++) kv.level = i;
    printf("kvo notifications %ld level %ld\n", ob.count, kv.level);
    double bs = 0; long ps = 0;
    for (int i = 0; i < 100; i++) { Box x = [b box:i]; bs += x.x + x.y * 2 + x.w * 3 + x.h * 4; Pair p = [b pair:i]; ps += p.a - p.b; }
    printf("struct returns %.1f %ld\n", bs, ps);
    long odd = 0; double mx = 0;
    for (int i = 0; i < 100; i++) { odd += [b isOdd:i]; mx += [b mix:i d:i * 0.5 f:i * 0.25f l:-i]; }
    printf("guest typed %ld %.2f\n", odd, mx);
    NSMutableArray* arr = [NSMutableArray array];
    for (int i = 0; i < 50; i++) [arr addObject:@(i * 3)];   /* host: void, object argument (tagged NSNumber) */
    long hs = 0; double hd = 0;
    for (int i = 0; i < 50; i++) {
      hs += [arr[i] longValue] + (long)[arr count] + [arr[i] isEqual:@(i * 3)] + [arr containsObject:@(i)];
      hd += [arr[i] doubleValue] + [@(i * 0.5) floatValue];
    }
    NSString* str = [NSString stringWithFormat:@"%d-%s", 7, "x"];
    hs += (long)[str length] + [str characterAtIndex:1] + [str hasPrefix:@"7"] + (long)[str rangeOfString:@"x"].location;
    printf("host typed %ld %.2f\n", hs, hd);
    __block long bsum = 0;
    [arr enumerateObjectsUsingBlock:^(id o, NSUInteger i, BOOL* stop) { bsum += [o longValue]; if (i == 40) *stop = YES; }];
    printf("block argument %ld\n", bsum);
    long cs = 0;
    for (int i = 0; i < 100; i++) cs += [[NSNumber numberWithInt:i] intValue] + (long)[NSString class];   /* class receivers */
    printf("class receivers %ld\n", cs - 100L * (long)[NSString class]);
    pthread_t th[2];
    NSArray* pairs = @[b, ot];
    for (int k = 0; k < 2; k++) pthread_create(&th[k], NULL, hammer, (__bridge void*)pairs);
    long ts = 0;
    for (int k = 0; k < 2; k++) { void* r; pthread_join(th[k], &r); ts += (long)r; }
    printf("threads %ld\n", ts);
    perf_end(t0);
  }
  return 0;
}
