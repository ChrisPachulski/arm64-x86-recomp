// A struct of guest callbacks returning CGFloat (CTRunDelegateCallbacks), called by CoreText during headless line layout.
#import <Foundation/Foundation.h>
#include <CoreText/CoreText.h>
#include <stdio.h>

static int deallocs;
static void d_dealloc(void* ref) { deallocs++; }
static CGFloat d_ascent(void* ref) { return *(CGFloat*)ref * 2; }
static CGFloat d_descent(void* ref) { return *(CGFloat*)ref / 4; }
static CGFloat d_width(void* ref) { return *(CGFloat*)ref * 3 + 0.5; }

int main(void) {
  @autoreleasepool {
    setvbuf(stdout, NULL, _IOLBF, 0);
    static CGFloat base = 10.25;
    CTRunDelegateCallbacks cb = {kCTRunDelegateVersion1, d_dealloc, d_ascent, d_descent, d_width};
    CTRunDelegateRef d = CTRunDelegateCreate(&cb, &base);
    printf("refcon round trip %d\n", CTRunDelegateGetRefCon(d) == &base);
    NSMutableAttributedString* s = [[NSMutableAttributedString alloc] initWithString:@"￼"];
    [s addAttribute:(id)kCTRunDelegateAttributeName value:(__bridge id)d range:NSMakeRange(0, 1)];
    CTLineRef line = CTLineCreateWithAttributedString((__bridge CFAttributedStringRef)s);
    CGFloat asc = 0, desc = 0, lead = 0;
    double w = CTLineGetTypographicBounds(line, &asc, &desc, &lead);
    printf("line: width %.4f ascent %.4f descent %.4f\n", w, asc, desc);
    CFRelease(line); s = nil; CFRelease(d);
  }
  printf("deallocs %d\n", deallocs);
  return 0;
}
