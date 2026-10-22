/* A host function whose type carries a parameter attribute (dispatch_sync's noescape block) is bridged through its type
   without the attribute (gdyld GD_EH, libclang spelling); the block must run (was loud before; the name is kept). */
#include <stdio.h>
#include <dispatch/dispatch.h>

int main(void) {
    __block int n = 0;
    dispatch_queue_t q = dispatch_queue_create("t", NULL);
    dispatch_sync(q, ^{ n = 5; });
    printf("block ran %d\n", n);
    return 0;
}
