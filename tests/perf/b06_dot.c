/* SIMD float dot product with intrinsics (NEON vmulq/vaddq on arm64, SSE mulps/addps on x86-64): same operation order, exact result. */
#include "perf.h"
#include <stdlib.h>
#if defined(__aarch64__)
#include <arm_neon.h>
#else
#include <immintrin.h>
#endif

enum { N = 4096 };
__attribute__((noinline)) static float dot(const float* a, const float* b) {
#if defined(__aarch64__)
  float32x4_t s0 = vdupq_n_f32(0), s1 = s0, s2 = s0, s3 = s0;
  for (int i = 0; i < N; i += 16) {
    s0 = vaddq_f32(s0, vmulq_f32(vld1q_f32(a + i), vld1q_f32(b + i)));
    s1 = vaddq_f32(s1, vmulq_f32(vld1q_f32(a + i + 4), vld1q_f32(b + i + 4)));
    s2 = vaddq_f32(s2, vmulq_f32(vld1q_f32(a + i + 8), vld1q_f32(b + i + 8)));
    s3 = vaddq_f32(s3, vmulq_f32(vld1q_f32(a + i + 12), vld1q_f32(b + i + 12)));
  }
  float32x4_t t = vaddq_f32(vaddq_f32(s0, s1), vaddq_f32(s2, s3));
  float r[4]; vst1q_f32(r, t);
#else
  __m128 s0 = _mm_setzero_ps(), s1 = s0, s2 = s0, s3 = s0;
  for (int i = 0; i < N; i += 16) {
    s0 = _mm_add_ps(s0, _mm_mul_ps(_mm_loadu_ps(a + i), _mm_loadu_ps(b + i)));
    s1 = _mm_add_ps(s1, _mm_mul_ps(_mm_loadu_ps(a + i + 4), _mm_loadu_ps(b + i + 4)));
    s2 = _mm_add_ps(s2, _mm_mul_ps(_mm_loadu_ps(a + i + 8), _mm_loadu_ps(b + i + 8)));
    s3 = _mm_add_ps(s3, _mm_mul_ps(_mm_loadu_ps(a + i + 12), _mm_loadu_ps(b + i + 12)));
  }
  __m128 t = _mm_add_ps(_mm_add_ps(s0, s1), _mm_add_ps(s2, s3));
  float r[4]; _mm_storeu_ps(r, t);
#endif
  return (r[0] + r[1]) + (r[2] + r[3]);
}

int main(void) {
  float* a = malloc(N * sizeof(float)); float* b = malloc(N * sizeof(float));
  uint64_t s = 7;
  for (int i = 0; i < N; i++) { a[i] = (float)(perf_xs(&s) % 2000) / 1000.0f - 1.0f; b[i] = (float)(perf_xs(&s) % 2000) / 1000.0f; }
  double acc = 0;
  uint64_t t0 = perf_ns();
  for (int r = 0; r < 360000; r++) { a[r & (N - 1)] += 1e-3f; acc += dot(a, b); }
  perf_end(t0);
  printf("%a\n", acc);
  free(a); free(b);
  return 0;
}
