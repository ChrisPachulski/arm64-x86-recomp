#include <stdio.h>
long fy_icall_ret(long, long), fy_icall_entry(long, long), fy_interior(long, long), fy_host(long, long);
static const long A[] = {5, 5, 7, 1, 9, 9}, B[] = {5, 6, 7, 2, 9, 3};

#define RUN(f) do { printf("%-16s", #f); for (int i = 0; i < 6; i++) printf(" %ld", f(A[i], B[i])); printf("\n"); } while (0)

int main(void) {
  RUN(fy_icall_ret);
  RUN(fy_icall_entry);
  RUN(fy_interior);
  RUN(fy_host);
  return 0;
}
