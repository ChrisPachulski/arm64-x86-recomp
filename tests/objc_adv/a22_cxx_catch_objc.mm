// Objective-C++: a plain C++ throw/catch with RAII (the TU's personality is __objc_personality_v0), an NSException raised
// by the host caught by catch(NSException*), and one caught by catch(...).
#import <Foundation/Foundation.h>
#include <cstdio>
#include <stdexcept>
struct Guard { const char* n; ~Guard() { printf("~Guard %s\n", n); } };
__attribute__((noinline)) static void thrower(int k) { Guard g{"thrower"}; if (k) throw std::runtime_error("plain c++"); }
int main() {
  setvbuf(stdout, NULL, _IONBF, 0);
  @autoreleasepool {
    try { thrower(1); } catch (const std::exception& e) { printf("caught cxx: %s\n", e.what()); }
    try { Guard g{"objc"}; [@[@1] objectAtIndex:3]; } catch (NSException* e) { printf("caught NSException* %s\n", e.name.UTF8String); }
    try { [NSException raise:@"Custom" format:@"n=%d", 3]; } catch (...) { printf("caught ...\n"); }
  }
  return 0;
}
