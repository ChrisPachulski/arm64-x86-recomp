// e1_noeh with work() called through a volatile function pointer: a plain call the translation cannot inline.
#include "perf.h"

static uint64_t live, rare;
struct Guard { uint64_t v; explicit Guard(uint64_t x) : v(x) { live++; } ~Guard() { live--; } };
__attribute__((noinline)) static uint64_t work(uint64_t i) {
  Guard g(i);
  if (i % 100000 == 99999) { rare++; return 'r'; }
  return g.v ^ (i >> 3);
}
static uint64_t (*volatile fp)(uint64_t) = work;

int main() {
  uint64_t s = 0;
  uint64_t t0 = perf_ns();
  for (uint64_t i = 0; i < 40000000; i++) s += fp(i);
  perf_end(t0);
  printf("%llu %llu %llu\n", (unsigned long long)s, (unsigned long long)rare, (unsigned long long)live);
  return 0;
}
