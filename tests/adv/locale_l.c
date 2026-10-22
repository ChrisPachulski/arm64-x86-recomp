/* *_l formatting and scanning honor their locale argument, not the process locale (C here). */
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <xlocale.h>

int main(void) {
    locale_t fr = newlocale(LC_ALL_MASK, "fr_FR.UTF-8", NULL);
    if (!fr) { printf("no fr_FR locale\n"); return 1; }
    char buf[64], *s = NULL;
    double d = 0, e = 0;
    snprintf_l(buf, sizeof buf, fr, "%.2f|%d", 1.5, 7);
    asprintf_l(&s, fr, "%.1f", 2.5);
    int n = sscanf_l("3,25 4.5", fr, "%lf", &d);
    sscanf_l("4.5", NULL, "%lf", &e);
    printf("snprintf_l [%s] asprintf_l [%s] sscanf_l %d %.2f c-locale %.2f\n", buf, s, n, d, e);
    snprintf_l(buf, sizeof buf, NULL, "%.2f", 1.5);
    printf("NULL locale [%s] plain [%.2f]\n", buf, 1.5);
    free(s);
    freelocale(fr);
    return 0;
}
