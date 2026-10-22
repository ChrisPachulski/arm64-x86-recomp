/* A bytecode interpreter loop: a dense switch (jump table) over 12 opcodes running a fixed program 2M times. */
#include "perf.h"

enum { PUSH, ADD, SUB, MUL, XOR, SHR, DUP, SWAP, DEC, JNZ, POP, HALT };
__attribute__((noinline)) static int64_t run(const int* code, int64_t seed) {
  int64_t st[16]; int sp = 0, pc = 0;
  st[sp++] = seed;
  for (;;) {
    switch (code[pc++]) {
      case PUSH: st[sp++] = code[pc++]; break;
      case ADD: sp--; st[sp - 1] += st[sp]; break;
      case SUB: sp--; st[sp - 1] -= st[sp]; break;
      case MUL: sp--; st[sp - 1] *= st[sp]; break;
      case XOR: sp--; st[sp - 1] ^= st[sp]; break;
      case SHR: st[sp - 1] = (int64_t)((uint64_t)st[sp - 1] >> 3); break;
      case DUP: st[sp] = st[sp - 1]; sp++; break;
      case SWAP: { int64_t t = st[sp - 1]; st[sp - 1] = st[sp - 2]; st[sp - 2] = t; break; }
      case DEC: st[sp - 1]--; break;
      case JNZ: { int t = code[pc++]; if (st[sp - 1] != 0) pc = t; break; }
      case POP: sp--; break;
      default: return st[0];
    }
  }
}

int main(void) {
  static const int prog[] = {PUSH, 20, SWAP, PUSH, 7, MUL, DUP, SHR, XOR, PUSH, 3, ADD, SWAP, DEC, JNZ, 2, POP, HALT};
  int64_t acc = 0;
  uint64_t t0 = perf_ns();
  for (int64_t i = 0; i < 1000000; i++) acc += run(prog, i);
  perf_end(t0);
  printf("%lld\n", (long long)acc);
  return 0;
}
