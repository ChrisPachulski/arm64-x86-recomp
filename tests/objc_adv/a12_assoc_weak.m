// Associated objects (retain, copy, assign; released with the owner), __weak / objc_loadWeakRetained to guest objects,
// weak tables, weak capture in blocks, and the order of -dealloc / .cxx_destruct across a 3-level guest hierarchy.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
static NSMutableArray* events;
@interface Tr : NSObject @property (copy) NSString* tag; + (instancetype)t:(NSString*)s; @end
@implementation Tr
+ (instancetype)t:(NSString*)s { Tr* t = [Tr new]; t.tag = s; return t; }
- (void)dealloc { [events addObject:[@"dealloc " stringByAppendingString:_tag]]; }
@end
@interface L1 : NSObject { Tr* _a1; Tr* _a2; } @end
@interface L2 : L1 { Tr* _b1; } @end
@interface L3 : L2 @property (strong) Tr* c1; @property (strong) Tr* c2; @end
@implementation L1 - (instancetype)init { if ((self = [super init])) { _a1 = [Tr t:@"a1"]; _a2 = [Tr t:@"a2"]; } return self; }
- (void)dealloc { [events addObject:@"L1 dealloc"]; } @end
@implementation L2 - (instancetype)init { if ((self = [super init])) _b1 = [Tr t:@"b1"]; return self; }
- (void)dealloc { [events addObject:[NSString stringWithFormat:@"L2 dealloc sees b1=%@", _b1.tag]]; } @end
@implementation L3 - (instancetype)init { if ((self = [super init])) { _c1 = [Tr t:@"c1"]; _c2 = [Tr t:@"c2"]; } return self; }
- (void)dealloc { [events addObject:[NSString stringWithFormat:@"L3 dealloc sees c1=%@", _c1.tag]]; } @end
static char kRetain, kCopy, kAssign;
extern id objc_loadWeakRetained(__weak id* p) __attribute__((ns_returns_retained));
int main(void) {
  events = [NSMutableArray array];
  @autoreleasepool {
    __weak Tr* w = nil;
    __weak id wl3 = nil;
    NSHashTable* ht = [NSHashTable weakObjectsHashTable];
    NSMapTable* mt = [NSMapTable strongToWeakObjectsMapTable];
    @autoreleasepool {
      Tr* owner = [Tr t:@"owner"];
      w = owner;
      objc_setAssociatedObject(owner, &kRetain, [Tr t:@"assoc-retain"], OBJC_ASSOCIATION_RETAIN_NONATOMIC);
      NSMutableString* ms = [NSMutableString stringWithString:@"copied"];
      objc_setAssociatedObject(owner, &kCopy, ms, OBJC_ASSOCIATION_COPY);
      [ms appendString:@"-mutated"];
      objc_setAssociatedObject(owner, &kAssign, @"assigned", OBJC_ASSOCIATION_ASSIGN);
      printf("assoc %s %s %s\n", [objc_getAssociatedObject(owner, &kRetain) tag].UTF8String,
             [objc_getAssociatedObject(owner, &kCopy) UTF8String], [objc_getAssociatedObject(owner, &kAssign) UTF8String]);
      Tr* strong = w;
      printf("weak live %s\n", strong.tag.UTF8String);
      strong = nil;
      L3* l3 = [L3 new];
      wl3 = l3;
      [ht addObject:l3]; [mt setObject:l3 forKey:@"l3"];
      void (^wb)(void) = ^{ printf("weak-captured %s\n", w ? "live" : "nil"); };
      wb();
      printf("tables %lu %d\n", (unsigned long)ht.allObjects.count, [mt objectForKey:@"l3"] != nil);
      objc_setAssociatedObject(owner, &kRetain, [Tr t:@"assoc-replacement"], OBJC_ASSOCIATION_RETAIN_NONATOMIC);
      [events addObject:@"--- leaving scope"];
    }
    printf("weak after %s %s tables %lu %d\n", w ? "live" : "nil", wl3 ? "live" : "nil", (unsigned long)ht.allObjects.count,
           [mt objectForKey:@"l3"] != nil);
    id loaded = objc_loadWeakRetained((__weak id*)&w);
    printf("loadWeakRetained %s\n", loaded ? "obj" : "nil");
  }
  for (NSString* e in events) printf("%s\n", e.UTF8String);
  return 0;
}
