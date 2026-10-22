/* very large frames with landing pads: 2 MB locals recursing twice on the 8 MB main stack, and a 6 MB frame on a
   pthread created with a 16 MB stack; the arrays must survive the catch */
#include <cstdio>
#include <cstring>
#include <pthread.h>
#include <stdexcept>

__attribute__((noinline)) void thrower(int k) { if (k) throw std::runtime_error("big frame throw"); }

template <int MB> __attribute__((noinline)) long big(int depth, int seed) {
    char a[MB << 20];
    memset(a, seed, sizeof a);
    a[0] = (char)(seed + 1);
    long r = 0;
    try {
        if (depth) r = big<MB>(depth - 1, seed + 1);
        thrower(depth == 0);
    } catch (std::runtime_error& e) {
        r += 1000;
    }
    long s = 0;
    for (size_t i = 0; i < sizeof a; i += 4096) s += a[i];
    return r + s + a[0];
}
static void* thread_fn(void*) { return (void*)big<6>(0, 3); }

int main() {
    printf("main 2MB x3 frames: %ld\n", big<2>(2, 1));
    pthread_attr_t at;
    pthread_attr_init(&at);
    pthread_attr_setstacksize(&at, 16 << 20);
    pthread_t t;
    pthread_create(&t, &at, thread_fn, nullptr);
    void* r;
    pthread_join(t, &r);
    printf("thread 6MB frame: %ld\n", (long)r);
    return 0;
}
