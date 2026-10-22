// Guest code the host calls with structs by value, floats and doubles: guest methods through NSInvocation (libffi side),
// KVC getters / setters of struct and floating properties, blocks with NSRange parameters, and typed function-pointer
// parameters of Foundation methods (sortedArrayUsingFunction:context:hint:, NSPointerFunctions size / description).
#import <Foundation/Foundation.h>
#include <stdio.h>

typedef struct { double x, y, w, h; } Rect4;                   // HFA of 4 doubles: v0-v3 on arm64, memory on x86-64
typedef struct { long a; double b; int c; } Mix24;             // 24 bytes, not an HFA: by reference on arm64, memory on x86-64
typedef struct { float f; int i; } FI;                         // 8 bytes mixed
typedef struct { char c[3]; } Odd3;                            // 3-byte struct
typedef struct { float a, b, c; } F3;                          // HFA of 3 floats

@interface Calc : NSObject
@property double dval;
@property float fval;
@property NSRange rng;
@property Rect4 rect;
@property Mix24 mix;
@end
@implementation Calc
- (double)mix:(double)a f:(float)b r:(NSRange)r q:(Rect4)q m:(Mix24)m fi:(FI)fi o:(Odd3)o t:(F3)t {
  return a + b + r.location * 10 + r.length + q.x + q.y * 2 + q.w * 3 + q.h * 4 + m.a + m.b + m.c + fi.f + fi.i
         + o.c[0] + o.c[1] + o.c[2] + t.a + t.b + t.c;
}
- (Rect4)grow:(Rect4)r by:(double)d { return (Rect4){r.x - d, r.y - d, r.w + 2 * d, r.h + 2 * d}; }
- (Mix24)mixOf:(long)a b:(double)b c:(int)c { return (Mix24){a, b, c}; }
- (float)many:(float)a :(float)b :(float)c :(float)d :(float)e :(float)f :(float)g :(float)h :(float)i :(float)j :(double)k :(int)l {
  return a + b + c + d + e + f + g + h + i * 10 + j * 100 + (float)k * 1000 + l * 10000;
}
- (F3)triple:(float)s { return (F3){s, s * 2, s * 3}; }
@end

static NSInteger by_len(id a, id b, void* ctx) {
  NSInteger d = (NSInteger)[a length] - (NSInteger)[b length];
  return d * *(int*)ctx < 0 ? NSOrderedAscending : d == 0 ? [a compare:b] : NSOrderedDescending;
}
static NSUInteger sz_fn(const void* p) { return 4; }
static NSString* desc_fn(const void* p) { return [NSString stringWithFormat:@"<int %d>", *(const int*)p]; }

static void invoke(Calc* c, SEL s, void (^set)(NSInvocation*), void* ret) {
  NSInvocation* inv = [NSInvocation invocationWithMethodSignature:[c methodSignatureForSelector:s]];
  inv.target = c; inv.selector = s; set(inv); [inv invoke]; [inv getReturnValue:ret];
}

