// srec_lib.m: libsrec.dylib, served by the host (see srec.h). The C accessors call the methods from native code (right ABI).
#import <Foundation/Foundation.h>
#include "srec.h"

@interface SRec ()
- (void)setM:(SRecMixed)m;
@end
@implementation SRec {
  SRecMixed m_;
}
- (SRecMixed)getM { return m_; }
- (void)setM:(SRecMixed)m { m_ = m; }
@end

void* srec_new(void) {
  SRec* o = [SRec new];
  SRecMixed m = {{1.5f, 2.5f, 3.5f, 4.5f}, 7};
  [o setM:m];
  return (void*)o;
}
int srec_tag(void* o) { return [(SRec*)o getM].tag; }
float srec_v(void* o, int i) { return [(SRec*)o getM].v[i]; }
