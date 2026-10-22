/* Shared by every tests/perf benchmark: kernel timing to stderr (PERF_NS), results to stdout (compared). */
#ifndef PERF_H
#define PERF_H
#include <stdint.h>
#include <stdio.h>
#include <time.h>
static inline uint64_t perf_ns(void) { return clock_gettime_nsec_np(CLOCK_UPTIME_RAW); }
static inline void perf_end(uint64_t t0) { fprintf(stderr, "PERF_NS %llu\n", (unsigned long long)(perf_ns() - t0)); }
static inline uint64_t perf_xs(uint64_t* s) { uint64_t x = *s; x ^= x << 13; x ^= x >> 7; x ^= x << 17; return *s = x; }
#endif
