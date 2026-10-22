#include "hcb.h"
long hcb_run(hcb_cb cb, long x) { volatile char pad[512]; pad[0] = (char)x; return cb(x) + pad[0] - (char)x; }
hcb_run_fn hcb_runner(void) { return hcb_run; }
