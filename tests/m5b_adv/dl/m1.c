// libm1 (in sub/, linked by main as @rpath/libm1.dylib); links libm2 (sub/, @loader_path rpath).
#include <dlfcn.h>
#include <stdio.h>
int m1_data = 41;
__thread int m1_tls = 5;
int dup_name(void) { return 1; }                               // also defined by main
int both_name(void) { return 1; }                              // also defined by libm2
int m1_add(int a, int b) { return a + b + m1_data; }
int m1_cmp(const void* a, const void* b) { return *(const int*)a - *(const int*)b; }
int* m1_tls_addr(void) { return &m1_tls; }
void* m1_thread(void* p) { return (void*)((long)p * 2); }
void m1_disp(void* p) { *(int*)p += 100; }
__attribute__((noinline)) void* m1_open_sibling(void) {      // @loader_path from inside libm1 (not a tail call)
  void* h = dlopen("@loader_path/libm2.dylib", RTLD_LAZY);
  __asm__ volatile("" ::: "memory");
  return h;
}
