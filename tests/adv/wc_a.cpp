/* Dylib A: weak pick(); its own call to pick() goes through weak coalescing. */
#include "wc.h"
extern "C" __attribute__((weak)) int pick(void) { return 1; }
Info lib_a() { counter += 1; Reg<int>::n += 10; return {&counter, &typeid(Shape), &Reg<int>::n, pick()}; }
