/* #10 symbol suffixes: built with __DARWIN_NON_CANCELABLE=1, so read() is _read$NOCANCEL. A thread with a pending
   deferred cancellation reads from a pipe: the non-cancelable read returns the data, the thread is then canceled at
   pthread_testcancel(). Calling the plain (cancelable) read would cancel the thread inside read. */
#include <stdio.h>
#include <pthread.h>
#include <unistd.h>

static int fds[2];
static volatile long got = -1;
static volatile int after;

static void *worker(void *arg) {
    (void)arg;
    char buf[16];
    pthread_cancel(pthread_self());
    got = read(fds[0], buf, sizeof buf);
    after = 1;
    pthread_testcancel();
    after = 2;
    return NULL;
}

int main(void) {
    pthread_t t;
    void *res = NULL;
    if (pipe(fds) || write(fds[1], "hello", 5) != 5) return 1;
    pthread_create(&t, NULL, worker, NULL);
    pthread_join(t, &res);
    printf("read %ld after %d canceled %d\n", got, after, res == PTHREAD_CANCELED);
    return 0;
}
