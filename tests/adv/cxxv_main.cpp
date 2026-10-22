/* Guest side of cxxv.h: every call and callback crosses gbridge.hpp with a non-trivial or non-literal HFA value. */
#include <stdio.h>
#include "cxxv.h"

static int g_nt(NT x) { return x.n * 3; }
static NT g_mk(int v) { return NT(v + 5); }
static float g_ah(AH a) { return a.a[0].x + 2 * a.a[0].y + 4 * a.a[1].x + 8 * a.a[1].y; }

int main() {
    setvbuf(stdout, NULL, _IONBF, 0);                          /* lines before a crash still show */
    NT t(7);
    printf("read_nt %d\n", cv_read_nt(t));
    printf("make_nt %d\n", cv_make_nt(11).n);
    AH a; a.a[0].x = 1; a.a[0].y = 2; a.a[1].x = 3; a.a[1].y = 7;
    printf("read_ah %g\n", cv_read_ah(a));
    AH r = cv_make_ah(0.5f);
    printf("make_ah %g %g %g %g\n", r.a[0].x, r.a[0].y, r.a[1].x, r.a[1].y);
    printf("call_nt %d\n", cv_call_nt(g_nt, 4));
    printf("call_mk %d\n", cv_call_mk(g_mk, 4));
    printf("call_ah %g\n", cv_call_ah(g_ah, 1.5f));
    return 0;
}
