/* Register contract, entry shape: a callee reads x9, a scratch register its caller set, as machine-outlined code
   does. The call site must store every register (gdyld GDA_X_) while the image keeps AAPCS64 elsewhere. */
#include <stdio.h>
#ifdef __aarch64__
long call_peek(long);
__asm__(".text\n.p2align 2\n"
        "_peek9:\n"
        "  add x0, x0, x9\n"
        "  ret\n"
        ".globl _call_peek\n"
        "_call_peek:\n"
        "  stp x29, x30, [sp, #-16]!\n"
        "  mov x29, sp\n"
        "  lsl x9, x0, #3\n"
        "  bl _peek9\n"
        "  ldp x29, x30, [sp], #16\n"
        "  ret\n");
#else
static long call_peek(long a) { return a + (a << 3); }
#endif
int main(void) {
    for (long a = 1; a <= 4; a++) printf("peek %ld -> %ld\n", a, call_peek(a));
    return 0;
}
