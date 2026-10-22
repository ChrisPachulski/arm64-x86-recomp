/* #3 loud: an untyped host code pointer (dlsym of a function the guest never imports) must not be called with a
   guessed signature; the translated program stops at the call. */
#include <stdio.h>
#include <stdlib.h>
#include <dlfcn.h>

int main(void) {
    void (*f)(unsigned) = (void (*)(unsigned))dlsym(RTLD_DEFAULT, "srandom");
    f(3);
    printf("random %ld\n", random());
    return 0;
}
