/* #12: executable linked against the dylib with an -init routine. */
#include <stdio.h>
int get(void);
int main(void) {
    printf("main %d\n", get());
    return 0;
}
