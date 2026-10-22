// srec_main.m: sends to a host object a method whose record holds a SIMD vector. SREC_CASE 1: the getter (32-byte sret on
// x86-64, a 4-byte record by its encoding; refused from srec.h); 2: the setter (not in srec.h; refused by its offsets).
#import <Foundation/Foundation.h>
#include <stdio.h>
#include "srec.h"

@interface SRec (Set)
- (void)setM:(SRecMixed)m;
@end

static void show(const char* what, void* o) {
  printf("%s: tag %d v %g %g %g %g\n", what, srec_tag(o), srec_v(o, 0), srec_v(o, 1), srec_v(o, 2), srec_v(o, 3));
}

int main(void) {
  setvbuf(stdout, NULL, _IOLBF, 0);
  SRec* o = (SRec*)srec_new();
  show("host made", o);
#if SREC_CASE == 1
  SRecMixed g = [o getM];
  printf("getM: tag %d v %g %g %g %g\n", g.tag, g.v[0], g.v[1], g.v[2], g.v[3]);
#else
  SRecMixed s = {{9.0f, 8.0f, 7.0f, 6.0f}, 42};
  [o setM:s];
#endif
  show("after", o);
  return 0;
}
