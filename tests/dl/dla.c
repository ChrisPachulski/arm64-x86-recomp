// libdla: a guest dylib the main program links (@rpath); it links libdlb itself (@rpath), which main does not.
int dla_counter = 40;
int dla_add(int a, int b) { dla_counter++; return a + b; }
int dla_cmp(const void* a, const void* b) { return *(const int*)b - *(const int*)a; }
