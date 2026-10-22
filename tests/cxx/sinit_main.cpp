#include <cstdio>
#include "sinit.h"

struct MainObj { const char* n; int seen; explicit MainObj(const char* s) : n(s), seen(lib_value) {
                     registry().add(n); printf("main ctor %s sees lib_value %d\n", n, seen); }
                 ~MainObj() { printf("main dtor %s\n", n); } };
MainObj main_first("main_first");
int main_value = lib_value * 2;
MainObj main_second("main_second");

static MainObj& lazy() { static MainObj m("lazy"); return m; }

int main() {
    printf("main starts: main_value %d\n", main_value);
    lazy(); lazy();
    printf("registry: %s\n", lib_order());
    return 0;
}
