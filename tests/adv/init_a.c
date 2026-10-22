/* Dylib A (no deps): constructor must run before B's and main's; exports a value B reads in its ctor. */
#include <stdio.h>
int a_ready;
__attribute__((constructor(101))) static void a_ctor_early(void) { printf("A ctor 101\n"); }
__attribute__((constructor)) static void a_ctor(void) { a_ready = 41; printf("A ctor\n"); }
__attribute__((destructor)) static void a_dtor(void) { printf("A dtor\n"); }
int a_value(void) { return a_ready + 1; }
