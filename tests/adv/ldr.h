/* long double reached through a C++ reference: the guest's is an 8-byte double, the host's an 80-bit x87 value in a
   16-byte slot, so native code must never touch the guest object. LL is a literal record, LN a non-literal one. */
#pragma once
struct LL { long double v; };
struct LN { LN() {} long double v; };
#ifdef __cplusplus
extern "C" {
#endif
void ld_set_ref(long double& x);
void ld_set_ll(LL& r);
void ld_set_ln(LN& r);
#ifdef __cplusplus
}
#endif
