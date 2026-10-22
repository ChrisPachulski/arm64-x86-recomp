/* A C++ exception thrown by a guest callback that a host function (qsort) is running unwinds through the host frames
   to the guest caller's handler, running the guest destructors on the way; the callee-saved state of the caller is
   intact in the handler. */
#include <cstdio>
#include <cstdlib>
#include <stdexcept>

static int calls;
struct Guard { const char* n; ~Guard() { printf("destroy %s\n", n); } };
static int cmp(const void* a, const void* b) {
    Guard g{"comparator guard"};
    int x = *(const int*)a, y = *(const int*)b;
    if (++calls == 3) throw std::runtime_error("comparator saw call 3");
    return x - y;
}
__attribute__((noinline)) static long sort_and_catch(int* v, long k) {
    long keep = k * 3;                                        /* lives in a callee-saved register across qsort */
    try { Guard g{"caller guard"}; qsort(v, 5, sizeof v[0], cmp); printf("not reached\n"); }
    catch (std::exception& e) { printf("caught %s, keep %ld\n", e.what(), keep); }
    return keep + 1;
}

int main() {
    int v[] = {5, 1, 3, 2, 4};
    printf("sorting\n");
    printf("returned %ld after %d calls\n", sort_and_catch(v, 14), calls);
    calls = -100;
    qsort(v, 5, sizeof v[0], cmp);
    printf("second sort %d %d %d %d %d\n", v[0], v[1], v[2], v[3], v[4]);
    return 0;
}
