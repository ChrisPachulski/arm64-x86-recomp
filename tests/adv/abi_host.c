/* Guest -> host marshalling: struct/HFA by value, >16-byte returns, float vs double, 11-arg call with
   Apple-packed stack args (bool at sp+8, int at sp+12), all into real system libraries. */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <CoreGraphics/CoreGraphics.h>

static void pr(const char *tag, CGRect r) { printf("%s %a %a %a %a\n", tag, r.origin.x, r.origin.y, r.size.width, r.size.height); }

int main(void) {
    div_t d = div(-17, 5);                                  /* 8-byte struct return */
    ldiv_t l = ldiv(-170000000000L, 7);                     /* 16-byte struct return */
    lldiv_t q = lldiv(1234567890123LL, -97);
    printf("div %d %d ldiv %ld %ld lldiv %lld %lld\n", d.quot, d.rem, l.quot, l.rem, q.quot, q.rem);
    volatile float a = 1.5f, b = 2.25f, c = -0.125f;
    int e = 0, qq = 0; float ip = 0;
    printf("fmaf %a ldexpf %a sqrtf %a\n", fmaf(a, b, c), ldexpf(3.0f, -4), sqrtf(a));
    float m = frexpf(48.0f, &e);
    float rq = remquof(29.0f, 3.0f, &qq);
    float fp = modff(-3.75f, &ip);
    printf("frexpf %a %d remquof %a %d modff %a %a hypot %a\n", m, e, rq, qq, fp, ip, hypot(3.0, (double)b));
    CGRect r1 = CGRectMake(1, 2, 3, 4), r2 = CGRectMake(-5, 0.5, 2, 10);
    pr("union", CGRectUnion(r1, r2));                       /* 32-byte HFA in d0-d3 on arm64, sret on x86-64 */
    pr("inset", CGRectInset(r1, 0.25, -1.5));               /* HFA + 2 doubles: d0-d3, d4, d5 */
    pr("isect", CGRectIntersection(r1, CGRectOffset(r2, 6.5, 1)));
    CGRect sl, rem;
    CGRectDivide(r1, &sl, &rem, 1.25, CGRectMinYEdge);      /* HFA + 2 ptrs + double + enum */
    pr("slice", sl); pr("rem", rem);
    CGAffineTransform t = CGAffineTransformMake(1, 2, 3, 4, 5, 6); /* 48-byte non-HFA: sret via x8 */
    CGAffineTransform t2 = CGAffineTransformConcat(t, CGAffineTransformMakeRotation(0.5));
    printf("concat %a %a %a %a %a %a\n", t2.a, t2.b, t2.c, t2.d, t2.tx, t2.ty);
    CGPoint p = CGPointApplyAffineTransform(CGPointMake(7, -3), t2); /* 16-byte HFA ret, 48-byte indirect arg */
    CGSize s = CGSizeApplyAffineTransform(CGSizeMake(2, 5), CGAffineTransformInvert(t));
    printf("point %a %a size %a %a contains %d eq %d\n", p.x, p.y, s.width, s.height,
           CGRectContainsPoint(r1, CGPointMake(2, 3)), CGAffineTransformEqualToTransform(t, t));
    static unsigned char px[64];
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceGray();
    CGDataProviderRef dp = CGDataProviderCreateWithData(NULL, px, sizeof px, NULL);
    CGImageRef img = CGImageCreate(8, 4, 8, 8, 16, cs, kCGImageAlphaNone, dp, NULL, true,
                                   kCGRenderingIntentPerceptual); /* args 9-11 on the stack, Apple-packed */
    printf("img %d w %zu h %zu bpr %zu bpp %zu interp %d intent %d\n", img != NULL,
           img ? CGImageGetWidth(img) : 0, img ? CGImageGetHeight(img) : 0, img ? CGImageGetBytesPerRow(img) : 0,
           img ? CGImageGetBitsPerPixel(img) : 0, img ? CGImageGetShouldInterpolate(img) : -1,
           img ? (int)CGImageGetRenderingIntent(img) : -1);
    CGImageRelease(img); CGDataProviderRelease(dp); CGColorSpaceRelease(cs);
    return 0;
}
