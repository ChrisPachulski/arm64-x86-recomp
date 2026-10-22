/* Dense double matrix multiply, 512 x 512, i-k-j order (the compiler vectorizes the inner loop). */
#include "perf.h"
#include <stdlib.h>

enum { N = 512 };
static void matmul(const double* a, const double* b, double* c) {
  for (int i = 0; i < N * N; i++) c[i] = 0;
  for (int i = 0; i < N; i++)
    for (int k = 0; k < N; k++) {
      double aik = a[i * N + k];
      for (int j = 0; j < N; j++) c[i * N + j] += aik * b[k * N + j];
    }
}

int main(void) {
  double* a = malloc(N * N * sizeof(double)); double* b = malloc(N * N * sizeof(double)); double* c = malloc(N * N * sizeof(double));
  uint64_t s = 1234567;
  for (int i = 0; i < N * N; i++) { a[i] = (double)(perf_xs(&s) % 1000) / 999.0; b[i] = (double)(perf_xs(&s) % 1000) / 777.0; }
  uint64_t t0 = perf_ns();
  matmul(a, b, c);
  matmul(c, b, a);
  perf_end(t0);
  double sum = 0;
  for (int i = 0; i < N * N; i++) sum += a[i];
  printf("%.6e %.6e\n", sum, a[N * N / 2 + 17]);
  free(a); free(b); free(c);
  return 0;
}
