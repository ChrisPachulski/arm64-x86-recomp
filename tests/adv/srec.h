/* srec.h: a host Objective-C class (srec_lib.m) with a record holding a SIMD vector, for run_adv's srec_get_loud and
   srec_set_loud. Its type encoding drops the vector ({?=i}), so the x86-64 method passes and returns 32 bytes where the
   encoding says 4. getM is declared here (gdyld reads this header); setM: is not, so only its offsets can tell. */
typedef float srec_f4 __attribute__((ext_vector_type(4)));
typedef struct { srec_f4 v; int tag; } SRecMixed;
#ifdef __OBJC__
#import <Foundation/NSObject.h>
@interface SRec : NSObject
- (SRecMixed)getM;
@end
#endif
void* srec_new(void);
int srec_tag(void* o);
float srec_v(void* o, int i);
