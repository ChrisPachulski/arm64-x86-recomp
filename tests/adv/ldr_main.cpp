/* Loud: a long double (or a record holding one) handed to the host by reference. LDR_CASE picks the call: 1 long double&,
   2 literal record&, 3 non-literal record&. A canary right after the value shows an x87 store through the guest pointer. */
#include <stdio.h>
#include <string.h>
#include "ldr.h"

int main() {
    struct { long double v; unsigned long canary; } s = {0.5L, 0x1122334455667788UL};
    LL ll; ll.v = 0.5L;
    LN ln; ln.v = 0.5L;
#if LDR_CASE == 1
    ld_set_ref(s.v);
#elif LDR_CASE == 2
    ld_set_ll(ll); s.v = ll.v;
#else
    ld_set_ln(ln); s.v = ln.v;
#endif
    printf("value %g canary %lx\n", (double)s.v, s.canary);
    return 0;
}
