/* longjmp across frames with C++ destructors and try/catch(...) (native: neither runs), out of a catch handler (the
   handled exception stays "current"), and out of a destructor running during unwinding (the unwind is abandoned) */
#include <csetjmp>
#include <cstdio>
#include <exception>
#include <stdexcept>

static jmp_buf jb;
static int live;
struct Loud { int id; Loud(int i) : id(i) { live++; } ~Loud() { live--; printf("  ~Loud %d\n", id); } };

__attribute__((noinline)) void inner(int n) {
    Loud l(n);
    try {
        if (n == 0) longjmp(jb, 7);
        inner(n - 1);
    } catch (...) { printf("  WRONG catch(...) at %d\n", n); }
}
__attribute__((noinline)) void from_catch() {
    Loud l(50);
    try { throw std::runtime_error("handled when jumped"); }
    catch (std::exception& e) { printf("  in handler: %s\n", e.what()); longjmp(jb, 8); }
}
struct JumpOnDestroy { ~JumpOnDestroy() { printf("  JumpOnDestroy uncaught=%d\n", std::uncaught_exceptions()); longjmp(jb, 9); } };
__attribute__((noinline)) void from_cleanup() { Loud l(60); JumpOnDestroy j; throw std::logic_error("abandoned"); }

int main() {
    Loud outer(100);
    volatile int stage = 0;
    int r = setjmp(jb);
    printf("setjmp %d stage %d live %d uncaught %d current %d\n", r, stage, live, std::uncaught_exceptions(),
           std::current_exception() != nullptr);
    if (stage == 0) { stage = 1; inner(3); }
    else if (stage == 1) { stage = 2; from_catch(); }
    else if (stage == 2) { stage = 3; try { from_cleanup(); } catch (...) { printf("WRONG caught after longjmp\n"); } }
    try { throw 1; } catch (int) { printf("normal throw still works, uncaught %d\n", std::uncaught_exceptions()); }
    printf("end live %d\n", live);
    return 0;
}
