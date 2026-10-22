// Saved-IMP swizzle of a HOST method: the replacement calls the original host IMP directly.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
@interface Box : NSObject @end
@implementation Box @end
static IMP origDesc;
static NSString* newDesc(id self, SEL _cmd) { NSString* o = ((NSString* (*)(id, SEL))origDesc)(self, _cmd); return [NSString stringWithFormat:@"wrapped(%lu)", (unsigned long)o.length > 0]; }
static IMP origUpper;
static NSString* newUpper(id self, SEL _cmd) { return [@"U:" stringByAppendingString:((NSString* (*)(id, SEL))origUpper)(self, _cmd)]; }
int main(void) {
  @autoreleasepool {
    origDesc = method_setImplementation(class_getInstanceMethod([NSObject class], @selector(description)), (IMP)newDesc);
    printf("%s\n", [Box new].description.UTF8String);
    Class sc = [@"abc" class];
    origUpper = method_setImplementation(class_getInstanceMethod(sc, @selector(uppercaseString)), (IMP)newUpper);
    printf("%s\n", [@"abc" uppercaseString].UTF8String);
  }
  return 0;
}
