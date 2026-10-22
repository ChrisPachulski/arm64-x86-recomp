#include "r3.h"
#include <cstdio>
BErr::~BErr() {}
void b_call(int kind) {
    try { a_throw(kind); }
    catch (AErr& e) { e.hops++; printf("  B saw AErr hops=%d\n", e.hops); throw; }
    catch (TErr<int>& e) { e.v *= 10; printf("  B saw TErr<int> v=%d\n", e.v); throw; }
    catch (...) { printf("  B saw other\n"); throw; }
}
