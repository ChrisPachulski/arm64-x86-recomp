#include <cstdio>
#include "xlib.h"

struct LibGuard { const char* n; explicit LibGuard(const char* s) : n(s) {} ~LibGuard() { printf("lib unwinds %s\n", n); } };

__attribute__((noinline)) static void fail_inner(int code) {
    LibGuard g("fail_inner");
    throw LibError("lib error " + std::to_string(code), code);
}
void lib_fail(int code) { LibGuard g("lib_fail"); fail_inner(code); }

int lib_call_back(int (*cb)(int), int x) {
    LibGuard g("lib_call_back");
    return cb(x) + 1;
}

int lib_catch_main_error(void (*cb)()) {
    try { cb(); }
    catch (std::logic_error& e) { printf("lib caught main's logic_error: %s\n", e.what()); return 1; }
    catch (...) { printf("lib caught something else\n"); return 2; }
    return 0;
}
