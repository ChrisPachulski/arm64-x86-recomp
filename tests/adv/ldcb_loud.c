/* LIMIT: a host function handing a guest callback a long double* (80-bit x87 on the host, 64-bit on the guest) has no
   faithful bridge; gdyld must refuse to link it. */
#include <stdio.h>
#include "ldcb.h"

static void show(long double* p) { printf("guest sees %.3f\n", (double)*p); *p += 1; }

int main(void) {
    printf("ld_mem -> %.3f\n", ld_mem(show));
    return 0;
}
