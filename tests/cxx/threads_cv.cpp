/* std::thread + mutex + condition_variable: a bounded producer/consumer queue and a counter under a mutex */
#include <condition_variable>
#include <cstdio>
#include <deque>
#include <mutex>
#include <thread>
#include <vector>

int main() {
    std::mutex mu;
    std::condition_variable cv_full, cv_empty;
    std::deque<int> q;
    const int N = 2000, CAP = 8;
    long consumed = 0; int count = 0;
    std::thread consumer([&] {
        for (int i = 0; i < N; i++) {
            std::unique_lock<std::mutex> lk(mu);
            cv_empty.wait(lk, [&] { return !q.empty(); });
            consumed += q.front(); q.pop_front(); count++;
            cv_full.notify_one();
        }
    });
    std::thread producer([&] {
        for (int i = 1; i <= N; i++) {
            std::unique_lock<std::mutex> lk(mu);
            cv_full.wait(lk, [&] { return (int)q.size() < CAP; });
            q.push_back(i);
            cv_empty.notify_one();
        }
    });
    producer.join(); consumer.join();
    printf("consumed %d items sum %ld (expect %ld)\n", count, consumed, (long)N * (N + 1) / 2);
    long counter = 0;
    std::vector<std::thread> ts;
    for (int t = 0; t < 8; t++)
        ts.emplace_back([&, t] { for (int i = 0; i < 1000; i++) { std::lock_guard<std::mutex> g(mu); counter += t; } });
    for (auto& t : ts) t.join();
    printf("counter %ld (expect %ld)\n", counter, 1000L * 28);
    std::mutex m2; std::condition_variable cv2; bool ready = false;
    std::thread waiter([&] {
        std::unique_lock<std::mutex> lk(m2);
        bool ok = cv2.wait_for(lk, std::chrono::seconds(10), [&] { return ready; });
        printf("wait_for returned %d\n", ok);
    });
    { std::lock_guard<std::mutex> g(m2); ready = true; }
    cv2.notify_all();
    waiter.join();
    printf("joinable after join %d, id differs %d\n", waiter.joinable(), std::this_thread::get_id() != std::thread::id());
    return 0;
}
