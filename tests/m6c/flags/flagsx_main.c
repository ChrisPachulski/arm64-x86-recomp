#include <stdio.h>
typedef long (*Drv)(long, long);
long fx_ret_direct(long, long), fx_ret_nested(long, long), fx_ret_tail(long, long);
long fx_entry_direct(long, long), fx_entry_thunk(long, long), fx_entry_call(long, long);
static const long A[] = {5, 5, 7, 1, 9, 9}, B[] = {5, 6, 7, 2, 9, 3};

#define RUN(f) do { printf("%-16s", #f); for (int i = 0; i < 6; i++) printf(" %ld", f(A[i], B[i])); printf("\n"); } while (0)

int main(void) {
  RUN(fx_ret_direct);
  RUN(fx_ret_nested);
  RUN(fx_ret_tail);
  RUN(fx_entry_direct);
  RUN(fx_entry_thunk);
  RUN(fx_entry_call);
  return 0;
}
