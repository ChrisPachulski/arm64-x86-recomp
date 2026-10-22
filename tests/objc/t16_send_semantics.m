// Message-send semantics: a non-variadic guest method whose name ends in WithFormat: keeps its argument; NSString formats
// with an embedded NUL (%c 0), %S (UTF-16), %C and %ls; forwarding hooks run once each (forwardingTargetForSelector:,
// methodSignatureForSelector:, forwardInvocation:); +resolveInstanceMethod: runs once.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
static int nft, nms, nfi, nres;
@interface L : NSObject - (NSString*)labelWithFormat:(NSString*)s; - (NSString*)appendFormat:(NSString*)s; @end
@implementation L
- (NSString*)labelWithFormat:(NSString*)s { return s; }
- (NSString*)appendFormat:(NSString*)s { return [s stringByAppendingString:@"!"]; }
@end
@interface F : NSObject @end
@implementation F
- (id)forwardingTargetForSelector:(SEL)s { nft++; return nil; }
- (NSMethodSignature*)methodSignatureForSelector:(SEL)s { nms++; return [NSMethodSignature signatureWithObjCTypes:"i@:i"]; }
- (void)forwardInvocation:(NSInvocation*)inv { nfi++; int x = 0; [inv getArgument:&x atIndex:2]; x *= 3; [inv setReturnValue:&x]; }
@end
static int dyn(id self, SEL _cmd, int x) { return x + 100; }
@interface R : NSObject @end
@implementation R
+ (BOOL)resolveInstanceMethod:(SEL)s {
  nres++;
  if (s == sel_registerName("dyn:")) { class_addMethod(self, s, (IMP)dyn, "i@:i"); return YES; }
  return [super resolveInstanceMethod:s];
}
@end
int main(void) {
  @autoreleasepool {
    L* l = [L new];
    printf("label %s | %s\n", [l labelWithFormat:@"plain %d"].UTF8String, [l appendFormat:@"x%@"].UTF8String);
    NSString* z = [NSString stringWithFormat:@"A%cB", 0];
    printf("nul: length %lu, chars %d %d %d\n", (unsigned long)z.length, [z characterAtIndex:0], z.length > 1 ? [z characterAtIndex:1] : -1,
           z.length > 2 ? [z characterAtIndex:2] : -1);
    unichar u16[] = {'U', 0x263A, 'z', 0};
    NSString* w = [NSString stringWithFormat:@"[%S] [%C] [%ls] [%5.2f|%-4d|%@]", u16, (unichar)0x00E9, L"wide", 3.14159, 42, @[@1]];
    printf("utf16: %s length %lu\n", w.UTF8String, (unsigned long)w.length);
    F* f = [F new];
    int r = ((int (*)(id, SEL, int))objc_msgSend)(f, sel_registerName("triple:"), 14);
    printf("forwarded %d: hooks %d/%d/%d\n", r, nft, nms, nfi);
    NSNumber* n = [f valueForKey:@"self"];
    printf("kvc self %s\n", n == (id)f ? "same" : "other");
    R* o = [R new];
    printf("resolved %d %d, resolver calls %d\n", ((int (*)(id, SEL, int))objc_msgSend)(o, sel_registerName("dyn:"), 5),
           ((int (*)(id, SEL, int))objc_msgSend)(o, sel_registerName("dyn:"), 6), nres);
  }
  return 0;
}
