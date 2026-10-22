/* Dylib B (depends on A): its ctor calls into A, so A must already be initialized. */
#include <stdio.h>
int a_value(void);
int b_seen;
__attribute__((constructor)) static void b_ctor(void) { b_seen = a_value(); printf("B ctor sees A=%d\n", b_seen); }
__attribute__((destructor)) static void b_dtor(void) { printf("B dtor\n"); }
int b_value(void) { return b_seen * 2; }
