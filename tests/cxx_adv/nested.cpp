/* std::nested_exception: throw_with_nested chains, rethrow_if_nested, nested_ptr, non-class payloads */
#include <cstdio>
#include <exception>
#include <stdexcept>
#include <string>

static void print_chain(const std::exception& e, int level) {
    printf("%*s%s\n", level * 2, "", e.what());
    try { std::rethrow_if_nested(e); }
    catch (const std::exception& in) { print_chain(in, level + 1); }
    catch (int v) { printf("%*sint %d\n", (level + 1) * 2, "", v); }
    catch (...) { printf("%*sunknown\n", (level + 1) * 2, ""); }
}
__attribute__((noinline)) void open_file(int k) {
    if (k == 0) throw std::runtime_error("disk read failed");
    throw k;
}
__attribute__((noinline)) void load(int k) {
    try { open_file(k); } catch (...) { std::throw_with_nested(std::runtime_error("load failed #" + std::to_string(k))); }
}
__attribute__((noinline)) void start(int k) {
    try { load(k); } catch (...) { std::throw_with_nested(std::logic_error("start failed")); }
}
struct Final final { int v; };

int main() {
    for (int k = 0; k < 2; k++) {
        try { start(k); } catch (const std::exception& e) { print_chain(e, 0); }
    }
    try { std::throw_with_nested(17); } catch (int v) { printf("throw_with_nested(int) -> plain int %d\n", v); }
    try {
        try { throw Final{3}; } catch (...) { std::throw_with_nested(Final{4}); }
    } catch (Final& f) {
        printf("final type not wrapped: v=%d\n", f.v);
    }
    try {
        try { throw std::out_of_range("leaf"); } catch (...) { std::throw_with_nested(std::runtime_error("wrap")); }
    } catch (std::nested_exception& n) {
        std::exception_ptr p = n.nested_ptr();
        printf("nested_ptr non-null %d\n", p != nullptr);
        try { n.rethrow_nested(); } catch (std::out_of_range& e) { printf("rethrow_nested -> %s\n", e.what()); }
        try { std::rethrow_exception(p); } catch (std::exception& e) { printf("rethrow_exception(nested_ptr) -> %s\n", e.what()); }
    }
    std::nested_exception empty;
    printf("empty nested_ptr null %d\n", empty.nested_ptr() == nullptr);
    return 0;
}
