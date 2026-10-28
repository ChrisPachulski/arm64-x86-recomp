/* a call through a null function pointer stops loudly (not a malloc zone's absent slot, which also reads 0) */
#include <stdio.h>

void (*volatile fn)(void);

int main(void) {
  printf("calling null\n");
  fflush(stdout);
  fn();
  return 0;
}
