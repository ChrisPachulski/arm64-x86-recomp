/* Executable linked against A then B: every coalescable weak definition must end up at one address. */
#include <stdio.h>
#include "wc.h"
int main() {
    Info a = lib_a(), b = lib_b();
    printf("inline variable one address %d %d value %d\n", a.counter == &counter, b.counter == &counter, counter);
    printf("typeinfo equal %d %d\n", *a.ti == typeid(Shape), *b.ti == typeid(Shape));
    printf("template static one address %d %d value %d\n", a.reg == &Reg<int>::n, b.reg == &Reg<int>::n, Reg<int>::n);
    printf("pick main %d a %d b %d\n", pick(), a.pick, b.pick);
    return 0;
}
