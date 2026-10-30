/* Polymorphic indirect calls (gdyld gd_icall_slow, the miss path of the per-site inline cache, and its shared cache): one site
   cycling through guest functions in order, one in random order, one switching its single target after a warm-up, guest and
   host-import targets mixed at one site, many sites sharing the same targets, and two threads driving one site with different
   targets at once. */
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef long (*fn)(long);
__attribute__((noinline)) static long g0(long x) { return x * 3 + 1; }
__attribute__((noinline)) static long g1(long x) { return x ^ (x >> 3); }
__attribute__((noinline)) static long g2(long x) { return x + 0x9e37; }
__attribute__((noinline)) static long g3(long x) { return (x << 1) - 5; }
__attribute__((noinline)) static long g4(long x) { return x - (x >> 2); }
__attribute__((noinline)) static long g5(long x) { return ~x & 0xffffff; }
static fn const volatile G[6] = {g0, g1, g2, g3, g4, g5};
static fn const volatile M[4] = {g0, labs, g3, labs};      /* guest and host import targets at one site */

__attribute__((noinline)) static long site(fn f, long x) { return f(x) & 0xfffffffffffL; }  /* one call site for every caller */
__attribute__((noinline)) static long site2(fn f, long x) { return f(x) & 0xfffffffffffL; }
__attribute__((noinline)) static long site3(fn f, long x) { return f(x) & 0xfffffffffffL; }

static uint64_t xs(uint64_t* s) { *s ^= *s << 13; *s ^= *s >> 7; *s ^= *s << 17; return *s; }

struct job { int sel; long out; };
static void* worker(void* p) {
  struct job* j = p;
  long x = j->sel + 1;
  for (int i = 0; i < 200000; i++) x = site3(G[(i & 1) ? j->sel : j->sel + 1], x);
  j->out = x;
  return NULL;
}

int main(void) {
  long x = 1;
  for (int i = 0; i < 60000; i++) x = site(G[i % 6], x);
  printf("cycle: %ld\n", x);
  uint64_t s = 88172645463325252ULL;
  x = 1;
  for (int i = 0; i < 60000; i++) x = site(G[xs(&s) % 6], x);
  printf("random: %ld\n", x);
  x = 1;
  for (int i = 0; i < 60000; i++) x = site2(i < 30000 ? G[2] : G[4], x);
  printf("switch: %ld\n", x);
  x = -7;
  for (int i = 0; i < 60000; i++) x = site2(M[xs(&s) % 4], x - 3);
  printf("mixed with host: %ld\n", x);
  long a = 0;
  for (int r = 0; r < 1000; r++)
    for (int k = 0; k < 6; k++) a += site(G[k], r) + site2(G[5 - k], r) + site3(G[(k + r) % 6], r);
  printf("shared targets: %ld\n", a);
  struct job j[2] = {{0, 0}, {3, 0}};
  pthread_t t[2];
  for (int i = 0; i < 2; i++) pthread_create(&t[i], NULL, worker, &j[i]);
  for (int i = 0; i < 2; i++) pthread_join(t[i], NULL);
  printf("threads: %ld %ld\n", j[0].out, j[1].out);
  return 0;
}
