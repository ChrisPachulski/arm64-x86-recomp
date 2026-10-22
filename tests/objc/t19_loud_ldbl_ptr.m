// LOUD: a pointer to long double crosses a guest/host method boundary (the host calls a guest method through
// NSInvocation). Guest long double is 8 bytes, host x87 16: the bridge must refuse the signature, never pass it as void*.
#import <Foundation/Foundation.h>
@interface K : NSObject - (void)put:(long double*)p; @end
@implementation K - (void)put:(long double*)p { *p = 2.5L; } @end
int main(void) {
  @autoreleasepool {
    K* k = [K new];
    struct { long double v; long canary; } s = {0, 0x1234};
    NSInvocation* inv = [NSInvocation invocationWithMethodSignature:[k methodSignatureForSelector:@selector(put:)]];
    inv.target = k; inv.selector = @selector(put:);
    long double* p = &s.v; [inv setArgument:&p atIndex:2]; [inv invoke];
    printf("value %.2Lf canary %lx\n", s.v, s.canary);
  }
  return 0;
}
