/* Host->guest->host->guest re-entry: qsort comparator that calls bsearch (guest comparator) and a nested
   qsort; atexit/pthread_once callbacks into guest code. */
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>

static int table[32];
static long hits, nested;
static pthread_once_t once = PTHREAD_ONCE_INIT;

static int cmp_int(const void *a, const void *b) { int x = *(const int *)a, y = *(const int *)b; return (x > y) - (x < y); }
static int cmp_outer(const void *a, const void *b) {
    int x = *(const int *)a, y = *(const int *)b;
    int inx = bsearch(&x, table, 32, sizeof(int), cmp_int) != NULL;
    int iny = bsearch(&y, table, 32, sizeof(int), cmp_int) != NULL;
    hits += inx + iny;
    if ((x ^ y) % 7 == 0) {                                 /* nested qsort from inside a comparator */
        int tmp[5] = {x, y, 3, -1, x + y};
        qsort(tmp, 5, sizeof(int), cmp_int);
        nested += tmp[0] + tmp[4];
    }
    if (inx != iny) return iny - inx;
    return (x > y) - (x < y);
}
static void init_once(void) { printf("once\n"); }
static void bye1(void) { printf("atexit1 hits=%ld\n", hits); }
static void bye2(void) { printf("atexit2 nested=%ld\n", nested); }

int main(void) {
    int keys[64];
    for (int i = 0; i < 32; i++) table[i] = i * 5;
    for (int i = 0; i < 64; i++) keys[i] = (i * 37 + 11) % 97;
    atexit(bye1);
    atexit(bye2);
    pthread_once(&once, init_once);
    pthread_once(&once, init_once);
    qsort(keys, 64, sizeof(int), cmp_outer);
    for (int i = 0; i < 64; i++) printf("%d%c", keys[i], i == 63 ? '\n' : ' ');
    printf("hits %ld nested %ld\n", hits, nested);
    return 5;
}
