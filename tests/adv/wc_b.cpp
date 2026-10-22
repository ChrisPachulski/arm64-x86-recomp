/* Dylib B (later in load order): the strong pick(), which must win over A's weak one. */
#include "wc.h"
extern "C" int pick(void) { return 2; }
Info lib_b() { counter += 2; Reg<int>::n += 20; return {&counter, &typeid(Shape), &Reg<int>::n, pick()}; }
