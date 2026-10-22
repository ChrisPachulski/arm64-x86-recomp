#import "a11_mixed.h"
@implementation MXEngine
- (instancetype)initWithTitle:(NSString *)t { if ((self = [super init])) { _title = [t copy]; } return self; }
- (NSString *)hook:(NSInteger)n { return [NSString stringWithFormat:@"base hook %ld", (long)n]; }
- (NSString *)step { self.ticks += 1; return [NSString stringWithFormat:@"%@ step %ld: %@", self.title, (long)self.ticks, [self hook:self.ticks * 3]]; }
- (NSInteger)sumFrom:(id<MXSource>)src count:(NSInteger)n {
  NSInteger s = 0; for (NSInteger i = 0; i < n; i++) s += [src valueAt:i];
  MXPoint p = {1.5, -2.25, (int)n};
  return s * 1000 + (NSInteger)[[src nameFor:p] length];
}
- (NSArray<NSString *> *)mapNames:(NSArray *)objs with:(NSString *(^)(id, NSUInteger))f {
  NSMutableArray *o = [NSMutableArray array];
  [objs enumerateObjectsUsingBlock:^(id obj, NSUInteger idx, BOOL *stop) { [o addObject:f(obj, idx)]; }];
  return o;
}
+ (MXEngine *)makeByName:(NSString *)cls { return [[NSClassFromString(cls) alloc] initWithTitle:@"byname"]; }
@end
MXPoint MXMid(MXPoint a, MXPoint b) { MXPoint r = {(a.x + b.x) / 2, (a.y + b.y) / 2, a.tag + b.tag}; return r; }
NSString *MXDescribe(id obj) { return [NSString stringWithFormat:@"[%@ %@]", NSStringFromClass([obj class]), [obj description]]; }
