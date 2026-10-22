// std::string: to_string + concatenation, find, a vector of 400K strings sorted, then joined and searched.
#include "perf.h"
#include <algorithm>
#include <string>
#include <vector>

int main() {
  std::vector<std::string> v;
  v.reserve(400000);
  uint64_t hits = 0, len = 0;
  uint64_t t0 = perf_ns();
  for (uint32_t i = 0; i < 400000; i++) {
    std::string k = "key_" + std::to_string((uint64_t)i * 7919u % 1000003u) + "_" + std::to_string(i & 255);
    if (k.find("99") != std::string::npos) hits++;
    len += k.size();
    v.push_back(std::move(k));
  }
  std::sort(v.begin(), v.end());
  std::string all;
  for (size_t i = 0; i < v.size(); i += 4) { all += v[i]; all += ','; }
  size_t pos = 0, n = 0;
  while ((pos = all.find("_7,", pos)) != std::string::npos) { n++; pos += 3; }
  perf_end(t0);
  printf("%llu %llu %zu %s %s %zu\n", (unsigned long long)hits, (unsigned long long)len, all.size(), v.front().c_str(), v.back().c_str(), n);
  return 0;
}
