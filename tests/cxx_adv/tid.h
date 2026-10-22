/* typeid / dynamic_cast / catch of polymorphic types across two images, including types with NO key function (weak
   RTTI emitted in both images) and templates */
#include <string>
#include <typeinfo>

struct Shape { virtual ~Shape(); virtual int sides() const = 0; };
struct Square : Shape { int sides() const override; };                  /* key function in the lib */
struct Blob : Shape { int sides() const override { return 0; } };       /* inline only: weak RTTI in both images */
template <class T> struct Poly : Shape { T v{}; int sides() const override { return (int)sizeof(T); } };
struct Weird : Blob, std::exception { const char* what() const noexcept override { return "weird"; } };
Shape* lib_make(int k);                                                   /* 0 Square 1 Blob 2 Poly<int> 3 Poly<double> 4 Weird */
const std::type_info& lib_type(int k);                                    /* typeid of the static type, taken in the lib */
void lib_throw(int k);                                                    /* throws the same object kinds by value */
bool lib_is_blob(const Shape* s);
const char* lib_anon_name();
const std::type_info& lib_anon_type();
