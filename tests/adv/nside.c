/* #13: every printf-family side effect happens exactly once and in order. %n writes into memory a preceding %s
   argument reads (the formatter must not walk the format twice), on the asprintf, long printf (> 4 KB) and truncated
   snprintf paths, plus %hn / %lln widths. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char big[5000];

int main(void) {
    int v = 0x00636261;
    char *out = NULL;
    int r = asprintf(&out, "%s%n", (char *)&v, &v);
    printf("asprintf %d [%s] v=%d\n", r, out, v);
    free(out);
    memset(big, 'x', sizeof big - 1);
    int w = 0x00636261;
    int n = printf("%s%s%n\n", big, (char *)&w, &w);
    printf("printf ret %d w=%d\n", n, w);
    char sb[8];
    int z = 0x00636261;
    r = snprintf(sb, sizeof sb, "%s-%s%n|", "longer", (char *)&z, &z);
    printf("snprintf %d [%s] z=%d\n", r, sb, z);
    short hh = 0;
    long long ll = 0;
    r = printf("ab%hn cd%lln\n", &hh, &ll);
    printf("ret %d hh=%d ll=%lld\n", r, hh, ll);
    return 0;
}
