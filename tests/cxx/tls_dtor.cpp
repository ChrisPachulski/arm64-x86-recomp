/* thread_local objects with non-trivial destructors (_tlv_atexit): per thread, in reverse construction order, before
   the thread is joined; on the main thread before static destructors at exit */
#include <cstdio>
#include <mutex>
#include <string>
#include <thread>

std::mutex out_mu;
struct Noisy {
    std::string name;
    explicit Noisy(std::string n) : name(std::move(n)) { std::lock_guard<std::mutex> g(out_mu); printf("construct %s\n", name.c_str()); }
    ~Noisy() { std::lock_guard<std::mutex> g(out_mu); printf("destroy %s\n", name.c_str()); fflush(stdout); }
};
thread_local Noisy tl_a("tl_a");
thread_local Noisy tl_b("tl_b");
thread_local int tl_counter = 0;
Noisy static_obj("static_obj");

void touch(const char* who) {
    tl_a.name += std::string("+") + who;
    tl_b.name += "+b";
    tl_counter++;
    std::lock_guard<std::mutex> g(out_mu);
    printf("%s sees %s %s counter %d\n", who, tl_a.name.c_str(), tl_b.name.c_str(), tl_counter);
}

int main() {
    std::thread t1([] { touch("t1"); touch("t1"); });
    t1.join();
    printf("t1 joined\n");
    std::thread t2([] { thread_local Noisy fn_local("fn_local_t2"); touch("t2"); });
    t2.join();
    printf("t2 joined\n");
    touch("main");
    printf("main returns\n");
    return 0;
}
