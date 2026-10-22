// Two guest images: a class hierarchy defined in a guest dylib, subclassed (and subclassed again) in the executable; super
// calls across images; ivars of every level; the dylib's +load before the executable's; a dylib category on a host class.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>

@interface Shape : NSObject
@property (nonatomic) double scale;
- (double)area;
- (NSString*)describe;
+ (int)libLoads;
@end
@interface Box : Shape
@property (nonatomic) double w, h;
@end
@interface NSArray (LibTotal)
- (double)totalArea;
@end

@interface Square : Box
@property (nonatomic, copy) NSString* label;
- (instancetype)initWithSide:(double)s;
@end
@implementation Square
+ (void)load { printf("load Square (exe), lib loads so far %d\n", [Shape libLoads]); }
- (instancetype)initWithSide:(double)s { if ((self = [super init])) { self.w = s; self.h = s; _label = @"sq"; } return self; }
- (double)area { return [super area] + 0.5; }
- (NSString*)describe { return [[super describe] stringByAppendingFormat:@" [%@]", _label]; }
@end
@interface Shape (Exe)
- (NSString*)tagged;
@end
@implementation Shape (Exe)
- (NSString*)tagged { return [NSString stringWithFormat:@"tagged %@ scale %g", NSStringFromClass([self class]), self.scale]; }
@end
@interface Cube : Square
@property (nonatomic) int faces;
@end
@implementation Cube
- (double)area { return [super area] * 6; }
@end

int main(void) {
  @autoreleasepool {
    Box* r = [Box new]; r.w = 2; r.h = 3;
    Square* s = [[Square alloc] initWithSide:4];
    Cube* c = [[Cube alloc] initWithSide:1]; c.faces = 6; c.scale = 2;
    printf("%s\n%s\n%s\n", r.describe.UTF8String, s.describe.UTF8String, c.describe.UTF8String);
    printf("superclass chain: %s < %s < %s < %s\n", class_getName([Cube class]), class_getName([Cube superclass]),
           class_getName([[Cube superclass] superclass]), class_getName([[[Cube superclass] superclass] superclass]));
    printf("%s | %s\n", [c tagged].UTF8String, [r tagged].UTF8String);
    printf("total %.2f isKind %d %d faces %d\n", [@[r, s, c] totalArea], [c isKindOfClass:[Box class]], [s isKindOfClass:[Cube class]], c.faces);
  }
  return 0;
}
