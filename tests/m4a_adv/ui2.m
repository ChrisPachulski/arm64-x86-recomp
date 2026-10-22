// Guest-only program (arm64): only ever run translated, never natively. argv[1] picks a case; UI2_INIT=<case> runs the
// case from a constructor, UI2_LOAD=<case> from a guest +load (both inside gdyld's initializer phase, GDYLD_INIT_ONLY).
// bez_*: NSBezierPath, a pure-geometry AppKit class, as a benign stand-in on each route into AppKit: the guard must stop
// it like any AppKit class; if it does not, the route is a hole and the real UI cases on that route are not run.
#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#import <CoreVideo/CoreVideo.h>
#include <objc/runtime.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void run_case(const char* w) {
  printf("case %s: before\n", w); fflush(stdout);
  Class bez = objc_getClass("NSBezierPath");                           // no message: objc_getClass is not a send
  SEL bp = sel_registerName("bezierPath");
  if (!strcmp(w, "bez_msg")) printf("REACHED %p\n", (void*)[NSBezierPath bezierPath]);
  else if (!strcmp(w, "bez_alloc")) printf("REACHED %p\n", (void*)[NSBezierPath alloc]);
  else if (!strcmp(w, "bez_imp")) {                                     // the class method's IMP, called directly
    IMP imp = class_getMethodImplementation(object_getClass((id)bez), bp);
    printf("REACHED %d\n", ((id (*)(id, SEL))imp)((id)bez, bp) != nil);
  } else if (!strcmp(w, "bez_inv")) {                                   // NSInvocation (Foundation) sends it on the host side
    NSMethodSignature* sig = [NSMethodSignature signatureWithObjCTypes:"@@:"];
    NSInvocation* inv = [NSInvocation invocationWithMethodSignature:sig];
    inv.target = (id)bez; inv.selector = bp;
    [inv invoke];
    id r = nil; [inv getReturnValue:&r];
    printf("REACHED %d\n", r != nil);
  } else if (!strcmp(w, "bez_each")) {                                  // NSArray sends it to each element on the host side
    [@[(id)bez] makeObjectsPerformSelector:bp];
    printf("REACHED each\n");
  } else if (!strcmp(w, "screen")) printf("REACHED %lu\n", (unsigned long)[NSScreen screens].count);
  else if (!strcmp(w, "cursor")) { [NSCursor hide]; printf("REACHED cursor\n"); }
  else if (!strcmp(w, "cvlink")) { CVDisplayLinkRef l = NULL; printf("REACHED %d\n", CVDisplayLinkCreateWithActiveCGDisplays(&l)); }
  else if (!strcmp(w, "cgmove")) printf("REACHED %d\n", CGDisplayMoveCursorToPoint(0, CGPointMake(1, 1)));
  else printf("%s\n", [NSString stringWithFormat:@"%d-%s", 7, "foundation ok"].UTF8String);
  fflush(stdout);
}

@interface G2Load : NSObject
@end
@implementation G2Load
+ (void)load { const char* w = getenv("UI2_LOAD"); if (w) run_case(w); }
@end

__attribute__((constructor)) static void ui2_ctor(void) { const char* w = getenv("UI2_INIT"); if (w) run_case(w); }

int main(int argc, char** argv) {
  @autoreleasepool { run_case(argc > 1 ? argv[1] : "ok"); }
  return 0;
}
