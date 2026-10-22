// A raw native IMP (NSInvocation copies the bytes of -methodForSelector:'s result, so no bridge sees it) whose third
// argument looks like Swift metadata: header[0] -> a table whose slot 0 is that IMP. The call must still be typed as the
// method it is (double return in xmm0), not taken for a Swift value witness.
#import <Foundation/Foundation.h>
int main(void) {
  @autoreleasepool {
    NSNumber* n = @42.5;
    SEL s = @selector(doubleValue), mfs = @selector(methodForSelector:);
    NSInvocation* inv = [NSInvocation invocationWithMethodSignature:[n methodSignatureForSelector:mfs]];
    inv.target = n; inv.selector = mfs;
    [inv setArgument:&s atIndex:2];
    [inv invoke];
    double (*f)(id, SEL, void*) = NULL;
    [inv getReturnValue:&f];
    static void* table[16];
    static void* header[2];
    table[0] = (void*)f; header[0] = (void*)table; header[1] = (void*)0x200;
    double plain = f(@1.25, s, NULL);                         /* leaves 1.25 in v0: a mistyped call keeps it */
    double tricky = f(n, s, &header[1]);
    printf("plain %.2f tricky %.2f\n", plain, tricky);
  }
  return 0;
}
