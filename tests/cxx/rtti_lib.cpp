#include "rtti.h"

Animal::~Animal() {}
Mixin::~Mixin() {}
const char* Dog::sound() const { return "woof"; }
const char* Puppy::sound() const { return "yip"; }
const char* Cat::sound() const { return "meow"; }
const char* Robot::sound() const { return "beep"; }
Animal* make_animal(int k) {
    switch (k) { case 0: return new Dog; case 1: return new Puppy; case 2: return new Cat; default: return new Robot; }
}
const std::type_info& lib_typeid_of(const Animal* a) { return typeid(*a); }
bool lib_is_dog(const Animal* a) { return dynamic_cast<const Dog*>(a) != nullptr; }
