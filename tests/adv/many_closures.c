/* 100 distinct guest comparators of one signature handed to qsort: each one becomes a native closure. */
#include <stdio.h>
#include <stdlib.h>

#define C(i) static int cmp##i(const void* a, const void* b) { int x = *(const int*)a ^ i, y = *(const int*)b ^ i; return (x > y) - (x < y); }
#define C10(t) C(t##0) C(t##1) C(t##2) C(t##3) C(t##4) C(t##5) C(t##6) C(t##7) C(t##8) C(t##9)
C10() C10(1) C10(2) C10(3) C10(4) C10(5) C10(6) C10(7) C10(8) C10(9)
#define P(i) cmp##i,
#define P10(t) P(t##0) P(t##1) P(t##2) P(t##3) P(t##4) P(t##5) P(t##6) P(t##7) P(t##8) P(t##9)
static int (*const CMP[])(const void*, const void*) = {P10() P10(1) P10(2) P10(3) P10(4) P10(5) P10(6) P10(7) P10(8) P10(9)};

int main(void) {
    long sum = 0;
    for (int k = 0; k < 100; k++) {
        int v[16];
        for (int i = 0; i < 16; i++) v[i] = (i * 37 + k) % 101;
        qsort(v, 16, sizeof v[0], CMP[k]);
        sum = sum * 31 % 1000000007 + v[0] + 7 * v[15];
        if (k % 25 == 24) printf("after %d comparators: %ld\n", k + 1, sum);
    }
    qsort((int[]){3, 1, 2}, 3, sizeof(int), CMP[64]);         /* a comparator seen before reuses its closure */
    printf("done\n");
    return 0;
}
