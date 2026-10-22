#include "r3.h"
#include <cstdio>
#include <exception>
void c_call(int kind) {
    try { b_call(kind); }
    catch (AErr& e) {
        e.hops++;
        printf("  C saw AErr hops=%d\n", e.hops);
        if (kind == 4) { std::exception_ptr p = std::current_exception(); std::rethrow_exception(p); }
        if (kind == 5) throw BErr(std::string("C replaced: ") + e.what(), e.hops);
        throw;
    }
    catch (TErr<int>& e) { e.v += 1; printf("  C saw TErr<int> v=%d\n", e.v); throw; }
    catch (int v) { printf("  C saw int %d\n", v); throw v + 1; }
}
