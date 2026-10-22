/* Direct calls: naive recursive Fibonacci (about 30M calls) and a small non-inlined leaf called in a loop. */
#include "perf.h"

__attribute__((noinline)) static uint64_t fib(uint32_t n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
__attribute__((noinline)) static uint64_t leaf(uint64_t a, uint64_t b) { return (a ^ b) + (a >> 3); }

int main(void) {
  uint64_t t0 = perf_ns();
  uint64_t f = fib(35);
  uint64_t x = 1;
  for (uint64_t i = 0; i < 50000000; i++) x = leaf(x, i);
  perf_end(t0);
  printf("%llu %llu\n", (unsigned long long)f, (unsigned long long)x);
  return 0;
}
