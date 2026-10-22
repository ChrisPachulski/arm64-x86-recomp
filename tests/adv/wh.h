/* Host library; the guest declares these weak itself. */
#pragma once
int wh_present(void);
int wh_absent(void);
extern int wh_absent_data;
