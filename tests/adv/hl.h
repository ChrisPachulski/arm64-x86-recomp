/* Two host libraries export the same C name; each guest image binds it two-level to its own library. */
#pragma once
int hl_f(void);
