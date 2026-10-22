// A FILE left open is flushed by exit() inside the host libc, which calls the FILE's own _write: a fopen'd file
// (libc's __swrite) and a funopen'd one (a guest write callback). Any bridged call taking the FILE* runs first.
// argv[1]: "fopen" or "funopen" (default: both).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int w_cb(void* c, const char* b, int n) { fprintf(stderr, "funopen write callback: %d bytes\n", n); return n; }

int main(int argc, char** argv) {
  const char* w = argc > 1 ? argv[1] : "both";
  if (strcmp(w, "funopen")) {
    FILE* f = fopen("exit_flush.txt", "w");
    fputs("line one\n", f);                                     // a bridged call taking the FILE*
    fwrite("line two\n", 1, 9, f);
    printf("fopen: written, left open, ftell %ld\n", ftell(f));
  }
  if (strcmp(w, "fopen")) {
    FILE* g = funopen(NULL, NULL, w_cb, NULL, NULL);
    fputs("to the callback\n", g);
    printf("funopen: written, left open\n");
  }
  fflush(stdout);
  return 0;                                                     // exit() flushes both FILEs in the host libc
}
