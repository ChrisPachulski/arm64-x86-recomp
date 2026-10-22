/* A signal handler that re-registers itself (signal()) while the main thread keeps registering it too: a signal
   delivered while the bridge is converting the handler must not deadlock the handler's own conversion. */
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <unistd.h>

static volatile sig_atomic_t handled;
static volatile int stop;
static pthread_t main_thread;

static void h(int s) { (void)s; handled++; signal(SIGUSR1, h); }
static void* sender(void* p) {
    (void)p;
    for (int i = 0; i < 20000 && !stop; i++) { pthread_kill(main_thread, SIGUSR1); if (i % 64 == 0) usleep(50); }
    return NULL;
}

int main(void) {
    main_thread = pthread_self();
    signal(SIGUSR1, h);
    pthread_t t;
    pthread_create(&t, NULL, sender, NULL);
    for (int i = 0; i < 300000; i++) signal(SIGUSR1, h);
    stop = 1;
    pthread_join(t, NULL);
    printf("done, handler ran: %s\n", handled > 0 ? "yes" : "no");
    return 0;
}
