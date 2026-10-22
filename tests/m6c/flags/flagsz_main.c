#include <stdio.h>
long fz_interior_b(long, long), fz_interior_bl(long, long), fz_brlocal(long, long), fz_interior_cond(long, long);
static const long A[] = {5, 5, 7, 1, 9, 9}, B[] = {5, 6, 7, 2, 9, 3};

#define RUN(f) do { printf("%-16s", #f); for (int i = 0; i < 6; i++) printf(" %ld", f(A[i], B[i])); printf("\n"); } while (0)

int main(void) {
  RUN(fz_interior_b);
  RUN(fz_interior_bl);
  RUN(fz_interior_cond);
  RUN(fz_brlocal);
  return 0;
}
