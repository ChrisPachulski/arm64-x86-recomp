// Protocols (guest-defined, incorporated, optional methods, properties) and conformsToProtocol:; host protocols adopted by
// guest classes (NSCopying used by the host's dictionary keys); categories on host classes and on guest classes, a
// category overriding a guest method, category properties and protocol adoption.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>

@protocol Named <NSObject>
@property (nonatomic, readonly) NSString* name;
- (NSString*)greet:(NSString*)who;
@optional
- (int)optionalCount;
@end
@protocol Ranked <Named>
+ (int)maxRank;
@end
@protocol Unused
- (void)never;
@end

@interface Person : NSObject <Ranked, NSCopying> { NSString* _n; }
- (instancetype)initWithName:(NSString*)n;
@end
@implementation Person
- (instancetype)initWithName:(NSString*)n { if ((self = [super init])) _n = [n copy]; return self; }
- (NSString*)name { return _n; }
- (NSString*)greet:(NSString*)who { return [NSString stringWithFormat:@"%@ greets %@", _n, who]; }
+ (int)maxRank { return 10; }
- (id)copyWithZone:(NSZone*)z { printf("copyWithZone %s\n", _n.UTF8String); return [[Person allocWithZone:z] initWithName:_n]; }
- (NSUInteger)hash { return _n.hash; }
- (BOOL)isEqual:(id)o { return [o isKindOfClass:[Person class]] && [[o name] isEqual:_n]; }
- (NSString*)kind { return @"person"; }
@end

@interface Person (Extra) <Unused>
@property (nonatomic, readonly) NSString* shout;
- (NSString*)kind;
@end
@implementation Person (Extra)
- (NSString*)shout { return _n.uppercaseString; }
- (NSString*)kind { return @"person+category"; }
- (void)never {}
@end

@interface NSString (Guest)
- (NSString*)guestReversed;
+ (NSString*)guestHello;
@end
@implementation NSString (Guest)
- (NSString*)guestReversed {
  NSMutableString* r = [NSMutableString string];
  for (NSInteger i = (NSInteger)self.length - 1; i >= 0; i--) [r appendFormat:@"%C", [self characterAtIndex:(NSUInteger)i]];
  return r;
}
+ (NSString*)guestHello { return @"hello from a category on a host class"; }
@end

int main(void) {
  @autoreleasepool {
    Person* p = [[Person alloc] initWithName:@"ada"];
    printf("%s | %s\n", [p greet:@"bob"].UTF8String, p.name.UTF8String);
    printf("conforms Named %d Ranked %d NSCopying %d Unused %d NSCoding %d\n", [p conformsToProtocol:@protocol(Named)],
           [p conformsToProtocol:@protocol(Ranked)], [p conformsToProtocol:@protocol(NSCopying)], [p conformsToProtocol:@protocol(Unused)],
           [p conformsToProtocol:@protocol(NSCoding)]);
    printf("class conforms %d, protocol inherits %d, name %s\n", [Person conformsToProtocol:@protocol(Named)],
           protocol_conformsToProtocol(@protocol(Ranked), @protocol(Named)), protocol_getName(@protocol(Ranked)));
    printf("lookup by name: %d %d\n", objc_getProtocol("Ranked") == @protocol(Ranked), NSProtocolFromString(@"Named") == @protocol(Named));
    struct objc_method_description md = protocol_getMethodDescription(@protocol(Named), @selector(greet:), YES, YES);
    printf("method description: %s %s\n", sel_getName(md.name), md.types ? "typed" : "untyped");
    printf("optional responds %d, maxRank %d\n", [p respondsToSelector:@selector(optionalCount)], [[p class] maxRank]);
    id<Named> named = p;
    printf("via protocol type: %s\n", [named greet:@"eve"].UTF8String);
    NSMutableDictionary* d = [NSMutableDictionary dictionary];
    d[p] = @"value";                                        /* the host copies the key through the guest's NSCopying */
    printf("dict lookup by equal key: %s\n", [d[[[Person alloc] initWithName:@"ada"]] UTF8String]);
    printf("category: %s %s\n", p.shout.UTF8String, [p kind].UTF8String);
    printf("host class category: %s / %s\n", [@"stressed" guestReversed].UTF8String, [NSString guestHello].UTF8String);
    printf("mutable inherits category: %s\n", [[NSMutableString stringWithString:@"abc"] guestReversed].UTF8String);
    unsigned n = 0;
    objc_property_t* props = class_copyPropertyList([Person class], &n);
    printf("properties:");
    for (unsigned i = 0; i < n; i++) printf(" %s", property_getName(props[i]));
    printf("\n");
    free(props);
    unsigned np = 0;
    Protocol* __unsafe_unretained* pl = class_copyProtocolList([Person class], &np);
    printf("protocols:");
    for (unsigned i = 0; i < np; i++) printf(" %s", protocol_getName(pl[i]));
    printf("\n");
    free(pl);
  }
  return 0;
}
