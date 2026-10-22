// std::thread x 8 doing integer work, publishing into shared atomics every 64 iterations; order-independent result.
#include "perf.h"
#include <atomic>
#include <thread>
#include <vector>

int main() {
  std::atomic<uint64_t> total{0}, ticks{0};
  uint64_t t0 = perf_ns();
  std::vector<std::thread> ts;
  for (int t = 0; t < 8; t++)
    ts.emplace_back([t, &total, &ticks] {
      uint64_t s = 1000 + t, acc = 0;
      for (int i = 0; i < 20000000; i++) {
        acc += perf_xs(&s) & 0xFF;
        if ((i & 63) == 63) { total.fetch_add(acc, std::memory_order_relaxed); acc = 0; ticks.fetch_add(1); }
      }
      total.fetch_add(acc);
    });
  for (auto& th : ts) th.join();
  perf_end(t0);
  printf("%llu %llu\n", (unsigned long long)total.load(), (unsigned long long)ticks.load());
  return 0;
}
