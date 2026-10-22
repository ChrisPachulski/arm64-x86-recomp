/* #12 LC_ROUTINES_64: seed() is the dylib's -init routine and must run before its constructors. The x86_64 oracle
   links with -init (ld turns it into the first initializer); the arm64 guest gets a real LC_ROUTINES_64 command
   patched into its header by run_adv.py, since current linkers no longer emit one. */
#include <stdio.h>
int seeded;
void seed(void) { seeded = 7; printf("seed (-init)\n"); }
__attribute__((constructor)) static void ctor(void) { printf("ctor sees %d\n", seeded); }
int get(void) { return seeded; }
