/* exit(3) from a non-main thread while main is blocked in pthread_join: atexit + destructor order, exit code. */
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <unistd.h>

static void bye(void) { printf("atexit ran\n"); }
__attribute__((destructor)) static void dtor(void) { printf("dtor ran\n"); }
static void *t(void *a) { (void)a; printf("thread exiting\n"); exit(3); }

int main(void) {
    atexit(bye);
    pthread_t th;
    pthread_create(&th, NULL, t, NULL);
    pthread_join(th, NULL);
    sleep(5);
    printf("main should not get here\n");
    return 0;
}
