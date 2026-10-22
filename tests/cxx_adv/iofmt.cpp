/* iostream formatting: floats (fixed/scientific/hexfloat, precision 0..17, inf/nan/-0, denormals, float limits),
   integer bases with showbase/uppercase/showpos, a custom numpunct grouping facet, named locales, put_time, parsing */
#include <cfloat>
#include <cmath>
#include <cstdio>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
#include <sstream>
#include <string>

struct Grouped : std::numpunct<char> {
    char do_thousands_sep() const override { return '\''; }
    std::string do_grouping() const override { return "\3\2"; }
    char do_decimal_point() const override { return ','; }
    std::string do_truename() const override { return "yes"; }
};

int main() {
    const double vals[] = {0.1, 1.0 / 3.0, -0.0, 1e300 * 10, -1e300 * 10, std::nan(""), DBL_MIN / 4, DBL_MAX, 123456789.125, 5e-324};
    for (double v : vals) {
        std::ostringstream os;
        os << std::setprecision(17) << v << " | " << std::fixed << std::setprecision(3) << v << " | " << std::scientific
           << std::setprecision(0) << v << " | " << std::hexfloat << v << " | " << std::uppercase << v << std::nouppercase;
        std::cout << os.str() << '\n';
    }
    std::cout << std::defaultfloat;
    for (int p = 0; p <= 17; p += 3) std::cout << "prec " << p << ": " << std::setprecision(p) << M_PI << " " << 1e21 * M_PI << " " << FLT_MAX << '\n';
    std::cout << std::setprecision(6) << "float " << 1.0f / 3.0f << " " << FLT_MIN << " " << FLT_EPSILON << " showpoint " << std::showpoint << 2.0 << std::noshowpoint << '\n';
    std::cout << std::showbase << std::hex << 255 << ' ' << std::uppercase << 255 << ' ' << std::nouppercase << std::oct << 8 << ' ' << 0
              << std::dec << std::noshowbase << ' ' << std::showpos << 5 << ' ' << 0 << ' ' << -5 << std::noshowpos << '\n';
    std::cout << std::hex << std::setw(10) << std::internal << std::setfill('0') << std::showbase << 0xBEEF << std::dec << std::noshowbase
              << std::setfill(' ') << " min ll " << std::numeric_limits<long long>::min() << " max ull " << std::numeric_limits<unsigned long long>::max() << '\n';
    std::ostringstream g;
    g.imbue(std::locale(std::locale::classic(), new Grouped));
    g << 1234567890 << ' ' << -98765432.5 << ' ' << std::fixed << std::setprecision(2) << 1234567.891 << ' ' << std::boolalpha << true;
    std::cout << "grouped: " << g.str() << '\n';
    const char* names[] = {"en_US.UTF-8", "de_DE.UTF-8", "fr_FR.ISO8859-1"};
    for (const char* n : names) {
        try {
            std::locale l(n);
            std::ostringstream o;
            o.imbue(l);
            o << 1234567.25 << ' ' << 9876543 << ' ' << std::showbase << std::put_money(123456.0L);
            std::cout << n << ": " << o.str() << " | name " << l.name() << '\n';
        } catch (std::runtime_error& e) { std::cout << n << ": locale error " << e.what() << '\n'; }
    }
    std::tm tm = {};
    tm.tm_year = 126; tm.tm_mon = 9; tm.tm_mday = 16; tm.tm_hour = 13; tm.tm_min = 5; tm.tm_sec = 9; tm.tm_wday = 5; tm.tm_yday = 288;
    std::cout << "put_time " << std::put_time(&tm, "%Y-%m-%d %H:%M:%S %a %b %j %p") << '\n';
    std::istringstream in("0x1F 077 1e400 -1e-400 nan inf 3.5abc 12'345");
    int h = 0, o = 0; double big = 0, tiny = 0, n1 = 0;
    in >> std::hex >> h >> std::oct >> o >> std::dec;
    in >> big; std::cout << "parse hex " << h << " oct " << o << " 1e400 -> " << big << " fail " << in.fail() << '\n';
    in.clear(); in >> tiny; std::cout << "-1e-400 -> " << tiny << " fail " << in.fail() << '\n';
    in.clear(); in >> n1; std::cout << "nan -> " << n1 << " fail " << in.fail() << '\n';
    double t35 = 0; std::string rest;
    std::istringstream in2("3.5abc"); in2 >> t35 >> rest; std::cout << "3.5abc -> " << t35 << " rest " << rest << '\n';
    std::istringstream in3("12'345,5"); in3.imbue(std::locale(std::locale::classic(), new Grouped));
    double gv = 0; in3 >> gv; std::cout << "grouped parse -> " << std::fixed << std::setprecision(1) << gv << " fail " << in3.fail() << '\n';
    return 0;
}
