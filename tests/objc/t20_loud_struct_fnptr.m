// LOUD: guest functions in the code-pointer fields of a struct handed by pointer to a native method that calls them
// (_CFStreamDelegate copies its context and calls retain/release). Native code would jump into guest memory: the bridge
// must stop with a diagnostic instead.
#import <Foundation/Foundation.h>
#import <objc/message.h>
struct Ctx { long version; void* info; const void* (*retain)(const void*); void (*release)(const void*); CFStringRef (*desc)(const void*); };
static const void* myRetain(const void* p) { printf("retain called\n"); return p; }
static void myRelease(const void* p) { printf("release called\n"); }
int main(void) {
  @autoreleasepool {
    struct Ctx ctx = {0, (void*)1, myRetain, myRelease, NULL};
    id d = ((id (*)(id, SEL, unsigned long, void*, void*))objc_msgSend)([NSClassFromString(@"_CFStreamDelegate") alloc],
           sel_registerName("initWithStreamEvents:callback:context:"), 0, NULL, &ctx);
    printf("delegate %s\n", d ? "made" : "nil");
  }
  printf("done\n");
  return 0;
}
