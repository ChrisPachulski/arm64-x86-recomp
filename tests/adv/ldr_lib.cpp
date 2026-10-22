/* Host side of ldr.h. */
#include "ldr.h"

void ld_set_ref(long double& x) { x = 1.0L; }
void ld_set_ll(LL& r) { r.v = 2.0L; }
void ld_set_ln(LN& r) { r.v = 3.0L; }
