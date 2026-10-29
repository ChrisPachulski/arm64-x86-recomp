/* Register contract, pointer shape: a callee that reads x9 is called through a pointer, which no call site can
   tell, so gdyld must keep full register sync for the whole image. */
#include <stdio.h>
#ifdef __aarch64__
long call_ptr(long);
__asm__(".text\n.p2align 2\n"
        "_peekp:\n"
        "  add x0, x0, x9\n"
        "  ret\n"
        ".globl _call_ptr\n"
        "_call_ptr:\n"
        "  stp x29, x30, [sp, #-16]!\n"
        "  mov x29, sp\n"
        "  adrp x8, _peekp@PAGE\n"
        "  add x8, x8, _peekp@PAGEOFF\n"
        "  lsl x9, x0, #3\n"
        "  blr x8\n"
        "  ldp x29, x30, [sp], #16\n"
        "  ret\n");
#else
static long call_ptr(long a) { return a + (a << 3); }
#endif
int main(void) {
    for (long a = 1; a <= 4; a++) printf("ptr %ld -> %ld\n", a, call_ptr(a));
    return 0;
}
