/* Regression check, not a speed test: a 32-bit store and a 64-bit load through two pointers that alias at run time.
   Built with -fno-strict-aliasing on both sides; a translation compiled with type-based alias analysis hoists the load. */
#include "perf.h"
#include <stdlib.h>

__attribute__((noinline)) static uint64_t f(uint64_t a, uint64_t b, int n) {
  uint64_t s = 0;
  for (int i = 0; i < n; i++) { *(uint32_t*)a = (uint32_t)i; s += *(uint64_t*)b; }
  return s;
}

int main(void) {
  uint64_t* p = calloc(1, 8);
  uint64_t t0 = perf_ns();
  uint64_t s = f((uint64_t)p, (uint64_t)p, 30000000);
  perf_end(t0);
  printf("%llu\n", (unsigned long long)s);
  free(p);
  return 0;
}
