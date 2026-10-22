// Virtual calls over 1024 objects of 4 classes in random order, then calls through a function-pointer table.
#include "perf.h"
#include <memory>
#include <vector>

struct Shape { virtual ~Shape() {} virtual uint64_t step(uint64_t x) = 0; };
struct A : Shape { uint64_t k = 3; uint64_t step(uint64_t x) override { return x * k + 1; } };
struct B : Shape { uint64_t k = 5; uint64_t step(uint64_t x) override { return (x ^ k) >> 1; } };
struct C : Shape { uint64_t k = 7; uint64_t step(uint64_t x) override { return x + (k << 2); } };
struct D : Shape { uint64_t k = 9; uint64_t step(uint64_t x) override { return x - k * 3; } };

__attribute__((noinline)) static uint64_t f0(uint64_t x) { return x * 3 + 7; }
__attribute__((noinline)) static uint64_t f1(uint64_t x) { return x ^ (x >> 9); }
__attribute__((noinline)) static uint64_t f2(uint64_t x) { return x + 0x9E3779B9; }
__attribute__((noinline)) static uint64_t f3(uint64_t x) { return (x << 1) | (x >> 63); }
static uint64_t (*const volatile FT[4])(uint64_t) = {f0, f1, f2, f3};

int main() {
  uint64_t s = 5;
  std::vector<std::unique_ptr<Shape>> v;
  for (int i = 0; i < 1024; i++) {
    switch (perf_xs(&s) & 3) {
      case 0: v.emplace_back(new A); break;
      case 1: v.emplace_back(new B); break;
      case 2: v.emplace_back(new C); break;
      default: v.emplace_back(new D); break;
    }
  }
  uint64_t (*ft[4])(uint64_t) = {FT[0], FT[1], FT[2], FT[3]};
  uint8_t sel[1024];
  for (int i = 0; i < 1024; i++) sel[i] = (uint8_t)(perf_xs(&s) & 3);
  uint64_t x = 1, y = 1;
  uint64_t t0 = perf_ns();
  for (int r = 0; r < 10000; r++)
    for (auto& p : v) x = p->step(x);
  for (int r = 0; r < 10000; r++)
    for (int i = 0; i < 1024; i++) y = ft[sel[i]](y);
  perf_end(t0);
  printf("%016llx %016llx\n", (unsigned long long)x, (unsigned long long)y);
  return 0;
}
