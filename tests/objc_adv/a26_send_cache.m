// The per-site send cache's guest-method fast path (gbridge gd_msgsend, gobjc msg_guest): one send site warmed on a guest
// method, then the method replaced with method_setImplementation and with class_replaceMethod (a block IMP); the receiver's
// class changed under it by KVO (a host-side isa swizzle that bumps no epoch) and back; a subclass and its overriding
// method at a site cached on the base class; and tagged pointers, nil and guest objects alternating at one site.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
@interface Acc : NSObject { long v; } - (long)add:(long)x; @property long w; @end
@implementation Acc
- (long)add:(long)x { v += x ^ (v >> 7); return v; }
@end
@interface Sub : Acc @end
@implementation Sub
- (long)add:(long)x { return [super add:x] * 2; }
@end
@interface NSObject (Tag) - (long)gtag; @end
@implementation NSObject (Tag)
- (long)gtag { return (long)[NSStringFromClass([self class]) length]; }
@end
@interface Obs : NSObject @property long seen; @end
@implementation Obs
- (void)observeValueForKeyPath:(NSString*)k ofObject:(id)o change:(NSDictionary*)c context:(void*)x { self.seen++; }
@end
static long newAdd(id self, SEL _cmd, long x) { return x * 1000; }
__attribute__((noinline)) static long send_add(Acc* a, long x) { return [a add:x]; }  // the one send site under test
__attribute__((noinline)) static void send_setw(Acc* a, long x) { [a setW:x]; }
__attribute__((noinline)) static long send_tag(id o) { return [o gtag]; }
static long warm(Acc* a, long n) { long s = 0; for (long i = 0; i < n; i++) s += send_add(a, i); return s; }

int main(void) {
  @autoreleasepool {
    Acc* a = [Acc new];
    printf("warm: %ld\n", warm(a, 5000));
    Method m = class_getInstanceMethod([Acc class], @selector(add:));
    IMP old = method_setImplementation(m, (IMP)newAdd);
    printf("after method_setImplementation: %ld %ld\n", send_add(a, 3), warm(a, 100));
    class_replaceMethod([Acc class], @selector(add:), imp_implementationWithBlock(^long(id s, long x) { return x + 7; }), "q@:q");
    printf("after class_replaceMethod: %ld %ld\n", send_add(a, 3), warm(a, 100));
    method_setImplementation(m, old);
    printf("restored: %ld %ld\n", send_add(a, 3), warm(a, 100));
    Sub* b = [Sub new];
    long t = 0;
    for (int i = 0; i < 2000; i++) t += send_add((i & 3) ? a : b, i);
    printf("base and subclass at one site: %ld\n", t);
    for (long i = 0; i < 1000; i++) send_setw(a, i);
    Obs* o = [Obs new];
    [a addObserver:o forKeyPath:@"w" options:0 context:NULL];
    for (long i = 0; i < 1000; i++) send_setw(a, i);
    printf("kvo: seen %ld, w %ld, add %ld\n", o.seen, a.w, send_add(a, 2));
    [a removeObserver:o forKeyPath:@"w"];
    for (long i = 0; i < 1000; i++) send_setw(a, i + 1);
    printf("kvo removed: seen %ld, w %ld\n", o.seen, a.w);
    NSArray* rs = @[a, @7, [NSString stringWithFormat:@"%d", 42], [NSNumber numberWithLongLong:1LL << 62], b, @3.5];
    long g = 0;
    for (int i = 0; i < 6000; i++) g += send_tag(rs[i % rs.count]) * (i % 7);
    g += send_tag(nil);
    printf("tagged, objects and nil at one site: %ld\n", g);
  }
  return 0;
}
