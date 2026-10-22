/* variable-length arrays and alloca in frames with landing pads: the catching frame lowered its SP after entry, the
   callee that throws has its own VLA and a handler for another type, buffers must be intact after the catch */
#include <alloca.h>
#include <csetjmp>
#include <cstdio>
#include <cstring>
#include <stdexcept>

static int dtors;
struct D { ~D() { dtors++; } };

__attribute__((noinline)) void thrower(int n, int depth) {
    volatile char pad[n * 8 + 1];
    pad[0] = 1;
    D d;
    try {
        if (depth == 0) throw std::runtime_error("vla throw");
        thrower(n + 3, depth - 1);
    } catch (std::logic_error&) { printf("WRONG\n"); }
    pad[n * 8] = 2;
}
__attribute__((noinline)) long catcher(int n, int depth) {
    int buf[n];
    for (int i = 0; i < n; i++) buf[i] = i * 3 + 1;
    char* extra = (char*)alloca(n * 16 + 7);
    memset(extra, 0x5A, n * 16 + 7);
    D d;
    long sum = 0;
    try { thrower(n, depth); }
    catch (std::runtime_error& e) {
        for (int i = 0; i < n; i++) sum += buf[i];
        for (int i = 0; i < n * 16 + 7; i++) sum += extra[i] == 0x5A ? 0 : 1000000;
    }
    return sum;
}
__attribute__((noinline)) long loop_alloca(int rounds) {
    long total = 0;
    for (int r = 0; r < rounds; r++) {
        int* p = (int*)alloca(sizeof(int) * (r + 1));
        p[r] = r;
        try { if (r % 2) throw r; total += p[r]; }
        catch (int v) { total += v * 100 + p[r]; }
    }
    return total;
}
static jmp_buf jb;
__attribute__((noinline)) void jumper(int n) { volatile int v[n]; v[0] = n; longjmp(jb, v[0]); }
__attribute__((noinline)) int vla_after_setjmp(int n) {
    int r = setjmp(jb);
    if (r) return r;
    volatile int big[n];
    big[n - 1] = 1;
    jumper(n + big[n - 1]);
    return -1;
}

int main() {
    for (int n = 1; n <= 257; n += 64)
        for (int depth = 0; depth < 4; depth++) printf("n %d depth %d sum %ld\n", n, depth, catcher(n, depth));
    printf("loop alloca %ld\n", loop_alloca(20));
    printf("vla after setjmp %d\n", vla_after_setjmp(1000));
    printf("dtors %d\n", dtors);
    return 0;
}
