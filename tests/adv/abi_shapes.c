/* Guest side of abih.h (#4, #5): guest -> host calls with 16-byte-aligned aggregates (odd x register start, stack
   alignment), padded vs homogeneous unions and structs, short vectors and HVAs, and host -> guest closures with the
   same shapes. Results print in %a so any lane or register mix-up shows. */
#include <stdio.h>
#include "abih.h"

static long g_p16(long x, P16 p, long y) { return x * 100 + p.a * 10 + p.b - y; }
static UD2 g_ud2(UD2 u, double k) { UD2 r; r.b[0] = u.b[0] + k; r.b[1] = u.b[1] * k; return r; }
static UF3 g_uf3(double a0, double a1, double a2, double a3, double a4, double a5, double a6, UF3 u, char c, float z) {
    UF3 r; r.s.x = u.s.x * z; r.s.y = u.f[1] + (float)a6 - (float)a0; r.s.z = u.s.z + c / 64.0f + (float)(a1 + a5); return r;
}
static SUD g_sud(SUD s, UD2 u, double k) { SUD r; r.u.b[0] = s.d + k; r.u.b[1] = u.b[1] - s.u.b[0]; r.d = u.b[0] * s.u.b[1]; return r; }
static HVA2 g_hva2(HVA2 h, v4f k) { HVA2 r; r.c[0] = h.c[0] - k; r.c[1] = h.c[1] * k; return r; }
static double g_dpad(long x, DPad p, long y) { return x * p.a - y; }

int main(void) {
    P16 p = {7, -9};
    printf("p16 %ld spill %ld stack %ld\n", h_p16(1, p, 2), h_p16_spill(1, 2, 3, 4, 5, 6, 7, p, 8),
           h_p16_stack(1, 2, 3, 4, 5, 6, 7, 8, -5, p, 9));
    P16 r = h_p16_ret(-4);
    DPad d = {0.75};
    printf("p16ret %ld %ld dpad %a\n", r.a, r.b, h_dpad(3, d, -8));
    UD2 u = {.b = {1.5, -0.25}};
    UD2 ur = h_ud2(u, 3.0);
    UF3 f = {.f = {2.0f, 0.5f, -1.0f}};
    UF3 fr = h_uf3(0.5, 1, 2, 3, 4, 5, 6.5, f, 'x', 3.0f);
    printf("ud2 %a %a uf3 %a %a %a\n", ur.b[0], ur.b[1], fr.f[0], fr.f[1], fr.f[2]);
    SUD s = {{.b = {0.5, 1.5}}, -2.0};
    SUD sr = h_sud(s, u, 0.125);
    UMIX m = {.l = 40};
    printf("sud %a %a %a umix %ld\n", sr.u.b[0], sr.u.b[1], sr.d, h_umix(2, m, 3.9).l);
    HVA2 h = {{{1, -1, 2, -2}, {0.5f, 0.25f, 8, 16}}};
    HVA2 hr = h_hva2(h, (v4f){2, 3, 4, 5});
    v4f v = h_v4((v4f){1, 2, 3, 4}, (v4f){-1, 0.5f, 2, 10});
    printf("hva2 %a %a %a %a | %a %a %a %a v4 %a %a %a %a\n", hr.c[0].x, hr.c[0].y, hr.c[0].z, hr.c[0].w,
           hr.c[1].x, hr.c[1].y, hr.c[1].z, hr.c[1].w, v.x, v.y, v.z, v.w);
    printf("closures p16 %ld ud2 %a uf3 %a sud %a hva2 %a dpad %a\n", h_call_p16(g_p16, 5), h_call_ud2(g_ud2, 1.25),
           h_call_uf3(g_uf3), h_call_sud(g_sud), h_call_hva2(g_hva2), h_call_dpad(g_dpad));
    return 0;
}
