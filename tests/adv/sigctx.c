/* SA_SIGINFO handler reading the interrupted machine context through its own architecture's layout: the stack
   pointer, frame pointer and pc must be plausible values of the interrupted thread, and siginfo must be intact. */
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ucontext.h>

static uintptr_t top;
static int signo, sp_ok, fp_ok, pc_ok, size_ok;

static void h(int s, siginfo_t* si, void* p) {
    ucontext_t* uc = (ucontext_t*)p;
#if defined(__arm64__)
    uint64_t sp = uc->uc_mcontext->__ss.__sp, fp = uc->uc_mcontext->__ss.__fp, pc = uc->uc_mcontext->__ss.__pc;
#else
    uint64_t sp = uc->uc_mcontext->__ss.__rsp, fp = uc->uc_mcontext->__ss.__rbp, pc = uc->uc_mcontext->__ss.__rip;
#endif
    signo = s == si->si_signo ? s : -1;
    sp_ok = sp < top && sp > top - (1u << 20);
    fp_ok = fp >= sp && fp < top + 4096;
    pc_ok = pc > 4096;
    size_ok = uc->uc_mcsize >= sizeof *uc->uc_mcontext;
}

int main(void) {
    char anchor = 0;
    top = (uintptr_t)&anchor;
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = h;
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGUSR1, &sa, NULL);
    raise(SIGUSR1);
    printf("signo %d sp_ok %d fp_ok %d pc_ok %d mcsize_ok %d\n", signo, sp_ok, fp_ok, pc_ok, size_ok);
    struct sigaction old;
    sigaction(SIGUSR1, NULL, &old);
    printf("old handler is h: %d, SA_SIGINFO kept: %d\n", old.sa_sigaction == h, (old.sa_flags & SA_SIGINFO) != 0);
    return 0;
}
