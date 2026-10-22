// arrayWithObjects: and setWithObjects: alone (stdout unbuffered so a later crash cannot hide earlier lines).
#import <Foundation/Foundation.h>
int main(void) {
  setvbuf(stdout, NULL, _IONBF, 0);
  @autoreleasepool {
    NSArray* a = [NSArray arrayWithObjects:@"a", @"b", @"c", @4, nil];
    printf("array %lu %s\n", (unsigned long)a.count, [a componentsJoinedByString:@","].UTF8String);
    NSSet* s = [NSSet setWithObjects:@"p", @"q", @"p", nil];
    printf("set %lu\n", (unsigned long)s.count);
    NSArray* b = [[NSArray alloc] initWithObjects:@"x", @"y", nil];
    printf("init %lu\n", (unsigned long)b.count);
  }
  return 0;
}
