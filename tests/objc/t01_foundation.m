// Foundation values through objc_msgSend: strings, collections, numbers, autorelease pools, struct returns, toll-free
// bridging, variadic format methods.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>

int main(void) {
  @autoreleasepool {
    NSString* s = [NSString stringWithFormat:@"%@-%d-%.2f-%s-%ld", @"abc", 42, 3.25, "cstr", (long)-7];
    printf("format: %s (len %lu)\n", s.UTF8String, (unsigned long)s.length);
    NSMutableString* m = [NSMutableString stringWithString:@"x"];
    [m appendFormat:@"[%@|%u]", @[@1, @2], 9u];
    printf("append: %s\n", m.UTF8String);
    NSRange r = [s rangeOfString:@"42"];
    printf("range: %lu %lu\n", (unsigned long)r.location, (unsigned long)r.length);
    NSArray* a = @[@"pear", @"apple", @"fig"];
    NSArray* sorted = [a sortedArrayUsingSelector:@selector(compare:)];
    printf("sorted: %s\n", [sorted componentsJoinedByString:@","].UTF8String);
    NSDictionary* d = @{@"k1": @10, @"k2": @[@"a", @"b"], @"k3": @{@"n": @YES}};
    for (NSString* k in [d.allKeys sortedArrayUsingSelector:@selector(compare:)]) printf("dict %s = %s\n", k.UTF8String, [[d[k] description] stringByReplacingOccurrencesOfString:@"\n" withString:@" "].UTF8String);
    NSNumber* n = @(1.5); NSNumber* i = @(-3); NSNumber* b = @NO;
    printf("numbers: %f %d %d %s %lld\n", n.doubleValue, i.intValue, b.boolValue, [n stringValue].UTF8String, [@(1LL << 40) longLongValue]);
    NSValue* v = [NSValue valueWithRect:NSMakeRect(1.5, 2.5, 30, 40)];
    NSRect rc = v.rectValue;
    printf("rect: %g %g %g %g\n", rc.origin.x, rc.origin.y, rc.size.width, rc.size.height);
    NSPoint p = NSMakePoint(7, 8); NSValue* pv = [NSValue valueWithPoint:p];
    printf("point: %g %g size %g\n", pv.pointValue.x, pv.pointValue.y, [NSValue valueWithSize:NSMakeSize(3, 4)].sizeValue.height);
    CFStringRef cf = (__bridge CFStringRef)s;
    printf("cf: len %ld char0 %c\n", (long)CFStringGetLength(cf), (char)CFStringGetCharacterAtIndex(cf, 0));
    CFStringRef made = CFStringCreateWithCString(NULL, "from CF", kCFStringEncodingUTF8);
    NSString* back = (__bridge_transfer NSString*)made;
    printf("toll-free: %s %lu upper %s\n", back.UTF8String, (unsigned long)back.length, back.uppercaseString.UTF8String);
    NSMutableArray* ma = [NSMutableArray array];
    for (int k = 0; k < 5; k++) @autoreleasepool { [ma addObject:[NSString stringWithFormat:@"item%d", k * k]]; }
    printf("mutable: %s count %lu contains %d index %lu\n", [ma componentsJoinedByString:@" "].UTF8String, (unsigned long)ma.count,
           [ma containsObject:@"item9"], (unsigned long)[ma indexOfObject:@"item16"]);
    NSData* data = [@"hello" dataUsingEncoding:NSUTF8StringEncoding];
    printf("data: %lu %s\n", (unsigned long)data.length, [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
    printf("class: %s super %s responds %d\n", NSStringFromClass([s class]).UTF8String ? "ok" : "no", class_getName([NSMutableString superclass]),
           [s respondsToSelector:@selector(length)]);
    id nilobj = nil;
    printf("nil send: %lu %f\n", (unsigned long)[nilobj length], [nilobj doubleValue]);
  }
  return 0;
}
