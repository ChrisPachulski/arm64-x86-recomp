// Autorelease pools on guest pthreads and NSThreads: nested pools drained at the right time (deallocs counted at each
// drain), objects autoreleased with no pool at all on a thread (drained at thread exit), ARC returns across threads.
#import <Foundation/Foundation.h>
#include <pthread.h>
#include <stdatomic.h>
static atomic_int deallocs;
@interface D : NSObject @property int n; + (instancetype)make:(int)n; - (D*)child; @end
@implementation D
+ (instancetype)make:(int)n { D* d = [D new]; d.n = n; return d; }           // returned autoreleased through ARC rules
- (D*)child { return [D make:_n + 1]; }
- (void)dealloc { atomic_fetch_add(&deallocs, 1); }
@end
__attribute__((noinline)) static id autoreleased(int n) { D* d = [D make:n]; return (__bridge id)(__bridge void*)[d child]; }
typedef struct { int id; int before, inner, after; } Res;
static void* work(void* arg) {
  Res* r = arg;
  @autoreleasepool {
    for (int i = 0; i < 1000; i++) { id x = [NSString stringWithFormat:@"%d-%d", r->id, i]; (void)x; [D make:i]; }
    @autoreleasepool {
      for (int i = 0; i < 500; i++) [[D make:i] child];
    }
    r->inner = 1;
  }
  return NULL;
}
static void* nopool(void* arg) {
  for (int i = 0; i < 300; i++) { NSMutableArray* a = [NSMutableArray array]; [a addObject:[D make:i]]; (void)autoreleased(i); }
  return NULL;
}
int main(void) {
  @autoreleasepool {
    int before = atomic_load(&deallocs);
    pthread_t t[6]; Res r[6];
    for (int i = 0; i < 6; i++) { r[i] = (Res){i, 0, 0, 0}; pthread_create(&t[i], NULL, work, &r[i]); }
    for (int i = 0; i < 6; i++) pthread_join(t[i], NULL);
    printf("pthread pools: deallocs %d\n", atomic_load(&deallocs) - before);
    before = atomic_load(&deallocs);
    pthread_t np; pthread_create(&np, NULL, nopool, NULL); pthread_join(np, NULL);
    usleep(100000);
    printf("no-pool thread drained at exit: %d\n", atomic_load(&deallocs) - before);
    before = atomic_load(&deallocs);
    NSCondition* cond = [NSCondition new]; __block int done = 0;
    for (int k = 0; k < 4; k++)
      [NSThread detachNewThreadWithBlock:^{
        @autoreleasepool { for (int i = 0; i < 250; i++) (void)autoreleased(i); }
        [cond lock]; done++; [cond signal]; [cond unlock];
      }];
    [cond lock]; while (done < 4) [cond wait]; [cond unlock];
    printf("NSThread pools: %d\n", atomic_load(&deallocs) - before);
    before = atomic_load(&deallocs);
    @autoreleasepool { for (int i = 0; i < 100; i++) (void)autoreleased(i); printf("inside main pool: %d\n", atomic_load(&deallocs) - before); }
    printf("after main pool: %d\n", atomic_load(&deallocs) - before);
  }
  return 0;
}
