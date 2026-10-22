/* LIMIT: an SA_SIGINFO handler that edits the interrupted machine context (here a scratch register) cannot be honored
   by the translated world; it must stop loudly instead of writing into the host's x86 context. */
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/ucontext.h>

static void h(int s, siginfo_t* si, void* p) {
    (void)s; (void)si;
    ucontext_t* uc = (ucontext_t*)p;
#if defined(__arm64__)
    uc->uc_mcontext->__ss.__x[9] = 12345;
#else
    uc->uc_mcontext->__ss.__r11 = 12345;
#endif
}

int main(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = h;
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGUSR1, &sa, NULL);
    printf("before raise\n");
    fflush(stdout);
    raise(SIGUSR1);
    printf("after raise\n");
    return 0;
}
