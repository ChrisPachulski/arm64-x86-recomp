#include "empty.h"
long e_take(struct Empty e, long x) { (void)e; return x; }
long e_mid(long a, struct Empty e, long b, struct Empty f, double d) { (void)e; (void)f; return a * 100 + b * 10 + (long)d; }
struct Empty e_ret(long* p) { struct Empty e; *p = 5; return e; }
long e_call(long (*cb)(struct Empty, long), long x) { struct Empty e; return cb(e, x); }
long e_call_mid(long (*cb)(long, struct Empty, long), long a, long b) { struct Empty e; return cb(a, e, b); }
