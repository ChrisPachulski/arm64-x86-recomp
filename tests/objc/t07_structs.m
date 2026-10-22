// Struct and many-argument messages in both directions: HFAs (CGRect, NSEdgeInsets, 3 floats), NSRange, mixed and small
// structs, 48-byte CGAffineTransform (indirect on both arches), stack-passed arguments; the host calls guest methods with
// them through NSInvocation and KVC (NSValue boxing), the guest sends them to host and guest receivers.
#import <Foundation/Foundation.h>
#import <AppKit/NSGraphics.h>

typedef struct { float x, y, z; } V3;
typedef struct { int i; double d; } Mixed;
typedef struct { char a; short b; } Tiny;
typedef struct { int v[5]; } Five;
typedef struct { double m[6]; } Aff;

@interface Geo : NSObject
@property (nonatomic) NSRect frame;
@property (nonatomic) NSRange span;
- (NSRect)inset:(NSRect)r by:(NSEdgeInsets)e;
- (V3)cross:(V3)a with:(V3)b;
- (Mixed)mix:(Mixed)m times:(int)k;
- (Tiny)tiny:(Tiny)t;
- (Five)five:(Five)f plus:(int)k;
- (Aff)aff:(Aff)a scale:(double)s;
- (double)many:(int)a :(double)b :(long)c :(float)d :(int)e :(double)f :(short)g :(double)h :(int)i :(double)j :(char)k :(double)l :(NSRect)r;
@end
@implementation Geo
- (NSRect)inset:(NSRect)r by:(NSEdgeInsets)e {
  return NSMakeRect(r.origin.x + e.left, r.origin.y + e.bottom, r.size.width - e.left - e.right, r.size.height - e.top - e.bottom);
}
- (V3)cross:(V3)a with:(V3)b { return (V3){a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
- (Mixed)mix:(Mixed)m times:(int)k { return (Mixed){m.i * k, m.d * k}; }
- (Tiny)tiny:(Tiny)t { return (Tiny){(char)(t.a + 1), (short)(t.b * 2)}; }
- (Five)five:(Five)f plus:(int)k { for (int i = 0; i < 5; i++) f.v[i] += k; return f; }
- (Aff)aff:(Aff)a scale:(double)s { for (int i = 0; i < 6; i++) a.m[i] *= s; return a; }
- (double)many:(int)a :(double)b :(long)c :(float)d :(int)e :(double)f :(short)g :(double)h :(int)i :(double)j :(char)k :(double)l :(NSRect)r {
  return a + b + c + d + e + f + g + h + i + j + k + l + r.origin.x + r.size.height;
}
@end

int main(void) {
  @autoreleasepool {
    Geo* g = [Geo new];
    NSRect r = [g inset:NSMakeRect(0, 0, 100, 50) by:NSEdgeInsetsMake(1, 2, 3, 4)];
    printf("inset: %g %g %g %g\n", r.origin.x, r.origin.y, r.size.width, r.size.height);
    V3 c = [g cross:(V3){1, 0, 0} with:(V3){0, 1, 0}];
    printf("cross: %g %g %g\n", c.x, c.y, c.z);
    Mixed m = [g mix:(Mixed){3, 1.25} times:4];
    Tiny t = [g tiny:(Tiny){'a', 300}];
    Five f = [g five:(Five){{1, 2, 3, 4, 5}} plus:10];
    Aff a = [g aff:(Aff){{1, 2, 3, 4, 5, 6}} scale:0.5];
    printf("mixed %d %g tiny %c %d five %d %d aff %g %g\n", m.i, m.d, t.a, t.b, f.v[0], f.v[4], a.m[0], a.m[5]);
    printf("many: %g\n", [g many:1 :2 :3 :4 :5 :6 :7 :8 :9 :10 :11 :12 :NSMakeRect(13, 0, 0, 14)]);
    g.frame = NSMakeRect(5, 6, 7, 8);
    g.span = NSMakeRange(3, 9);
    NSValue* fv = [g valueForKey:@"frame"];
    NSValue* sv = [g valueForKey:@"span"];
    printf("kvc box: %s range %lu %lu\n", NSStringFromRect(fv.rectValue).UTF8String, (unsigned long)sv.rangeValue.location, (unsigned long)sv.rangeValue.length);
    [g setValue:[NSValue valueWithRect:NSMakeRect(1, 1, 2, 2)] forKey:@"frame"];
    printf("kvc set: %s\n", NSStringFromRect(g.frame).UTF8String);
    NSMethodSignature* sig = [g methodSignatureForSelector:@selector(inset:by:)];
    NSInvocation* inv = [NSInvocation invocationWithMethodSignature:sig];
    inv.target = g; inv.selector = @selector(inset:by:);
    NSRect in = NSMakeRect(10, 10, 20, 20); NSEdgeInsets e = NSEdgeInsetsMake(1, 1, 1, 1);
    [inv setArgument:&in atIndex:2]; [inv setArgument:&e atIndex:3];
    [inv invoke];
    NSRect out; [inv getReturnValue:&out];
    printf("invocation: %s\n", NSStringFromRect(out).UTF8String);
    NSInvocation* inv2 = [NSInvocation invocationWithMethodSignature:[g methodSignatureForSelector:@selector(aff:scale:)]];
    inv2.target = g; inv2.selector = @selector(aff:scale:);
    Aff in2 = {{2, 4, 6, 8, 10, 12}}; double sc = 3;
    [inv2 setArgument:&in2 atIndex:2]; [inv2 setArgument:&sc atIndex:3];
    [inv2 invoke];
    Aff out2; [inv2 getReturnValue:&out2];
    printf("invocation 48-byte: %g %g\n", out2.m[0], out2.m[5]);
    NSAffineTransform* xf = [NSAffineTransform transform];
    [xf translateXBy:3 yBy:4]; [xf scaleBy:2];
    NSAffineTransformStruct ts = xf.transformStruct;
    NSPoint p = [xf transformPoint:NSMakePoint(1, 1)];
    printf("host 48-byte return: %g %g %g %g %g %g point %g %g\n", ts.m11, ts.m12, ts.m21, ts.m22, ts.tX, ts.tY, p.x, p.y);
    NSRange rr = [@"abcdefabc" rangeOfString:@"abc" options:NSBackwardsSearch range:NSMakeRange(1, 8)];
    printf("range with range arg: %lu %lu\n", (unsigned long)rr.location, (unsigned long)rr.length);
    NSValue* bv = [NSValue valueWithBytes:&m objCType:@encode(Mixed)];
    Mixed m2; [bv getValue:&m2 size:sizeof m2];
    printf("valueWithBytes: %d %g %s\n", m2.i, m2.d, bv.objCType);
  }
  return 0;
}
