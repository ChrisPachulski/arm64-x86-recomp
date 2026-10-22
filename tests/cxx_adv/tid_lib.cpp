#include "tid.h"
Shape::~Shape() {}
int Square::sides() const { return 4; }
namespace { struct Anon : Shape { int sides() const override { return -1; } }; }
Shape* lib_make(int k) {
    switch (k) { case 0: return new Square; case 1: return new Blob; case 2: return new Poly<int>; case 3: return new Poly<double>; default: return new Weird; }
}
const std::type_info& lib_type(int k) {
    switch (k) { case 0: return typeid(Square); case 1: return typeid(Blob); case 2: return typeid(Poly<int>); case 3: return typeid(Poly<double>); default: return typeid(Weird); }
}
void lib_throw(int k) {
    switch (k) { case 0: throw Square(); case 1: throw Blob(); case 2: throw Poly<int>(); case 3: throw Poly<double>(); default: throw Weird(); }
}
bool lib_is_blob(const Shape* s) { return dynamic_cast<const Blob*>(s) != nullptr; }
const char* lib_anon_name() { return typeid(Anon).name(); }
const std::type_info& lib_anon_type() { return typeid(Anon); }
