/* longjmp out of a guest comparator that HOST qsort is running (crosses libc frames), then qsort again normally */
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>

static jmp_buf jb;
static int calls;
static int cmp(const void* a, const void* b) {
    int x = *(const int*)a, y = *(const int*)b;
    if (++calls == 5) longjmp(jb, 33);
    return (x > y) - (x < y);
}
static int plain(const void* a, const void* b) { int x = *(const int*)a, y = *(const int*)b; return (x > y) - (x < y); }

int main(void) {
    int v[] = {9, 5, 1, 7, 3, 2, 8, 4, 6, 0};
    volatile int round = 0;
    int r = setjmp(jb);
    printf("setjmp %d after %d calls (round %d)\n", r, calls, round);
    if (round++ < 2) { calls = 0; qsort(v, 10, sizeof v[0], cmp); printf("not reached\n"); }
    qsort(v, 10, sizeof v[0], plain);
    for (int i = 0; i < 10; i++) printf("%d ", v[i]);
    printf("\n");
    return 0;
}
