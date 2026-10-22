/* a C++ exception thrown by a guest comparator that HOST qsort / qsort_r / bsearch is running: natively it unwinds
   through libc's frames to main's handler (record what native does) */
#include <cstdio>
#include <cstdlib>
#include <stdexcept>

static int calls;
static int cmp(const void* a, const void* b) {
    int x = *(const int*)a, y = *(const int*)b;
    if (++calls == 4) throw std::runtime_error("comparator call 4");
    return x - y;
}
struct Guard { ~Guard() { printf("guard destroyed\n"); } };

int main() {
    int v[] = {9, 5, 1, 7, 3, 2, 8, 4, 6, 0};
    printf("start\n");
    fflush(stdout);
    try { Guard g; qsort(v, 10, sizeof v[0], cmp); printf("not reached\n"); }
    catch (std::exception& e) { printf("caught %s after %d calls\n", e.what(), calls); }
    int sum = 0;
    for (int x : v) sum += x;
    printf("elements preserved sum %d\n", sum);
    return 0;
}
