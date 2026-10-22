/* exceptions thrown from deep recursion where every level has a handler for a DIFFERENT type (and a destructor), so
   phase 1 walks thousands of non-matching handlers; kind 2 is caught and rethrown at every level until a handler halfway up returns */
#include <cstdio>
#include <stdexcept>
#include <string>

static long dtors, rethrows;
struct D { int n; ~D() { dtors += n & 1 ? 1 : 2; } };

__attribute__((noinline)) int dive(int n, int limit, int kind) {
    D guard{n};
    try {
        if (n == limit) {
            if (kind == 0) throw std::runtime_error("bottom " + std::to_string(n));
            if (kind == 1) throw n;
            throw std::out_of_range("range " + std::to_string(n));
        }
        return dive(n + 1, limit, kind) + 1;
    } catch (std::logic_error& e) {
        if (kind == 2 && n == limit / 2) { printf("  mid handler at %d: %s\n", n, e.what()); return -n; }
        rethrows++;                                            /* every other level catches and rethrows */
        throw;
    } catch (double) {
        printf("  WRONG double handler at %d\n", n);
        return -2;
    }
}

int main() {
    const int depths[] = {1, 10, 1000, 20000};
    for (int kind = 0; kind < 3; kind++)
        for (int limit : depths) {
            dtors = rethrows = 0;
            long r = 0;
            try { r = dive(0, limit, kind); printf("kind %d depth %d returned %ld", kind, limit, r); }
            catch (std::runtime_error& e) { printf("kind %d depth %d caught runtime_error %s", kind, limit, e.what()); }
            catch (int v) { printf("kind %d depth %d caught int %d", kind, limit, v); }
            catch (std::exception& e) { printf("kind %d depth %d caught exception %s", kind, limit, e.what()); }
            printf(" | dtors %ld rethrows %ld\n", dtors, rethrows);
        }
    return 0;
}
