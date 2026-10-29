/* Prologue saves the stores of which stay: _reread reads x19 after restoring it from its save slot, and _peekslot
   loads its saved x19 through x29 into x0. Their callers' x19 must reach both, so neither save may be dropped
   (recompile unread_saves), while the image runs under the register contract. */
#include <stdio.h>
#ifdef __aarch64__
long call_reread(long);
long call_peek(long);
__asm__(".text\n.p2align 2\n"
        "_reread:\n"
        "  str x19, [sp, #-16]!\n"
        "  mov x19, #7\n"
        "  add x0, x0, x19\n"
        "  ldr x19, [sp], #16\n"
        "  add x0, x0, x19\n"
        "  ret\n"
        "_peekslot:\n"
        "  stp x29, x30, [sp, #-32]!\n"
        "  mov x29, sp\n"
        "  str x19, [sp, #16]\n"
        "  mov x19, #5\n"
        "  ldr x0, [x29, #16]\n"
        "  ldr x19, [sp, #16]\n"
        "  ldp x29, x30, [sp], #32\n"
        "  ret\n"
        ".globl _call_reread\n"
        "_call_reread:\n"
        "  stp x20, x19, [sp, #-32]!\n"
        "  stp x29, x30, [sp, #16]\n"
        "  add x29, sp, #16\n"
        "  add x19, x0, #1000\n"
        "  bl _reread\n"
        "  add x0, x0, x19\n"
        "  ldp x29, x30, [sp, #16]\n"
        "  ldp x20, x19, [sp], #32\n"
        "  ret\n"
        ".globl _call_peek\n"
        "_call_peek:\n"
        "  stp x20, x19, [sp, #-32]!\n"
        "  stp x29, x30, [sp, #16]\n"
        "  add x29, sp, #16\n"
        "  add x19, x0, #500\n"
        "  bl _peekslot\n"
        "  add x0, x0, x19\n"
        "  ldp x29, x30, [sp, #16]\n"
        "  ldp x20, x19, [sp], #32\n"
        "  ret\n");
#else
static long call_reread(long a) { return a + 7 + (1000 + a) + (1000 + a); }
static long call_peek(long a) { return (500 + a) + (500 + a); }
#endif
int main(void) {
    for (long a = 1; a <= 4; a++) printf("reread %ld -> %ld, peek %ld -> %ld\n", a, call_reread(a), a, call_peek(a));
    return 0;
}
