// Ivars in a guest subclass of a host class (offsets slid), atomic struct/object properties, KVC on bare ivars,
// +resolveInstanceMethod: for @dynamic properties, +initialize per class, guest objects as NSDictionary keys / NSSet
// members (host calls copyWithZone:/hash/isEqual:), NSCache, global (non-capturing) blocks handed to the host, and super
// calls into host methods returning a 48-byte struct (stret) and a 2-double HFA from a guest NSAffineTransform subclass.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
static NSMutableArray* events;
@interface Op : NSOperation { @public int _count; double _ratio; NSString* _label; char _tag[13]; } @property (atomic) NSRect area; @property (atomic, strong) id thing; @end
@implementation Op
+ (void)initialize { [events addObject:[NSString stringWithFormat:@"initialize %@", NSStringFromClass(self)]]; }
- (void)main { _count += 5; _ratio = _count / 4.0; _label = [NSString stringWithFormat:@"ran %d", _count]; strcpy(_tag, "tag-ok"); }
@end
@interface Op2 : Op @end
@implementation Op2 @end
@interface Dyn : NSObject @property (nonatomic, copy) NSString* value; @end
@implementation Dyn
@dynamic value;
static NSString* dynGet(id self, SEL _cmd) { return objc_getAssociatedObject(self, @selector(value)); }
static void dynSet(id self, SEL _cmd, NSString* v) { objc_setAssociatedObject(self, @selector(value), [@"dyn:" stringByAppendingString:v], OBJC_ASSOCIATION_COPY); }
+ (BOOL)resolveInstanceMethod:(SEL)s {
  if (s == @selector(value)) { class_addMethod(self, s, (IMP)dynGet, "@16@0:8"); return YES; }
  if (s == @selector(setValue:)) { class_addMethod(self, s, (IMP)dynSet, "v24@0:8@16"); return YES; }
  return [super resolveInstanceMethod:s];
}
@end
@interface Key : NSObject <NSCopying> @property int k; @end
@implementation Key
- (id)copyWithZone:(NSZone*)z { Key* c = [Key new]; c.k = _k; [events addObject:@"copy"]; return c; }
- (NSUInteger)hash { return (NSUInteger)(_k % 7); }
- (BOOL)isEqual:(id)o { return [o isKindOfClass:[Key class]] && ((Key*)o).k == _k; }
@end
@interface Xf : NSAffineTransform @end
@implementation Xf
- (NSAffineTransformStruct)transformStruct { NSAffineTransformStruct s = [super transformStruct]; s.tX += 100; return s; }
- (NSPoint)transformPoint:(NSPoint)p { NSPoint q = [super transformPoint:p]; return NSMakePoint(q.x * 10, q.y * 10); }
@end
int main(void) {
  events = [NSMutableArray array];
  @autoreleasepool {
    NSOperationQueue* q = [NSOperationQueue new];
    Op* op = [Op2 new];
    op->_count = 3;
    [q addOperation:op]; [q waitUntilAllOperationsAreFinished];
    op.area = NSMakeRect(1, 2, 3, 4); op.thing = @"thing";
    printf("ivars %d %g %s %s finished %d area %g thing %s\n", op->_count, op->_ratio, op->_label.UTF8String, op->_tag, (int)op.isFinished,
           op.area.size.height, [op.thing UTF8String]);
    printf("kvc ivar %s %s\n", [[op valueForKey:@"label"] UTF8String], [[[op valueForKey:@"count"] description] UTF8String]);
    printf("ivar offsets monotonic %d\n", ivar_getOffset(class_getInstanceVariable([Op class], "_count")) < ivar_getOffset(class_getInstanceVariable([Op class], "_label")));
    Dyn* d = [Dyn new]; d.value = @"v1";
    printf("dynamic %s responds %d\n", d.value.UTF8String, (int)[d respondsToSelector:@selector(setValue:)]);
    NSMutableDictionary* dict = [NSMutableDictionary dictionary];
    for (int i = 0; i < 20; i++) { Key* k = [Key new]; k.k = i; dict[k] = @(i * i); }
    Key* probe = [Key new]; probe.k = 13;
    NSMutableSet* set = [NSMutableSet set];
    for (int i = 0; i < 30; i++) { Key* k = [Key new]; k.k = i % 10; [set addObject:k]; }
    printf("dict %lu probe %s set %lu contains %d\n", (unsigned long)dict.count, [dict[probe] description].UTF8String, (unsigned long)set.count, (int)[set containsObject:probe]);
    NSCache* cache = [NSCache new];
    [cache setObject:@"cached" forKey:probe];
    printf("cache %s\n", [[cache objectForKey:probe] UTF8String]);
    dispatch_sync(dispatch_queue_create("g", 0), ^{ [events addObject:@"global block ran"]; });
    [@[@1, @2] enumerateObjectsUsingBlock:^(id o, NSUInteger i, BOOL* s) { printf("global enum %lu\n", (unsigned long)i); }];
    Xf* xf = [Xf transform];
    [xf translateXBy:1 yBy:2];
    NSAffineTransformStruct ts = xf.transformStruct;
    NSPoint p = [xf transformPoint:NSMakePoint(3, 4)];
    NSSize sz = [xf transformSize:NSMakeSize(1, 1)];
    printf("stret super %g %g %g %g %g %g point %g %g size %g %g\n", ts.m11, ts.m12, ts.m21, ts.m22, ts.tX, ts.tY, p.x, p.y, sz.width, sz.height);
  }
  NSArray* ev = events;
  printf("events copy=%lu\n", (unsigned long)[[ev filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(id e, NSDictionary* b) { return [e isEqual:@"copy"]; }]] count]);
  for (NSString* e in ev) if (![e isEqualToString:@"copy"]) printf("%s\n", e.UTF8String);
  return 0;
}
