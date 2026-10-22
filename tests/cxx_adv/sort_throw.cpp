/* std::sort / stable_sort / std::set with a comparator that throws after k comparisons: the exception reaches the
   caller, the container still holds a permutation of its elements, the temporary buffer is released */
#include <algorithm>
#include <cstdio>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

struct Boom { long at; };
static long ncmp, limit;
struct Cmp { bool operator()(int a, int b) const { if (++ncmp == limit) throw Boom{ncmp}; return a < b; } };
struct SCmp { bool operator()(const std::string& a, const std::string& b) const { if (++ncmp == limit) throw Boom{ncmp}; return a < b; } };

static unsigned long hash_seq(const std::vector<int>& v) { unsigned long h = 1469598103934665603UL; for (int x : v) h = (h ^ (unsigned)x) * 1099511628211UL; return h; }

int main() {
    std::vector<int> base(2000);
    for (int i = 0; i < 2000; i++) base[i] = (i * 7919) % 2003;
    const long ks[] = {1, 10, 500, 5000, 20000};
    for (long k : ks) {
        for (int alg = 0; alg < 3; alg++) {
            std::vector<int> v = base;
            ncmp = 0; limit = k;
            const char* what = "completed";
            try {
                if (alg == 0) std::sort(v.begin(), v.end(), Cmp());
                else if (alg == 1) std::stable_sort(v.begin(), v.end(), Cmp());
                else std::partial_sort(v.begin(), v.begin() + 100, v.end(), Cmp());
            } catch (Boom& b) { what = "threw"; }
            std::vector<int> s = v, sb = base;
            std::sort(s.begin(), s.end()); std::sort(sb.begin(), sb.end());
            printf("k %5ld alg %d %s after %ld cmps | permutation %d | seq hash %lx\n", k, alg, what, ncmp, s == sb, hash_seq(v));
        }
    }
    std::vector<std::string> words;
    for (int i = 0; i < 300; i++) words.push_back(std::string(1 + i % 7, (char)('a' + (i * 13) % 26)) + std::to_string(i));
    ncmp = 0; limit = 900;
    try { std::sort(words.begin(), words.end(), SCmp()); } catch (Boom& b) { printf("string sort threw at %ld\n", b.at); }
    size_t total = 0; for (auto& w : words) total += w.size();
    printf("strings intact total length %zu first %s\n", total, words[0].c_str());
    std::set<int, Cmp> st;
    ncmp = 0; limit = 50;
    int inserted = 0;
    try { for (int i = 0; i < 100; i++) { st.insert(base[i]); inserted++; } } catch (Boom&) { printf("set insert threw after %d inserts, size %zu\n", inserted, st.size()); }
    limit = -1;
    long sum = 0; for (int x : st) sum += x;
    printf("set sum %ld\n", sum);
    return 0;
}
