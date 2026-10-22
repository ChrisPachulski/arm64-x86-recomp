/* std::string / vector / map / unordered_map / shared_ptr / function */
#include <algorithm>
#include <cstdio>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

struct Tracked { int v; explicit Tracked(int x) : v(x) { printf("Tracked %d\n", v); } ~Tracked() { printf("~Tracked %d\n", v); } };

int main() {
    std::string s = "short";
    std::string l = "a considerably longer string that cannot use the small buffer";
    s += " + appended"; l.append(3, '!');
    printf("strings [%s] %zu [%s] %zu find %zu substr [%s]\n", s.c_str(), s.size(), l.c_str(), l.size(), l.find("longer"), l.substr(2, 12).c_str());
    std::vector<int> v;
    for (int i = 0; i < 100; i++) v.push_back((i * 37) % 101);
    std::sort(v.begin(), v.end());
    long sum = 0; for (int x : v) sum += x;
    printf("vector size %zu front %d back %d sum %ld\n", v.size(), v.front(), v.back(), sum);
    std::vector<std::string> vs = {"pear", "apple", "fig"};
    std::sort(vs.begin(), vs.end());
    printf("sorted strings %s %s %s\n", vs[0].c_str(), vs[1].c_str(), vs[2].c_str());
    std::map<std::string, int> m;
    for (auto& w : {"one", "two", "three", "two", "one", "one"}) m[w]++;
    for (auto& [k, c] : m) printf("map %s=%d\n", k.c_str(), c);
    std::unordered_map<std::string, int> um;
    for (int i = 0; i < 500; i++) um["k" + std::to_string(i % 50)] += i;
    std::vector<std::pair<std::string, int>> items(um.begin(), um.end());
    std::sort(items.begin(), items.end());
    printf("unordered_map size %zu first %s=%d last %s=%d\n", um.size(), items.front().first.c_str(), items.front().second,
           items.back().first.c_str(), items.back().second);
    {
        auto a = std::make_shared<Tracked>(1);
        std::shared_ptr<Tracked> b = a;
        std::weak_ptr<Tracked> w = a;
        printf("use_count %ld\n", a.use_count());
        a.reset();
        printf("after reset use_count %ld expired %d\n", b.use_count(), w.expired());
        std::unique_ptr<Tracked> u(new Tracked(2));
    }
    std::function<int(int)> f = [k = 3](int x) { return x * k; };
    std::function<int(int)> g = [&f](int x) { return f(x) + 1; };
    int (*plain)(int) = [](int x) { return -x; };
    std::function<int(int)> h = plain;
    printf("function %d %d %d empty %d\n", f(5), g(5), h(5), !std::function<void()>());
    try { std::function<void()> e; e(); } catch (std::bad_function_call&) { printf("bad_function_call caught\n"); }
    try { v.at(1000); } catch (std::out_of_range&) { printf("vector::at out_of_range caught\n"); }
    return 0;
}
