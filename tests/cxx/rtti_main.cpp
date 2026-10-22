#include <cstdio>
#include "rtti.h"

struct Local : Cat { const char* sound() const override { return "local"; } };

int main() {
    Animal* zoo[] = {make_animal(0), make_animal(1), make_animal(2), make_animal(3), new Local};
    for (Animal* a : zoo) {
        const Dog* d = dynamic_cast<const Dog*>(a);
        const Puppy* p = dynamic_cast<const Puppy*>(a);
        Mixin* m = dynamic_cast<Mixin*>(a);                    /* cross-cast to a sibling base */
        printf("%-12s sound %-6s dog %d puppy %d mixin %d libdog %d same-type %d ptr-name-match %d\n", typeid(*a).name(),
               a->sound(), d != nullptr, p != nullptr, m ? m->tagv : -1, lib_is_dog(a), typeid(*a) == lib_typeid_of(a),
               typeid(*a).name() == lib_typeid_of(a).name());
    }
    printf("typeid(Dog) main==lib %d, before(Cat,Dog) consistent %d\n", typeid(Dog) == lib_typeid_of(zoo[0]),
           typeid(Cat).before(typeid(Dog)) != typeid(Dog).before(typeid(Cat)));
    try { Animal& r = *zoo[2]; (void)dynamic_cast<Dog&>(r); }
    catch (std::bad_cast& e) { printf("bad_cast caught\n"); }
    try { Animal* n = nullptr; (void)typeid(*n); }
    catch (std::bad_typeid& e) { printf("bad_typeid caught\n"); }
    for (Animal* a : zoo) delete a;
    return 0;
}
