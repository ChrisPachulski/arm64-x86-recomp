/* voucher_adopt, weakly imported as Swift's concurrency back-deployment shim does (test the pointer, then call): adopt NULL to
   take the thread's voucher, adopt it back, on the main thread and inside a dispatch block. */
#include <dispatch/dispatch.h>
#include <stdio.h>

extern void* voucher_adopt(void* v) __attribute__((weak_import));   /* libdispatch, no public header */

static void take_and_restore(const char* where) {
    void* v = voucher_adopt(NULL);
    void* back = voucher_adopt(v);
    printf("%s: voucher present %d, adopt-back returned NULL %d\n", where, v != NULL, back == NULL);
}

int main(void) {
    printf("voucher_adopt resolved: %d\n", &voucher_adopt != NULL);
    if (&voucher_adopt == NULL) return 1;
    take_and_restore("main thread");
    dispatch_queue_t q = dispatch_queue_create("gd.voucher", DISPATCH_QUEUE_SERIAL);
    dispatch_sync(q, ^{ take_and_restore("dispatch_sync block"); });
    dispatch_semaphore_t s = dispatch_semaphore_create(0);
    dispatch_async(q, ^{ take_and_restore("dispatch_async block"); dispatch_semaphore_signal(s); });
    dispatch_semaphore_wait(s, DISPATCH_TIME_FOREVER);
    return 0;
}
