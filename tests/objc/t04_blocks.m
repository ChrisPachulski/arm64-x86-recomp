// Blocks both ways: guest blocks handed to the host (Foundation enumeration/sorting/notifications, libdispatch async,
// sync (noescape), apply, once, groups, NSThread), __block variables copied to the heap by the host, blocks returning
// doubles and structs, a host block (dispatch_block_create) called by guest code, guest heap blocks stored in host arrays.
#import <Foundation/Foundation.h>

typedef double (^Scale)(double, int);
typedef NSPoint (^MkPoint)(double x, double y);

static NSMutableArray* g_later;

static void keep(void (^b)(void)) { [g_later addObject:[b copy]]; }

int main(void) {
  @autoreleasepool {
    g_later = [NSMutableArray array];
    NSArray* a = @[@5, @3, @9, @1, @7];
    __block int seen = 0;
    [a enumerateObjectsUsingBlock:^(NSNumber* n, NSUInteger i, BOOL* stop) {
      seen += n.intValue; printf("enum %lu=%d\n", (unsigned long)i, n.intValue);
      if (i == 3) *stop = YES;
    }];
    printf("seen %d\n", seen);
    NSArray* s = [a sortedArrayUsingComparator:^NSComparisonResult(NSNumber* x, NSNumber* y) { return [y compare:x]; }];
    printf("sorted desc: %s\n", [s componentsJoinedByString:@","].UTF8String);
    NSIndexSet* big = [a indexesOfObjectsPassingTest:^BOOL(NSNumber* n, NSUInteger i, BOOL* stop) { return n.intValue > 4; }];
    printf("passing: %lu first %lu\n", (unsigned long)big.count, (unsigned long)big.firstIndex);

    dispatch_queue_t q = dispatch_queue_create("t04.serial", DISPATCH_QUEUE_SERIAL);
    dispatch_group_t g = dispatch_group_create();
    __block NSString* msg = @"start";                      /* a __block object: byref keep/destroy helpers */
    __block long total = 0;
    for (int i = 1; i <= 4; i++)
      dispatch_group_async(g, q, ^{ total += i * 10; msg = [msg stringByAppendingFormat:@"+%d", i]; });
    dispatch_group_wait(g, DISPATCH_TIME_FOREVER);
    printf("async on a serial queue: total %ld msg %s main %d\n", total, msg.UTF8String, [NSThread isMainThread]);
    __block int synced = 0;
    dispatch_sync(q, ^{ synced = 42; });
    printf("sync: %d\n", synced);
    long* slots = calloc(16, sizeof(long));
    dispatch_apply(16, dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^(size_t i) { slots[i] = (long)(i * i); });
    long sum = 0; for (int i = 0; i < 16; i++) sum += slots[i];
    printf("apply: sum %ld last %ld\n", sum, slots[15]);
    free(slots);
    static dispatch_once_t once; __block int once_runs = 0;
    for (int i = 0; i < 3; i++) dispatch_once(&once, ^{ once_runs++; });
    printf("once: %d\n", once_runs);

    __block int notes = 0;
    id obs = [[NSNotificationCenter defaultCenter] addObserverForName:@"t04.note" object:nil queue:nil
                                                           usingBlock:^(NSNotification* n) { notes++; printf("note %s %s\n", n.name.UTF8String, [n.userInfo[@"k"] UTF8String]); }];
    [[NSNotificationCenter defaultCenter] postNotificationName:@"t04.note" object:nil userInfo:@{@"k": @"v1"}];
    [[NSNotificationCenter defaultCenter] postNotificationName:@"t04.note" object:nil userInfo:@{@"k": @"v2"}];
    [[NSNotificationCenter defaultCenter] removeObserver:obs];
    [[NSNotificationCenter defaultCenter] postNotificationName:@"t04.note" object:nil];
    printf("notes %d\n", notes);

    double base = 1.5;
    Scale sc = ^double(double x, int k) { return x * k + base; };
    MkPoint mp = ^NSPoint(double x, double y) { return NSMakePoint(x + base, y - base); };
    NSPoint pt = mp(10, 20);
    printf("block returns: %g point %g %g\n", sc(2.0, 3), pt.x, pt.y);
    NSString* captured = @"captured-object";
    for (int i = 0; i < 3; i++) keep(^{ printf("later %d %s\n", i, captured.UTF8String); });
    for (void (^b)(void) in g_later) b();                  /* guest calls of the host-held heap copies */

    dispatch_block_t hb = dispatch_block_create(0, ^{ printf("inside a host-wrapped block\n"); });
    hb();                                                  /* the guest calls a block the host built */
    dispatch_semaphore_t sem = dispatch_semaphore_create(0);
    __block int thread_val = 0;
    [NSThread detachNewThreadWithBlock:^{ thread_val = [NSThread isMainThread] ? -1 : 7; dispatch_semaphore_signal(sem); }];
    dispatch_semaphore_wait(sem, DISPATCH_TIME_FOREVER);
    printf("thread block: %d\n", thread_val);
    NSBlockOperation* op = [NSBlockOperation blockOperationWithBlock:^{ printf("operation ran\n"); }];
    [op start];
    void (^again)(void) = op.executionBlocks.firstObject;
    again();
  }
  return 0;
}
