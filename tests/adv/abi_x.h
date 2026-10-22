/* Cross-image ABI shapes shared by abi_xlib.c (guest dylib) and abi_xmain.c (guest executable). */
typedef struct { int a, b; } S8;
typedef struct { int a, b, c; } S12;
typedef struct { long a; double b; } S16;
typedef struct { long a, b, c; } S24;
typedef struct { float x, y; } HF2;
typedef struct { float x, y, z; } HF3;
typedef struct { double a, b, c; } HD3;
typedef struct { double a, b, c, d, e; } Big40;
typedef struct { char c; short s; } Odd4;

long many_int(long, long, long, long, long, long, long, long, long, long, long, long);
long many_small(int, int, int, int, int, int, int, int, char, short, char, int, Odd4);
double mixed(int, double, int, float, int, double, int, float, int, double, int, float,
             int, double, int, float, int, double, int, float, float, double, int);
S8 s8_swap(S8);
S12 s12_add(S12, S12);
S16 s16_mul(S16, int);
S24 s24_rot(S24, long);
HF2 hf2_add(HF2, HF2);
HF3 hf3_cross(HF3, HF3);
HD3 hd3_sum3(HD3, HD3, HD3, double);
Big40 big_make(double, float, double, float, double);
double apply_hd3(HD3 (*)(HD3, HD3, HD3, double), HD3);
