/* iostreams: std::cout and ostringstream with integers and floating point, manipulators, std::locale("C"), parsing back */
#include <iomanip>
#include <iostream>
#include <locale>
#include <sstream>
#include <string>

int main() {
    std::cout << "int " << 42 << " neg " << -17 << " long " << 1234567890123LL << " unsigned " << 4000000000u << '\n';
    std::cout << "double " << 3.14159 << " sci " << std::scientific << 6.02e23 << std::defaultfloat << " small " << 1e-7 << '\n';
    std::cout << "fixed " << std::fixed << std::setprecision(3) << 2.0 / 3.0 << " " << -0.5 << std::defaultfloat << '\n';
    std::cout << "hex " << std::hex << 255 << " oct " << std::oct << 8 << std::dec << " bool " << std::boolalpha << true << '\n';
    std::cout << "width [" << std::setw(8) << std::left << "ab" << "][" << std::setw(6) << std::right << std::setfill('*') << 7 << "]\n";
    std::cout << std::setfill(' ');
    std::ostringstream os;
    os << "x=" << 12 << ",y=" << 2.5 << ",z=" << 1.0f / 3.0f << ",c=" << 'q';
    std::cout << "ostringstream: " << os.str() << " (" << os.str().size() << " chars)\n";
    std::ostringstream loc;
    loc.imbue(std::locale("C"));
    loc << 1234567 << " " << 1234.5;
    std::cout << "locale C: " << loc.str() << " name " << std::locale("C").name() << " global " << std::locale().name() << '\n';
    std::istringstream in("17 2.75 word -3");
    int a = 0, d = 0; double b = 0; std::string w;
    in >> a >> b >> w >> d;
    std::cout << "parsed " << a << " " << b << " " << w << " " << d << " ok " << bool(in) << '\n';
    std::cout << "isdigit " << std::isdigit('7', std::locale("C")) << " toupper " << std::toupper('m', std::locale::classic()) << '\n';
    std::cerr << "to stderr\n";
    std::cout << "to_string " << std::to_string(99) << " " << std::to_string(1.5) << " stoi " << std::stoi("-88") << " stod " << std::stod("6.25") << std::endl;
    return 0;
}
