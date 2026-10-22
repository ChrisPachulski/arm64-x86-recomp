/* A guest block passed to the host (dispatch_async): gobjc.hpp gives it a typed invoke closure in place; it must run (was loud
   before blocks were bridged; the name is kept). */
#include <stdio.h>
#include <dispatch/dispatch.h>

static void drain(void *ctx) { (void)ctx; }

int main(void) {
    __block int n = 0;
    dispatch_queue_t q = dispatch_queue_create("t", NULL);
    dispatch_async(q, ^{ n = 5; });
    dispatch_sync_f(q, NULL, drain);                         /* serial queue: the block has run */
    printf("block ran %d\n", n);
    return 0;
}
