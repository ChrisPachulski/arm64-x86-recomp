// Guest swizzling: method_exchangeImplementations on guest and on host methods, the swizzled method calling the original
// through its swapped selector, and the classic saved-IMP pattern (method_setImplementation, then calling the old IMP).
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
@interface G : NSObject - (NSString*)foo; - (NSString*)bar; - (int)num:(int)x; @end
@implementation G
- (NSString*)foo { return @"foo"; }
- (NSString*)bar { return [@"bar>" stringByAppendingString:[self bar]]; }   // after swizzle [self bar] is the original foo
- (int)num:(int)x { return x + 1; }
@end
@implementation NSString (Swz)
- (NSString*)swz_lowercaseString { return [@"swz:" stringByAppendingString:[self swz_lowercaseString]]; }
@end
static IMP origNum;
static int newNum(id self, SEL _cmd, int x) { return ((int (*)(id, SEL, int))origNum)(self, _cmd, x) * 100; }
int main(void) {
  @autoreleasepool {
    G* g = [G new];
    method_exchangeImplementations(class_getInstanceMethod([G class], @selector(foo)), class_getInstanceMethod([G class], @selector(bar)));
    printf("guest swap: foo=%s bar=%s\n", g.foo.UTF8String, g.bar.UTF8String);
    Class sc = [@"ABC" class];
    method_exchangeImplementations(class_getInstanceMethod(sc, @selector(lowercaseString)), class_getInstanceMethod(sc, @selector(swz_lowercaseString)));
    printf("host swap: %s\n", [@"ABC" lowercaseString].UTF8String);
    method_exchangeImplementations(class_getInstanceMethod(sc, @selector(lowercaseString)), class_getInstanceMethod(sc, @selector(swz_lowercaseString)));
    printf("host swap back: %s\n", [@"ABC" lowercaseString].UTF8String);
    Method m = class_getInstanceMethod([G class], @selector(num:));
    origNum = method_setImplementation(m, (IMP)newNum);
    printf("saved guest IMP: %d\n", [g num:4]);
  }
  return 0;
}
