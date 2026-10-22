// e3_eh_nothrow's control: the same Guard and call shape, but noexcept everywhere, so no landing pads exist.
#include "perf.h"

static uint64_t live, rare;
static volatile uint64_t never = ~0ULL;
struct Guard { uint64_t v; explicit Guard(uint64_t x) : v(x) { live++; } ~Guard() { live--; } };
__attribute__((noinline)) static void note(const Guard* g) noexcept { rare += g->v; }
__attribute__((noinline)) static uint64_t work(uint64_t i) noexcept {
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
