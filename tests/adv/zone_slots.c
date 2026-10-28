/* calls through malloc zone function slots, as SQLite's mem1 does: the virtual default zone (not in the zone list) and
   a created zone (in it) */
#include <malloc/malloc.h>
#include <stdio.h>
#include <string.h>

static int use(malloc_zone_t* z, const char* name) {
  char* p = z->malloc(z, 100);
  if (!p) return printf("%s: malloc failed\n", name), 1;
  memset(p, 'a', 100);
  int ok = z->size(z, p) >= 100;
  p = z->realloc(z, p, 5000);
  ok = ok && p && p[99] == 'a' && z->size(z, p) >= 5000;
  int* q = z->calloc(z, 10, sizeof(int));
  ok = ok && q && q[9] == 0;
  void* m = z->version >= 5 && z->memalign ? z->memalign(z, 256, 64) : z->malloc(z, 64);
  ok = ok && m && (z->version < 5 || !z->memalign || ((unsigned long)m & 255) == 0);
  z->free(z, q);
  z->free(z, m);
  z->free(z, p);
  printf("%s: %s\n", name, ok ? "ok" : "wrong");
  return !ok;
}

int main(void) {
  int bad = use(malloc_default_zone(), "default zone");
  malloc_zone_t* z = malloc_create_zone(0, 0);
  malloc_set_zone_name(z, "zone_slots");
  bad |= use(z, "created zone");
  malloc_destroy_zone(z);
  return bad;
}
