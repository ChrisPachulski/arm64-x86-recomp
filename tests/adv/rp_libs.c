/* #8 runpath context. RP_B (built twice: run/lib = "app", run/plugins/lib = "plugin"), RP_D (run/plugins/deps only),
   RP_C (requests @rpath/librpd, declares no LC_RPATH), RP_A (plugin: requests @rpath/librpb and @rpath/librpc,
   declares @loader_path/deps). The executable declares @loader_path/lib: expanded against the executable it finds
   run/lib/librpb ("app"); librpd is found only through A's runpath, an ancestor of C in the load chain. */
#ifdef RP_B
const char *b_where(void) { return WHERE; }
#endif
#ifdef RP_D
const char *d_where(void) { return "deps"; }
#endif
#ifdef RP_C
const char *d_where(void);
const char *c_via_d(void) { return d_where(); }
#endif
#ifdef RP_A
#include <stdio.h>
const char *b_where(void);
const char *c_via_d(void);
void a_report(void) { printf("b from %s, d from %s\n", b_where(), c_via_d()); }
#endif
