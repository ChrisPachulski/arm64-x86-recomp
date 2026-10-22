/* Integer loops and hashing: FNV-1a over a 16 MB buffer, a murmur3 finalizer mix, Collatz step counts. */
#include "perf.h"
#include <stdlib.h>
#include <string.h>

int main(void) {
  enum { N = 1 << 24 };
  uint8_t* buf = malloc(N);
  uint64_t s = 88172645463325252ULL;
  for (int i = 0; i < N; i += 8) { uint64_t v = perf_xs(&s); memcpy(buf + i, &v, 8); }
  uint64_t t0 = perf_ns();
  uint32_t fnv = 2166136261u;
  for (int r = 0; r < 4; r++)
    for (int i = 0; i < N; i++) { fnv ^= buf[i]; fnv *= 16777619u; }
  uint64_t mix = 0;
  for (int r = 0; r < 4; r++)
    for (int i = 0; i < N / 8; i++) {
      uint64_t k; memcpy(&k, buf + 8 * i, 8);
      k ^= k >> 33; k *= 0xff51afd7ed558ccdULL; k ^= k >> 33; k *= 0xc4ceb9fe1a85ec53ULL; k ^= k >> 33;
      mix += k ^ (mix << 5);
    }
  uint64_t steps = 0;
  for (uint64_t n = 1; n < 300000; n++) { uint64_t x = n; while (x != 1) { x = (x & 1) ? 3 * x + 1 : x >> 1; steps++; } }
  perf_end(t0);
  printf("%08x %016llx %llu\n", fnv, (unsigned long long)mix, (unsigned long long)steps);
  free(buf);
  return 0;
}
