/* Register contract, return shape: a callee hands back a value in x9 and the caller reads it after the call. The
   image keeps AAPCS64, but that call site must reload every register and that callee must write them all back. */
#include <stdio.h>
#ifdef __aarch64__
long call_ret9(long);
__asm__(".text\n.p2align 2\n"
        "_ret9:\n"
        "  lsl x9, x0, #2\n"
        "  mov x0, #1\n"
        "  ret\n"
        ".globl _call_ret9\n"
        "_call_ret9:\n"
        "  stp x29, x30, [sp, #-16]!\n"
        "  mov x29, sp\n"
        "  bl _ret9\n"
        "  add x0, x0, x9\n"
        "  ldp x29, x30, [sp], #16\n"
        "  ret\n");
#else
static long call_ret9(long a) { return 1 + (a << 2); }
#endif
int main(void) {
    for (long a = 1; a <= 4; a++) printf("late %ld -> %ld\n", a, call_ret9(a));
    return 0;
}
