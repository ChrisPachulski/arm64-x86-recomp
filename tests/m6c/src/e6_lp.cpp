// 40M calls of work(), whose Guard needs a landing pad because note() may throw; e6_nolp.cpp is this file with -fno-exceptions.
#include "perf.h"

static uint64_t live, rare;
static volatile uint64_t never = ~0ULL;
struct Guard { uint64_t v; explicit Guard(uint64_t x) : v(x) { live++; } ~Guard() { live--; } };
__attribute__((noinline)) static void note(const Guard* g) { rare += g->v; if (rare == 1) {
#if __cpp_exceptions
  throw 1;
#else
  __builtin_trap();
#endif
} }
__attribute__((noinline)) static uint64_t work(uint64_t i) {
  Guard g(i);
  if (i == never) note(&g);
  return g.v ^ (i >> 3);
}

int main() {
  uint64_t s = 0;
  uint64_t t0 = perf_ns();
  for (uint64_t i = 0; i < 40000000; i++) s += work(i);
  perf_end(t0);
  printf("%llu %llu %llu\n", (unsigned long long)s, (unsigned long long)rare, (unsigned long long)live);
  return 0;
}