int main(void) {
  @autoreleasepool {
    setvbuf(stdout, NULL, _IOLBF, 0);
    Calc* c = [Calc new];
    // NSInvocation: the host calls the guest IMP with everything at once
    __block double a = 1.5; __block float b = 0.25f; __block NSRange r = {3, 4}; __block Rect4 q = {1, 2, 3, 4};
    __block Mix24 m = {100, 0.5, 7}; __block FI fi = {0.75f, 9}; __block Odd3 o = {{1, 2, 3}}; __block F3 t = {0.5f, 1.5f, 2.5f};
    double dr = 0;
    invoke(c, @selector(mix:f:r:q:m:fi:o:t:), ^(NSInvocation* i) {
      [i setArgument:&a atIndex:2]; [i setArgument:&b atIndex:3]; [i setArgument:&r atIndex:4]; [i setArgument:&q atIndex:5];
      [i setArgument:&m atIndex:6]; [i setArgument:&fi atIndex:7]; [i setArgument:&o atIndex:8]; [i setArgument:&t atIndex:9]; }, &dr);
    printf("invocation mix: %.4f (direct %.4f)\n", dr, [c mix:a f:b r:r q:q m:m fi:fi o:o t:t]);
    Rect4 rr = {0}; __block double by = 0.5;
    invoke(c, @selector(grow:by:), ^(NSInvocation* i) { [i setArgument:&q atIndex:2]; [i setArgument:&by atIndex:3]; }, &rr);
    printf("invocation grow: %.2f %.2f %.2f %.2f\n", rr.x, rr.y, rr.w, rr.h);
    Mix24 mr = {0}; __block long la = -5; __block double lb = 6.25; __block int lc = 11;
    invoke(c, @selector(mixOf:b:c:), ^(NSInvocation* i) { [i setArgument:&la atIndex:2]; [i setArgument:&lb atIndex:3]; [i setArgument:&lc atIndex:4]; }, &mr);
    printf("invocation mixOf: %ld %.2f %d\n", mr.a, mr.b, mr.c);
    float fr = 0; static float fs[10] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}; __block double k = 0.5; __block int l = 3;
    invoke(c, @selector(many::::::::::::), ^(NSInvocation* i) {
      for (int j = 0; j < 10; j++) [i setArgument:&fs[j] atIndex:2 + j];
      [i setArgument:&k atIndex:12]; [i setArgument:&l atIndex:13]; }, &fr);
    printf("invocation many floats: %.1f\n", fr);
    F3 tr = {0}; __block float ts = 1.25f;
    invoke(c, @selector(triple:), ^(NSInvocation* i) { [i setArgument:&ts atIndex:2]; }, &tr);
    printf("invocation triple: %.3f %.3f %.3f\n", tr.a, tr.b, tr.c);
    // KVC: host-side boxing of guest getters / unboxing into guest setters
    c.dval = 3.125; c.fval = -0.5f; c.rng = NSMakeRange(8, 2); c.rect = (Rect4){5, 6, 7, 8}; c.mix = (Mix24){-1, 2.5, 3};
    printf("KVC get: %s %s %s\n", [[c valueForKey:@"dval"] description].UTF8String, [[c valueForKey:@"fval"] description].UTF8String,
           NSStringFromRange([[c valueForKey:@"rng"] rangeValue]).UTF8String);
    Rect4 kr; [[c valueForKey:@"rect"] getValue:&kr size:sizeof kr];
    Mix24 km; [[c valueForKey:@"mix"] getValue:&km size:sizeof km];
    printf("KVC get structs: %.1f %.1f %.1f %.1f | %ld %.2f %d\n", kr.x, kr.y, kr.w, kr.h, km.a, km.b, km.c);
    [c setValue:@(9.75) forKey:@"dval"]; [c setValue:@(1.5f) forKey:@"fval"]; [c setValue:[NSValue valueWithRange:NSMakeRange(1, 9)] forKey:@"rng"];
    Rect4 nr = {-1, -2, -3, -4}; [c setValue:[NSValue valueWithBytes:&nr objCType:@encode(Rect4)] forKey:@"rect"];
    Mix24 nm = {42, -0.25, 6}; [c setValue:[NSValue valueWithBytes:&nm objCType:@encode(Mix24)] forKey:@"mix"];
    printf("KVC set: %.2f %.2f %s | %.0f %.0f %.0f %.0f | %ld %.2f %d\n", c.dval, c.fval, NSStringFromRange(c.rng).UTF8String,
           c.rect.x, c.rect.y, c.rect.w, c.rect.h, c.mix.a, c.mix.b, c.mix.c);
    NSArray* many = @[c, [Calc new]]; ((Calc*)many[1]).dval = 0.25;
    printf("KVC collection ops: sum %s max %s\n", [[many valueForKeyPath:@"@sum.dval"] description].UTF8String,
           [[many valueForKeyPath:@"@max.dval"] description].UTF8String);
    // blocks with NSRange by value
    NSMutableString* subs = [NSMutableString string];
    [@"ab cde  f" enumerateSubstringsInRange:NSMakeRange(0, 9) options:NSStringEnumerationByWords
                                 usingBlock:^(NSString* w, NSRange sr, NSRange er, BOOL* stop) { [subs appendFormat:@"[%@ %lu+%lu %lu+%lu]", w,
                                   (unsigned long)sr.location, (unsigned long)sr.length, (unsigned long)er.location, (unsigned long)er.length]; }];
    printf("substrings: %s\n", subs.UTF8String);
    NSMutableIndexSet* is = [NSMutableIndexSet indexSet]; [is addIndexesInRange:NSMakeRange(2, 3)]; [is addIndexesInRange:NSMakeRange(10, 2)];
    NSMutableString* rs = [NSMutableString string];
    [is enumerateRangesUsingBlock:^(NSRange g, BOOL* stop) { [rs appendFormat:@"%lu+%lu ", (unsigned long)g.location, (unsigned long)g.length]; }];
    printf("index ranges: %s\n", rs.UTF8String);
    NSMutableAttributedString* as = [[NSMutableAttributedString alloc] initWithString:@"hello world"];
    [as addAttribute:@"k" value:@1 range:NSMakeRange(0, 5)]; [as addAttribute:@"k" value:@2 range:NSMakeRange(6, 5)];
    NSMutableString* ar = [NSMutableString string];
    [as enumerateAttribute:@"k" inRange:NSMakeRange(0, 11) options:0 usingBlock:^(id v, NSRange g, BOOL* stop) {
      [ar appendFormat:@"%@@%lu+%lu ", v, (unsigned long)g.location, (unsigned long)g.length]; }];
    printf("attribute runs: %s\n", ar.UTF8String);
    // typed function-pointer parameters of Foundation methods
    int dir = 1;
    NSArray* words = @[@"pear", @"fig", @"banana", @"kiwi", @"apple"];
    NSData* hint = [words sortedArrayHint];
    printf("sorted with hint: %s\n", [[words sortedArrayUsingFunction:by_len context:&dir hint:hint] componentsJoinedByString:@","].UTF8String);
    NSPointerFunctions* pf = [NSPointerFunctions pointerFunctionsWithOptions:NSPointerFunctionsMallocMemory | NSPointerFunctionsStructPersonality
                                                                             | NSPointerFunctionsCopyIn];
    pf.sizeFunction = sz_fn; pf.descriptionFunction = desc_fn;
    NSPointerArray* pa = [[NSPointerArray alloc] initWithPointerFunctions:pf];
    int vals[3] = {7, 8, 9};
    for (int i = 0; i < 3; i++) [pa addPointer:&vals[i]];
    vals[0] = 70;                                                 // CopyIn: the array holds copies of size sz_fn()
    printf("pointer array: %d %d %d, size fn round trip %d desc fn round trip %d\n", *(int*)[pa pointerAtIndex:0], *(int*)[pa pointerAtIndex:1],
           *(int*)[pa pointerAtIndex:2], pa.pointerFunctions.sizeFunction == sz_fn, pa.pointerFunctions.descriptionFunction == desc_fn);
    printf("pointer array description has <int 8>: %d\n", [[pa description] containsString:@"<int 8>"]);
    NSUInteger (*gs)(const void*) = pf.sizeFunction;
    printf("getter on the same object round trip %d\n", gs == sz_fn);
    printf("call through the getter result: %lu %s\n", (unsigned long)gs(vals), pa.pointerFunctions.descriptionFunction(&vals[1]).UTF8String);
  }
  return 0;
}
