/* OpenSSL's sigaction sites (ui_openssl.c pushsig / popsig around a terminal password read): a plain
   handler (sa_flags 0, no SA_SIGINFO) on every signal but SIGKILL, SIGUSR1 and SIGUSR2, old actions saved, SIGWINCH to
   SIG_DFL, then every saved action restored. */
#include <signal.h>
#include <stdio.h>
#include <string.h>

static struct sigaction savsig[NSIG];
static volatile sig_atomic_t intr_signal;

static void recsig(int i) { intr_signal = i; }

static void pushsig(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = recsig;
    for (int i = 1; i < NSIG; i++) {
        if (i == SIGUSR1 || i == SIGUSR2 || i == SIGKILL) continue;
        sigaction(i, &sa, &savsig[i]);
    }
    signal(SIGWINCH, SIG_DFL);
}

static void popsig(void) {
    for (int i = 1; i < NSIG; i++) {
        if (i == SIGUSR1 || i == SIGUSR2 || i == SIGKILL) continue;
        sigaction(i, &savsig[i], NULL);
    }
}

int main(void) {
    signal(SIGTERM, SIG_IGN);                                 /* a non-default action that popsig must bring back */
    pushsig();
    raise(SIGINT);
    printf("recsig saw signal %d\n", (int)intr_signal);
    struct sigaction cur;
    sigaction(SIGHUP, NULL, &cur);
    printf("while pushed: SIGHUP handler is recsig %d, flags %d\n", cur.sa_handler == recsig, cur.sa_flags);
    popsig();
    sigaction(SIGINT, NULL, &cur);
    printf("after pop: SIGINT default %d\n", cur.sa_handler == SIG_DFL);
    sigaction(SIGTERM, NULL, &cur);
    printf("after pop: SIGTERM ignored %d\n", cur.sa_handler == SIG_IGN);
    return 0;
}
