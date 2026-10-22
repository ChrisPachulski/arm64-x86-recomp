/* #9: executable linked against interposer 1 then 2; its puts() goes through both wrappers to the real puts. */
#include <stdio.h>
int ip_marker_1(void);
int ip_marker_2(void);
int main(void) {
    puts("hello");
    printf("markers %d %d\n", ip_marker_1(), ip_marker_2());
    return 0;
}
