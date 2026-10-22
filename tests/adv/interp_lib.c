/* Dylib built -flat_namespace -undefined dynamic_lookup: provided_by_main resolves by flat search into the
   executable; also carries a __DATA,__interpose tuple replacing rand() for the other images. */
#include <stdlib.h>
int provided_by_main(int);
static int my_rand(void) { return 4242; }
__attribute__((used, section("__DATA,__interpose"))) static const struct { const void *rep, *orig; } interp_rand =
    {(const void *)my_rand, (const void *)rand};
int lib_calls_main(int x) { return provided_by_main(x) + 1; }
int lib_rand(void) { return rand(); }
