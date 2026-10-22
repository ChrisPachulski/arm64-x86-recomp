/* an exception through 50 frames, each holding an RAII object whose destructor prints; then a constructor that throws
   with a partially built object (built members and bases destroyed, unbuilt ones not) */
#include <cstdio>
#include <stdexcept>

struct Guard { int id; explicit Guard(int i) : id(i) {} ~Guard() { printf("~Guard %d\n", id); } };

__attribute__((noinline)) int dive(int depth) {
    Guard g(depth);
    if (depth == 50) throw std::runtime_error("bottom");
    return dive(depth + 1) + 1;
}

struct Member { const char* n; explicit Member(const char* s) : n(s) { printf("Member %s built\n", n); }
                ~Member() { printf("Member %s destroyed\n", n); } };
struct Bomb { explicit Bomb(int x) { if (x) { printf("Bomb throwing\n"); throw 17; } } };
struct BaseObj { BaseObj() { printf("BaseObj built\n"); } ~BaseObj() { printf("BaseObj destroyed\n"); } };
struct Partial : BaseObj {
    Member a; Bomb b; Member c;
    explicit Partial(int x) : a("a"), b(x), c("c") { printf("Partial body\n"); }
    ~Partial() { printf("~Partial (must not run)\n"); }
};
struct Arr { Member m[3] = {Member("m0"), Member("m1"), Member("m2")}; Bomb b{1}; };

int main() {
    try { dive(1); } catch (std::exception& e) { printf("caught at top: %s\n", e.what()); }
    try { Partial p(1); } catch (int v) { printf("ctor threw %d\n", v); }
    try { Partial* p = new Partial(1); delete p; } catch (int v) { printf("new-expression ctor threw %d (memory freed)\n", v); }
    try { Arr a; } catch (int v) { printf("array member init threw %d\n", v); }
    { Partial ok(0); printf("built ok\n"); }
    return 0;
}
