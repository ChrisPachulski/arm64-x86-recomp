// Dealloc timing of ARC +0 returns inside one autorelease pool: a guest method return vs a guest C function return vs a
// block return (native: the return-value handoff frees each object at the caller's scope end, before the pool drains).
#import <Foundation/Foundation.h>
static int deallocs;
@interface D : NSObject + (instancetype)make; @end
@implementation D + (instancetype)make { return [D new]; } - (void)dealloc { deallocs++; } @end
__attribute__((noinline)) static D* cfunc(void) { return [D new]; }
int main(void) {
  @autoreleasepool {
    D* (^blk)(void) = ^D*(void) { return [D new]; };
    int b;
    @autoreleasepool { b = deallocs; for (int i = 0; i < 100; i++) { D* d = [D make]; (void)d; } printf("method return: %d freed before drain\n", deallocs - b); }
    @autoreleasepool { b = deallocs; for (int i = 0; i < 100; i++) { D* d = cfunc(); (void)d; } printf("C function return: %d freed before drain\n", deallocs - b); }
    @autoreleasepool { b = deallocs; for (int i = 0; i < 100; i++) { D* d = blk(); (void)d; } printf("block return: %d freed before drain\n", deallocs - b); }
    @autoreleasepool { b = deallocs; for (int i = 0; i < 100; i++) { NSString* s = [NSString stringWithFormat:@"%d", i]; (void)s; } printf("host return ok\n"); }
  }
  return 0;
}
