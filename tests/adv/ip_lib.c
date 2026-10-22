/* #9 chained interposers: built twice (IP=1, IP=2); each dylib interposes puts() with a wrapper that prints its tag
   and calls puts(). dyld chains them: other images -> the later wrapper -> the earlier wrapper -> the real puts. */
#include <stdio.h>
#define STR2(x) #x
#define STR(x) STR2(x)
static int wrap(const char *s) { fputs("[" STR(IP) "]", stdout); return puts(s); }
__attribute__((used, section("__DATA,__interpose"))) static const struct { const void *rep, *orig; } tuple =
    {(const void *)wrap, (const void *)puts};
#define CAT2(a, b) a##b
#define CAT(a, b) CAT2(a, b)
int CAT(ip_marker_, IP)(void) { return IP; }
