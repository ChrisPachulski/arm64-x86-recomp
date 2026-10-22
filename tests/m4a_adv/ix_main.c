/* Driver for ix_a.s + filler + ix_b.s (arm64 guest) and its x86_64 oracle (the same functions restated in C).
   No argument: every function on several inputs. "dl NAME" etc.: look NAME up through dlsym with one handle kind and
   call it with 5. "lib NAME": the guest dylib libixd looks NAME up and calls it. "off HEX": (guest only) call the code
   address ka + HEX. "hdr" / "data": (guest only) call the mach header / a constant: must stop loudly. */
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <mach-o/ldsyms.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef long (*fn)(long);
jmp_buf ix_jb, ix_jb2;
long ixd_lookup(const char* how, const char* name, long x);   /* libixd */
long ixd_apply(fn f, long x);                                  /* libixd: f(x) + 1 */
const long ix_const[4] = {1, 2, 3, 4};
#include "fill_decl.h"                                         /* generated: fill_N(x), FILL_N */
#if defined(__aarch64__)
long ka(long), kb(long), kc(long), fj(long, long), fjx(long), fjy(long), fr(long), fq(long), fs(long), ft(long);
long xb1(long), xb2(long), xb3(long), xb4(long), xb5(long);
#else
static long k_mid(long x) { return 7 * x - 3; }
static long r_mid(long x) { return x + 7; }
long ka(long x) { return x + 1; }
long kb(long x) { return k_mid(x) + 1000; }
long kc(long x) { return x != 5 ? k_mid(x) : 55; }
long fj(long x, long y) { switch (x) { case 0: return y + 10; case 1: return 2 * y; case 2: return y * y; case 3: return y - 1; } return -1; }
long fjx(long y) { return y * y; }
long fjy(long y) { return y < 0 ? y - 1 : 77; }
long fr(long x) { return x + 2; }
long fq(long x) { return x + 10; }
long fs(long x) { return 2 * r_mid(x); }
long ft(long x) { return x & 1 ? r_mid(x) : x; }
long xb1(long x) { return k_mid(x) + 5; }
long xb2(long x) { return x == 0 ? -3 : 2 * x; }
long xb3(long x) { return fs(x); }
long xb4(long x) { return ka(x); }
long xb5(long x) { return x & 2 ? -5 : r_mid(x); }
#endif

static long fj1(long y) { return fj(1, y) * 1000 + fj(3, y) * 10 + fj(7, y); }

static void table(void) {
  static const fn fns[] = {ka, kb, kc, fjx, fjy, fr, fq, fs, ft, xb1, xb2, xb3, xb4, xb5, fj1};
  static const char* names = "ka kb kc fjx fjy fr fq fs ft xb1 xb2 xb3 xb4 xb5 fj1";
  printf("%s\n", names);
  for (long x = -3; x <= 6; x++) {
    printf("x=%ld", x);
    for (unsigned i = 0; i < sizeof fns / sizeof *fns; i++) printf(" %ld", fns[i](x));
    printf("\n");
  }
  long s = 0;
  for (int i = 0; i < FILL_N; i++) s += fills[i](i);
  printf("fill sum %ld; ixd_apply(kb, 2) %ld; ixd_apply(xb2, 4) %ld\n", s, ixd_apply(kb, 2), ixd_apply(xb2, 4));
}

static void* handle(const char* how) {
  char path[4096]; uint32_t n = sizeof path;
  if (!strcmp(how, "dl")) return RTLD_DEFAULT;
  if (!strcmp(how, "dlm")) return RTLD_MAIN_ONLY;
  if (!strcmp(how, "dls")) return RTLD_SELF;
  if (!strcmp(how, "dl0")) return dlopen(NULL, RTLD_LAZY);
  if (!strcmp(how, "dlx")) return _NSGetExecutablePath(path, &n) ? NULL : dlopen(path, RTLD_LAZY | RTLD_NOLOAD);
  return NULL;
}

int main(int argc, char** argv) {
  if (argc < 2) { table(); return 0; }
  setvbuf(stdout, NULL, _IONBF, 0);
  if (!strcmp(argv[1], "off")) { printf("off %s: %ld\n", argv[2], ((fn)((char*)ka + strtol(argv[2], NULL, 16)))(5)); return 0; }
  fn volatile vp = (fn)(void*)&_mh_execute_header;                    /* volatile: an indirect call, not a direct bl */
  if (!strcmp(argv[1], "hdr")) { printf("hdr: %ld\n", vp(5)); return 0; }
  if (!strcmp(argv[1], "data")) { vp = (fn)(void*)ix_const; printf("data: %ld\n", vp(5)); return 0; }
  if (!strcmp(argv[1], "dll")) {                                       /* the guest dylib, already loaded, by its install name */
#if defined(__aarch64__)
    void* h = dlopen("@rpath/libixd_arm64.dylib", RTLD_LAZY | RTLD_NOLOAD);
#else
    void* h = dlopen("@rpath/libixd_x86_64.dylib", RTLD_LAZY | RTLD_NOLOAD);
#endif
    fn f = h ? (fn)dlsym(h, argv[2]) : NULL;
    printf("dll %s: handle %s, symbol %s", argv[2], h ? "ok" : "NULL", f ? "found" : "NULL");
    if (f) printf(", value %ld", f(5));
    printf("\n");
    return 0;
  }
  if (!strcmp(argv[1], "lib")) { printf("lib %s %s: %ld\n", argv[2], argv[3], ixd_lookup(argv[2], argv[3], 5)); return 0; }
  void* h = handle(argv[1]);
  fn f = h ? (fn)dlsym(h, argv[2]) : NULL;
  printf("%s %s: handle %s, symbol %s", argv[1], argv[2], h ? "ok" : "NULL", f ? "found" : "NULL");
  if (f) printf(", value %ld", f(5));
  printf("\n");
  return 0;
}

long zz_last(long x) { return x * 1000 + 7; }                 /* last function of the image (source order) */
