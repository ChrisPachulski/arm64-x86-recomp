// Variadic methods implemented by guest classes and sent from guest code (one with a format-like name).
#import <Foundation/Foundation.h>
@interface V : NSObject
- (long)sum:(int)n, ...;
- (NSString*)tagWithFormat:(NSString*)f, ...;
@end
@implementation V
- (long)sum:(int)n, ... {
  va_list ap; va_start(ap, n); long t = 0;
  for (int i = 0; i < n; i++) t += va_arg(ap, int);
  va_end(ap); return t;
}
- (NSString*)tagWithFormat:(NSString*)f, ... {
  va_list ap; va_start(ap, f);
  char buf[128]; vsnprintf(buf, sizeof buf, f.UTF8String, ap);
  va_end(ap); return [NSString stringWithFormat:@"[%s]", buf];
}
@end
int main(void) {
  @autoreleasepool {
    V* v = [V new];
    printf("sum %ld\n", [v sum:4, 10, 20, 30, 40]);
    printf("%s\n", [v tagWithFormat:@"%d-%s", 12, "ab"].UTF8String);
  }
  return 0;
}
