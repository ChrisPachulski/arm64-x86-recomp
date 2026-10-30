/* icall_gic's library: 64 functions 512 bytes apart. gdyld loads it 32 MB above the main image, so the shared inline-cache
   slot of a function here ((t >> 2) ^ (t >> 18), 16 bits) is that of a main-image function 512 bytes away in image offset. */
#define F(n) __attribute__((aligned(512), noinline)) long lf##n(long x) { return x * (2 * n + 3) + n; }
F(0) F(1) F(2) F(3) F(4) F(5) F(6) F(7) F(8) F(9) F(10) F(11) F(12) F(13) F(14) F(15)
F(16) F(17) F(18) F(19) F(20) F(21) F(22) F(23) F(24) F(25) F(26) F(27) F(28) F(29) F(30) F(31)
F(32) F(33) F(34) F(35) F(36) F(37) F(38) F(39) F(40) F(41) F(42) F(43) F(44) F(45) F(46) F(47)
F(48) F(49) F(50) F(51) F(52) F(53) F(54) F(55) F(56) F(57) F(58) F(59) F(60) F(61) F(62) F(63)
typedef long (*fn)(long);
#undef F
#define F(n) lf##n,
fn const LT[64] = {
F(0) F(1) F(2) F(3) F(4) F(5) F(6) F(7) F(8) F(9) F(10) F(11) F(12) F(13) F(14) F(15)
F(16) F(17) F(18) F(19) F(20) F(21) F(22) F(23) F(24) F(25) F(26) F(27) F(28) F(29) F(30) F(31)
F(32) F(33) F(34) F(35) F(36) F(37) F(38) F(39) F(40) F(41) F(42) F(43) F(44) F(45) F(46) F(47)
F(48) F(49) F(50) F(51) F(52) F(53) F(54) F(55) F(56) F(57) F(58) F(59) F(60) F(61) F(62) F(63)
};
