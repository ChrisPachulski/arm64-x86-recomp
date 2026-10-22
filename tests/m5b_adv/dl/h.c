// libh: universal (x86_64 + arm64) host image, linked by nothing.
int h_value = 9;
int h_cmp(const void* a, const void* b) { return *(const int*)b - *(const int*)a; }
