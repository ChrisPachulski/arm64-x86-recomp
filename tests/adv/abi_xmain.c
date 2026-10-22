/* Guest executable: caller side of every cross-image ABI shape; 9+ ints, mixed fp beyond 8, packed stack args. */
#include <stdio.h>
#include "abi_x.h"

int main(void) {
    printf("many_int %ld\n", many_int(1, -2, 3, -4, 5, -6, 7, -8, 900000000000L, -10, 11, 0x7fffffffffffL));
    Odd4 o = {-3, -30000};
    printf("many_small %ld\n", many_small(1, 2, 3, 4, 5, 6, 7, 8, -9, 32000, 'z', -123456, o));
    printf("mixed %a\n", mixed(1, 1.5, 2, 2.25f, 3, -3.5, 4, 0.1f, 5, 1e10, 6, -7.75f, 7, 0.3, 8, 1e-3f, 9, -1e-9,
                               10, 3.0f, -4.5f, 2.0 / 3.0, 11));
    S8 a = s8_swap((S8){7, -8});
    S12 b = s12_add((S12){1, 2, 3}, (S12){-10, 20, 0x40000000});
    S16 c = s16_mul((S16){-5, 0.125}, 3);
    S24 d = s24_rot((S24){1, 2, 3}, 0x100000000L);
    printf("s8 %d %d s12 %d %d %d s16 %ld %a s24 %ld %ld %ld\n", a.a, a.b, b.a, b.b, b.c, c.a, c.b, d.a, d.b, d.c);
    HF2 e = hf2_add((HF2){1.5f, -2.0f}, (HF2){0.25f, 3.5f});
    HF3 f = hf3_cross((HF3){1, 2, 3}, (HF3){-4, 0.5f, 6});
    HD3 v = {1.25, -2.5, 3.75};
    HD3 g = hd3_sum3(v, (HD3){0.5, 0.5, 2}, (HD3){-1, 4, 1e3}, 0.75); /* third HD3 spills: v0-v7 hold only 2 */
    Big40 h = big_make(1.0, 2.5f, -3.0, 0.1f, 9.0);
    printf("hf2 %a %a hf3 %a %a %a hd3 %a %a %a\n", e.x, e.y, f.x, f.y, f.z, g.a, g.b, g.c);
    printf("big40 %a %a %a %a %a apply %a\n", h.a, h.b, h.c, h.d, h.e, apply_hd3(hd3_sum3, v));
    return 0;
}
