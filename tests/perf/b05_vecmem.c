/* 128-bit vector copy and fill kernels over sizes 64 B .. 64 KB (q-register loads/stores on arm64, SSE on x86-64). */
#include "perf.h"
#include <stdlib.h>
#include <string.h>

typedef unsigned char v16 __attribute__((vector_size(16), aligned(1)));

__attribute__((noinline)) static void vcopy(unsigned char* d, const unsigned char* s, size_t n) {
  for (size_t i = 0; i < n; i += 64) {
    v16 a = *(const v16*)(s + i), b = *(const v16*)(s + i + 16), c = *(const v16*)(s + i + 32), e = *(const v16*)(s + i + 48);
    *(v16*)(d + i) = a; *(v16*)(d + i + 16) = b; *(v16*)(d + i + 32) = c; *(v16*)(d + i + 48) = e;
  }
}
__attribute__((noinline)) static void vfill(unsigned char* d, unsigned char x, size_t n) {
  v16 v = {x, x, x, x, x, x, x, x, x, x, x, x, x, x, x, x};
  for (size_t i = 0; i < n; i += 32) { *(v16*)(d + i) = v; *(v16*)(d + i + 16) = v; }
}
__attribute__((noinline)) static uint64_t vsum(const unsigned char* s, size_t n) {
  typedef uint64_t u2 __attribute__((vector_size(16), aligned(1)));
  u2 acc = {0, 0};
  for (size_t i = 0; i < n; i += 16) acc ^= *(const u2*)(s + i) + (acc << 1);
  return acc[0] ^ acc[1];
}

int main(void) {
  enum { MAX = 65536 };
  unsigned char* src = malloc(MAX + 64); unsigned char* dst = malloc(MAX + 64);
  uint64_t s = 42;
  for (int i = 0; i < MAX; i++) src[i] = (unsigned char)perf_xs(&s);
  static const size_t sizes[] = {64, 256, 1024, 4096, 65536};
  uint64_t h = 0;
  uint64_t t0 = perf_ns();
  for (int k = 0; k < 5; k++) {
    size_t n = sizes[k], reps = (size_t)(1u << 29) / n;
    for (size_t r = 0; r < reps; r++) {
      vcopy(dst, src + (r & 15) * 0, n);
      dst[r % n] ^= (unsigned char)r;
      if ((r & 7) == 0) vfill(dst + n / 2, (unsigned char)r, n / 2);
    }
    h = h * 31 + vsum(dst, n);
  }
  perf_end(t0);
  printf("%016llx\n", (unsigned long long)h);
  free(src); free(dst);
  return 0;
}
