/* Objective-C message sends in a hot loop: 20M sends of -add: to a guest NSObject subclass, 4M of -[NSArray count] (host). */
#include "perf.h"
#import <Foundation/Foundation.h>

@interface Acc : NSObject { long v; }
- (long)add:(long)x;
@end
@implementation Acc
- (long)add:(long)x { v += x ^ (v >> 7); return v; }
@end

int main(void) {
  @autoreleasepool {
    Acc* a = [Acc new];
    NSArray* arr = @[@1, @2, @3];
    long s = 0;
    uint64_t t0 = perf_ns();
    for (long i = 0; i < 20000000; i++) s += [a add:i];
    for (long i = 0; i < 4000000; i++) s += (long)[arr count];
    perf_end(t0);
    printf("%ld\n", s);
    [a release];
  }
  return 0;
}
