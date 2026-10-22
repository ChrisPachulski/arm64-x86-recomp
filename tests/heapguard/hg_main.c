/* GDYLD_HEAP_GUARD bed program (run with the guard at 128-144, guest only or ,host). argv[1]: ok (blocks in and out of
   the guarded range, calloc, realloc across the range, the host's reallocf on a guest block, malloc_size, aligned_alloc,
   default-zone calls, dladdr and dlsym of malloc, quarantine churn), uaf (a write to a freed 140-byte block), overflow
   (a write one byte past a 144-byte block), double (a 140-byte block freed twice), uaf_host (a write to a freed 140-byte
   block the host allocated: strdup). */
#include <dlfcn.h>
#include <malloc/malloc.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned sum(const unsigned char* p, size_t n) { unsigned s = 0; for (size_t i = 0; i < n; i++) s = s * 31 + p[i]; return s; }

int main(int argc, char** argv) {
  const char* mode = argc > 1 ? argv[1] : "ok";
  if (!strcmp(mode, "uaf")) { volatile char* p = malloc(140); free((void*)p); p[8] = 1; puts("uaf not caught"); return 0; }
  if (!strcmp(mode, "overflow")) { volatile char* p = malloc(144); p[144] = 1; puts("overflow not caught"); return 0; }
  if (!strcmp(mode, "double")) { void* volatile p = malloc(140); free(p); free(p); puts("double free not caught"); return 0; }
  if (!strcmp(mode, "spin")) {                             /* about a second in translated code, for the profiler check */
    volatile unsigned long s = 0;
    for (unsigned long i = 0; i < 300000000UL; i++) s += i * 2654435761u;
    printf("spin %lu\n", (unsigned long)(s & 0xffff)); return 0;
  }
  if (!strcmp(mode, "uaf_host")) {
    char s[140]; memset(s, 'a', 139); s[139] = 0;
    volatile char* p = strdup(s); free((void*)p); p[8] = 1; puts("host uaf not caught"); return 0;
  }
  Dl_info di; int r = dladdr((void*)malloc, &di);
  void* (*m)(size_t) = (void* (*)(size_t))dlsym(RTLD_DEFAULT, "malloc");
  void* q = m(140); memset(q, 8, 140);
  printf("dladdr malloc %d %s %s, dlsym call %d\n", r, strrchr(di.dli_fname, '/') + 1, di.dli_sname, ((unsigned char*)q)[139]);
  free(q);
  unsigned char* a = malloc(140); memset(a, 7, 140);
  unsigned char* b = calloc(10, 14);
  unsigned char* c = malloc(64); memset(c, 3, 64);
  printf("calloc zero %d, sizes %d %d\n", sum(b, 140) == 0, malloc_size(a) >= 140, malloc_size(c) >= 64);
  a = realloc(a, 4000); memset(a + 140, 9, 3860);          /* out of the range: the system zone */
  c = realloc(c, 130); memset(c + 64, 5, 66);              /* into the range */
  unsigned char* d = reallocf(malloc(136), 138);           /* the host's reallocf on a guest block */
  memset(d, 1, 138);
  unsigned char* e = aligned_alloc(64, 128); memset(e, 2, 128);
  malloc_zone_t* z = malloc_default_zone();
  unsigned char* f = malloc_zone_malloc(z, 132); memset(f, 4, 132);
  f = malloc_zone_realloc(z, f, 134); f[133] = 6;
  printf("sums %u %u %u %u %u aligned %d\n", sum(a, 4000), sum(c, 130), sum(d, 138), sum(f, 134), sum(e, 128),
         ((unsigned long)e & 63) == 0);
  malloc_zone_free(z, f); free(e); free(d); free(c); free(a); free(b);
  for (int i = 0; i < 20000; i++) { void* volatile p = malloc(129 + i % 16); ((char*)p)[0] = 1; free(p); }
  puts("ok done");
  return 0;
}
