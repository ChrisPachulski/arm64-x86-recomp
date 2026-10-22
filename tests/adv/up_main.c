/* #11: executable linked against A only. */
#include <stdio.h>
int a_calls_b(void);
__attribute__((constructor)) static void m_ctor(void) { printf("main ctor\n"); }
int main(void) {
    printf("main %d\n", a_calls_b());
    return 0;
}
