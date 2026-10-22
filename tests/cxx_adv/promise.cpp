/* exceptions carried across threads: promise::set_exception, std::async, packaged_task, future_error codes, one
   exception_ptr rethrown concurrently on 8 threads */
#include <atomic>
#include <cstdio>
#include <future>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

struct Payload : std::runtime_error { int v; Payload(int x) : std::runtime_error("payload " + std::to_string(x)), v(x) {} };

int main() {
    std::promise<int> p;
    std::future<int> f = p.get_future();
    std::thread t([&p] { try { throw Payload(1); } catch (...) { p.set_exception(std::current_exception()); } });
    try { f.get(); } catch (Payload& e) { printf("promise: %s v=%d\n", e.what(), e.v); }
    t.join();
    auto a = std::async(std::launch::async, [] { if (true) throw std::out_of_range("async boom"); return 3; });
    try { a.get(); } catch (std::out_of_range& e) { printf("async: %s\n", e.what()); }
    std::packaged_task<int(int)> task([](int x) -> int { if (x > 2) throw Payload(x); return x; });
    auto tf = task.get_future();
    std::thread t2(std::move(task), 5);
    t2.join();
    try { tf.get(); } catch (Payload& e) { printf("packaged_task: %s\n", e.what()); }
    std::future<void> broken;
    { std::promise<void> dead; broken = dead.get_future(); }
    try { broken.get(); } catch (std::future_error& e) { printf("broken promise code %d is broken_promise %d\n", e.code().value(), e.code() == std::future_errc::broken_promise); }
    std::promise<int> twice;
    twice.set_value(1);
    try { twice.set_value(2); } catch (std::future_error& e) { printf("already satisfied %d\n", e.code() == std::future_errc::promise_already_satisfied); }
    std::exception_ptr shared;
    try { throw Payload(99); } catch (...) { shared = std::current_exception(); }
    std::atomic<int> hits{0};
    std::vector<std::thread> ts;
    for (int i = 0; i < 8; i++)
        ts.emplace_back([&] { for (int k = 0; k < 500; k++) { try { std::rethrow_exception(shared); } catch (Payload& e) { if (e.v == 99) hits++; } } });
    for (auto& x : ts) x.join();
    printf("shared exception_ptr rethrown %d times\n", hits.load());
    std::promise<std::string> ps;
    auto fs = ps.get_future().share();
    std::thread t3([&] { ps.set_value(std::string(100, 'z')); });
    t3.join();
    printf("shared_future value len %zu\n", fs.get().size());
    return 0;
}
