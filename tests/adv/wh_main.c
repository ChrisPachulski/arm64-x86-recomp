/* Weak imports of host functions absent at run time must read as NULL in the guest. */
#include <stdio.h>
extern int wh_present(void) __attribute__((weak_import));
extern int wh_absent(void) __attribute__((weak_import));
extern int wh_absent_data __attribute__((weak_import));

int main(void) {
    printf("present %s absent %s data %s\n", wh_present ? "yes" : "no", wh_absent ? "yes" : "no", &wh_absent_data ? "yes" : "no");
    if (wh_present) printf("wh_present() = %d\n", wh_present());
    if (wh_absent) printf("wh_absent() = %d\n", wh_absent());
    return 0;
}
