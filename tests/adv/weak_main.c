/* Weak imports absent at run time: a missing function, a missing data symbol, and a -weak_library that is
   absent entirely. All must bind to NULL, not trap and not to a stub that jumps somewhere. */
#include <stdio.h>
int always(void);
extern int maybe(void) __attribute__((weak_import));
extern int maybe_data __attribute__((weak_import));
extern int gone_fn(void) __attribute__((weak_import));
int main(void) {
    printf("always %d maybe %s data %s gone %s\n", always(), maybe ? "present" : "absent",
           &maybe_data ? "present" : "absent", gone_fn ? "present" : "absent");
    if (maybe) printf("maybe() = %d\n", maybe());
    return 0;
}
