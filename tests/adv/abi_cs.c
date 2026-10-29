/* Register contract, callee-saved shape: one callee reads x19 its caller set, another leaves x20 changed for its
   caller, as machine-outlined bodies do. Those call sites must store and reload every register and the second
   callee must store every register at its return, while the image keeps AAPCS64 elsewhere. */
#include <stdio.h>
#ifdef __aarch64__
long call_cs(long);
__asm__(".text\n.p2align 2\n"
        "_cs_in:\n"
        "  add x0, x0, x19\n"
        "  ret\n"
        "_cs_out:\n"
        "  lsl x20, x0, #1\n"
        "  ret\n"
        ".globl _call_cs\n"
        "_call_cs:\n"
        "  stp x20, x19, [sp, #-32]!\n"
        "  stp x29, x30, [sp, #16]\n"
        "  add x29, sp, #16\n"
        "  lsl x19, x0, #2\n"
        "  mov x0, #1\n"
        "  bl _cs_in\n"
        "  bl _cs_out\n"
        "  add x0, x20, x19\n"
        "  ldp x29, x30, [sp, #16]\n"
        "  ldp x20, x19, [sp], #32\n"
        "  ret\n");
#else
static long call_cs(long a) { return 2 * (1 + 4 * a) + 4 * a; }
#endif
int main(void) {
    for (long a = 1; a <= 4; a++) printf("cs %ld -> %ld\n", a, call_cs(a));
    return 0;
}
