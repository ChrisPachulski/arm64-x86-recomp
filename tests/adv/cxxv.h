/* C++ value shapes across the bridge (host library cxxv_lib.cpp, served to the guest by gdyld host_extra).
   NT: non-trivial for calls (user copy ctor, defaulted move): both ABIs pass and return it indirectly.
   AH: an array of non-literal records that is still an HFA (4 floats): s0-s3 on arm64, xmm on x86-64. */
#pragma once
struct NT { int n; NT(int v) : n(v) {} NT(const NT& o) : n(o.n) {} NT(NT&&) = default; };
struct H { H() {} float x, y; };
struct AH { H a[2]; };
#ifdef __cplusplus
extern "C" {
#endif
int cv_read_nt(NT x);
NT cv_make_nt(int v);
float cv_read_ah(AH a);
AH cv_make_ah(float b);
int cv_call_nt(int (*f)(NT), int v);
int cv_call_mk(NT (*f)(int), int v);
float cv_call_ah(float (*f)(AH), float b);
#ifdef __cplusplus
}
#endif
