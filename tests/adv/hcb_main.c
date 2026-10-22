/* handle -> guest callback -> handle -> guest callback -> longjmp to main's frame. The bridge must not keep pointing at
   the destroyed middle callback CPU: later callbacks (qsort, atexit after main returns) run on a valid stack. */
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include "hcb.h"

static jmp_buf jb;
static hcb_run_fn run;
static long depth;

static long inner(long x) { depth = x; longjmp(jb, 7); }
static long outer(long x) { return run(inner, x + 1) + 1000; }
static long plus1(long x) { return x + 1; }
static int cmp(const void* a, const void* b) { return *(const int*)a - *(const int*)b; }
static void bye(void) { printf("atexit: run(plus1, 41) = %ld\n", run(plus1, 41)); }

int main(void) {
    run = hcb_runner();
    atexit(bye);
    int r = setjmp(jb);
    if (!r) { run(outer, 1); printf("not reached\n"); }
    printf("longjmp back r=%d depth=%ld\n", r, depth);
    int v[64];
    for (int i = 0; i < 64; i++) v[i] = (i * 37) % 64;
    qsort(v, 64, sizeof v[0], cmp);
    printf("sorted %d %d %d, run(plus1, 1) = %ld\n", v[0], v[31], v[63], run(plus1, 1));
    if (!setjmp(jb)) run(outer, 10);
    printf("second longjmp depth=%ld\n", depth);
    return 0;
}
