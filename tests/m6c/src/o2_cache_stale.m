// Per-site ObjC send cache vs a method encoding that changes under the same (class, selector, IMP) (Codex m6c finding 2).
// One call site (send_q) sees: (1) a subclass that shadows its superclass's method with the same host IMP and another
// encoding; (2) a disposed class whose address a new class with the same IMP and another encoding reuses.
// The IMP is -[NSObject retainCount] (returns 1 here). Phase results under the old void encoding are not printed:
// a void-typed host call does not set x0 when translated. stderr reports whether the address was reused.
#import <Foundation/Foundation.h>
#include <objc/message.h>
#include <objc/runtime.h>
#include <stdio.h>

__attribute__((noinline)) static unsigned long send_q(id o, SEL s) { return ((unsigned long (*)(id, SEL))objc_msgSend)(o, s); }

int main(void) {
  SEL probe = sel_registerName("m6cProbe");
  IMP rc = method_getImplementation(class_getInstanceMethod([NSObject class], @selector(retainCount)));

  Class P = objc_allocateClassPair([NSObject class], "M6cP", 0);
  class_addMethod(P, probe, rc, "v@:");
  objc_registerClassPair(P);
  Class S = objc_allocateClassPair(P, "M6cS", 0);
  objc_registerClassPair(S);
  id s = class_createInstance(S, 0);
  send_q(s, probe);                                   // warms the site with P's v@: method
  send_q(s, probe);
  class_addMethod(S, probe, rc, "Q@:");               // same IMP, now Q@: on S itself
  printf("shadow %lu\n", send_q(s, probe));

  Class D = objc_allocateClassPair([NSObject class], "M6cD0", 0);
  class_addMethod(D, probe, rc, "v@:");
  objc_registerClassPair(D);
  id d = class_createInstance(D, 0);
  send_q(d, probe);
  send_q(d, probe);
  object_dispose(d);
  objc_disposeClassPair(D);
  int reused = 0;
  for (int i = 1; i <= 2000 && !reused; i++) {
    char nm[32];
    snprintf(nm, sizeof nm, "M6cD%d", i);
    Class N = objc_allocateClassPair([NSObject class], nm, 0);
    if (N != D) continue;
    class_addMethod(N, probe, rc, "Q@:");
    objc_registerClassPair(N);
    printf("reuse %lu\n", send_q(class_createInstance(N, 0), probe));
    reused = 1;
  }
  if (!reused) printf("reuse %lu\n", 1UL);
  fprintf(stderr, "address reused: %d\n", reused);
  return 0;
}
