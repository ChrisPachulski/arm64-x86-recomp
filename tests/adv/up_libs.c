/* #11 upward dylibs. UP_A initializes state and upward-links UP_B; UP_B (built -undefined dynamic_lookup) reads A's
   state in its constructor. dyld skips the upward edge while initializing bottom-up and runs B as a dangling upward
   link after the executable's own initializers: A, main, B (B sees A's state). */
#include <stdio.h>
#ifdef UP_A
static int state;
__attribute__((constructor)) static void a_ctor(void) { state = 42; printf("A ctor\n"); }
int a_state(void) { return state; }
int b_hello(void);
int a_calls_b(void) { return b_hello(); }
#endif
#ifdef UP_B
int a_state(void);
__attribute__((constructor)) static void b_ctor(void) { printf("B ctor sees A=%d\n", a_state()); }
int b_hello(void) { return 3; }
#endif
