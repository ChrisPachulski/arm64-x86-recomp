/* Concurrency: libdispatch worker threads calling a guest function concurrently, __thread TLV from 16 threads
   (with initializers and a 4 KB TLS array), pthread_key destructors invoked by the host at thread exit. */
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <stdatomic.h>
#include <dispatch/dispatch.h>

#define NT 16
static __thread long tl_calls;
static __thread long tl_shadow = 1000;
static __thread long tl_big[512] = {[0] = 3, [511] = 4};
static atomic_long bad, dtor_sum;
static pthread_key_t key;

static void work(void *ctx, size_t i) {
    long *slots = ctx;
    tl_calls++;
    tl_shadow++;
    if (tl_shadow - tl_calls != 1000 || tl_big[0] + tl_big[511] != 7) atomic_fetch_add(&bad, 1);
    slots[i] = (long)(i * i) + 3;
}
static void key_dtor(void *v) { atomic_fetch_add(&dtor_sum, (long)(intptr_t)v); }
static void *thr(void *arg) {
    long id = (long)(intptr_t)arg;
    for (int i = 0; i < 10000; i++) { tl_calls += id; tl_big[(i + id) & 511] ^= i; }
    pthread_setspecific(key, (void *)(intptr_t)(id + 1));
    return (void *)(intptr_t)(tl_calls + tl_shadow);
}

int main(void) {
    static long slots[1000];
    dispatch_apply_f(1000, dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), slots, work);
    long sum = 0;
    for (int i = 0; i < 1000; i++) sum += slots[i];
    printf("dispatch sum %ld bad %ld\n", sum, atomic_load(&bad));
    pthread_key_create(&key, key_dtor);
    pthread_t t[NT];
    for (long i = 0; i < NT; i++) pthread_create(&t[i], NULL, thr, (void *)(intptr_t)i);
    for (int i = 0; i < NT; i++) {
        void *r;
        pthread_join(t[i], &r);
        printf("%ld%c", (long)(intptr_t)r, i == NT - 1 ? '\n' : ' ');
    }
    printf("dtor_sum %ld main_tl_invariant %ld\n", atomic_load(&dtor_sum), tl_shadow - tl_calls);  /* items on main vary with scheduling */
    return 0;
}
