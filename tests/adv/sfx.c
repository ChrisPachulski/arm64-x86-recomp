/* #10 loud: the guest asks for a $-variant the x86-64 host does not have; gdyld must refuse to link rather than call
   the unsuffixed function. Linked -undefined dynamic_lookup, so neither build checks the symbol at link time. */
#include <stdio.h>
extern long read_weird(int, void *, unsigned long) __asm("_read$GDYLDTEST");
int main(void) {
    char b[4];
    printf("%ld\n", read_weird(0, b, 0));
    return 0;
}
