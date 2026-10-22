// A struct the host allocates and keeps (FTS from fts_open) with a guest comparator stored in it: every fts_read must
// still call the comparator with its two arguments, and the guest calling through the stored field reaches its function.
#include <fts.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int calls, nulls;
static int rev(const FTSENT** a, const FTSENT** b) {          /* reverse name order, so the output shows it was used */
  calls++;
  if (!a || !b || !*a || !*b) { nulls++; return 0; }
  return strcmp((*b)->fts_name, (*a)->fts_name);
}

int main(void) {
  char dir[] = "/tmp/gdyld_keepsXXXXXX";
  if (!mkdtemp(dir)) return 2;
  const char* names[] = {"b.txt", "d.txt", "a.txt", "c.txt"};
  for (int i = 0; i < 4; i++) { char p[256]; snprintf(p, sizeof p, "%s/%s", dir, names[i]); fclose(fopen(p, "w")); }
  for (int round = 0; round < 2; round++) {                   /* the second open reuses nothing from the first */
    char* roots[] = {dir, NULL};
    FTS* fts = fts_open(roots, FTS_PHYSICAL | FTS_NOCHDIR, rev);
    printf("round %d:", round);
    for (FTSENT* e; (e = fts_read(fts));) if (e->fts_info == FTS_F) printf(" %s", e->fts_name);
    FTSENT x = {0}; const FTSENT* px = &x;                    /* empty name: rev(x, x) is 0 */
    int (*stored)(const FTSENT**, const FTSENT**) = (int (*)(const FTSENT**, const FTSENT**))fts->fts_compar;
    printf(" | stored(x, x) %d\n", stored(&px, &px));
    fts_close(fts);
  }
  printf("comparator calls > 0: %d, null arguments: %d\n", calls > 0, nulls);
  for (int i = 0; i < 4; i++) { char p[256]; snprintf(p, sizeof p, "%s/%s", dir, names[i]); unlink(p); }
  rmdir(dir);
  return 0;
}
