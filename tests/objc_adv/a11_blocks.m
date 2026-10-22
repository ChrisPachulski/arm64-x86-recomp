// Blocks capturing objects, __block ints and objects, and other blocks; copied to the heap by the host (NSArray, copy,
// dispatch), called on other threads (dispatch_async, dispatch_apply, NSThread, NSOperationQueue), released (captured
// objects deallocate); host-made blocks (NSSortDescriptor comparator, dispatch_block_create) called by guest code; a
// host-called guest block writing through BOOL *stop.
#import <Foundation/Foundation.h>
#include <stdatomic.h>
static atomic_int deallocs;
@interface Cap : NSObject @property int v; @end
@implementation Cap - (void)dealloc { atomic_fetch_add(&deallocs, 1); } @end
typedef int (^IntFn)(int);
__attribute__((noinline)) static IntFn make_adder(int k, Cap* c) { return ^int(int x) { return x + k + c.v; }; }
__attribute__((noinline)) static IntFn compose(IntFn f, IntFn g) { return ^int(int x) { return f(g(x)); }; }
@interface Runner : NSObject - (int)run:(int (^)(int))fn with:(int)x; - (id)callHost:(dispatch_block_t)b; @end
@implementation Runner - (int)run:(int (^)(int))fn with:(int)x { return fn(x) * 2; }
- (id)callHost:(dispatch_block_t)b { b(); b(); return @"called twice"; } @end

int main(void) {
  setvbuf(stdout, NULL, _IONBF, 0);
  @autoreleasepool {
    __block int counter = 0;
    __block NSMutableArray* log = [NSMutableArray array];
    Runner* rn = [Runner new]; Runner* rnr = rn;
    @autoreleasepool {
      Cap* c = [Cap new]; c.v = 100;
      IntFn add5 = make_adder(5, c);
      IntFn twice = compose(add5, add5);
      NSMutableArray* held = [@[add5, twice] mutableCopy];
      printf("composed %d held %d\n", twice(1), ((IntFn)held[1])(2));
      dispatch_group_t grp = dispatch_group_create();
      dispatch_queue_t q = dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0);
      NSLock* lk = [NSLock new];
      for (int i = 0; i < 64; i++)
        dispatch_group_async(grp, q, ^{
          int r = twice(i);
          [lk lock]; counter += r; [log addObject:@(r)]; [lk unlock];
        });
      dispatch_group_wait(grp, DISPATCH_TIME_FOREVER);
      printf("async sum %d entries %lu\n", counter, (unsigned long)log.count);
      __block atomic_int applied = 0;
      dispatch_apply(100, q, ^(size_t i) { atomic_fetch_add(&applied, add5((int)i)); });
      printf("apply %d\n", (int)applied);
      __block int threadResult = 0;
      dispatch_semaphore_t sem = dispatch_semaphore_create(0);
      [NSThread detachNewThreadWithBlock:^{ @autoreleasepool { threadResult = twice(10); [log addObject:@"thread"]; } dispatch_semaphore_signal(sem); }];
      dispatch_semaphore_wait(sem, DISPATCH_TIME_FOREVER);
      NSOperationQueue* oq = [NSOperationQueue new];
      __block int opsum = 0;
      for (int i = 0; i < 10; i++) [oq addOperationWithBlock:^{ [lk lock]; opsum += add5(i); [lk unlock]; }];
      [oq waitUntilAllOperationsAreFinished];
      printf("thread %d ops %d\n", threadResult, opsum);
      __block id boxed = @"start";
      void (^setter)(NSString*) = ^(NSString* s) { boxed = [boxed stringByAppendingString:s]; };
      dispatch_sync(dispatch_queue_create("s", 0), ^{ setter(@"+sync"); });
      void (^heap)(NSString*) = [setter copy];
      heap(@"+heap");
      printf("byref object %s\n", [boxed UTF8String]);
      dispatch_block_t hq = dispatch_block_create_with_qos_class(0, QOS_CLASS_UTILITY, 0, ^{ counter += 7; });
      id hostRet = [rnr performSelector:@selector(callHost:) withObject:hq];
      printf("host block via host call %d %s\n", counter, [hostRet UTF8String]);
      dispatch_block_t hb = dispatch_block_create(0, ^{ counter += 1000; });
      hb();
      printf("dispatch_block_create %d\n", counter);
      __block int seen = 0;
      [@[@1, @2, @3, @4, @5] enumerateObjectsUsingBlock:^(id o, NSUInteger idx, BOOL* stop) { seen += [o intValue]; if (idx == 2) *stop = YES; }];
      printf("enumerate stop %d\n", seen);
      printf("runner %d\n", ((int (*)(id, SEL, id, int))[rn methodForSelector:@selector(run:with:)])(rn, @selector(run:with:), add5, 3));
      NSInvocation* inv = [NSInvocation invocationWithMethodSignature:[rn methodSignatureForSelector:@selector(run:with:)]];
      inv.target = rn; inv.selector = @selector(run:with:);
      IntFn arg = twice; int x = 4;
      [inv setArgument:&arg atIndex:2]; [inv setArgument:&x atIndex:3]; [inv retainArguments]; [inv invoke];
      int ir; [inv getReturnValue:&ir];
      printf("invocation block arg %d\n", ir);
    }
    printf("captured deallocs %d log %lu\n", (int)atomic_load(&deallocs), (unsigned long)log.count);
  }
  return 0;
}
