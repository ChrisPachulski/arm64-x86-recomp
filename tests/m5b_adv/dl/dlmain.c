// Adversarial guest dlopen / dlsym / dladdr: one line per probe, no addresses printed. argv[1] "hostcall" calls a host
// function obtained by dlsym directly (expected loud when translated).
#include <dlfcn.h>
#include <dispatch/dispatch.h>
#include <mach-o/dyld.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libgen.h>

int m1_add(int, int);
int* m1_tls_addr(void);
void* m1_open_sibling(void);
extern int m1_data;
int dup_name(void) { return 0; }                               // also defined by libm1
int main_export(int x) { return x * 3; }
static char DIR[1024];

static const char* base(const char* p) { static char b[1024]; if (!p) return "(null)"; strlcpy(b, p, sizeof b); return basename(b); }
static void* op(const char* tag, const char* path, int mode, void* ref) {
  void* h = dlopen(path, mode);
  printf("%-22s %s%s\n", tag, h ? "ok" : "NULL", h && ref ? (h == ref ? " same" : " DIFFERENT") : "");
  return h;
}
static void at_sym(const char* tag, const void* p) {
  Dl_info di; memset(&di, 0, sizeof di);
  int r = dladdr(p, &di);
  printf("dladdr %-15s r=%d file=%s sname=%s saddr_match=%d\n", tag, r, base(di.dli_fname), di.dli_sname ? di.dli_sname : "(null)",
         di.dli_saddr == p);
}
static void in_callback(void* ctx) {                           // dlopen reached from a host-called guest callback
  char p[1200]; snprintf(p, sizeof p, "%s/sub/libm1.dylib", DIR);
  *(void**)ctx = dlopen(p, RTLD_LAZY);
}

