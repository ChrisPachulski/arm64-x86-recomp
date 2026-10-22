/* Empty structs across the bridge in both directions must not shift later arguments. */
#include <stdio.h>
#include "empty.h"

static long seed(long a, long b) { return a + b; }
static long back(struct Empty e, long x) { (void)e; return x * 2; }
static long back_mid(long a, struct Empty e, long b) { (void)e; return a - b; }

int main(void) {
    struct Empty e;
    long s = seed(1, 456), r = 0;
    e_ret(&r);
    printf("e_take %ld e_mid %ld e_ret %ld seed %ld\n", e_take(e, 123), e_mid(1, e, 2, e, 3.0), r, s);
    printf("e_call %ld e_call_mid %ld\n", e_call(back, 21), e_call_mid(back_mid, 50, 8));
    return 0;
}
