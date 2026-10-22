/* ABI-route bed program: SecureTransport's cipher-suite arrays (SSLCipherSuite is uint16_t on arm64 macOS, uint32_t on
   x86_64) through SSLGetNumberSupportedCiphers, SSLGetSupportedCiphers into a buffer of exactly that many entries,
   SSLSetEnabledCiphers with the first eight, SSLGetEnabledCiphers back, and SSLGetNegotiatedCipher before a handshake
   (an error that leaves the value alone). Prints statuses, counts and cipher IDs. */
#include <Security/SecureTransport.h>
#include <stdio.h>
#include <stdlib.h>

static void ids(const char* what, const SSLCipherSuite* v, size_t n) {
  printf("%s:", what);
  for (size_t i = 0; i < n; i++) printf(" %04x", (unsigned)v[i]);
  printf("\n");
}

int main(void) {
  SSLContextRef c = SSLCreateContext(NULL, kSSLClientSide, kSSLStreamType);
  size_t n = 0;
  OSStatus s1 = SSLGetNumberSupportedCiphers(c, &n);
  SSLCipherSuite* v = malloc(n * sizeof *v);
  size_t m = n;
  OSStatus s2 = SSLGetSupportedCiphers(c, v, &m);
  printf("supported status %d %d count %zu returned %zu\n", (int)s1, (int)s2, n, m);
  ids("supported", v, m);
  OSStatus s3 = SSLSetEnabledCiphers(c, v, n < 8 ? n : 8);
  size_t e = 0;
  OSStatus s4 = SSLGetNumberEnabledCiphers(c, &e);
  SSLCipherSuite* w = malloc((e ? e : 1) * sizeof *w);
  size_t k = e;
  OSStatus s5 = SSLGetEnabledCiphers(c, w, &k);
  printf("enabled status %d %d %d count %zu returned %zu\n", (int)s3, (int)s4, (int)s5, e, k);
  ids("enabled", w, k);
  SSLCipherSuite one = 0x1234;
  OSStatus s6 = SSLGetNegotiatedCipher(c, &one);
  printf("negotiated status %d value %04x\n", (int)s6, (unsigned)one);
  free(w); free(v); CFRelease(c);
  return 0;
}
