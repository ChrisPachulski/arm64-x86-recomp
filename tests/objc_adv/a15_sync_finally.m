// @synchronized under contention (8 threads), recursive and nil @synchronized, @try/@finally with no exception (normal
// exit, return and break out of the @try), nested.
#import <Foundation/Foundation.h>
#include <pthread.h>
static NSObject* lockObj;
static long counter;
static void* worker(void* arg) {
  @autoreleasepool {
    for (int i = 0; i < 20000; i++) @synchronized(lockObj) { @synchronized(lockObj) { long c = counter; counter = c + 1; } }
  }
  return NULL;
}
static int with_finally(int k, NSMutableString* log) {
  @try {
    [log appendFormat:@"try%d ", k];
    if (k == 1) return 10;
    for (int i = 0; i < 3; i++) { @try { if (i == 1) break; [log appendString:@"loop "]; } @finally { [log appendFormat:@"inner-finally%d ", i]; } }
  } @finally {
    [log appendFormat:@"finally%d ", k];
  }
  return 20;
}
int main(void) {
  @autoreleasepool {
    lockObj = [NSObject new];
    pthread_t t[8];
    for (int i = 0; i < 8; i++) pthread_create(&t[i], NULL, worker, NULL);
    for (int i = 0; i < 8; i++) pthread_join(t[i], NULL);
    printf("counter %ld\n", counter);
    id nothing = nil;
    @synchronized(nothing) { printf("nil sync ok\n"); }
    NSMutableString* log = [NSMutableString string];
    int a = with_finally(0, log), b = with_finally(1, log);
    printf("finally %d %d: %s\n", a, b, log.UTF8String);
  }
  return 0;
}
