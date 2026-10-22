#include <cstdio>
#include "xlib.h"

static int cb_throws(int x) { if (x > 2) throw x * 10; return x; }
static void main_throws() { throw std::domain_error("from main"); }

int main() {
    for (int c = 1; c <= 3; c++) {
        try { lib_fail(c); } catch (LibError& e) { printf("main caught LibError %d: %s\n", e.code, e.what()); }
    }
    try { lib_fail(9); } catch (std::exception& e) { printf("main caught as std::exception: %s\n", e.what()); }
    printf("callback ok %d\n", lib_call_back(cb_throws, 2));
    try { lib_call_back(cb_throws, 5); } catch (int v) { printf("main caught its own throw through the lib: %d\n", v); }
    printf("lib_catch_main_error -> %d\n", lib_catch_main_error(main_throws));
    return 0;
}
