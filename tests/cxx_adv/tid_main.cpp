#include "tid.h"
#include <cstdio>
#include <typeindex>
#include <unordered_map>
namespace { struct Anon : Shape { int sides() const override { return -1; } }; }

int main() {
    const std::type_info* mine[] = {&typeid(Square), &typeid(Blob), &typeid(Poly<int>), &typeid(Poly<double>), &typeid(Weird)};
    std::unordered_map<std::type_index, int> idx;
    for (int k = 0; k < 5; k++) idx[std::type_index(*mine[k])] = k;
    for (int k = 0; k < 5; k++) {
        Shape* s = lib_make(k);
        const std::type_info& dyn = typeid(*s);
        printf("k %d %-16s sides %d | typeid==main %d lib==main %d hash== %d index->%d | dyncast Blob main %d lib %d Poly<int> %d exception %d\n",
               k, dyn.name(), s->sides(), dyn == *mine[k], lib_type(k) == *mine[k], dyn.hash_code() == mine[k]->hash_code(),
               idx.count(std::type_index(dyn)) ? idx[std::type_index(dyn)] : -1, dynamic_cast<Blob*>(s) != nullptr, lib_is_blob(s),
               dynamic_cast<Poly<int>*>(s) != nullptr, dynamic_cast<std::exception*>(s) != nullptr);
        delete s;
        try { lib_throw(k); }
        catch (Poly<double>& e) { printf("  caught Poly<double> sides %d\n", e.sides()); }
        catch (Poly<int>& e) { printf("  caught Poly<int> sides %d\n", e.sides()); }
        catch (std::exception& e) { printf("  caught std::exception %s\n", e.what()); }
        catch (Blob& e) { printf("  caught Blob\n"); }
        catch (Shape& e) { printf("  caught Shape sides %d\n", e.sides()); }
    }
    printf("anon: same name %d equal %d\n", std::string(lib_anon_name()) == typeid(Anon).name(), lib_anon_type() == typeid(Anon));
    return 0;
}
