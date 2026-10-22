/* a throw out of a noexcept function calls std::terminate, which runs the handler installed with std::set_terminate */
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <stdexcept>

[[noreturn]] void handler() {
    std::exception_ptr p = std::current_exception();
    try { if (p) std::rethrow_exception(p); printf("terminate without exception\n"); }
    catch (std::exception& e) { printf("terminate handler: active exception %s\n", e.what()); }
    fflush(stdout);
    std::exit(3);
}

__attribute__((noinline)) void deep_throw(int x) { if (x > 0) throw std::runtime_error("escaped noexcept"); }
void guarded(int x) noexcept { deep_throw(x); printf("not reached\n"); }

int main() {
    std::terminate_handler old = std::set_terminate(handler);
    printf("previous handler set: %d\n", old != nullptr);
    printf("current handler is ours: %d\n", std::get_terminate() == handler);
    try { deep_throw(1); } catch (std::exception& e) { printf("normal catch first: %s\n", e.what()); }
    guarded(1);
    printf("not reached either\n");
    return 0;
}
