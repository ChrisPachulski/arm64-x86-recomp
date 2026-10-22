// Struct returns both ways (large sret, 4-double HFA, mixed float/int), messages to nil returning structs/doubles (zeroed),
// struct returns through super, and host methods returning HFAs / large structs.
#import <Foundation/Foundation.h>

typedef struct { double a, b, c, d; } Quad;            // HFA4: arm64 v0-v3, x86-64 memory (stret)
typedef struct { float a, b, c, d; } QuadF;            // HFA4 float: arm64 s0-s3, x86-64 xmm0/xmm1
typedef struct { float f; int i; } FI;                 // mixed 8 bytes
typedef struct { int i; float f; double d; } IFD;      // mixed 16 bytes
typedef struct { double d; long l; } DL;               // x86: xmm0 + rax
typedef struct { long a, b, c; } L3;                   // 24 bytes, indirect both
typedef struct { char s[40]; int n; } Big;             // 44 bytes
typedef struct { float x; double y; } FD;              // not an HFA (mixed base types)

@interface S : NSObject
- (Quad)quad:(double)k;
- (QuadF)quadf:(float)k;
- (FI)fi:(int)k;
- (IFD)ifd:(IFD)x;
- (DL)dl:(DL)x;
- (L3)l3:(long)k;
- (Big)big:(const char*)s;
- (FD)fd:(FD)x;
- (double)dbl;
- (float)flt;
- (long long)ll;
- (NSRange)rng;
@end
@implementation S
- (Quad)quad:(double)k { return (Quad){k, k * 2, k * 3, k * 4}; }
- (QuadF)quadf:(float)k { return (QuadF){k, k + 1, k + 2, k + 3}; }
- (FI)fi:(int)k { return (FI){k * 0.5f, k}; }
- (IFD)ifd:(IFD)x { return (IFD){x.i + 1, x.f * 2, x.d * 3}; }
- (DL)dl:(DL)x { return (DL){x.d + 0.25, x.l - 7}; }
- (L3)l3:(long)k { return (L3){k, -k, k * k}; }
- (Big)big:(const char*)s { Big b; memset(&b, 0, sizeof b); snprintf(b.s, sizeof b.s, "big<%s>", s); b.n = (int)strlen(s); return b; }
- (FD)fd:(FD)x { return (FD){x.x * 3, x.y / 2}; }
- (double)dbl { return 6.5; }
- (float)flt { return 1.25f; }
- (long long)ll { return -1234567890123LL; }
- (NSRange)rng { return NSMakeRange(11, 22); }
@end

@interface S2 : S @end
@implementation S2
- (Quad)quad:(double)k { Quad q = [super quad:k + 1]; q.d = -q.d; return q; }
- (L3)l3:(long)k { L3 r = [super l3:k]; r.c += 1000; return r; }
- (Big)big:(const char*)s { Big b = [super big:s]; b.s[0] = 'B'; return b; }
- (IFD)ifd:(IFD)x { IFD r = [super ifd:x]; r.i *= 10; return r; }
@end
@interface S3 : S2 @end
@implementation S3
- (Quad)quad:(double)k { Quad q = [super quad:k * 10]; q.a += 0.5; return q; }
- (Big)big:(const char*)s { Big b = [super big:s]; b.n += 100; return b; }
@end

__attribute__((noinline)) static id maybe(int k) { return k ? [S3 new] : nil; }
static volatile int zero = 0;

