/* Function pointers across the bridge (#3, #2): a guest handler handed to the host comes back as the same pointer
   (signal, sigaction old action), sigaction's handler inside the struct is bridged in both directions (plain and
   SA_SIGINFO), an import handed over comes back as the import, a genuine host function returned typed is callable and
   keeps the identity of the untyped dlsym pointer it came from, and a struct of host code pointers passes through. */
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <string.h>
#include <dlfcn.h>
#include <CoreFoundation/CoreFoundation.h>

static volatile int hits;
static void h1(int s) { hits += s; }
static void h2(int s, siginfo_t *si, void *uc) { (void)uc; hits += 1000 * s + si->si_signo; }

int main(void) {
    sig_t old = signal(SIGUSR1, h1);
    sig_t back = signal(SIGUSR1, SIG_DFL);
    printf("signal: old was SIG_DFL %d, returned handler is h1 %d\n", old == SIG_DFL, back == h1);
    signal(SIGUSR1, h1);
    raise(SIGUSR1);
    printf("raise via signal: hits %d\n", hits);

    struct sigaction sa, oa, cur;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = h1;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGUSR2, &sa, &oa);
    raise(SIGUSR2);
    sigaction(SIGUSR2, NULL, &cur);
    printf("sigaction: old SIG_DFL %d, current is h1 %d, hits %d\n", oa.sa_handler == SIG_DFL, cur.sa_handler == h1, hits);
    sa.sa_sigaction = h2;
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGUSR2, &sa, &oa);
    raise(SIGUSR2);
    sigaction(SIGUSR2, NULL, &cur);
    printf("siginfo: old was h1 %d, current is h2 %d, siginfo flag %d, hits %d\n", oa.sa_handler == h1,
           cur.sa_sigaction == h2, (cur.sa_flags & SA_SIGINFO) != 0, hits);

    signal(SIGUSR1, (sig_t)abs);
    sig_t imp = signal(SIGUSR1, SIG_DFL);
    printf("import comes back as the import: %d\n", imp == (sig_t)abs);

    printf("dlsym of an imported function is the import: %d\n", dlsym(RTLD_DEFAULT, "abs") == (void *)abs);
    void *p = dlsym(RTLD_DEFAULT, "srandom");                 /* never imported: a genuine host function */
    signal(SIGUSR1, (sig_t)p);
    sig_t q = signal(SIGUSR1, SIG_DFL);
    printf("host function keeps dlsym identity: %d\n", (void *)q == p);
    q(7);
    printf("typed host handle called srandom(7): random() = %ld\n", random());

    int one = 1, two = 2;
    CFNumberRef n1 = CFNumberCreate(NULL, kCFNumberIntType, &one), n2 = CFNumberCreate(NULL, kCFNumberIntType, &two);
    const void *vals[] = {n1, n2};
    CFArrayRef arr = CFArrayCreate(NULL, vals, 2, &kCFTypeArrayCallBacks);
    printf("CFArray with host callbacks: count %ld contains %d\n", (long)CFArrayGetCount(arr),
           CFArrayContainsValue(arr, CFRangeMake(0, 2), n2));
    CFRelease(arr); CFRelease(n1); CFRelease(n2);
    return 0;
}
