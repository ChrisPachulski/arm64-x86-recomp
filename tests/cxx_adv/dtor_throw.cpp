/* exceptions thrown while another is in flight: a destructor run during unwinding throws and catches locally (three
   frames deep inside the destructor), a catch block throws and catches a second exception, then rethrows the first */
#include <cstdio>
#include <exception>
#include <stdexcept>
#include <string>

__attribute__((noinline)) void inner3(const std::string& s) { throw std::logic_error("inner from " + s); }
__attribute__((noinline)) void inner2(const std::string& s) { std::string t = s + "+"; inner3(t); }
__attribute__((noinline)) void inner1(const std::string& s) { std::string t = s + "+"; inner2(t); }

struct Cleaner {
    const char* n;
    ~Cleaner() {
        printf("~%s uncaught=%d\n", n, std::uncaught_exceptions());
        try { inner1(n); }
        catch (std::exception& e) { printf("  dtor %s caught '%s' uncaught=%d\n", n, e.what(), std::uncaught_exceptions()); }
    }
};
struct Deeper {                                                /* a destructor whose own local unwinding runs a Cleaner */
    ~Deeper() {
        try { Cleaner c{"deeper-inner"}; throw 5; }
        catch (int v) { printf("  Deeper caught int %d uncaught=%d\n", v, std::uncaught_exceptions()); }
    }
};

__attribute__((noinline)) void f3() { Cleaner c{"f3"}; Deeper d; throw std::runtime_error("outer"); }
__attribute__((noinline)) void f2() { Cleaner c{"f2"}; f3(); }
__attribute__((noinline)) void f1() { Cleaner c{"f1"}; f2(); }

int main() {
    try { f1(); } catch (std::exception& e) { printf("main caught '%s' uncaught=%d\n", e.what(), std::uncaught_exceptions()); }
    try {
        throw std::runtime_error("first");
    } catch (std::exception& first) {
        try { throw std::out_of_range("second"); }
        catch (std::exception& second) {
            std::exception_ptr cur = std::current_exception();
            try { std::rethrow_exception(cur); } catch (std::out_of_range& again) { printf("cur is second: %s\n", again.what()); }
            printf("in second handler, first=%s second=%s\n", first.what(), second.what());
        }
        try { throw; } catch (std::runtime_error& again) { printf("rethrow after nested handler: %s\n", again.what()); }
    }
    printf("after: current_exception null %d uncaught=%d\n", std::current_exception() == nullptr, std::uncaught_exceptions());
    return 0;
}
