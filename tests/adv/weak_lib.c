/* Link-time dylib: WEAK_FULL defines maybe() (link stub); the runtime copy is built without it. */
int always(void) { return 7; }
#ifdef WEAK_FULL
int maybe(void) { return 99; }
int maybe_data = 5;
#endif
