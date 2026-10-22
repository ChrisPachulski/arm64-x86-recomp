/* frame records: walking the frame-pointer chain from the innermost function must find each caller's return address
   inside that caller (bl/blr write the guest return address to x30, prologues store it with x29) */
#include <stdint.h>
#include <stdio.h>

typedef int (*fp_t)(int);
__attribute__((noinline)) static int f3(int x);
__attribute__((noinline)) static int f2(int x) { int r = f3(x + 1); return r + 1; }
__attribute__((noinline)) static int f1(int x) { volatile fp_t p = f2; int r = p(x + 1); return r + 1; }   /* indirect call (blr) */

static const char* callers[] = {"f2", "f1", "main"};
static uintptr_t lo[3], hi[3];

__attribute__((noinline)) static int f3(int x) {
    void** fp = (void**)__builtin_frame_address(0);
    for (int k = 0; k < 3; k++) {
        uintptr_t ra = (uintptr_t)fp[1];
        printf("frame %d: return address inside %s: %d\n", k, callers[k], ra > lo[k] && ra < hi[k]);
        fp = (void**)fp[0];
    }
    printf("return address of f3 inside f2: %d\n", (uintptr_t)__builtin_return_address(0) > lo[0]
           && (uintptr_t)__builtin_return_address(0) < hi[0]);
    return x;
}

int main(void) {
    lo[0] = (uintptr_t)f2; hi[0] = lo[0] + 64;
    lo[1] = (uintptr_t)f1; hi[1] = lo[1] + 96;
    lo[2] = (uintptr_t)main; hi[2] = lo[2] + 160;
    printf("result %d\n", f1(1));
    return 0;
}
