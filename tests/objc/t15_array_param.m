// Array-typed method parameters (encoded [4f], [3i], passed as a pointer on both arches): guest methods invoked by the host
// through NSInvocation (host -> guest closures), sent from the guest, and the encodings the runtime reports.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
@interface A : NSObject - (float)first:(float[4])a; - (int)sum:(int[3])v plus:(double)d; @end
@implementation A
- (float)first:(float[4])a { return a[0] + 10 * a[3]; }
- (int)sum:(int[3])v plus:(double)d { return v[0] + v[1] + v[2] + (int)d; }
@end
int main(void) {
  @autoreleasepool {
    A* a = [A new];
    float f[4] = {1.5f, 2, 3, 4};
    int v[3] = {10, 20, 30};
    printf("encodings %s | %s\n", method_getTypeEncoding(class_getInstanceMethod([A class], @selector(first:))),
           method_getTypeEncoding(class_getInstanceMethod([A class], @selector(sum:plus:))));
    printf("direct %.1f %d\n", [a first:f], [a sum:v plus:2.9]);
    NSInvocation* inv = [NSInvocation invocationWithMethodSignature:[a methodSignatureForSelector:@selector(first:)]];
    inv.target = a; inv.selector = @selector(first:);
    float* fp = f; [inv setArgument:&fp atIndex:2]; [inv invoke];
    float r = 0; [inv getReturnValue:&r];
    printf("invocation first %.1f\n", r);
    NSInvocation* i2 = [NSInvocation invocationWithMethodSignature:[a methodSignatureForSelector:@selector(sum:plus:)]];
    i2.target = a; i2.selector = @selector(sum:plus:);
    int* vp = v; double d = 4.5; [i2 setArgument:&vp atIndex:2]; [i2 setArgument:&d atIndex:3]; [i2 invoke];
    int s = 0; [i2 getReturnValue:&s];
    printf("invocation sum %d\n", s);
  }
  return 0;
}
