/* swprintf %n at every length modifier stores exactly that width (hh: 1 byte, h: 2, none: 4, l/ll/j/z: 8). */
#include <stdio.h>
#include <wchar.h>
#include <string.h>
#include <stdint.h>
int main(void) {
  wchar_t buf[32];
  unsigned char b[8] = {0, 17, 34, 51, 68, 85, 102, 119};
  swprintf(buf, 32, L"x%hhn", (signed char*)&b[0]);
  printf("hh: %d %d %d %d\n", b[0], b[1], b[2], b[3]);
  short s[2] = {-1, -1};
  swprintf(buf, 32, L"abc%hn", &s[0]);
  printf("h: %d %d\n", s[0], s[1]);
  int i[2] = {-1, -1};
  swprintf(buf, 32, L"abcd%n", &i[0]);
  printf("none: %d %d\n", i[0], i[1]);
  long long q[2] = {-1, -1};
  swprintf(buf, 32, L"%ls%lln", L"wide", &q[0]);
  printf("ll: %lld %lld\n", q[0], q[1]);
  long l = -1;
  swprintf(buf, 32, L"%d%ln", 12345, &l);
  printf("l: %ld\n", l);
  return 0;
}
