/* Host side of abih.h: plain C, the same source for the x86_64 host library and the arm64 link stub. */
#include "abih.h"

long h_p16(long x, P16 p, long y) { return x + 2 * p.a + 3 * p.b + 5 * y; }
long h_p16_spill(long a0, long a1, long a2, long a3, long a4, long a5, long a6, P16 p, long y) {
    return a0 + a1 + a2 + a3 + a4 + a5 + 7 * a6 + 11 * p.a + 13 * p.b + 17 * y;
}
long h_p16_stack(long a0, long a1, long a2, long a3, long a4, long a5, long a6, long a7, int z, P16 p, long y) {
    return a0 + a1 + a2 + a3 + a4 + a5 + a6 + 3 * a7 + 19 * z + 23 * p.a + 29 * p.b + 31 * y;
}
P16 h_p16_ret(long x) { P16 r = {x * 3, -x}; return r; }
double h_dpad(long x, DPad p, long y) { return x + p.a * 1.5 + y * 0.25; }
UD2 h_ud2(UD2 u, double k) { UD2 r; r.b[0] = u.b[0] * k; r.b[1] = u.b[1] - k; return r; }
UF3 h_uf3(double a0, double a1, double a2, double a3, double a4, double a5, double a6, UF3 u, char c, float z) {
    UF3 r; r.s.x = u.s.x + (float)a6 + c; r.s.y = u.f[1] * z; r.s.z = u.s.z - (float)(a0 + a1 + a2 + a3 + a4 + a5); return r;
}
SUD h_sud(SUD s, UD2 u, double k) { SUD r; r.u.b[0] = s.u.b[1] + u.b[0]; r.u.b[1] = s.d * k; r.d = s.u.b[0] - u.b[1]; return r; }
UMIX h_umix(long a, UMIX u, double d) { UMIX r; r.l = u.l + a + (long)d; return r; }
HVA2 h_hva2(HVA2 h, v4f k) { HVA2 r; r.c[0] = h.c[1] * k; r.c[1] = h.c[0] + k; return r; }
v4f h_v4(v4f a, v4f b) { return a * b - a; }
long h_call_p16(long (*f)(long, P16, long), long x) { P16 p = {x + 1, x + 2}; return f(x, p, x + 3) * 2; }
double h_call_ud2(UD2 (*f)(UD2, double), double k) { UD2 u = {.b = {k, -k}}; UD2 r = f(u, k * 2); return r.b[0] + r.b[1] * 3; }
float h_call_uf3(UF3 (*f)(double, double, double, double, double, double, double, UF3, char, float)) {
    UF3 u = {.f = {1.5f, -2.0f, 4.25f}};
    UF3 r = f(1, 2, 3, 4, 5, 6, 7, u, 'A', 0.5f);
    return r.f[0] + 10 * r.f[1] + 100 * r.f[2];
}
double h_call_sud(SUD (*f)(SUD, UD2, double)) {
    SUD s = {{.b = {1.25, 2.5}}, 3.75}; UD2 u = {.b = {-0.5, 8}};
    SUD r = f(s, u, 2.0); return r.u.b[0] + 2 * r.u.b[1] + 4 * r.d;
}
float h_call_hva2(HVA2 (*f)(HVA2, v4f)) {
    HVA2 h = {{{1, 2, 3, 4}, {5, 6, 7, 8}}}; v4f k = {0.5f, -1, 2, 0.25f};
    HVA2 r = f(h, k); return r.c[0].x + r.c[0].w + r.c[1].y * 10 + r.c[1].z * 100;
}
double h_call_dpad(double (*f)(long, DPad, long)) { DPad p = {2.5}; return f(9, p, -4) * 2; }
