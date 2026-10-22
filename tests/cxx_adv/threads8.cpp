/* 8 threads throw and catch concurrently (3 frames with destructors each throw), started together on a barrier */
#include <atomic>
#include <condition_variable>
#include <cstdio>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

static std::atomic<long> dtors{0};
struct D { ~D() { dtors.fetch_add(1, std::memory_order_relaxed); } };
struct TErr : std::runtime_error { int t, i; TErr(int a, int b) : std::runtime_error("t" + std::to_string(a)), t(a), i(b) {} };

__attribute__((noinline)) void lvl3(int t, int i) { D d; if (i % 3 != 2) throw TErr(t, i); }
__attribute__((noinline)) void lvl2(int t, int i) { D d; std::string s(40, 'x'); lvl3(t, i); }
__attribute__((noinline)) int lvl1(int t, int i) {
    D d;
    try { lvl2(t, i); return 0; }
    catch (std::logic_error&) { return -1000000; }
}

int main() {
    const int N = 8, ITERS = 4000;
    std::mutex mu; std::condition_variable cv; int ready = 0;
    std::vector<long> sums(N), caught(N);
    std::vector<std::thread> th;
    for (int t = 0; t < N; t++)
        th.emplace_back([&, t] {
            { std::unique_lock<std::mutex> lk(mu); if (++ready == N) cv.notify_all(); else cv.wait(lk, [&] { return ready == N; }); }
            for (int i = 0; i < ITERS; i++) {
                try { sums[t] += lvl1(t, i); }
                catch (TErr& e) { if (e.t != t || e.i != i) printf("CROSSED t%d got t%d i%d/%d\n", t, e.t, e.i, i); sums[t] += e.i; caught[t]++; }
            }
        });
    for (auto& x : th) x.join();
    long tot = 0;
    for (int t = 0; t < N; t++) { printf("thread %d caught %ld sum %ld\n", t, caught[t], sums[t]); tot += caught[t]; }
    printf("total caught %ld dtors %ld\n", tot, dtors.load());
    return 0;
}
