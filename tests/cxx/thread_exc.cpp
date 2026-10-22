/* exceptions thrown and caught inside std::thread bodies, on several threads at once, and one carried back via
   exception_ptr */
#include <cstdio>
#include <exception>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

struct G { int t; ~G() { results[t] += 1000; } static int results[8]; };
int G::results[8];

__attribute__((noinline)) void work(int t, int i) { if (i % 3 == 0) throw std::runtime_error("t" + std::to_string(t)); }

int main() {
    std::vector<std::thread> ts;
    int caught[8] = {0};
    for (int t = 0; t < 8; t++)
        ts.emplace_back([t, &caught] {
            for (int i = 0; i < 300; i++) {
                try { G g{t}; work(t, i); } catch (std::runtime_error& e) { if (e.what()[1] - '0' == t) caught[t]++; }
            }
        });
    for (auto& t : ts) t.join();
    for (int t = 0; t < 8; t++) printf("thread %d caught %d guards %d\n", t, caught[t], G::results[t]);
    std::exception_ptr carried;
    std::thread th([&carried] { try { throw std::logic_error("from worker"); } catch (...) { carried = std::current_exception(); } });
    th.join();
    try { std::rethrow_exception(carried); } catch (std::logic_error& e) { printf("main rethrew: %s\n", e.what()); }
    return 0;
}
