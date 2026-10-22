// std::unordered_map<uint64_t, uint32_t>: 1M inserts, 2M lookups (about half hit), 250K erases.
#include "perf.h"
#include <unordered_map>

int main() {
  uint64_t s = 77;
  std::unordered_map<uint64_t, uint32_t> m;
  uint64_t t0 = perf_ns();
  for (uint32_t i = 0; i < 1000000; i++) m[perf_xs(&s) & 0x3FFFFF] += i;
  uint64_t hits = 0, sum = 0;
  for (int i = 0; i < 2000000; i++) {
    auto it = m.find(perf_xs(&s) & 0x3FFFFF);
    if (it != m.end()) { hits++; sum += it->second; }
  }
  for (int i = 0; i < 250000; i++) m.erase(perf_xs(&s) & 0x3FFFFF);
  perf_end(t0);
  printf("%zu %llu %llu\n", m.size(), (unsigned long long)hits, (unsigned long long)sum);
  return 0;
}
