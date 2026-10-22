/* setjmp/longjmp in C: longjmp out of 3 nested frames, a second setjmp return value, longjmp(.., 0) -> 1, re-arming
   in a loop, callee-saved state restored, sigsetjmp/siglongjmp with the signal mask, _setjmp/_longjmp */
#include <setjmp.h>
#include <signal.h>
#include <stdio.h>

static jmp_buf jb;
static sigjmp_buf sjb;
static int depth_reached;

__attribute__((noinline)) static void level3(int v) { depth_reached = 3; longjmp(jb, v); }
__attribute__((noinline)) static void level2(int v) { depth_reached = 2; level3(v); printf("not reached 2\n"); }
__attribute__((noinline)) static void level1(int v) { depth_reached = 1; level2(v); printf("not reached 1\n"); }

__attribute__((noinline)) static int nested_owner(void) {
    jmp_buf inner;
    volatile int local = 10;
    int r = _setjmp(inner);
    if (r == 0) { local = 20; _longjmp(inner, 7); }
    return r * 100 + local;
}

int main(void) {
    volatile int count = 0;
    int r = setjmp(jb);
    printf("setjmp returned %d (count %d, depth %d)\n", r, count, depth_reached);
    if (count < 3) { count++; level1(count == 3 ? 0 : 40 + count); }
    long callee_saved = 0;
    for (int i = 0; i < 5; i++) {                              /* re-arm the same buffer in a loop */
        volatile int i_seen = i;
        if (setjmp(jb) == 0) level1(i + 1);
        else callee_saved += i_seen;
    }
    printf("loop sum %ld\n", callee_saved);
    printf("nested owner %d\n", nested_owner());
    sigset_t blk, cur;
    sigemptyset(&blk); sigaddset(&blk, SIGUSR1);
    if (sigsetjmp(sjb, 1) == 0) {
        sigprocmask(SIG_BLOCK, &blk, NULL);
        sigprocmask(SIG_BLOCK, NULL, &cur);
        printf("blocked before siglongjmp %d\n", sigismember(&cur, SIGUSR1));
        siglongjmp(sjb, 5);
    }
    sigprocmask(SIG_BLOCK, NULL, &cur);
    printf("after siglongjmp mask restored: blocked %d\n", sigismember(&cur, SIGUSR1));
    return 0;
}
