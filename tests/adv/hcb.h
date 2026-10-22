/* Host library for the handle-chain test: hcb_runner() hands the guest a host function pointer (a typed handle, not an
   import) that calls back into guest code. */
#pragma once
typedef long (*hcb_cb)(long);
typedef long (*hcb_run_fn)(hcb_cb, long);
long hcb_run(hcb_cb cb, long x);
hcb_run_fn hcb_runner(void);
