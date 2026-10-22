// Variadic format methods recognised by name (stringWithFormat:, appendFormat:, stringByAppendingFormat:,
// localizedStringWithFormat:, initWithFormat:) with every common conversion, positional arguments, '*' widths, many args.
#import <Foundation/Foundation.h>

@interface Named : NSObject @property (copy) NSString* name; @end
@implementation Named - (NSString*)description { return [NSString stringWithFormat:@"<Named %@>", self.name]; } @end

int main(void) {
  @autoreleasepool {
    Named* n = [Named new]; n.name = @"zed";
    id nothing = nil;
    NSString* s;
    s = [NSString stringWithFormat:@"int %d %i %u %ld %lld %llu %hd %hhd %zu %td", -1, 2, 3u, -4L, -5LL, 6ULL, (short)-7, (char)8, (size_t)9, (ptrdiff_t)-10];
    printf("%s\n", s.UTF8String);
    s = [NSString stringWithFormat:@"hex %x %X %#x %08x %llx %o %#o", 255, 255, 255, 255, 0x123456789abcULL, 8, 8];
    printf("%s\n", s.UTF8String);
    s = [NSString stringWithFormat:@"flt %f %.3f %e %E %g %G %10.4f| %-10.2f| %+f %a", 1.5, 3.14159, 12345.678, 0.000123, 1e20, 1e-5, 2.5, 7.25, 1.0, 1.0];
    printf("%s\n", s.UTF8String);
    s = [NSString stringWithFormat:@"mix %d %f %d %f %d %f %d %f %d %f %d %f", 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5];
    printf("%s\n", s.UTF8String);
    s = [NSString stringWithFormat:@"str %s|%10s|%-6s|%.2s %c%c %C %%", "abc", "right", "left", "trunc", 'o', 'k', (unichar)0x41];
    printf("%s\n", s.UTF8String);
    s = [NSString stringWithFormat:@"obj %@ %@ %@ %@ %@", n, nothing, @42, @[@1, @"two"], @{@"k": @3.5}];
    printf("%s\n", s.UTF8String);
    s = [NSString stringWithFormat:@"pos %2$@ %1$@ %3$d %2$@", @"first", @"second", 33];
    printf("%s\n", s.UTF8String);
    s = [NSString stringWithFormat:@"star [%*d] [%-*d] [%.*f] [%*.*f]", 6, 42, 5, 7, 2, 3.14159, 9, 3, 2.71828];
    printf("%s\n", s.UTF8String);
    s = [NSString stringWithFormat:@"many %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d", 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20];
    printf("%s\n", s.UTF8String);
    NSMutableString* m = [NSMutableString stringWithString:@"m:"];
    [m appendFormat:@" %d/%@/%.1f", 7, n, 0.25];
    [m appendFormat:@" %s", "tail"];
    printf("%s\n", m.UTF8String);
    s = [@"base" stringByAppendingFormat:@"+%03d+%@", 5, @"x"];
    printf("%s\n", s.UTF8String);
    s = [NSString localizedStringWithFormat:@"loc %d %@", 1234567, @"y"];
    printf("%s\n", s.UTF8String);
    s = [[NSString alloc] initWithFormat:@"init %d %@ %f", 9, n, 0.5];
    printf("%s\n", s.UTF8String);
    s = [NSString stringWithFormat:@"%@", @"just-one"];
    printf("%s\n", s.UTF8String);
    s = [NSString stringWithFormat:@"no args"];
    printf("%s\n", s.UTF8String);
    NSString* fmt = [@"dyn %" stringByAppendingString:@"d-%@"];
    s = [NSString stringWithFormat:fmt, 77, @"z"];
    printf("%s\n", s.UTF8String);
    s = [NSString stringWithFormat:@"long double %Lf %Lg", (long double)1.5, (long double)2.25];
    printf("%s\n", s.UTF8String);
  }
  return 0;
}
