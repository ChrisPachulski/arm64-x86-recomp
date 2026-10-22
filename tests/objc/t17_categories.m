// Categories and class properties as the runtime keeps them: guest categories (this image) overriding a method of a guest
// class (t17_categories.lib.m) leave every entry enumerable; the newest of two overriding categories wins; class-method
// categories; class properties declared in a guest protocol and in a guest category.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
@protocol HasAnswer
@property (class, nonatomic, readonly) int answer;
@property (nonatomic, readonly) int inst;
@end
@interface Person : NSObject <HasAnswer> - (NSString*)kind; + (NSString*)species; @end
@interface Person (A) @property (class, nonatomic, readonly) int catAnswer; - (NSString*)kind; @end
@implementation Person (A)
- (NSString*)kind { return @"category A"; }
+ (int)catAnswer { return 7; }
@end
@interface Person (B) - (NSString*)kind; + (NSString*)species; @end
@implementation Person (B)
- (NSString*)kind { return @"category B"; }
+ (NSString*)species { return @"cat B species"; }
@end
static void list(Class c, const char* sel) {
  unsigned n = 0; Method* ms = class_copyMethodList(c, &n); int hits = 0;
  NSMutableArray* imps = [NSMutableArray array];
  for (unsigned i = 0; i < n; i++)
    if (!strcmp(sel_getName(method_getName(ms[i])), sel)) {
      hits++;
      NSString* (*f)(id, SEL) = (NSString* (*)(id, SEL))method_getImplementation(ms[i]);
      [imps addObject:f((id)[Person new], method_getName(ms[i]))];
    }
  free(ms);
  printf("%s entries %d: %s\n", sel, hits, [imps componentsJoinedByString:@", "].UTF8String);
}
int main(void) {
  @autoreleasepool {
    printf("kind %s, species %s\n", [Person new].kind.UTF8String, [Person species].UTF8String);
    list([Person class], "kind");
    unsigned n = 0; Method* ms = class_copyMethodList(object_getClass([Person class]), &n); int sp = 0;
    for (unsigned i = 0; i < n; i++) sp += !strcmp(sel_getName(method_getName(ms[i])), "species");
    free(ms);
    printf("class method species entries %d\n", sp);
    Protocol* p = objc_getProtocol("HasAnswer");
    objc_property_t pa = protocol_getProperty(p, "answer", YES, NO), pi = protocol_getProperty(p, "inst", YES, YES);
    printf("protocol class property %s (%s), instance property %s\n", pa ? property_getName(pa) : "none", pa ? property_getAttributes(pa) : "-",
           pi ? property_getName(pi) : "none");
    objc_property_t ca = class_getProperty(object_getClass([Person class]), "catAnswer");
    printf("category class property %s (%s), value %d\n", ca ? property_getName(ca) : "none", ca ? property_getAttributes(ca) : "-", Person.catAnswer);
  }
  return 0;
}
