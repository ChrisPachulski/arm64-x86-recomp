/* catch-and-rethrow through three dylibs: A throws, B and C catch and rethrow, main catches */
#include <stdexcept>
#include <string>

struct AErr : std::runtime_error { int hops; AErr(const std::string& m) : std::runtime_error(m), hops(0) {} ~AErr() override; };
struct BErr : AErr { int b; BErr(const std::string& m, int v) : AErr(m), b(v) {} ~BErr() override; };
template <class T> struct TErr { T v; TErr(T x) : v(x) {} virtual ~TErr() {} };        /* no key function: weak RTTI in every image */
void a_throw(int kind);
void b_call(int kind);
void c_call(int kind);
long a_live();                                                          /* AErr objects alive (ctor - dtor) */
