/* function-try-blocks: constructor (member and base initialisers throw; handler runs after members are destroyed and
   the exception is rethrown implicitly), destructor (noexcept(false), handler rethrows), plain function returning
   from its handler, and main itself */
#include <cstdio>
#include <stdexcept>
#include <string>

static std::string log_;
struct Member { int id; Member(int i, bool fail) : id(i) { if (fail) throw std::runtime_error("member " + std::to_string(i)); log_ += "M" + std::to_string(i); }
                ~Member() { log_ += "~M" + std::to_string(id); } };
struct Base { Base(bool fail) { if (fail) throw 7; log_ += "B"; } ~Base() { log_ += "~B"; } };
struct Widget : Base {
    Member a, b;
    Widget(int failwhere) try : Base(failwhere == 0), a(1, failwhere == 1), b(2, failwhere == 2) {
        log_ += "W";
        if (failwhere == 3) throw std::logic_error("body");
    } catch (std::exception& e) {
        log_ += "[ctor handler " + std::string(e.what()) + "]";
    } catch (int v) {
        log_ += "[ctor handler int " + std::to_string(v) + "]";
    }
    ~Widget() noexcept(false) try {
        log_ += "~W";
        if (a.id == 1 && b.id == 2 && throw_in_dtor) throw std::out_of_range("dtor");
    } catch (std::out_of_range& e) {
        log_ += "[dtor handler]";
    }
    static bool throw_in_dtor;
};
bool Widget::throw_in_dtor = false;

__attribute__((noinline)) int parse(const char* s) try {
    return std::stoi(s);
} catch (std::invalid_argument&) {
    return -1;
} catch (std::out_of_range&) {
    return -2;
}

int main() try {
    for (int w = 0; w < 5; w++) {
        log_.clear();
        try { Widget x(w); log_ += "|ok|"; }
        catch (std::exception& e) { log_ += "|main " + std::string(e.what()) + "|"; }
        catch (int v) { log_ += "|main int " + std::to_string(v) + "|"; }
        printf("fail at %d: %s\n", w, log_.c_str());
    }
    log_.clear();
    Widget::throw_in_dtor = true;
    try { Widget x(4); } catch (std::out_of_range& e) { log_ += "|main " + std::string(e.what()) + "|"; }
    printf("dtor throws: %s\n", log_.c_str());
    printf("parse %d %d %d\n", parse("42"), parse("zz"), parse("99999999999999"));
    throw std::runtime_error("from main body");
} catch (std::exception& e) {
    printf("main handler: %s\n", e.what());
    return 4;
}
