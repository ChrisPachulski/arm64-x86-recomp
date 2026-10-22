/* LIMIT: makecontext/swapcontext (fibers) are a loud trap in the translated world (a later milestone) */
#define _XOPEN_SOURCE 600
#include <stdio.h>
#include <ucontext.h>

static ucontext_t main_ctx, fib_ctx;
static char stack[64 * 1024];
static void fiber(void) { printf("in fiber\n"); swapcontext(&fib_ctx, &main_ctx); }

int main(void) {
    printf("before getcontext\n");
    fflush(stdout);
    getcontext(&fib_ctx);
    fib_ctx.uc_stack.ss_sp = stack; fib_ctx.uc_stack.ss_size = sizeof stack; fib_ctx.uc_link = &main_ctx;
    makecontext(&fib_ctx, fiber, 0);
    swapcontext(&main_ctx, &fib_ctx);
    printf("back in main\n");
    return 0;
}
