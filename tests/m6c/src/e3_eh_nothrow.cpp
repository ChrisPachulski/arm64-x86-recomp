// b13_exc with its landing pads but no throw at run time: 40M guarded calls in a try, the throw condition never true.
#include "perf.h"
#include <stdexcept>

static uint64_t live;
static volatile uint64_t never = ~0ULL;
struct Guard { uint64_t v; explicit Guard(uint64_t x) : v(x) { live++; } ~Guard() { live--; } };
__attribute__((noinline)) static uint64_t work(uint64_t i) {
  Guard g(i);
  if (i == never) throw std::runtime_error("never");
  return g.v ^ (i >> 3);
}

int main() {
  uint64_t s = 0, caught = 0;
  uint64_t t0 = perf_ns();
  for (uint64_t i = 0; i < 40000000; i++) {
    try { s += work(i); }
    catch (const std::exception& e) { caught++; s += (uint64_t)e.what()[0]; }
  }
  perf_end(t0);
  printf("%llu %llu %llu\n", (unsigned long long)s, (unsigned long long)caught, (unsigned long long)live);
  return 0;
}
