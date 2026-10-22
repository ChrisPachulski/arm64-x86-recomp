// class_addMethod with guest C IMPs and imp_implementationWithBlock (capturing state) on guest and host classes;
// calls by message, performSelector, NSInvocation and from host code (KVC).
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
@interface Empty : NSObject @end
@interface NSObject (Dyn) - (int)triple:(int)x; - (double)half:(double)x; - (double)guestMul:(double)a by:(int)b; - (NSRect)rectK:(double)k; @end
@implementation Empty @end
static int triple(id self, SEL _cmd, int x) { return 3 * x; }
static double half(id self, SEL _cmd, double x) { return x / 2; }
int main(void) {
  setvbuf(stdout, NULL, _IONBF, 0);
  @autoreleasepool {
    class_addMethod([Empty class], sel_registerName("triple:"), (IMP)triple, "i20@0:8i16");
    class_addMethod([Empty class], sel_registerName("half:"), (IMP)half, "d24@0:8d16");
    __block int calls = 0;
    NSString* prefix = @"blk";
    IMP bi = imp_implementationWithBlock(^NSString*(id self, NSString* s) { calls++; return [NSString stringWithFormat:@"%@:%@", prefix, s]; });
    class_addMethod([Empty class], sel_registerName("tag:"), bi, "@24@0:8@16");
    IMP bk = imp_implementationWithBlock(^id(id self) { calls++; return @"kvc-value"; });
    class_addMethod([Empty class], sel_registerName("magic"), bk, "@16@0:8");
    IMP bd = imp_implementationWithBlock(^double(id self, double a, int b) { calls++; return a * b; });
    class_addMethod([NSObject class], sel_registerName("guestMul:by:"), bd, "d28@0:8d16i24");
    id e = [Empty new];
    printf("triple %d half %g\n", [e triple:7],
           [e half:5]);
    printf("tag %s\n", [[e performSelector:sel_registerName("tag:") withObject:@"x"] UTF8String]);
    printf("kvc %s\n", [[e valueForKey:@"magic"] UTF8String]);
    printf("host class block %g\n", [@"anything" guestMul:2.5 by:4]);
    NSInvocation* inv = [NSInvocation invocationWithMethodSignature:[e methodSignatureForSelector:sel_registerName("triple:")]];
    inv.target = e; inv.selector = sel_registerName("triple:");
    int a = 11; [inv setArgument:&a atIndex:2]; [inv invoke];
    int out; [inv getReturnValue:&out];
    printf("invocation triple %d calls %d responds %d\n", out, calls, (int)[e respondsToSelector:sel_registerName("tag:")]);
    imp_removeBlock(bi);
  }
  return 0;
}
