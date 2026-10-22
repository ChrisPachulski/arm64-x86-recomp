// +load before main (superclass first, then categories), +initialize on first message (superclass first, once per class),
// an NSThread subclass whose -main override the host runs on its own thread, NSCondition hand-off, C++-free static init.
#import <Foundation/Foundation.h>

static char g_log[512];
static void note(const char* s) { strlcat(g_log, s, sizeof g_log); strlcat(g_log, " ", sizeof g_log); }

@interface Base : NSObject @end
@implementation Base
+ (void)load { note("load:Base"); }
+ (void)initialize { if (self == [Base class]) note("init:Base"); else note("init:Base-for-sub"); }
+ (int)value { return 1; }
@end
@interface Derived : Base @end
@implementation Derived
+ (void)load { note("load:Derived"); }
+ (void)initialize { note("init:Derived"); }
+ (int)value { return [super value] + 10; }
@end
@interface Base (Late) @end
@implementation Base (Late)
+ (void)load { note("load:Base(Late)"); }
@end
@interface Lazy : NSObject @end
@implementation Lazy
+ (void)initialize { note("init:Lazy"); }
@end

__attribute__((constructor)) static void ctor(void) { note("constructor"); }

@interface Worker : NSThread
@property (nonatomic) int result;
@property (nonatomic, strong) NSCondition* cond;
@property (nonatomic) BOOL done;
@end
@implementation Worker
- (void)main {
  @autoreleasepool {
    int r = 0;
    for (int i = 1; i <= 100; i++) r += i;
    [_cond lock];
    _result = r + ([NSThread isMainThread] ? 1000 : 0);
    _done = YES;
    [_cond signal];
    [_cond unlock];
    printf("worker name %s\n", self.name.UTF8String);
  }
}
@end

int main(void) {
  @autoreleasepool {
    note("main");
    printf("Derived value %d\n", [Derived value]);
    printf("log: %s\n", g_log);
    g_log[0] = 0;
    [Lazy class]; [Lazy class];
    printf("log: %s\n", g_log);
    Worker* w = [Worker new];
    w.name = @"t05-worker";
    w.cond = [NSCondition new];
    [w start];
    [w.cond lock];
    while (!w.done) [w.cond wait];
    [w.cond unlock];
    while (!w.finished) usleep(1000);
    printf("worker result %d finished %d\n", w.result, w.finished);
  }
  return 0;
}
