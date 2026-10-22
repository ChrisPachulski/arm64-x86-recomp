// dlopen / dlsym / dlclose of the program's own images (translated: guest images) by every kind of name, and of host
// libraries; argv[1] "outside" dlopens libdlc, an arm64 image outside the load graph (translated-only case).
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libgen.h>
#include <unistd.h>

extern int dla_counter;
int dla_add(int, int);
int main_export(int x) { return x * 3; }                      // exported by the executable (dlopen(NULL) / dlsym)
int main_data = 77;

static void at_sym(const char* tag, const void* p) {           // dladdr: image leaf, symbol, exact start
  Dl_info di; memset(&di, 0, sizeof di);
  int r = dladdr(p, &di);
  const char* f = di.dli_fname ? strrchr(di.dli_fname, '/') : NULL;
  printf("dladdr %s: r=%d file=%s sname=%s saddr_match=%d\n", tag, r, f ? f + 1 : "(null)", di.dli_sname ? di.dli_sname : "(null)", di.dli_saddr == p);
}

static void* open_named(const char* nm) {
  void* h = dlopen(nm, RTLD_LAZY);
  printf("dlopen(%s): %s\n", nm, h ? "ok" : "NULL");
  return h;
}

int main(int argc, char** argv) {
  char exe[1024]; uint32_t n = sizeof exe;
  _NSGetExecutablePath(exe, &n);
  char abs[1200]; snprintf(abs, sizeof abs, "%s/libdla.dylib", dirname(exe));
  if (argc > 1 && !strcmp(argv[1], "outside")) {
    char c[1200]; snprintf(c, sizeof c, "%s/libdlc.dylib", dirname(exe));
    void* h = dlopen(c, RTLD_NOW);
    const char* e = dlerror();
    printf("outside: %s | %s\n", h ? "loaded" : "NULL", e ? e : "(no error)");
    return 0;
  }
  void* h1 = open_named("@rpath/libdla.dylib");
  void* h2 = dlopen(abs, RTLD_LAZY);
  printf("dlopen(absolute path): %s\n", h2 ? "ok" : "NULL");
  void* h3 = open_named("@loader_path/libdla.dylib");
  void* h4 = open_named("@executable_path/libdla.dylib");
  void* hb = open_named("@rpath/libdlb.dylib");
  printf("same image through every name: %d\n", dlsym(h1, "dla_add") == dlsym(h2, "dla_add") && dlsym(h2, "dla_add") == dlsym(h3, "dla_add")
                                                  && dlsym(h3, "dla_add") == dlsym(h4, "dla_add"));
  int (*add)(int, int) = (int (*)(int, int))dlsym(h1, "dla_add");
  int* counter = (int*)dlsym(h1, "dla_counter");
  printf("dlsym function is the linked one: %d, data is the linked one: %d\n", add == dla_add, counter == &dla_counter);
  printf("call through dlsym: %d, counter %d\n", add(2, 3), *counter);
  int v[] = {4, 9, 1, 7};
  qsort(v, 4, sizeof v[0], (int (*)(const void*, const void*))dlsym(h1, "dla_cmp"));   // the address escapes to host code
  printf("qsort with a dlsym'd comparator: %d %d %d %d\n", v[0], v[1], v[2], v[3]);
  printf("dependency search: dla->dlb %d, dlb->dla %d, dla->malloc %d\n", dlsym(h1, "dlb_name") != NULL, dlsym(hb, "dla_add") != NULL,
         dlsym(h1, "malloc") != NULL);
  const char* (*nm)(void) = (const char* (*)(void))dlsym(h1, "dlb_name");
  printf("dlb_name() via libdla's handle: %s\n", nm());
  void* (*m)(size_t) = (void* (*)(size_t))dlsym(h1, "malloc");    // host code the program also imports: callable
  void* p = m(32); free(p);
  void* volatile q = malloc(8); free(q);                       // the program imports malloc itself
  printf("malloc through dlsym: %d\n", p != NULL);
  void* h0 = dlopen(NULL, RTLD_LAZY);
  int (*me)(int) = (int (*)(int))dlsym(h0, "main_export");
  printf("dlopen(NULL): main_export %d main_data %d dla_add %d\n", me ? me(5) : -1, dlsym(h0, "main_data") ? *(int*)dlsym(h0, "main_data") : -1,
         dlsym(h0, "dla_add") != NULL);
  printf("RTLD_DEFAULT dla_add: %d\n", dlsym(RTLD_DEFAULT, "dla_add") == (void*)dla_add);
  printf("missing symbol: %d\n", dlsym(h1, "no_such_symbol") == NULL);
  printf("dlclose: %d %d %d %d %d %d\n", dlclose(h1), dlclose(h2), dlclose(h3), dlclose(h4), dlclose(hb), dlclose(h0));
  printf("still callable after dlclose: %d\n", dla_add(1, 1));
  void* z = dlopen("/usr/lib/libz.1.dylib", RTLD_LAZY);
  printf("host library: %s, zlibVersion %s\n", z ? "ok" : "NULL", z && dlsym(z, "zlibVersion") ? "found" : "missing");
  if (z) printf("host dlclose: %d\n", dlclose(z));
  void* hh = dlopen("@loader_path/libdlh.dylib", RTLD_LAZY);         // a host image next to the executable
  printf("host image by @loader_path: %s, dlh_value %d\n", hh ? "ok" : "NULL", hh && dlsym(hh, "dlh_value") ? *(int*)dlsym(hh, "dlh_value") : -1);
  void* no = dlopen("libnope_gdyld.dylib", RTLD_LAZY);
  printf("missing library: %s, dlerror set %d\n", no ? "loaded" : "NULL", dlerror() != NULL);
  at_sym("dla_add", (const void*)dla_add);
  at_sym("dla_add+4", (const char*)dla_add + 4);
  at_sym("dla_counter", &dla_counter);
  at_sym("main_export", (const void*)main_export);
  at_sym("malloc", (const void*)malloc);
  if (chdir("/")) return 3;                                   // the leaf name cannot resolve through the cwd
  void* hl = dlopen("libdla.dylib", RTLD_LAZY);
  printf("leaf name of a loaded image: %s, same %d\n", hl ? "ok" : "NULL", hl && dlsym(hl, "dla_add") == (void*)dla_add);
  return 0;
}
