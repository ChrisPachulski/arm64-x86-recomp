/* thread_local variables keep their declared alignment in every thread's TLS block. Alignments up to 512 only: the
   native x86-64 dyld oracle takes the block from plain malloc (a 1024-aligned variable lands at 512 mod 1024 in a
   second thread there), so larger ones are not a differential check. */
#include <cstdint>
#include <cstdio>
#include <thread>

thread_local char small = 'a';
alignas(512) thread_local char kb[64];
alignas(64) thread_local int line = 5;
alignas(256) thread_local double dz[4];

static unsigned long mod(const void* p, unsigned long m) {    /* opaque: the compiler folds % of a declared alignment */
    uintptr_t u = (uintptr_t)p;
    __asm__ volatile("" : "+r"(u));
    return (unsigned long)(u % m);
}

static void report(const char* who) {
    kb[0] = small; dz[1] = line;
    printf("%s kb%%512 %lu line%%64 %lu dz%%256 %lu small %c line %d dz %.0f\n", who, mod(kb, 512), mod(&line, 64), mod(dz, 256), kb[0], line, dz[1]);
}

int main() {
    report("main");
    std::thread t([] { line = 9; report("thread"); });
    t.join();
    report("main again");
    return 0;
}
