/* Host side of cxxv.h: the same source for the x86_64 host library and the arm64 link stub. */
#include "cxxv.h"

int cv_read_nt(NT x) { return x.n; }
NT cv_make_nt(int v) { return NT(v * 2); }
float cv_read_ah(AH a) { return a.a[1].y * 10 + a.a[0].x; }
AH cv_make_ah(float b) { AH r; r.a[0].x = b; r.a[0].y = b * 2; r.a[1].x = b * 3; r.a[1].y = b * 4; return r; }
int cv_call_nt(int (*f)(NT), int v) { return f(NT(v)) + 100; }
int cv_call_mk(NT (*f)(int), int v) { return f(v).n + 1000; }
float cv_call_ah(float (*f)(AH), float b) { return f(cv_make_ah(b)); }
