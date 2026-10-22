/* Guest long-double math imports handed to the host as long double(*)(long double) callbacks. */
#include <math.h>
#include <stdio.h>
#include "ldcb.h"

static long double twice(long double x) { return 2 * x; }

int main(void) {
    printf("sqrtl(4) %.3f fabsl(-3) %.3f floorl(2.5) %.3f twice(1.5) %.3f\n", (double)ld_apply(sqrtl, 4.0L),
           (double)ld_apply(fabsl, -3.0L), (double)ld_apply(floorl, 2.5L), (double)ld_apply(twice, 1.5L));
    return 0;
}
