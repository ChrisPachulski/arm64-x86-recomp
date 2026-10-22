/* #7 flat lookup order. One source, four dylibs: FO_A re-exports C, FO_B and FO_C both define f(), FO_D is built
   -undefined dynamic_lookup so its call to f() is a flat bind. Load order main, A, B, D, C: a shallow flat search
   finds B; following A's re-export first would wrongly pick C. */
#if defined(FO_B) || defined(FO_C)
const char *f(void) {
#ifdef FO_B
    return "B";
#else
    return "C";
#endif
}
#endif
#ifdef FO_A
int a_marker(void) { return 1; }
#endif
#ifdef FO_D
const char *f(void);
const char *d_calls_f(void) { return f(); }
#endif
