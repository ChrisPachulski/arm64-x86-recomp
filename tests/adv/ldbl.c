/* #1 long double: on Apple arm64 long double is double, so modfl/frexpl/remquol/... are the double functions. A
   canary right after modfl's output proves the host does not store an 80-bit x87 value into 8 bytes of guest memory.
   Built -fno-builtin so every call is a real import. */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int main(void) {
    volatile long double a = 3.25L, b = 48.0L, c = 29.0L, d = 3.0L;
    struct { long double v; int canary; } s = {0, 0x5a5a};
    long double fr = modfl(a, &s.v);
    printf("modfl %a %a canary %x\n", (double)fr, (double)s.v, s.canary);
    int e = 0, q = 0;
    long double m = frexpl(b, &e);
    long double rq = remquol(c, d, &q);
    printf("frexpl %a %d remquol %a %d\n", (double)m, e, (double)rq, q & 7);   /* C guarantees only the low 3 bits */
    printf("ldexpl %a sqrtl %a powl %a fabsl %a floorl %a\n", (double)ldexpl(d, -4), (double)sqrtl(2.25L * a / a),
           (double)powl(2.0L, 10.0L + a - a), (double)fabsl(-a), (double)floorl(-a));
    printf("nanl %d strtold %a hypotl %a\n", isnan((double)nanl("")), (double)strtold("0.375", NULL), (double)hypotl(d, 4.0L));
    return 0;
}
