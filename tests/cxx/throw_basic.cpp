/* throw/catch by exact type, by base class, catch(...), rethrow, nested try */
#include <cstdio>
#include <stdexcept>
#include <string>

struct Base { int code; explicit Base(int c) : code(c) {} virtual ~Base() {} };
struct Derived : Base { const char* tag; Derived(int c, const char* t) : Base(c), tag(t) {} };
struct Plain { int v; };

__attribute__((noinline)) void thrower(int kind) {
    switch (kind) {
    case 0: throw 42;
    case 1: throw Derived(7, "derived");
    case 2: throw std::out_of_range("range!");
    case 3: throw Plain{99};
    case 4: throw std::string("a string");
    default: break;
    }
}

int main() {
    try { thrower(0); } catch (int v) { printf("exact int %d\n", v); }
    try { thrower(1); } catch (Derived& d) { printf("exact Derived %d %s\n", d.code, d.tag); }
    try { thrower(1); } catch (Base& b) { printf("base Base %d\n", b.code); }
    try { thrower(2); } catch (std::logic_error& e) { printf("base logic_error %s\n", e.what()); }
    try { thrower(2); } catch (std::exception& e) { printf("base exception %s\n", e.what()); }
    try { thrower(3); } catch (...) { printf("catch-all\n"); }
    try { thrower(4); } catch (const std::string& s) { printf("const ref string %s\n", s.c_str()); }
    try { thrower(3); } catch (int) { printf("WRONG\n"); } catch (Plain p) { printf("second handler Plain %d\n", p.v); }
    try {
        try { thrower(1); } catch (Base& b) { printf("inner caught %d, rethrowing\n", b.code); b.code = 8; throw; }
    } catch (Derived& d) { printf("outer got rethrown Derived %d %s\n", d.code, d.tag); }
    try {
        try {
            try { thrower(0); } catch (int v) { printf("level3 %d\n", v); throw std::runtime_error("from level3"); }
        } catch (std::runtime_error& e) { printf("level2 %s\n", e.what()); throw 3.5; }
    } catch (double d) { printf("level1 %.2f\n", d); }
    int n = 0;
    for (int i = 0; i < 1000; i++) { try { thrower(i % 5); } catch (...) { n++; } }
    printf("1000 throws caught %d\n", n);
    try { thrower(9); printf("no throw path\n"); } catch (...) { printf("WRONG\n"); }
    return 0;
}
