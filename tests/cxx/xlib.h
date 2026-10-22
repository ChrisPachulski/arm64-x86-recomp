/* exceptions crossing a guest dylib boundary, both directions */
#include <stdexcept>
#include <string>

struct LibError : std::runtime_error {
    int code;
    LibError(const std::string& m, int c) : std::runtime_error(m), code(c) {}
};
void lib_fail(int code);                                       /* throws LibError from inside the dylib */
int lib_call_back(int (*cb)(int), int x);                      /* calls cb through dylib frames with RAII */
int lib_catch_main_error(void (*cb)());                        /* catches what main throws, returns a code */
