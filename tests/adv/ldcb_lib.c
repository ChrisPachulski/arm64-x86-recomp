#include "ldcb.h"
long double ld_apply(long double (*f)(long double), long double x) { return f(x); }
double ld_mem(void (*cb)(long double*)) { long double x = 3.25L; cb(&x); return (double)x; }