int main(int argc, char** argv) {
  char exe[1024]; uint32_t n = sizeof exe;
  _NSGetExecutablePath(exe, &n);
  char tmp[1024]; strlcpy(tmp, exe, sizeof tmp); strlcpy(DIR, dirname(tmp), sizeof DIR);
  char p[1200];
  void* h = op("@rpath", "@rpath/libm1.dylib", RTLD_LAZY, NULL);
  snprintf(p, sizeof p, "%s/sub/libm1.dylib", DIR); op("absolute", p, RTLD_LAZY, h);
  snprintf(p, sizeof p, "%s/sub/../sub/libm1.dylib", DIR); op("dotdot", p, RTLD_LAZY, h);
  snprintf(p, sizeof p, "%s//sub//libm1.dylib", DIR); op("double slash", p, RTLD_LAZY, h);
  snprintf(p, sizeof p, "%s/link_m1.dylib", DIR); op("symlink", p, RTLD_LAZY, h);
  op("relative ./", "./sub/libm1.dylib", RTLD_LAZY, h);
  op("relative bare", "sub/libm1.dylib", RTLD_LAZY, h);
  op("leaf name", "libm1.dylib", RTLD_LAZY, h);
  op("@executable_path", "@executable_path/sub/libm1.dylib", RTLD_LAZY, h);
  op("main @loader_path m2", "@loader_path/libm2.dylib", RTLD_LAZY, NULL);
  snprintf(p, sizeof p, "%s/sub/libm1.dylib", DIR); op("NOLOAD loaded", p, RTLD_LAZY | RTLD_NOLOAD, h);
  snprintf(p, sizeof p, "%s/sub/libm2.dylib", DIR); void* h2 = op("NOLOAD dependency", p, RTLD_LAZY | RTLD_NOLOAD, NULL);
  snprintf(p, sizeof p, "%s/libh.dylib", DIR); op("NOLOAD not loaded", p, RTLD_LAZY | RTLD_NOLOAD, NULL);
  printf("dlerror after NOLOAD miss: %s\n", dlerror() ? "set" : "NULL");
  printf("dlerror again: %s\n", dlerror() ? "set" : "NULL");
  void* sib = m1_open_sibling();
  printf("m1 @loader_path sibling: %s same_as_noload %d\n", sib ? "ok" : "NULL", sib == h2);
  void* hexe = op("executable by path", exe, RTLD_LAZY, NULL);
  int (*me)(int) = hexe ? (int (*)(int))dlsym(hexe, "main_export") : NULL;
  printf("exe handle main_export: %d\n", me ? me(4) : -1);
  // dlsym: data, function, missing, scope of a handle
  int* d = (int*)dlsym(h, "m1_data");
  int (*add)(int, int) = (int (*)(int, int))dlsym(h, "m1_add");
  printf("data %d func %d linked-data-same %d\n", d ? *d : -1, add ? add(1, 2) : -1, d == &m1_data);
  printf("missing NULL %d dlerror %s\n", dlsym(h, "m1_nope") == NULL, dlerror() ? "set" : "NULL");
  printf("dlerror cleared: %s\n", dlerror() ? "set" : "NULL");
  printf("underscored name NULL %d\n", dlsym(h, "_m1_add") == NULL);
  void* z = dlopen("/usr/lib/libz.1.dylib", RTLD_LAZY);
  snprintf(p, sizeof p, "%s/libh.dylib", DIR); void* hh = dlopen(p, RTLD_LAZY);
  printf("libz %s libh %s\n", z ? "ok" : "NULL", hh ? "ok" : "NULL");
  void* hm2 = dlopen("@rpath/libm2.dylib", RTLD_LAZY);
  printf("m2 handle: m1_add %d zlibVersion %d h_value %d malloc %d m2_name %d\n", dlsym(hm2, "m1_add") != NULL,
         dlsym(hm2, "zlibVersion") != NULL, dlsym(hm2, "h_value") != NULL, dlsym(hm2, "malloc") != NULL, dlsym(hm2, "m2_name") != NULL);
  printf("m1 handle: zlibVersion %d h_value %d\n", dlsym(h, "zlibVersion") != NULL, dlsym(h, "h_value") != NULL);
  printf("exe handle: zlibVersion %d m2_name %d\n", dlsym(hexe, "zlibVersion") != NULL, dlsym(hexe, "m2_name") != NULL);
  // interposition and special handles
  int (*f)(void);
  f = (int (*)(void))dlsym(RTLD_DEFAULT, "dup_name"); printf("RTLD_DEFAULT dup_name -> %d\n", f ? f() : -1);
  f = (int (*)(void))dlsym(h, "dup_name"); printf("m1 handle dup_name -> %d\n", f ? f() : -1);
  f = (int (*)(void))dlsym(RTLD_NEXT, "dup_name"); printf("RTLD_NEXT dup_name -> %d\n", f ? f() : -1);
  f = (int (*)(void))dlsym(RTLD_SELF, "dup_name"); printf("RTLD_SELF dup_name -> %d\n", f ? f() : -1);
  f = (int (*)(void))dlsym(h, "both_name"); printf("m1 handle both_name -> %d\n", f ? f() : -1);
  f = (int (*)(void))dlsym(hm2, "both_name"); printf("m2 handle both_name -> %d\n", f ? f() : -1);
  f = (int (*)(void))dlsym(RTLD_DEFAULT, "both_name"); printf("RTLD_DEFAULT both_name -> %d\n", f ? f() : -1);
  printf("RTLD_MAIN_ONLY m1_add NULL %d main_export %d\n", dlsym(RTLD_MAIN_ONLY, "m1_add") == NULL, dlsym(RTLD_MAIN_ONLY, "main_export") != NULL);
  // thread-local variable through dlsym: the calling thread's instance
  int* t = (int*)dlsym(h, "m1_tls");
  printf("dlsym tls: found %d is-this-thread %d\n", t != NULL, t == m1_tls_addr());
  // dladdr on guest code and data
  at_sym("m1_add", (const void*)m1_add);
  at_sym("m1_add+8", (const char*)m1_add + 8);
  at_sym("m1_data", &m1_data);
  at_sym("main", (const void*)main);
  at_sym("malloc", (const void*)malloc);
  // dlsym'd pointers handed to host code
  int v[5] = {3, 1, 4, 1, 5};
  qsort(v, 5, sizeof v[0], (int (*)(const void*, const void*))dlsym(h, "m1_cmp"));
  printf("qsort guest dlsym cmp: %d %d %d %d %d\n", v[0], v[1], v[2], v[3], v[4]);
  qsort(v, 5, sizeof v[0], (int (*)(const void*, const void*))dlsym(hh, "h_cmp"));
  printf("qsort host dlsym cmp: %d %d %d %d %d\n", v[0], v[1], v[2], v[3], v[4]);
  pthread_t th; void* rv = NULL;
  pthread_create(&th, NULL, (void* (*)(void*))dlsym(h, "m1_thread"), (void*)21); pthread_join(th, &rv);
  printf("pthread dlsym fn: %ld\n", (long)rv);
  int cnt = 1;
  dispatch_sync_f(dispatch_get_global_queue(0, 0), &cnt, (dispatch_function_t)dlsym(h, "m1_disp"));
  printf("dispatch_sync_f dlsym fn: %d\n", cnt);
  void* hcb = NULL;
  dispatch_sync_f(dispatch_queue_create("q", NULL), &hcb, in_callback);
  printf("dlopen inside host callback: %s same %d\n", hcb ? "ok" : "NULL", hcb == h);
  printf("dlclose guest %d, still NOLOAD %d\n", dlclose(h), dlopen("@rpath/libm1.dylib", RTLD_NOLOAD) != NULL);
  if (argc > 1 && !strcmp(argv[1], "hostcall")) {
    int (*hc)(const void*, const void*) = (int (*)(const void*, const void*))dlsym(hh, "h_cmp");
    int a = 1, b = 2;
    printf("direct call of dlsym'd host fn: %d\n", hc(&a, &b));
  }
  return 0;
}
