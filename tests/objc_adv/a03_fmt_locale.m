// Variadic method whose name does not end in a recognised format suffix: -initWithFormat:locale:, ...
#import <Foundation/Foundation.h>
int main(void) {
  @autoreleasepool {
    NSString* s = [[NSString alloc] initWithFormat:@"locale %d-%@-%.2f" locale:nil, 42, @"x", 1.5];
    printf("%s\n", s.UTF8String);
    NSLocale* l = [NSLocale localeWithLocaleIdentifier:@"en_US"];
    s = [[NSString alloc] initWithFormat:@"%d|%@" locale:l, 7, @"y"];
    printf("%s\n", s.UTF8String);
  }
  return 0;
}
