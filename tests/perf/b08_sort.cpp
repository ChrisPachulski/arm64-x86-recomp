// std::sort of 4M random 32-bit keys, then of 1M pairs by a lambda comparator.
#include "perf.h"
#include <algorithm>
#include <utility>
#include <vector>

int main() {
  uint64_t s = 2024;
  std::vector<uint32_t> v(1 << 22);
  for (auto& x : v) x = (uint32_t)perf_xs(&s);
  std::vector<std::pair<uint32_t, uint32_t>> p(1 << 20);
  for (auto& x : p) x = {(uint32_t)perf_xs(&s) % 1000, (uint32_t)perf_xs(&s)};
  uint64_t t0 = perf_ns();
  std::sort(v.begin(), v.end());
  std::sort(p.begin(), p.end(), [](const auto& a, const auto& b) { return a.first != b.first ? a.first < b.first : a.second > b.second; });
  perf_end(t0);
  uint64_t h = 0;
  for (size_t i = 0; i < v.size(); i += 997) h = h * 31 + v[i];
  for (size_t i = 0; i < p.size(); i += 991) h = h * 31 + p[i].second;
  printf("%016llx\n", (unsigned long long)h);
  return 0;
}
