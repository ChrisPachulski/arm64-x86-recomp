/* Host-library ABI shapes (#4 16-byte aggregates, #5 HFA/HVA unions and structs). The library is built for x86_64
   and served to the translated guest as a host library (gdyld host_extra), so every call crosses gbridge.hpp. */
typedef struct { long a, b; } __attribute__((aligned(16))) P16;      /* 16-byte aligned: may start in an odd x reg */
typedef struct { double a; } __attribute__((aligned(16))) DPad;      /* padding: not an HFA, two x regs */
typedef union { double a; double b[2]; } UD2;                         /* union HFA, 2 doubles */
typedef union { float f[3]; struct { float x, y, z; } s; } UF3;       /* union HFA, 3 floats */
typedef struct { UD2 u; double d; } SUD;                              /* struct holding a union: HFA, 3 doubles */
typedef union { double d; long l; } UMIX;                             /* mixed union: one x reg */
typedef float v4f __attribute__((ext_vector_type(4)));                /* short vector: one q reg */
typedef struct { v4f c[2]; } HVA2;                                    /* HVA, 2 q regs */

long h_p16(long x, P16 p, long y);
long h_p16_spill(long a0, long a1, long a2, long a3, long a4, long a5, long a6, P16 p, long y);
long h_p16_stack(long a0, long a1, long a2, long a3, long a4, long a5, long a6, long a7, int z, P16 p, long y);
P16 h_p16_ret(long x);
double h_dpad(long x, DPad p, long y);
UD2 h_ud2(UD2 u, double k);
UF3 h_uf3(double a0, double a1, double a2, double a3, double a4, double a5, double a6, UF3 u, char c, float z);
SUD h_sud(SUD s, UD2 u, double k);
UMIX h_umix(long a, UMIX u, double d);
HVA2 h_hva2(HVA2 h, v4f k);
v4f h_v4(v4f a, v4f b);
long h_call_p16(long (*f)(long, P16, long), long x);
double h_call_ud2(UD2 (*f)(UD2, double), double k);
float h_call_uf3(UF3 (*f)(double, double, double, double, double, double, double, UF3, char, float));
double h_call_sud(SUD (*f)(SUD, UD2, double));
float h_call_hva2(HVA2 (*f)(HVA2, v4f));
double h_call_dpad(double (*f)(long, DPad, long));
