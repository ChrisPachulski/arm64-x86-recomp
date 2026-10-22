/* an uncaught exception: the unwinder reaches the end of the guest stack, libc++abi prints its message and aborts */
#include <cstdio>
#include <stdexcept>

struct Note { ~Note() { printf("destructor must not run (no handler: phase 1 fails before cleanup)\n"); } };
__attribute__((noinline)) void boom() { Note n; throw std::runtime_error("nobody catches this"); }

int main() {
    printf("before\n");
    fflush(stdout);
    boom();
    printf("after\n");
    return 0;
}
