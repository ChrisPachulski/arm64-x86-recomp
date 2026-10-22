/* Flat-namespace fallback into the executable plus interposed rand() seen from main and from the dylib. */
#include <stdio.h>
#include <stdlib.h>
int lib_calls_main(int);
int lib_rand(void);
int provided_by_main(int x) { return x * 3; }
int main(void) {
    srand(1);
    int (*volatile rp)(void) = rand;
    printf("flat %d main_rand %d ptr_rand %d lib_rand %d\n", lib_calls_main(5), rand(), rp(), lib_rand());
    return 0;
}
