/* a 2 MB frame on a thread whose stack is 256 KB: natively ___chkstk_darwin probes each page and the guard page stops
   it (crash); a silent success means the probe is skipped and the frame landed outside the stack */
#include <cstdio>
#include <pthread.h>

__attribute__((noinline)) long huge(int seed) {
    char a[2 << 20];
    a[0] = (char)seed;
    a[sizeof a - 1] = (char)(seed + 1);
    __asm__ volatile("" : : "r"(a) : "memory");                 /* keep the whole frame */
    return a[0] + a[sizeof a - 1];
}
static void* fn(void*) { return (void*)huge(7); }

int main() {
    printf("start\n");
    fflush(stdout);
    pthread_attr_t at;
    pthread_attr_init(&at);
    pthread_attr_setstacksize(&at, 256 << 10);
    pthread_t t;
    printf("create %d\n", pthread_create(&t, &at, fn, nullptr));
    void* r;
    pthread_join(t, &r);
    printf("returned %ld\n", (long)r);
    return 0;
}
