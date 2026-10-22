/* Variadic edge cases: 12+ mixed args, float promotion, %lld %c %p, positional, %Lf, %*d, long output,
   vsnprintf/vfprintf through guest va_list wrappers, sscanf pointer varargs, asprintf, stdout data import. */
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <stdint.h>

static int wrap(char *b, size_t n, const char *f, ...) {
    va_list ap, ap2;
    va_start(ap, f);
    va_copy(ap2, ap);
    int need = vsnprintf(NULL, 0, f, ap2);                  /* va_list consumed twice via va_copy */
    va_end(ap2);
    int r = vsnprintf(b, n, f, ap);
    va_end(ap);
    return need * 1000 + r;
}
static void logf_(const char *f, ...) { va_list ap; va_start(ap, f); vfprintf(stdout, f, ap); va_end(ap); }

int main(void) {
    float f = 1.25f;
    printf("p12 %d %u %ld %lld %c %f %e %g %s %x %hhd %zu\n", -7, 4000000000u, -5L, -123456789012LL, 'Z', f,
           6.02e23, 1e-5, "str", 0xBEEF, (int)300, (size_t)99);
    printf("promo %f %.3f %a %a\n", f, 0.1f, 3.5f, (double)0.1f);
    printf("dbl10 %g %g %g %g %g %g %g %g %g %g\n", 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.5, 10.25);
    printf("mix16 %d %f %d %f %lld %f %d %f %c %f %d %f %u %f %d %f\n", 1, 0.5, 2, 1.5, 3LL, 2.5, 4, 3.5, 'q',
           4.5, 6, 5.5, 7u, 6.5, 8, 7.5);
    printf("pos %2$d %1$d %3$s\n", 11, 22, "three");
    printf("star |%*d|%-*.*f|\n", 6, 42, 9, 2, 3.14159);
    printf("Lf %Lf\n", (long double)2.5);
    char big[9001];
    memset(big, 'x', sizeof big - 1);
    big[sizeof big - 1] = 0;
    int n = printf("%s\n", big);
    printf("bigret %d\n", n);
    char s8[8];
    int r = snprintf(s8, sizeof s8, "%d-%d", 12345, 67890);
    printf("snp %d %s\n", r, s8);
    char wb[64];
    int w = wrap(wb, 12, "%s|%d|%f|%lld|%c", "ab", -3, 2.5f, 1LL << 40, '!');
    printf("wrap %d %s\n", w, wb);
    logf_("vfprintf %s %d %.2f %ld\n", "via", 9, 0.25, -1L);
    char pa[32], pb[32];
    void *p = &f;
    snprintf(pa, sizeof pa, "%p", p);
    snprintf(pb, sizeof pb, "0x%lx", (unsigned long)(uintptr_t)p);
    printf("p_ok %d null %p\n", strcmp(pa, pb) == 0, (void *)0);
    int x = 0; double y = 0; char word[16] = {0}; long long z = 0;
    int got = sscanf("12 3.5 hello -99", "%d %lf %15s %lld", &x, &y, word, &z);
    printf("sscanf %d %d %a %s %lld\n", got, x, y, word, z);
    char *as = NULL;
    int al = asprintf(&as, "%s-%05d-%.1e", "asp", 42, 12345.678);
    printf("asprintf %d %s\n", al, as);
    free(as);
    fprintf(stdout, "fprintf %d\n", 7);
    fputs("fputs ok\n", stdout);
    return 0;
}
