// nil-terminated variadic object lists: arrayWithObjects:, dictionaryWithObjectsAndKeys:, setWithObjects:, initWithObjects:.
#import <Foundation/Foundation.h>
int main(void) {
  @autoreleasepool {
    NSArray* a = [NSArray arrayWithObjects:@"a", @"b", @"c", @4, nil];
    printf("array %lu %s\n", (unsigned long)a.count, [a componentsJoinedByString:@","].UTF8String);
    NSDictionary* d = [NSDictionary dictionaryWithObjectsAndKeys:@1, @"one", @2, @"two", nil];
    printf("dict %lu %s\n", (unsigned long)d.count, [d[@"two"] description].UTF8String);
    NSSet* s = [NSSet setWithObjects:@"p", @"q", @"p", nil];
    printf("set %lu\n", (unsigned long)s.count);
    NSArray* b = [[NSArray alloc] initWithObjects:@"x", @"y", nil];
    printf("init %lu %s\n", (unsigned long)b.count, b.lastObject ? [b.lastObject UTF8String] : "nil");
  }
  return 0;
}
