/* Native x86_64 probe for gobjc.hpp's send-cache check: the same objc_msgLookup / objc_msgLookupSuper2 thunks (IMP in r11)
   must return what class_getMethodImplementation returns for every non-forwarded (receiver, selector), across runtime
   changes (swizzle, addMethod on a subclass, category-style replaceMethod, KVO isa change, tagged pointers, classes);
   for a forwarded selector the thunk must NOT return a real method's IMP. Prints one line per case and a summary. */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>

extern IMP gd_msglookup(id self, SEL sel);
extern IMP gd_msglookup_super2(const struct objc_super* sup, SEL sel);
__asm__(".text\n.p2align 4\n"
        "_gd_msglookup:\n  pushq %rbp\n  movq %rsp, %rbp\n  callq _objc_msgLookup\n  movq %r11, %rax\n  popq %rbp\n  retq\n"
        ".p2align 4\n"
        "_gd_msglookup_super2:\n  pushq %rbp\n  movq %rsp, %rbp\n  callq _objc_msgLookupSuper2\n  movq %r11, %rax\n  popq %rbp\n  retq\n");

@interface PBase : NSObject { @public long n; }
- (long)val;
- (long)other;
@end
@implementation PBase
- (long)val { return 1; }
- (long)other { return 2; }
@end
@interface PSub : PBase
@end
@implementation PSub
- (long)val { return 10; }
@end
@interface PObs : NSObject
@end
@implementation PObs
- (void)observeValueForKeyPath:(NSString*)k ofObject:(id)o change:(NSDictionary*)c context:(void*)x {}
@end
@interface PKvo : NSObject
@property long level;
@end
@implementation PKvo
@end

static long alt(id self, SEL _cmd) { return 7; }
static int bad = 0, cases = 0;

static void check(const char* what, id o, SEL s) {
  IMP a = gd_msglookup(o, s), b = class_getMethodImplementation(object_getClass(o), s);
  int ok = b == (IMP)_objc_msgForward ? a != b : a == b;
  cases++; bad += !ok;
  printf("%-34s %s\n", what, ok ? "same" : "DIFF");
}
static void check_super(const char* what, id o, Class cur, SEL s) {
  struct objc_super sp = {o, cur};
  IMP a = gd_msglookup_super2(&sp, s), b = class_getMethodImplementation(class_getSuperclass(cur), s);
  int ok = a == b;
  cases++; bad += !ok;
  printf("%-34s %s\n", what, ok ? "same" : "DIFF");
}

int main(void) {
  @autoreleasepool {
    PBase* b = [PBase new]; PSub* sb = [PSub new];
    for (int i = 0; i < 3; i++) { check("plain", b, @selector(val)); check("override", sb, @selector(val)); }
    check("inherited", sb, @selector(other));
    check("host method on guest-like class", b, @selector(description));
    check_super("super2 val", sb, [PSub class], @selector(val));
    check_super("super2 description", b, [PBase class], @selector(description));
    Method m1 = class_getInstanceMethod([PBase class], @selector(val)), m2 = class_getInstanceMethod([PBase class], @selector(other));
    method_exchangeImplementations(m1, m2);
    check("after exchange base", b, @selector(val));
    check("after exchange sub inherited", sb, @selector(other));
    method_exchangeImplementations(m1, m2);
    check("after exchange back", b, @selector(val));
    class_addMethod([PSub class], @selector(other), (IMP)alt, "q@:");
    check("after addMethod on subclass", sb, @selector(other));
    check("base untouched by addMethod", b, @selector(other));
    class_replaceMethod([PBase class], @selector(other), (IMP)alt, "q@:");
    check("after replaceMethod", b, @selector(other));
    method_setImplementation(class_getInstanceMethod([PSub class], @selector(val)), (IMP)alt);
    check("after setImplementation", sb, @selector(val));
    check("forwarded selector", b, @selector(noSuchSelector));
    PKvo* k = [PKvo new]; PObs* ob = [PObs new];
    check("kvo before", k, @selector(setLevel:));
    [k addObserver:ob forKeyPath:@"level" options:0 context:NULL];
    check("kvo observed (isa swizzled)", k, @selector(setLevel:));
    check("kvo observed getter", k, @selector(level));
    [k removeObserver:ob forKeyPath:@"level"];
    check("kvo removed", k, @selector(setLevel:));
    check("tagged NSNumber", @7, @selector(longValue));
    check("tagged NSString", [NSString stringWithFormat:@"%d", 1], @selector(length));
    check("class receiver", (id)[NSArray class], @selector(array));
    check("constant array", @[@1, @2], @selector(count));
    [b release]; [sb release]; [k release]; [ob release];
  }
  printf("cases %d, differing %d\n", cases, bad);
  return bad != 0;
}
