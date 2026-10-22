/* Large guest stack: 100k-frame recursion on main, a 2 MB frame (chkstk path), and 1M frames on a thread
   whose attr asks for a 128 MB stack (guest stack size must follow pthread_attr_setstacksize). */
#include <stdio.h>
#include <string.h>
#include <pthread.h>

__attribute__((noinline)) static long rec(long n, volatile long *sink) {
    if (n == 0) return 0;
    long r = rec(n - 1, sink) + (n & 7);
    *sink = r;
    return r;
}
__attribute__((noinline)) static long big_frame(int k) {
    volatile char buf[2 << 20];
    for (size_t i = 0; i < sizeof buf; i += 4096) buf[i] = (char)(i >> 12) + k;
    long s = 0;
    for (size_t i = 0; i < sizeof buf; i += 4096) s += buf[i];
    return s;
}
static void *deep(void *a) { volatile long s; return (void *)rec((long)a, &s); }

int main(void) {
    volatile long s;
    printf("rec100k %ld\n", rec(100000, &s));
    printf("big_frame %ld\n", big_frame(1));
    pthread_attr_t at;
    pthread_attr_init(&at);
    pthread_attr_setstacksize(&at, 128u << 20);
    pthread_t th;
    void *r;
    pthread_create(&th, &at, deep, (void *)1000000L);
    pthread_join(th, &r);
    printf("thread rec1M %ld\n", (long)r);
    return 0;
}
