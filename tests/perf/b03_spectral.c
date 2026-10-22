/* Spectral norm (benchmarks game), N = 1200, printed to 6 decimals. */
#include "perf.h"
#include <math.h>
#include <stdlib.h>

static double A(int i, int j) { return 1.0 / ((i + j) * (i + j + 1) / 2 + i + 1); }
static void mul_av(int n, const double* v, double* av) {
  for (int i = 0; i < n; i++) { double s = 0; for (int j = 0; j < n; j++) s += A(i, j) * v[j]; av[i] = s; }
}
static void mul_atv(int n, const double* v, double* atv) {
  for (int i = 0; i < n; i++) { double s = 0; for (int j = 0; j < n; j++) s += A(j, i) * v[j]; atv[i] = s; }
}
static void mul_atav(int n, const double* v, double* out, double* tmp) { mul_av(n, v, tmp); mul_atv(n, tmp, out); }

int main(void) {
  enum { N = 1200 };
  double* u = malloc(N * sizeof(double)); double* v = malloc(N * sizeof(double)); double* t = malloc(N * sizeof(double));
  for (int i = 0; i < N; i++) u[i] = 1;
  uint64_t t0 = perf_ns();
  for (int i = 0; i < 10; i++) { mul_atav(N, u, v, t); mul_atav(N, v, u, t); }
  double vbv = 0, vv = 0;
  for (int i = 0; i < N; i++) { vbv += u[i] * v[i]; vv += v[i] * v[i]; }
  perf_end(t0);
  printf("%.6f\n", sqrt(vbv / vv));
  free(u); free(v); free(t);
  return 0;
}
