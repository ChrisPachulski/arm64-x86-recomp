// 1,000 guest objects through NSArray sorting: a guest comparator block (serial and NSSortConcurrent), a guest compare:
// selector, sort descriptors on guest properties (KVC), and a stable sort; plus concurrent enumeration.
#import <Foundation/Foundation.h>
#include <stdatomic.h>
@interface Item : NSObject @property int ikey; @property (copy) NSString* name; @property double weight; @end
@implementation Item
- (NSComparisonResult)compareKey:(Item*)o { return _ikey < o.ikey ? NSOrderedAscending : _ikey > o.ikey ? NSOrderedDescending : NSOrderedSame; }
@end
static unsigned lcg = 12345;
static unsigned next(void) { lcg = lcg * 1103515245u + 12345u; return (lcg >> 8) & 0xffff; }
static unsigned long digest(NSArray* a) { unsigned long h = 1469598103934665603UL; for (Item* i in a) h = (h ^ (unsigned)i.ikey ^ ((unsigned long)i.name.hash << 3)) * 1099511628211UL; return h; }
int main(void) {
  @autoreleasepool {
    NSMutableArray* items = [NSMutableArray array];
    for (int i = 0; i < 1000; i++) { Item* it = [Item new]; it.ikey = (int)(next() % 500); it.name = [NSString stringWithFormat:@"n%04u", next() % 10000]; it.weight = next() / 7.0; [items addObject:it]; }
    __block atomic_int calls = 0;
    NSArray* a = [items sortedArrayUsingComparator:^NSComparisonResult(Item* x, Item* y) { atomic_fetch_add(&calls, 1); return [x compareKey:y]; }];
    printf("comparator first %d last %d sorted-ok %d\n", [a[0] ikey], [a.lastObject ikey], 1);
    int ok = 1; for (NSUInteger i = 1; i < a.count; i++) if ([a[i - 1] ikey] > [a[i] ikey]) ok = 0;
    printf("ascending %d calls>0 %d stable digest %lx\n", ok, calls > 0, digest(a));
    NSArray* c = [items sortedArrayWithOptions:NSSortConcurrent | NSSortStable usingComparator:^NSComparisonResult(Item* x, Item* y) {
      return x.weight < y.weight ? NSOrderedAscending : x.weight > y.weight ? NSOrderedDescending : NSOrderedSame; }];
    printf("concurrent digest %lx\n", digest(c));
    NSArray* s = [items sortedArrayUsingSelector:@selector(compareKey:)];
    ok = 1; for (NSUInteger i = 1; i < s.count; i++) if ([s[i - 1] ikey] > [s[i] ikey]) ok = 0;
    printf("selector sort ascending %d\n", ok);
    NSArray* d = [items sortedArrayUsingDescriptors:@[[NSSortDescriptor sortDescriptorWithKey:@"ikey" ascending:NO],
                                                       [NSSortDescriptor sortDescriptorWithKey:@"name" ascending:YES]]];
    printf("descriptors digest %lx first %d %s\n", digest(d), [d[0] ikey], [[d[0] name] UTF8String]);
    NSArray* st = [items sortedArrayWithOptions:NSSortStable usingComparator:^NSComparisonResult(Item* x, Item* y) {
      return (x.ikey / 100) < (y.ikey / 100) ? NSOrderedAscending : (x.ikey / 100) > (y.ikey / 100) ? NSOrderedDescending : NSOrderedSame; }];
    printf("stable digest %lx\n", digest(st));
    __block atomic_long sum = 0;
    [items enumerateObjectsWithOptions:NSEnumerationConcurrent usingBlock:^(Item* it, NSUInteger idx, BOOL* stop) { atomic_fetch_add(&sum, it.ikey); }];
    printf("concurrent enum sum %ld\n", (long)sum);
    NSMutableArray* m = [items mutableCopy];
    [m sortUsingComparator:^NSComparisonResult(Item* x, Item* y) { return [y compareKey:x]; }];
    printf("in-place desc first %d\n", [m[0] ikey]);
  }
  return 0;
}
