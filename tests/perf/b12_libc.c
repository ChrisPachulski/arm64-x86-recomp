/* Calls into host libc from a hot loop: memcpy of 1..256 bytes, strlen, malloc/free of 16..1040 bytes. */
#include "perf.h"
#include <stdlib.h>
#include <string.h>

int main(void) {
  static char strs[64][200];
  uint64_t s = 11;
  for (int i = 0; i < 64; i++) { int n = 1 + (int)(perf_xs(&s) % 199); memset(strs[i], 'a' + i % 26, (size_t)n); strs[i][n] = 0; }
  static unsigned char src[4096], dst[4096];
  for (int i = 0; i < 4096; i++) src[i] = (unsigned char)perf_xs(&s);
  void* ring[64] = {0};
  uint64_t h = 0;
  uint64_t t0 = perf_ns();
  for (int i = 0; i < 1500000; i++) {
    uint64_t r = perf_xs(&s);
    size_t n = 1 + (r & 255), off = (r >> 8) & 2047;
    memcpy(dst + off, src + ((r >> 20) & 2047), n);
    h += strlen(strs[i & 63]) + dst[off];
    int k = (int)((r >> 32) & 63);
    free(ring[k]);
    ring[k] = malloc(16 + ((r >> 40) & 1023));
    ((unsigned char*)ring[k])[0] = (unsigned char)r;
  }
  perf_end(t0);
  for (int k = 0; k < 64; k++) free(ring[k]);
  printf("%llu\n", (unsigned long long)h);
  return 0;
}
