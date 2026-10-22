// imp_implementationWithBlock with a block returning a struct the x86-64 ABI returns in memory (NSRect: arm64 HFA in
// v0-v3, so the arm64 compiler never sets BLOCK_USE_STRET) and one returning a large non-HFA struct.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
typedef struct { long a, b, c; } L3;
@interface Empty : NSObject @end
@implementation Empty @end
@interface Empty (Dyn) - (NSRect)rectK:(double)k; - (L3)l3:(long)k; @end
int main(void) {
  setvbuf(stdout, NULL, _IONBF, 0);
  @autoreleasepool {
    IMP bl = imp_implementationWithBlock(^L3(id self, long k) { return (L3){k, k + 1, k + 2}; });
    class_addMethod([Empty class], sel_registerName("l3:"), bl, "{?=qqq}24@0:8q16");
    L3 l = [[Empty new] l3:5];
    printf("block L3 %ld %ld %ld\n", l.a, l.b, l.c);
    IMP bs = imp_implementationWithBlock(^NSRect(id self, double k) { return NSMakeRect(k, k * 2, k * 3, k * 4); });
    class_addMethod([Empty class], sel_registerName("rectK:"), bs, "{CGRect={CGPoint=dd}{CGSize=dd}}24@0:8d16");
    NSRect r = [[Empty new] rectK:1.5];
    printf("block rect %g %g %g %g\n", r.origin.x, r.origin.y, r.size.width, r.size.height);
  }
  return 0;
}
