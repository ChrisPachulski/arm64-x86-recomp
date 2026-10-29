/* Computed goto (labels as values): threaded interpreters whose `goto *tab[i]` reads a table of absolute label
   addresses. run8 masks its index to the table size, run11 masks it past a shorter table (the bound is the mask, the
   table ends earlier), run_raw leaves its byte index unbounded and run_ptr jumps to a label address kept in memory:
   those two stay on the undecoded-br fallback. */
#include <stdint.h>
#include <stdio.h>

static const char *const names[] = {"add", "sub", "mul", "xor", "shl", "jnz", "dup", "halt"};

__attribute__((noinline)) static long run8(const uint8_t *code, long acc) {
  static const void *const tab[8] = {&&op_add, &&op_sub, &&op_mul, &&op_xor, &&op_shl, &&op_jnz, &&op_dup, &&op_halt};
  long pc = 0, tmp = 0;
#define NEXT8 goto *tab[code[pc++] & 7]
  NEXT8;
op_add: acc += code[pc++]; NEXT8;
op_sub: acc -= code[pc++]; NEXT8;
op_mul: acc *= code[pc++] | 1; NEXT8;
op_xor: acc ^= (long)code[pc++] << 3; NEXT8;
op_shl: acc = (acc << 1) ^ (acc >> 7); NEXT8;
op_jnz: if (--tmp > 0) pc = code[pc]; else pc++; NEXT8;
op_dup: tmp = code[pc++]; NEXT8;
op_halt: return acc;
}

__attribute__((noinline)) static long run11(const uint32_t *code, long acc, long *steps) {
  static const void *const tab[11] = {&&a0, &&a1, &&a2, &&a3, &&a4, &&a5, &&a6, &&a7, &&a8, &&a9, &&a10};
  uint32_t i; long pc = 0, k = 0;
#define NEXT11 do { i = code[pc++]; ++*steps; goto *tab[i & 15]; } while (0)
  NEXT11;
a0: acc += i >> 4; NEXT11;
a1: acc -= i >> 4; NEXT11;
a2: acc = acc * 3 + (i >> 4); NEXT11;
a3: acc ^= acc >> 5; NEXT11;
a4: k = i >> 4; NEXT11;
a5: if (k-- > 0) pc = i >> 4; NEXT11;
a6: acc += k; NEXT11;
a7: acc = (acc << 3) | (acc >> 61 & 7); NEXT11;
a8: acc -= (long)(i >> 4) * k; NEXT11;
a9: acc = acc % 1000003 + 17; NEXT11;
a10: return acc;
}

__attribute__((noinline)) static long run_raw(const uint8_t *code) {
  static const void *const tab[4] = {&&r0, &&r1, &&r2, &&r3};
  long acc = 1, pc = 0;
  goto *tab[code[pc++]];
r0: acc += 7; goto *tab[code[pc++]];
r1: acc *= 3; goto *tab[code[pc++]];
r2: acc -= 2; goto *tab[code[pc++]];
r3: return acc;
}

struct op { const void *go; int arg; };
__attribute__((noinline)) static long run_ptr(int n) {
  struct op ops[3] = {{&&p0, 5}, {&&p1, 3}, {&&p2, 0}};
  volatile int sel = 0; long acc = 0; int k = 0;
  goto *ops[sel].go;
p0: acc += ops[0].arg; sel = (k++ & 1) ? 1 : 0; if (k > n) sel = 2; goto *ops[sel].go;
p1: acc = acc * ops[1].arg % 100003; sel = 0; goto *ops[sel].go;
p2: return acc;
}

int main(void) {
  static const uint8_t prog8[] = {6, 200, 0, 3, 4, 2, 5, 3, 1, 1, 7};   /* dup 200; add 3; shl; mul 5; jnz ->3; sub 1; halt */
  static const uint32_t prog11[] = {4 | 120 << 4, 0 | 9 << 4, 2 | 5 << 4, 3, 6, 7, 8 | 2 << 4, 9, 5 | 1 << 4, 1 | 4 << 4, 10};
  static const uint8_t raw[] = {0, 1, 0, 1, 2, 0, 1, 3};
  long steps = 0, total = 0;
  for (int r = 0; r < 2000; r++) {
    total += run8(prog8, r);
    total ^= run11(prog11, r, &steps);
  }
  printf("run8+run11 %ld steps %ld\n", total, steps);
  printf("run_raw %ld run_ptr %ld %s\n", run_raw(raw), run_ptr(1000), names[total & 7]);
  return 0;
}
