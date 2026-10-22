/* #6 weak-definition coalescing across images: a C++17 inline variable, a template static and a weak C function
   that one image defines strongly must each end up at one address. The typeinfo of a class without a key function is
   NOT coalesced on Apple arm64 (hidden per image, non-unique RTTI: equality compares the names, flagged by the top
   bit of the name pointer), so it is compared with ==, which must hold in every image. */
#include <typeinfo>
struct Shape { virtual ~Shape() {} virtual int sides() const { return 0; } };
inline int counter = 100;
template<class T> struct Reg { static int n; };
template<class T> int Reg<T>::n = 7;
extern "C" int pick(void);
struct Info { const void *counter; const std::type_info *ti; const void *reg; int pick; };
Info lib_a();
Info lib_b();
