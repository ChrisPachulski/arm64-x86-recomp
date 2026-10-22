#include <stdio.h>
long fq_br_entry(long, long), fq_br_callee(long, long), fq_br_entry_far(long, long);
static const long A[] = {5, 5, 7, 1, 9, 9}, B[] = {5, 6, 7, 2, 9, 3};

#define RUN(f) do { printf("%-16s", #f); for (int i = 0; i < 6; i++) printf(" %ld", f(A[i], B[i])); printf("\n"); } while (0)

int main(void) {
  RUN(fq_br_entry);
  RUN(fq_br_callee);
  RUN(fq_br_entry_far);
  return 0;
}
