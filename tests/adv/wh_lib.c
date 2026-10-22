/* Link-time copy (WH_FULL) defines everything; the run-time copy lacks wh_absent and wh_absent_data. */
#include "wh.h"
int wh_present(void) { return 11; }
#ifdef WH_FULL
int wh_absent(void) { return 22; }
int wh_absent_data = 33;
#endif
