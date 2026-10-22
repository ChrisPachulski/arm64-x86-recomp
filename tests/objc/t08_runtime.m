// The runtime API from guest code: forwarding (fast and NSInvocation), +resolveInstanceMethod: adding a guest C function,
// class_replaceMethod / method_exchangeImplementations swizzles, imp_implementationWithBlock, methodForSelector: IMP
// caching of guest and host methods, performSelector:, associated objects, a class built at run time by guest code.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>

@interface Fwd : NSObject
@property (nonatomic, strong) NSString* target;
@end
@implementation Fwd
- (id)forwardingTargetForSelector:(SEL)s { return s == @selector(uppercaseString) ? _target : nil; }
- (NSMethodSignature*)methodSignatureForSelector:(SEL)s {
  return s == @selector(stringByAppendingString:) ? [_target methodSignatureForSelector:s] : [super methodSignatureForSelector:s];
}
- (void)forwardInvocation:(NSInvocation*)inv { printf("forwardInvocation %s\n", sel_getName(inv.selector)); [inv invokeWithTarget:_target]; }
@end

static long twice(id self, SEL _cmd, long x) { return 2 * x; }
static NSString* swizzled(id self, SEL _cmd) { return @"swizzled"; }

@interface Dyn : NSObject
- (NSString*)a;
- (NSString*)b;
- (NSString*)orig;
@end
@implementation Dyn
+ (BOOL)resolveInstanceMethod:(SEL)s {
  if (s == sel_registerName("twice:")) { class_addMethod(self, s, (IMP)twice, "q24@0:8q16"); return YES; }
  return [super resolveInstanceMethod:s];
}
- (NSString*)a { return @"A"; }
- (NSString*)b { return @"B"; }
- (NSString*)orig { return @"orig"; }
@end

static int counter_value(id self, SEL _cmd) { return 1000 + [objc_getAssociatedObject(self, "k") intValue]; }

int main(void) {
  @autoreleasepool {
    Fwd* f = [Fwd new]; f.target = @"forward me";
    printf("fast forward: %s\n", [(id)f uppercaseString].UTF8String);
    printf("invocation forward: %s\n", [(id)f stringByAppendingString:@"!"].UTF8String);
    Dyn* d = [Dyn new];
    printf("resolved: responds %d value %ld\n", [d respondsToSelector:sel_registerName("twice:")],
           ((long (*)(id, SEL, long))objc_msgSend)(d, sel_registerName("twice:"), 21));
    IMP old = class_replaceMethod([Dyn class], @selector(orig), (IMP)swizzled, "@16@0:8");
    printf("replaced: %s, old IMP called directly: %s\n", [d orig].UTF8String, ((NSString* (*)(id, SEL))old)(d, @selector(orig)).UTF8String);
    method_exchangeImplementations(class_getInstanceMethod([Dyn class], @selector(a)), class_getInstanceMethod([Dyn class], @selector(b)));
    printf("exchanged: a=%s b=%s\n", [d a].UTF8String, [d b].UTF8String);
    IMP blk = imp_implementationWithBlock(^NSString*(id self, NSString* s) { return [s stringByAppendingString:@"+block"]; });
    class_addMethod([Dyn class], sel_registerName("viaBlock:"), blk, "@24@0:8@16");
    printf("block IMP: %s\n", [[d performSelector:sel_registerName("viaBlock:") withObject:@"x"] UTF8String]);
    NSString* (*gimp)(id, SEL) = (NSString* (*)(id, SEL))[d methodForSelector:@selector(b)];
    NSUInteger (*himp)(id, SEL) = (NSUInteger (*)(id, SEL))[@"seven" methodForSelector:@selector(length)];
    printf("cached IMPs: guest %s host %lu\n", gimp(d, @selector(b)).UTF8String, (unsigned long)himp(@"seven", @selector(length)));
    printf("performSelector: %s\n", [[@"abc" performSelector:@selector(uppercaseString)] UTF8String]);
    objc_setAssociatedObject(d, "k", @42, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    printf("associated: %s\n", [objc_getAssociatedObject(d, "k") description].UTF8String);
    Class k = objc_allocateClassPair([Dyn class], "RuntimeMade", 0);
    class_addIvar(k, "count", sizeof(int), 2, "i");
    class_addMethod(k, sel_registerName("counter"), (IMP)counter_value, "i16@0:8");
    objc_registerClassPair(k);
    id o = [[k alloc] init];
    objc_setAssociatedObject(o, "k", @7, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    Ivar iv = class_getInstanceVariable(k, "count");
    *(int*)((char*)(__bridge void*)o + ivar_getOffset(iv)) = 5;
    printf("runtime class: %s counter %d ivar %d super-a %s\n", class_getName(object_getClass(o)),
           ((int (*)(id, SEL))objc_msgSend)(o, sel_registerName("counter")), *(int*)((char*)(__bridge void*)o + ivar_getOffset(iv)), [o a].UTF8String);
  }
  return 0;
}
