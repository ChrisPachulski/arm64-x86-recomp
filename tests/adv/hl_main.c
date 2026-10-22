/* libga binds hl_f to host libhla (returns 1), libgb binds hl_f to host libhlb (returns 2). */
#include <stdio.h>
int ga(void);
int gb(void);
int main(void) { printf("ga %d gb %d\n", ga(), gb()); return 0; }
