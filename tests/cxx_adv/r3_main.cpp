#include "r3.h"
#include <cstdio>
int main() {
    for (int kind = 0; kind < 6; kind++) {
        printf("kind %d\n", kind);
        try { c_call(kind); }
        catch (BErr& e) { printf("main BErr %s hops=%d b=%d\n", e.what(), e.hops, e.b); }
        catch (AErr& e) { printf("main AErr %s hops=%d\n", e.what(), e.hops); }
        catch (TErr<int>& e) { printf("main TErr<int> v=%d\n", e.v); }
        catch (int v) { printf("main int %d\n", v); }
        catch (std::string& s) { printf("main string %s\n", s.c_str()); }
        catch (...) { printf("main WRONG catch-all\n"); }
        printf("  live AErr %ld\n", a_live());
    }
    return 0;
}
