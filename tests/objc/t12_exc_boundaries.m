// Objective-C exceptions across guest and host frames: a host handler (NSInvocationOperation's -main) catches an exception
// raised in a guest method, after the guest @finally, ARC cleanup and @synchronized unlock ran; a guest @throw caught by
// the host; a guest block throwing through host -enumerateObjectsUsingBlock: into the guest caller's @catch; @catch(id),
// a guest exception class, rethrow from @catch, nested @finally, and @catch of a C-level raise in a guest callback.
#import <Foundation/Foundation.h>
#include <pthread.h>
static int finallies, deallocs;
static NSObject* lock;
@interface Tmp : NSObject @end
@implementation Tmp - (void)dealloc { deallocs++; } @end
@interface GuestError : NSException @end
@implementation GuestError @end
@interface T : NSObject - (id)boom; - (id)guestThrow; @end
@implementation T
- (id)boom {
  Tmp* local = [Tmp new];
  @synchronized(lock) {
    @try { [NSException raise:@"Boom" format:@"n=%d %@", 7, local ? @"live" : @"nil"]; }
    @finally { finallies++; }
  }
  return nil;
}
- (id)guestThrow { @throw [GuestError exceptionWithName:@"GuestError" reason:@"from guest" userInfo:@{@"k": @42}]; }
@end
static void* other_thread(void* arg) { @synchronized(lock) { printf("other thread got the lock\n"); } return NULL; }
static int depth(int n) {
  @try { if (n == 0) [@[] objectAtIndex:1]; else return depth(n - 1) + 1; }
  @finally { finallies++; }
  return 0;
}
int main(void) {
  setvbuf(stdout, NULL, _IONBF, 0);
  lock = [NSObject new];
  @autoreleasepool {
    NSInvocationOperation* op = [[NSInvocationOperation alloc] initWithTarget:[T new] selector:@selector(boom) object:nil];
    [op start];
    printf("after host catch: finallies %d deallocs %d\n", finallies, deallocs);
    pthread_t t; pthread_create(&t, NULL, other_thread, NULL); pthread_join(t, NULL);
    @try { [op result]; } @catch (NSException* e) { printf("result re-raised %s: %s\n", e.name.UTF8String, e.reason.UTF8String); }
    NSInvocationOperation* op2 = [[NSInvocationOperation alloc] initWithTarget:[T new] selector:@selector(guestThrow) object:nil];
    [op2 start];
    @try { [op2 result]; }
    @catch (GuestError* e) { printf("guest class caught %s %s %d\n", e.name.UTF8String, e.reason.UTF8String, [e.userInfo[@"k"] intValue]); }
    @try {
      [@[@1, @2, @3] enumerateObjectsUsingBlock:^(id o, NSUInteger i, BOOL* stop) {
        @try { if (i == 1) @throw [NSException exceptionWithName:@"InBlock" reason:[o description] userInfo:nil]; }
        @finally { finallies++; }
      }];
      printf("not reached\n");
    } @catch (id e) { printf("caught through host frames: %s %s, finallies %d\n", [e name].UTF8String, [e reason].UTF8String, finallies); }
    @try {
      @try { [(NSMutableDictionary*)@{} setObject:@1 forKey:@"k"]; }
      @catch (NSException* e) { printf("inner %s\n", e.name.UTF8String); @throw; }
      @finally { printf("inner finally\n"); }
    } @catch (NSException* e) { printf("outer %s\n", e.name.UTF8String); }
    @try { depth(5); } @catch (NSException* e) { printf("deep %s, finallies %d\n", e.name.UTF8String, finallies); }
  }
  printf("deallocs %d\n", deallocs);
  return 0;
}
