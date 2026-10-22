/* Separable [1 2 1]/4 image blur on a 2048 x 2048 8-bit image with intrinsics (NEON on arm64, SSE2 on x86-64), exact. */
#include "perf.h"
#include <stdlib.h>
#include <string.h>
#if defined(__aarch64__)
#include <arm_neon.h>
#else
#include <immintrin.h>
#endif

enum { W = 2048, H = 2048, P = 16, S = W + 2 * P };             /* P: border pixels on every side, S: row stride */

static inline void blur16(unsigned char* o, const unsigned char* a, const unsigned char* b, const unsigned char* c) {
#if defined(__aarch64__)
  uint8x16_t x = vld1q_u8(a), y = vld1q_u8(b), z = vld1q_u8(c);
  uint16x8_t lo = vaddq_u16(vaddl_u8(vget_low_u8(x), vget_low_u8(z)), vshll_n_u8(vget_low_u8(y), 1));
  uint16x8_t hi = vaddq_u16(vaddl_u8(vget_high_u8(x), vget_high_u8(z)), vshll_n_u8(vget_high_u8(y), 1));
  vst1q_u8(o, vcombine_u8(vrshrn_n_u16(lo, 2), vrshrn_n_u16(hi, 2)));
#else
  __m128i zero = _mm_setzero_si128(), two = _mm_set1_epi16(2);
  __m128i x = _mm_loadu_si128((const __m128i*)a), y = _mm_loadu_si128((const __m128i*)b), z = _mm_loadu_si128((const __m128i*)c);
  __m128i lo = _mm_add_epi16(_mm_add_epi16(_mm_unpacklo_epi8(x, zero), _mm_unpacklo_epi8(z, zero)), _mm_slli_epi16(_mm_unpacklo_epi8(y, zero), 1));
  __m128i hi = _mm_add_epi16(_mm_add_epi16(_mm_unpackhi_epi8(x, zero), _mm_unpackhi_epi8(z, zero)), _mm_slli_epi16(_mm_unpackhi_epi8(y, zero), 1));
  lo = _mm_srli_epi16(_mm_add_epi16(lo, two), 2); hi = _mm_srli_epi16(_mm_add_epi16(hi, two), 2);
  _mm_storeu_si128((__m128i*)o, _mm_packus_epi16(lo, hi));
#endif
}

__attribute__((noinline)) static void pass(unsigned char* dst, unsigned char* tmp, const unsigned char* src) {
  for (int y = 0; y < H; y++)
    for (int x = 0; x < W; x += 16) { const unsigned char* p = src + (y + P) * S + P + x; blur16(tmp + (y + P) * S + P + x, p - S, p, p + S); }
  for (int y = 0; y < H; y++)
    for (int x = 0; x < W; x += 16) { const unsigned char* p = tmp + (y + P) * S + P + x; blur16(dst + (y + P) * S + P + x, p - 1, p, p + 1); }
}

int main(void) {
  size_t n = (size_t)S * (H + 2 * P);
  unsigned char* a = calloc(n, 1); unsigned char* b = calloc(n, 1); unsigned char* t = calloc(n, 1);
  uint64_t s = 99;
  for (size_t i = 0; i < n; i++) a[i] = (unsigned char)perf_xs(&s);
  memcpy(b, a, n); memcpy(t, a, n);
  uint64_t t0 = perf_ns();
  for (int r = 0; r < 48; r++) { pass(b, t, a); pass(a, t, b); }
  perf_end(t0);
  uint64_t h = 1469598103934665603ULL;
  for (size_t i = 0; i < n; i++) { h ^= a[i]; h *= 1099511628211ULL; }
  printf("%016llx\n", (unsigned long long)h);
  free(a); free(b); free(t);
  return 0;
}
