/* #1 loud: gdyld must refuse to link a guest that hands a long double* to a host function. */
#include <stdio.h>
#include "ldp.h"
int main(void) {
    long double x = 1.5L;
    h_ldp(&x);
    printf("%a\n", (double)x);
    return 0;
}
