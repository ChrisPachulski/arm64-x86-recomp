/* Host library taking long-double callbacks: by value (bridged as double) and through memory (refused at link). */
#pragma once
long double ld_apply(long double (*f)(long double), long double x);
double ld_mem(void (*cb)(long double*));
