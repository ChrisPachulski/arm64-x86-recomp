#include <cstdio>
#include "sinit.h"

Reg& registry() { static Reg r; return r; }
struct LibObj { const char* n; explicit LibObj(const char* s) : n(s) { registry().add(n); printf("lib ctor %s\n", n); }
                ~LibObj() { printf("lib dtor %s\n", n); } };
static int compute() { registry().add("compute"); return 40 + 2; }
LibObj lib_first("lib_first");
int lib_value = compute();
LibObj lib_second("lib_second");
const char* lib_order() { return registry().log.c_str(); }
