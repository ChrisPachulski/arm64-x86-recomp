/* Computed goto through label tables the program patches at run time: each table sits in __DATA_CONST, which dyld
   makes read-only after fixups but whose maxprot still allows write, so mprotect reopens it. A lift that bakes the
   linked entries into its switch jumps to the old label. run_patch indexes its table; run_word's single slot is the
   word clang folds a constant index into. Patched targets: a label already in the table, and one only the patch reaches. */
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>

static int unlock(void *p, size_t n) {
    uintptr_t pg = (uintptr_t)getpagesize(), a = (uintptr_t)p & ~(pg - 1);
    return mprotect((void *)a, ((uintptr_t)p + n - a + pg - 1) & ~(pg - 1), PROT_READ | PROT_WRITE);
}

__attribute__((noinline)) int run_patch(const unsigned char *code, int patch) {
    static void *tab[4] __attribute__((section("__DATA_CONST,__const"))) = {&&op_add, &&op_dbl, &&op_sub, &&op_end};
    if (patch == 1) { if (unlock(tab, sizeof tab)) return -1000; tab[0] = &&op_dbl; }
    if (patch == 2) { if (unlock(tab, sizeof tab)) return -1000; tab[1] = &&op_neg; }
    int acc = 1, pc = 0;
    goto *tab[code[pc++] & 3];
op_add: acc += 3; goto *tab[code[pc++] & 3];
op_dbl: acc *= 2; goto *tab[code[pc++] & 3];
op_sub: acc -= 1; goto *tab[code[pc++] & 3];
op_neg: acc = -acc; goto *tab[code[pc++] & 3];
op_end: return acc;
}

__attribute__((noinline)) int run_word(int patch) {
    static void *tw[2] __attribute__((section("__DATA_CONST,__const"))) = {&&w_a, &&w_b};
    if (patch == 1) { if (unlock(tw, sizeof tw)) return -1000; tw[0] = &&w_b; }
    if (patch == 2) { if (unlock(tw, sizeof tw)) return -1000; tw[0] = &&w_c; }
    goto *tw[0];
w_a: return 10;
w_b: return 20;
w_c: return 30;
}

int main(void) {
    static const unsigned char prog[] = {0, 1, 0, 2, 1, 0, 3};          /* add dbl add sub dbl add end */
    int a = run_patch(prog, 0), b = run_patch(prog, 1), c = run_patch(prog, 2);
    int d = run_word(0), p1 = run_word(1), e = run_word(0), p2 = run_word(2), f = run_word(0);   /* a patching call jumps
                                                                       straight to its label: the next unpatched call loads the word */
    printf("patch %d %d %d word %d %d %d %d %d\n", a, b, c, d, p1, e, p2, f);
    return 0;
}
