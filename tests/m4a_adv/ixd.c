/* libixd: a guest dylib that calls into the main image through dlsym and through a function pointer it is given. */
#include <dlfcn.h>
#include <string.h>

typedef long (*fn)(long);

long ixd_apply(fn f, long x) { return f(x) + 1; }

long ixd_twice(long x) { return 2 * x; }

long ixd_lookup(const char* how, const char* name, long x) {
  void* h = !strcmp(how, "default") ? RTLD_DEFAULT : !strcmp(how, "main") ? RTLD_MAIN_ONLY : !strcmp(how, "self") ? RTLD_SELF
          : !strcmp(how, "next") ? RTLD_NEXT : dlopen(NULL, RTLD_LAZY);
  fn f = (fn)dlsym(h, name);
  return f ? f(x) : -999999;                                   /* not found */
}
