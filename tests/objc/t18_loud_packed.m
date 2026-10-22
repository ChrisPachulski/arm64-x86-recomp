// LOUD: a packed struct by value crosses a guest/host method boundary (the host calls a guest method through NSInvocation).
// The type encoding ({?=cd}) does not say packed; the stack offsets do (9 bytes, not 16): the bridge must refuse it, never
// pass a naturally aligned 16-byte record.
#import <Foundation/Foundation.h>
struct __attribute__((packed)) P { char c; double d; };
@interface K : NSObject - (double)take:(struct P)p tag:(int)t; @end
@implementation K - (double)take:(struct P)p tag:(int)t { return p.d * 10 + p.c + t; } @end
int main(void) {
  @autoreleasepool {
    K* k = [K new];
    NSInvocation* inv = [NSInvocation invocationWithMethodSignature:[k methodSignatureForSelector:@selector(take:tag:)]];
    inv.target = k; inv.selector = @selector(take:tag:);
    struct P p = {2, 1.5}; int t = 5;
    [inv setArgument:&p atIndex:2]; [inv setArgument:&t atIndex:3]; [inv invoke];
    double r = 0; [inv getReturnValue:&r];
    printf("packed result %.2f\n", r);
  }
  return 0;
}
