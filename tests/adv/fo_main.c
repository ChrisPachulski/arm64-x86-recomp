/* #7: executable linked against A (re-exports C), B, D (flat bind of f). */
#include <stdio.h>
int a_marker(void);
const char *d_calls_f(void);
int main(void) {
    printf("a %d flat f from %s\n", a_marker(), d_calls_f());
    return 0;
}
