/* std::exception_ptr: current_exception, rethrow_exception, make_exception_ptr, nested_exception */
#include <cstdio>
#include <exception>
#include <stdexcept>
#include <string>
#include <vector>

std::exception_ptr capture(int k) {
    try {
        if (k == 0) throw std::invalid_argument("bad arg");
        if (k == 1) throw 5;
        throw std::string("str");
    } catch (...) {
        return std::current_exception();
    }
}

void report(std::exception_ptr p) {
    try { std::rethrow_exception(p); }
    catch (std::invalid_argument& e) { printf("invalid_argument: %s\n", e.what()); }
    catch (int v) { printf("int: %d\n", v); }
    catch (std::string& s) { printf("string: %s\n", s.c_str()); }
}

void outer() {
    try { throw std::runtime_error("inner cause"); }
    catch (...) { std::throw_with_nested(std::logic_error("outer wrapper")); }
}

int main() {
    std::vector<std::exception_ptr> v;
    for (int k = 0; k < 3; k++) v.push_back(capture(k));
    for (auto& p : v) report(p);
    for (auto& p : v) report(p);                               /* rethrow twice: the object is shared */
    report(std::make_exception_ptr(std::invalid_argument("made")));
    std::exception_ptr none;
    printf("null ptr is %s\n", none ? "set" : "empty");
    try { outer(); } catch (std::logic_error& e) {
        printf("outer: %s\n", e.what());
        try { std::rethrow_if_nested(e); } catch (std::runtime_error& in) { printf("nested: %s\n", in.what()); }
    }
    printf("uncaught_exceptions %d\n", std::uncaught_exceptions());
    return 0;
}
