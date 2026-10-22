/* Host library with empty-struct parameters (Apple arm64 ignores them: no register, no stack slot). */
#pragma once
struct Empty {};
long e_take(struct Empty e, long x);
long e_mid(long a, struct Empty e, long b, struct Empty f, double d);
struct Empty e_ret(long* p);
long e_call(long (*cb)(struct Empty, long), long x);
long e_call_mid(long (*cb)(long, struct Empty, long), long a, long b);
