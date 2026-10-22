// flags: -fobjc-arc
#import <Foundation/Foundation.h>

static int g_lib_loads;
@interface Shape : NSObject
@property (nonatomic) double scale;
- (double)area;
- (NSString*)describe;
+ (int)libLoads;
@end
@implementation Shape
+ (void)load { g_lib_loads++; printf("load Shape (lib)\n"); }
+ (int)libLoads { return g_lib_loads; }
- (instancetype)init { if ((self = [super init])) _scale = 1; return self; }
- (double)area { return 0; }
- (NSString*)describe { return [NSString stringWithFormat:@"%@ area %.2f", NSStringFromClass([self class]), [self area] * _scale]; }
@end
@interface Box : Shape
@property (nonatomic) double w, h;
@end
@implementation Box
- (double)area { return _w * _h; }
@end
@interface NSArray (LibTotal)
- (double)totalArea;
@end
@implementation NSArray (LibTotal)
- (double)totalArea { double t = 0; for (Shape* s in self) t += [s area]; return t; }
@end
