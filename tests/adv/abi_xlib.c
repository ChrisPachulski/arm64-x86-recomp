/* Guest dylib: callee side of every cross-image ABI shape in abi_x.h. */
#include "abi_x.h"

long many_int(long a, long b, long c, long d, long e, long f, long g, long h, long i, long j, long k, long l) {
    return a + 2 * b + 3 * c + 4 * d + 5 * e + 6 * f + 7 * g + 8 * h + 9 * i + 10 * j + 11 * k + 12 * l;
}
long many_small(int a, int b, int c, int d, int e, int f, int g, int h, char i, short j, char k, int l, Odd4 o) {
    return a + b + c + d + e + f + g + h + 100L * i + 1000L * j + 7L * k + 13L * l + 17L * o.c + 19L * o.s;
}
double mixed(int i1, double d1, int i2, float f1, int i3, double d2, int i4, float f2, int i5, double d3, int i6,
             float f3, int i7, double d4, int i8, float f4, int i9, double d5, int i10, float f5, float f6,
             double d6, int i11) {
    return i1 + d1 * 2 + i2 * 3 + f1 * 4 + i3 * 5 + d2 * 6 + i4 * 7 + f2 * 8 + i5 * 9 + d3 * 10 + i6 * 11 + f3 * 12 +
           i7 * 13 + d4 * 14 + i8 * 15 + f4 * 16 + i9 * 17 + d5 * 18 + i10 * 19 + f5 * 20 + f6 * 21 + d6 * 22 +
           i11 * 23;
}
S8 s8_swap(S8 s) { S8 r = {s.b, s.a}; return r; }
S12 s12_add(S12 x, S12 y) { S12 r = {x.a + y.a, x.b + y.b, x.c + y.c}; return r; }
S16 s16_mul(S16 s, int k) { S16 r = {s.a * k, s.b * k}; return r; }
S24 s24_rot(S24 s, long k) { S24 r = {s.b + k, s.c + k, s.a + k}; return r; }
HF2 hf2_add(HF2 x, HF2 y) { HF2 r = {x.x + y.x, x.y * y.y}; return r; }
HF3 hf3_cross(HF3 u, HF3 v) { HF3 r = {u.y * v.z - u.z * v.y, u.z * v.x - u.x * v.z, u.x * v.y - u.y * v.x}; return r; }
HD3 hd3_sum3(HD3 x, HD3 y, HD3 z, double k) { HD3 r = {(x.a + y.a + z.a) * k, x.b - y.b + z.b, x.c * y.c - z.c}; return r; }
Big40 big_make(double a, float b, double c, float d, double e) { Big40 r = {a, b, c, d, e * 0.5}; return r; }
double apply_hd3(HD3 (*f)(HD3, HD3, HD3, double), HD3 v) { HD3 r = f(v, v, v, 1.5); return r.a + r.b + r.c; }
