/* static-initialization order across images: the dylib's globals are built before main's; within a unit in
   definition order; function-local statics on first use; destruction in reverse */
#include <string>
struct Reg { std::string log; void add(const char* s) { log += s; log += ' '; } };
Reg& registry();                                               /* function-local static in the dylib */
extern int lib_value;                                          /* dynamically initialized in the dylib */
const char* lib_order();
