// fts_open with and without a guest comparator (argv[1] "nocmp"), and fts_children: isolates the c1 fts crash.
#include <fts.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int ncmp;
static int cmp_fts(const FTSENT** a, const FTSENT** b) {
  if (!ncmp++) { printf("cmp entered a=%d b=%d\n", a != NULL, b != NULL); printf("cmp *a=%d\n", *a != NULL); printf("cmp name %s\n", (*a)->fts_name); }
  return strcmp((*a)->fts_name, (*b)->fts_name);
}

int main(int argc, char** argv) {
  setvbuf(stdout, NULL, _IOLBF, 0);
  int nocmp = argc > 1 && !strcmp(argv[1], "nocmp");
  char dir[] = "/tmp/gdyld_ftsXXXXXX"; mkdtemp(dir);
  const char* names[] = {"b.txt", "a.txt", "c.dat"};
  for (int i = 0; i < 3; i++) { char p[256]; snprintf(p, sizeof p, "%s/%s", dir, names[i]); fclose(fopen(p, "w")); }
  char* roots[] = {dir, NULL};
  printf("fts_open (%s)\n", nocmp ? "no comparator" : "guest comparator");
  FTS* fts = fts_open(roots, FTS_PHYSICAL | FTS_NOCHDIR, nocmp ? NULL : cmp_fts);
  printf("opened %d, stored comparator is ours %d\n", fts != NULL, (void*)fts->fts_compar == (void*)(nocmp ? NULL : cmp_fts));
  int files = 0;
  for (FTSENT* e; (e = fts_read(fts));) {
    printf("entry info %d level %d namelen %d, stored comparator is ours %d\n", e->fts_info, (int)e->fts_level, (int)e->fts_namelen,
           (void*)fts->fts_compar == (void*)(nocmp ? NULL : cmp_fts));
    if (e->fts_info == FTS_F) files++;
  }
  fts_close(fts);
  printf("files %d comparator used %d\n", files, ncmp > 0);
  for (int i = 0; i < 3; i++) { char p[256]; snprintf(p, sizeof p, "%s/%s", dir, names[i]); unlink(p); } rmdir(dir);
  return 0;
}
