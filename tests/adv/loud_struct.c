/* Was the #2 loud case; M5b bridges it: guest code in a function-pointer field of a struct handed to the host (here
   CFArrayCallBacks.equal) becomes a closure of the field's declared type, so the translated program must MATCH. */
#include <stdio.h>
#include <CoreFoundation/CoreFoundation.h>

static Boolean eq(const void *a, const void *b) { return a == b; }

int main(void) {
    CFArrayCallBacks cb = {0, NULL, NULL, NULL, eq};
    int x = 1, y = 2;
    const void *vals[] = {&x, &y};
    CFArrayRef arr = CFArrayCreate(NULL, vals, 2, &cb);
    printf("contains %d\n", CFArrayContainsValue(arr, CFRangeMake(0, 2), &y));
    CFRelease(arr);
    return 0;
}
