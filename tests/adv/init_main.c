/* Executable linked against B then A (reverse of dependency order): ctor/dtor order across images. */
#include <stdio.h>
int b_value(void);
int a_value(void);
__attribute__((constructor)) static void m_ctor(void) { printf("main ctor b=%d\n", b_value()); }
__attribute__((destructor)) static void m_dtor(void) { printf("main dtor\n"); }
int main(void) { printf("main %d %d\n", a_value(), b_value()); return 0; }
