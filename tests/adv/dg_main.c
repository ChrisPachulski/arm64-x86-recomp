/* dlsym must find guest exports (main executable and guest dylibs) before host definitions. */
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

int guest_marker = 7;
extern int dg_marker;
int dg_fn(void);

int main(void) {
    int (*f)(void) = (int (*)(void))dlsym(RTLD_DEFAULT, "dg_fn");
    printf("main marker %d lib marker %d\n", dlsym(RTLD_DEFAULT, "guest_marker") == (void*)&guest_marker,
           dlsym(RTLD_DEFAULT, "dg_marker") == (void*)&dg_marker);
    printf("fn same %d call %d\n", f == dg_fn, f ? f() : -1);
    printf("main-only main %d main-only lib %d\n", dlsym(RTLD_MAIN_ONLY, "guest_marker") == (void*)&guest_marker,
           dlsym(RTLD_MAIN_ONLY, "dg_marker") == NULL);
    printf("host strlen %d missing %d\n", dlsym(RTLD_DEFAULT, "strlen") != NULL, dlsym(RTLD_DEFAULT, "no_such_symbol_xyz") == NULL);
    return 0;
}
