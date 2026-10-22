// b13_exc without exceptions: the same 40M guarded calls, the rare case counted instead of thrown (no landing pads).
#include "perf.h"

static uint64_t live, rare;
struct Guard { uint64_t v; explicit Guard(uint64_t x) : v(x) { live++; } ~Guard() { live--; } };
__attribute__((noinline)) static uint64_t work(uint64_t i) {
  Guard g(i);
  if (i % 100000 == 99999) { rare++; return 'r'; }
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
