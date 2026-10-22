/* 128-bit division: clang calls ___udivti3 / ___umodti3 / ___divti3 / ___modti3 (compiler-rt in libSystem). */
#include <stdio.h>

static void hex(const char* what, unsigned __int128 v) {
    printf("%s %016llx%016llx\n", what, (unsigned long long)(v >> 64), (unsigned long long)v);
}

int main(void) {
    volatile unsigned __int128 a = ((unsigned __int128)0x0123456789abcdefULL << 64) | 0xfedcba9876543210ULL;
    volatile unsigned __int128 b = 0x1d2f3a4b5cULL;
    volatile __int128 s = -(__int128)a, t = 977;
    hex("udiv", a / b);
    hex("umod", a % b);
    hex("sdiv", (unsigned __int128)(s / t));
    hex("smod", (unsigned __int128)(s % t));
    return 0;
}
