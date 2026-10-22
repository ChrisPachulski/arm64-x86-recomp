/* RTTI across two images: classes defined in the dylib, cast and named in main */
#include <typeinfo>

struct Animal { virtual ~Animal(); virtual const char* sound() const = 0; };
struct Dog : Animal { const char* sound() const override; };
struct Puppy : Dog { const char* sound() const override; };
struct Cat : Animal { const char* sound() const override; };
struct Mixin { virtual ~Mixin(); int tagv = 5; };
struct Robot : Mixin, Dog { const char* sound() const override; };
Animal* make_animal(int k);                                    /* 0 Dog, 1 Puppy, 2 Cat, 3 Robot */
const std::type_info& lib_typeid_of(const Animal* a);
bool lib_is_dog(const Animal* a);