static void show(const char* tag, id o) {
  Quad q = [o quad:1.5]; QuadF qf = [o quadf:2]; FI fi = [o fi:7]; IFD ifd = [o ifd:(IFD){4, 1.5f, 2.25}];
  DL dl = [o dl:(DL){3.5, 100}]; L3 l3 = [o l3:9]; Big b = [o big:"xy"]; FD fd = [o fd:(FD){1.5f, 9}];
  NSRange r = [o rng];
  printf("%s quad %g %g %g %g | quadf %g %g %g %g | fi %g %d | ifd %d %g %g | dl %g %ld\n", tag, q.a, q.b, q.c, q.d,
         qf.a, qf.b, qf.c, qf.d, fi.f, fi.i, ifd.i, ifd.f, ifd.d, dl.d, dl.l);
  printf("%s l3 %ld %ld %ld | big '%s' %d | fd %g %g | dbl %g flt %g ll %lld | rng %lu %lu\n", tag, l3.a, l3.b, l3.c, b.s, b.n,
         fd.x, fd.y, [o dbl], [o flt], [o ll], (unsigned long)r.location, (unsigned long)r.length);
}

int main(void) {
  @autoreleasepool {
    show("S", [S new]);
    show("S3", maybe(1));
    show("nil", maybe(zero));
    id nilv = maybe(zero);
    NSValue* nv = nilv;
    NSRect nr = [nv rectValue]; NSRange nrg = [nv rangeValue];
    printf("nil host: rect %g %g %g %g range %lu %lu point %g\n", nr.origin.x, nr.origin.y, nr.size.width, nr.size.height,
           (unsigned long)nrg.location, (unsigned long)nrg.length, [nv pointValue].x);
    NSValue* rv = [NSValue valueWithRect:NSMakeRect(1.5, 2.5, 3.5, 4.5)];
    NSRect r = [rv rectValue];
    printf("host HFA4: %g %g %g %g\n", r.origin.x, r.origin.y, r.size.width, r.size.height);
    Quad hq = {9, 8, 7, 6};
    NSValue* qv = [NSValue valueWithBytes:&hq objCType:@encode(Quad)];
    Quad back; [qv getValue:&back size:sizeof back];
    printf("value Quad %g %g %g %g %s\n", back.a, back.b, back.c, back.d, qv.objCType);
    // host calls guest struct-returning methods through NSInvocation and KVC-free paths
    S3* s3 = [S3 new];
    NSInvocation* inv = [NSInvocation invocationWithMethodSignature:[s3 methodSignatureForSelector:@selector(quad:)]];
    inv.target = s3; inv.selector = @selector(quad:);
    double k = 2; [inv setArgument:&k atIndex:2]; [inv invoke];
    Quad iq; [inv getReturnValue:&iq];
    printf("inv quad %g %g %g %g\n", iq.a, iq.b, iq.c, iq.d);
    inv = [NSInvocation invocationWithMethodSignature:[s3 methodSignatureForSelector:@selector(big:)]];
    inv.target = s3; inv.selector = @selector(big:);
    const char* arg = "inv"; [inv setArgument:&arg atIndex:2]; [inv invoke];
    Big ib; [inv getReturnValue:&ib];
    printf("inv big '%s' %d\n", ib.s, ib.n);
    inv = [NSInvocation invocationWithMethodSignature:[s3 methodSignatureForSelector:@selector(dl:)]];
    inv.target = s3; inv.selector = @selector(dl:);
    DL din = {1.0, 5}; [inv setArgument:&din atIndex:2]; [inv invoke];
    DL dout; [inv getReturnValue:&dout];
    printf("inv dl %g %ld\n", dout.d, dout.l);
    // direct IMP call of a guest struct method obtained from the runtime
    Quad (*qimp)(id, SEL, double) = (Quad (*)(id, SEL, double))[s3 methodForSelector:@selector(quad:)];
    Quad dq = qimp(s3, @selector(quad:), 3);
    printf("imp quad %g %g %g %g\n", dq.a, dq.b, dq.c, dq.d);
    // host IMP returning an HFA, called directly
    NSRect (*rimp)(id, SEL) = (NSRect (*)(id, SEL))[rv methodForSelector:@selector(rectValue)];
    NSRect r2 = rimp(rv, @selector(rectValue));
    printf("host imp rect %g %g %g %g\n", r2.origin.x, r2.origin.y, r2.size.width, r2.size.height);
  }
  return 0;
}
