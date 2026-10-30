/* Shared inline-cache collisions (gdyld gd_icall_slow): one call site alternating between main-image functions and library
   functions 512 bytes apart in image offset, which share a slot of the shared cache (see icg_lib.c), so a hit there must
   compare the target before it calls. */
#include <stdio.h>

typedef long (*fn)(long);
extern fn const LT[64];
#define F(n) __attribute__((aligned(512), noinline)) static long mf##n(long x) { return x * (5 * n + 1) - n; }
F(0) F(1) F(2) F(3) F(4) F(5) F(6) F(7) F(8) F(9) F(10) F(11) F(12) F(13) F(14) F(15)
F(16) F(17) F(18) F(19) F(20) F(21) F(22) F(23) F(24) F(25) F(26) F(27) F(28) F(29) F(30) F(31)
#undef F
#define F(n) mf##n,
static fn const volatile MT[32] = {
F(0) F(1) F(2) F(3) F(4) F(5) F(6) F(7) F(8) F(9) F(10) F(11) F(12) F(13) F(14) F(15)
F(16) F(17) F(18) F(19) F(20) F(21) F(22) F(23) F(24) F(25) F(26) F(27) F(28) F(29) F(30) F(31)
};

__attribute__((noinline)) static long site(fn f, long x) { return f(x) & 0xffffffffffL; }

int main(void) {
  long x = 1, s = 0;
  for (int r = 0; r < 50; r++)
    for (int i = 0; i < 32; i++)
      for (int j = 0; j < 64; j++) { x = site(MT[i], x); x = site(LT[j], x); s += x & 0xff; }
  printf("alternating main and library targets: %ld %ld\n", x, s);
  return 0;
}
