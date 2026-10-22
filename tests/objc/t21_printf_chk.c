/* Fortified printf (__sprintf_chk / __snprintf_chk and their v forms, as _FORTIFY_SOURCE emits them): calls within the
   object size format normally; an object size smaller than maxlen ends in libc's overflow report, as natively. */
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
static int vs(char* b, size_t os, const char* f, ...) { va_list ap; va_start(ap, f); int r = __builtin___vsprintf_chk(b, 0, os, f, ap); va_end(ap); return r; }
static int vsn(char* b, size_t mx, size_t os, const char* f, ...) { va_list ap; va_start(ap, f); int r = __builtin___vsnprintf_chk(b, mx, 0, os, f, ap); va_end(ap); return r; }
int main(void) {
  setvbuf(stdout, NULL, _IONBF, 0);
  char buf[16];
  int r = __builtin___sprintf_chk(buf, 0, sizeof buf, "%d-%s", 42, "ok");
  printf("sprintf_chk %d [%s]\n", r, buf);
  r = __builtin___snprintf_chk(buf, 6, 0, sizeof buf, "%s", "truncated");
  printf("snprintf_chk %d [%s]\n", r, buf);
  r = vs(buf, sizeof buf, "%x|%c", 255, 'z');
  printf("vsprintf_chk %d [%s]\n", r, buf);
  r = vsn(buf, 4, sizeof buf, "%05d", 7);
  printf("vsnprintf_chk %d [%s]\n", r, buf);
  char small[4];
  printf("about to overflow\n");
  r = __builtin___snprintf_chk(small, 8, 0, sizeof small, "x");
  printf("not reached %d\n", r);
  return 0;
}
