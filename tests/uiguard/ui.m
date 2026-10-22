// Guest-only program (arm64): each argv[1] case calls one window-server / AppKit-UI / GPU entry point. It is only ever
// run translated, where gdyld's guard must stop it loudly before the call; it is never run natively.
#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#import <Metal/Metal.h>
#import <QuartzCore/CAMetalLayer.h>
#include <CoreGraphics/CoreGraphics.h>
#include <stdio.h>
#include <string.h>
#include <dlfcn.h>
#include <unistd.h>
#include <objc/runtime.h>

@interface GView : NSView                 // a guest subclass of an AppKit class
@end
@implementation GView
@end

static IMP saved_invoke;                  // NSInvocation's own -invoke, kept by the guest after method_setImplementation
static void guest_invoke(id self, SEL _cmd) { ((void (*)(id, SEL))saved_invoke)(self, _cmd); }

int main(int argc, char** argv) {
  @autoreleasepool {
    const char* w = argc > 1 ? argv[1] : "ok";
    printf("case %s: before\n", w); fflush(stdout);
    if (!strcmp(w, "probe_msg")) printf("REACHED %p\n", (void*)[NSColor redColor]);      // benign AppKit class: guard pre-flight
    else if (!strcmp(w, "probe_alloc")) printf("REACHED %p\n", (void*)[NSColor alloc]);  // benign, through objc_alloc
    else if (!strcmp(w, "mtl")) printf("REACHED %p\n", (void*)MTLCreateSystemDefaultDevice());
    else if (!strcmp(w, "mtlall")) printf("REACHED %p\n", (void*)MTLCopyAllDevices());
    else if (!strcmp(w, "app")) printf("REACHED %p\n", (void*)[NSApplication sharedApplication]);
    else if (!strcmp(w, "appmain")) printf("REACHED %d\n", NSApplicationMain(argc, (const char**)argv));
    else if (!strcmp(w, "win")) printf("REACHED %p\n", (void*)[NSWindow alloc]);
    else if (!strcmp(w, "gview")) printf("REACHED %p\n", (void*)[[GView alloc] init]);
    else if (!strcmp(w, "layer")) printf("REACHED %p\n", (void*)[CAMetalLayer layer]);
    else if (!strcmp(w, "cg")) printf("REACHED %u\n", CGMainDisplayID());
    else if (!strcmp(w, "cfalert")) {                                   // an assert reporter: a window-server modal alert
      CFOptionFlags r = 0;
      printf("REACHED %d\n", (int)CFUserNotificationDisplayAlert(0, 0, NULL, NULL, NULL, CFSTR("t"), CFSTR("m"), NULL, NULL, NULL, &r));
    }
    // host-side routes the guest starts into AppKit; every target is benign (NSColor, NSBitsPerPixelFromDepth) if the guard failed
    else if (!strncmp(w, "r_", 2)) {
      Class col = objc_getClass("NSColor");                          // no message to the class: the route is what is tested
      SEL red = sel_registerName("redColor");
      void* f = dlsym(RTLD_DEFAULT, "NSBitsPerPixelFromDepth");
      if (!strcmp(w, "r_imp")) printf("REACHED %p\n", (void*)((id (*)(id, SEL))class_getMethodImplementation(object_getClass(col), red))(col, red));
      else if (!strcmp(w, "r_method_imp")) printf("REACHED %p\n", (void*)((id (*)(id, SEL))method_getImplementation(class_getClassMethod(col, red)))(col, red));
      else if (!strcmp(w, "r_invoke") || !strcmp(w, "r_invoke_target")) {
        NSInvocation* inv = [NSInvocation invocationWithMethodSignature:[NSMethodSignature signatureWithObjCTypes:"@@:"]];
        inv.selector = red;
        if (!strcmp(w, "r_invoke")) { inv.target = col; [inv invoke]; } else [inv invokeWithTarget:col];
        printf("REACHED invocation\n");
      }
      else if (!strcmp(w, "r_perform_all")) { [@[col] makeObjectsPerformSelector:red]; printf("REACHED perform\n"); }
      else if (!strcmp(w, "r_nstimer")) { [NSTimer scheduledTimerWithTimeInterval:0.01 target:col selector:red userInfo:nil repeats:NO];
                                          CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.2, false); printf("REACHED timer\n"); }
      else if (!strcmp(w, "r_thread")) { [NSThread detachNewThreadSelector:red toTarget:col withObject:nil]; sleep(1); printf("REACHED thread\n"); }
      else if (!strcmp(w, "r_observer")) { [[NSNotificationCenter defaultCenter] addObserver:col selector:red name:@"gdyld" object:nil];
                                           [[NSNotificationCenter defaultCenter] postNotificationName:@"gdyld" object:nil]; printf("REACHED observer\n"); }
      else if (!strcmp(w, "r_dlsym")) printf("REACHED %ld\n", ((long (*)(int))f)(0));
      else if (!strcmp(w, "r_dispatch")) { dispatch_async_f(dispatch_get_main_queue(), NULL, (dispatch_function_t)f);
                                           CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.2, false); printf("REACHED dispatch\n"); }
      else if (!strcmp(w, "r_cftimer") || !strcmp(w, "r_cftimer_import")) {   // a host AppKit function as a run loop timer callback
        CFRunLoopTimerCallBack cb = !strcmp(w, "r_cftimer") ? (CFRunLoopTimerCallBack)f : (CFRunLoopTimerCallBack)NSBitsPerPixelFromDepth;
        CFRunLoopTimerRef t = CFRunLoopTimerCreate(NULL, CFAbsoluteTimeGetCurrent(), 0, 0, 0, cb, NULL);
        CFRunLoopAddTimer(CFRunLoopGetCurrent(), t, kCFRunLoopDefaultMode);
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.2, false);
        printf("REACHED cftimer\n");
      }
      else if (!strncmp(w, "r_inv_", 6)) {                             // an invocation of [NSColor redColor] reached host-side
        NSInvocation* inv = [NSInvocation invocationWithMethodSignature:[NSMethodSignature signatureWithObjCTypes:"@@:"]];
        inv.selector = red; inv.target = col;
        if (!strcmp(w, "r_inv_saved")) {                                // the saved original IMP, called by the guest's replacement
          saved_invoke = method_setImplementation(class_getInstanceMethod([NSInvocation class], @selector(invoke)), (IMP)guest_invoke);
          [inv invoke];
        }
        else if (!strcmp(w, "r_inv_perform")) [inv performSelector:@selector(invoke)];
        else if (!strcmp(w, "r_inv_perform_all")) [@[inv] makeObjectsPerformSelector:@selector(invoke)];
        else if (!strcmp(w, "r_inv_timer")) { [NSTimer scheduledTimerWithTimeInterval:0.01 target:inv selector:@selector(invoke) userInfo:nil repeats:NO];
                                               CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.2, false); }
        printf("REACHED invocation route\n");
      }
    }
    else printf("%s\n", [NSString stringWithFormat:@"%d-%s", 7, "foundation ok"].UTF8String);
  }
  return 0;
}
