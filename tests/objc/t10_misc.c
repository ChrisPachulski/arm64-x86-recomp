// flags: -liconv
/* The small imports: swprintf (Apple-arm64 variadic, wide format), CommonCrypto SHA-256, __ulock_wait/__ulock_wake (a waiter
   parked on a guest address and woken by another thread), fortified string functions. */
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include <stdint.h>
#include <pthread.h>
#include <unistd.h>
#include <CommonCrypto/CommonDigest.h>
#include <CommonCrypto/CommonCryptor.h>
#include <CommonCrypto/CommonRandom.h>
#include <mach-o/dyld.h>
#include <libgen.h>
#include <fnmatch.h>
#include <poll.h>
#include <iconv.h>
#include <sys/event.h>
#include <sys/sysctl.h>
#include <malloc/malloc.h>

extern int __ulock_wait(uint32_t op, void* addr, uint64_t value, uint32_t timeout_us);
extern int __ulock_wake(uint32_t op, void* addr, uint64_t wake_value);
#define UL_COMPARE_AND_WAIT 1

static volatile uint32_t word;
static void* waker(void* p) {
  (void)p;
  usleep(20000);
  __atomic_store_n(&word, 1, __ATOMIC_SEQ_CST);
  __ulock_wake(UL_COMPARE_AND_WAIT, (void*)&word, 0);
  return NULL;
}

int main(void) {
  wchar_t w[128];
  int n = swprintf(w, 128, L"%d|%5.2f|%ls|%s|%c|%lc|%x|%%", 42, 3.14159, L"wide", "narrow", 'c', L'W', 255);
  printf("swprintf %d: %ls\n", n, w);
  printf("swprintf overflow: %d\n", swprintf(w, 4, L"%s", "toolong"));
  unsigned char md[CC_SHA256_DIGEST_LENGTH];
  CC_SHA256_CTX ctx;
  CC_SHA256_Init(&ctx);
  CC_SHA256_Update(&ctx, "ab", 2);
  CC_SHA256_Update(&ctx, "c", 1);
  CC_SHA256_Final(md, &ctx);
  printf("sha256(abc) = ");
  for (int i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) printf("%02x", md[i]);
  printf("\n");
  CC_SHA256("hello", 5, md);
  printf("sha256(hello) starts %02x%02x%02x%02x\n", md[0], md[1], md[2], md[3]);
  pthread_t t;
  pthread_create(&t, NULL, waker, NULL);
  int waits = 0;
  while (__atomic_load_n(&word, __ATOMIC_SEQ_CST) == 0) { __ulock_wait(UL_COMPARE_AND_WAIT, (void*)&word, 0, 0); waits++; }
  pthread_join(t, NULL);
  printf("ulock: woken, word %u\n", word); (void)waits;
  printf("ulock_wake with no waiter: %d\n", __ulock_wake(UL_COMPARE_AND_WAIT, (void*)&word, 0) < 0);
  char buf[16];
  strlcpy(buf, "fortified", sizeof buf);
  strlcat(buf, "-cat", sizeof buf);
  char big[32]; memcpy(big, buf, sizeof buf); memset(big + 13, '!', 2); big[15] = 0;
  snprintf(big + 16, 16, "%d-%s", 7, "x");
  printf("chk: %s %s\n", big, big + 16);
  char path[1024]; uint32_t psz = sizeof path;
  printf("executable: %d %s\n", _NSGetExecutablePath(path, &psz), basename(path));
  printf("fnmatch %d %d poll %d\n", fnmatch("*.m", "t.m", 0), fnmatch("*.m", "t.c", 0), poll(NULL, 0, 0));
  int kq = kqueue(); printf("kqueue %s\n", kq >= 0 ? "ok" : "fail"); close(kq);
  int pg = 0; size_t pgl = sizeof pg; sysctlbyname("hw.pagesize", &pg, &pgl, NULL, 0); printf("pagesize %d\n", pg);
  unsigned char rnd[8]; printf("random rc %d\n", (int)CCRandomGenerateBytes(rnd, sizeof rnd));
  unsigned char key[16] = {0}, in[16] = {0}, out[32]; size_t moved = 0;
  CCCryptorStatus st = CCCrypt(kCCEncrypt, kCCAlgorithmAES, kCCOptionECBMode, key, 16, NULL, in, 16, out, sizeof out, &moved);
  printf("aes: %d %zu %02x%02x%02x%02x\n", (int)st, moved, out[0], out[1], out[2], out[3]);
  iconv_t cd = iconv_open("UTF-16LE", "UTF-8"); char src[] = "h\xc3\xa9", dst[16]; char* ip = src; char* op = dst; size_t il = 3, ol = sizeof dst;
  size_t r = iconv(cd, &ip, &il, &op, &ol); iconv_close(cd);
  printf("iconv %zu out %zu bytes %02x %02x\n", r, sizeof dst - ol, (unsigned char)dst[2], (unsigned char)dst[3]);
  void* zp = malloc_zone_malloc(malloc_default_zone(), 64); printf("zone alloc %s\n", zp ? "ok" : "fail"); malloc_zone_free(malloc_default_zone(), zp);
  return 0;
}
