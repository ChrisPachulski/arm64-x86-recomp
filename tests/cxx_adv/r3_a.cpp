#include "r3.h"
static long live;
AErr::~AErr() { live--; }
long a_live() { return live; }
struct Raii { const char* s; ~Raii(); };
Raii::~Raii() { (void)s; }
void a_throw(int kind) {
    Raii r{"a"};
    switch (kind) {
    case 0: live++; throw AErr("from A");
    case 1: throw 42;
    case 2: throw std::string("string from A");
    case 3: throw TErr<int>{7};
    default: live++; throw AErr("A for nested");
    }
}
