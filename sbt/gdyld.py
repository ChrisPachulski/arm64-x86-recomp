"""gdyld: multi-image guest loader for the AArch64 -> C -> x86-64 recompiler. Loads an arm64 executable and its
guest dylibs at per-image bases, resolves binds through export tries (two-level, flat, weak, interpose), lifts
every image into its own C unit, generates the host bridge table (bridge.hpp, prototypes from the real SDK
headers) and the layout (initializers, TLV, LC_MAIN), and links one native x86-64 executable.
Library; proven by tests/adv/run_adv.py."""
###############
# imports and constants
###############
from __future__ import annotations
import bisect, concurrent.futures, functools, hashlib, importlib, json, multiprocessing, os, re, resource, shutil, struct, subprocess, sys, time
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
import macho
import recompile as R
import gswift

HERE = os.path.dirname(os.path.abspath(__file__))
V8DIR = os.path.join(os.path.dirname(HERE), "v8")                     # pinned headers + per-build V8 generators
V8_LIB_RE = re.compile(r"/libv8(_libbase|_libplatform)?\.dylib$")
V8_HEADERS = ["v8.h", "libplatform/libplatform.h", "libplatform/v8-tracing.h", "v8-inspector.h"]
V8_DEFINES = ["-DV8_COMPRESS_POINTERS", "-DV8_31BIT_SMIS_ON_64BIT_ARCH"]   # embedder config 3 (V8::Initialize(3))
V8_STACK_ARGS = {"__ZN2v87Isolate13SetStackLimitEm": 1}                # import -> x register holding a guest-stack address
GUESTRT = os.environ.get("GDYLD_GUESTRT") or os.path.join(os.path.dirname(HERE), "guestrt", "lib")   # guestrt/build.sh output
OBJ_CACHE = os.environ.get("GDYLD_OBJCACHE") or os.path.join(HERE, "build", "objcache")   # content-addressed .o of image chunks
EXT_FILE = os.path.join(HERE, "extensions.txt")                       # optional: host-library bridge modules, one per line
EXTENSIONS = [importlib.import_module(m.strip()) for m in (open(EXT_FILE) if os.path.exists(EXT_FILE) else [])
              if m.strip() and not m.lstrip().startswith("#")]        # each: LIB_RE, HEADER, prepare(names, keys, out_dir, sdk)
RUNTIME = {"/usr/lib/libunwind.1.dylib": "libunwind.1.dylib", "/usr/lib/libc++abi.1.dylib": "libc++abi.1.dylib",
           "/usr/lib/libc++abi.dylib": "libc++abi.1.dylib", "/usr/lib/libc++.1.dylib": "libc++.1.dylib"}   # install name -> guest file
RUNTIME_LOAD = {"/usr/lib/libunwind.1.dylib": 0x400000000, "/usr/lib/libc++abi.1.dylib": 0x410000000,
                "/usr/lib/libc++.1.dylib": 0x420000000}               # fixed bases: runtime chunks are identical in every program
LIBSYSTEM, LIBUNWIND = "/usr/lib/libSystem.B.dylib", "/usr/lib/libunwind.1.dylib"   # libSystem re-exports the unwinder
INTRINSICS = {LIBUNWIND: {"___libunwind_Registers_arm64_jumpto": "gd_jumpto"}}      # image id -> {local symbol: host function}
SETJMP = {"_setjmp", "__setjmp", "_sigsetjmp"}                         # their return sites become resume points
FULL_SPILL = {"___chkstk_darwin"}                                      # host routines reading past the arguments (sp_chkstk: x9): GDA_G_
MSG_SENDS = {"_objc_msgSend": 0, "_objc_msgSendSuper": 1, "_objc_msgSendSuper2": 2}   # recompile GD_MSGSEND kinds (gobjc send's sup)
CHUNK_INSNS = 6000                                                     # instructions per compiled C chunk (bounds clang RSS)
FUNC_RE = re.compile(r"\bfunc_([0-9a-f]+)\b")                          # a lifted function's C name in chunk source
OPTNONE_CASES = 256                                                    # ponytail: -O0 for undecoded-br functions; decode their tables if hot
FLAT_O2_CASES = 8192                                                   # a c->-state switch this size compiles in ~10 s at -O2; 45k cases took >10 min
LC_SYMTAB, N_TYPE, N_SECT, N_STAB = 0x2, 0x0E, 0x0E, 0xE0
CLANG, CLANGXX = "/usr/bin/clang", "/usr/bin/clang++"
GUEST_BASE = 0x200000000
IMAGE_ALIGN = 0x1000000
IMPORT_BASE = 0x1F0000000                                              # one 64-byte slot per host import, below the images
IMP_SLOT = 64
HANDLE_BASE = IMPORT_BASE + 0x8000000                                  # typed handles for host function pointers given to the guest
RT_CONSTS = {"GD_IMPORT_BASE": "0x%xULL" % IMPORT_BASE, "GD_IMP_SLOT": IMP_SLOT,
             "GD_HANDLE_BASE": "0x%xULL" % HANDLE_BASE, "GD_HANDLE_SLOT": 16, "GD_MAX_HANDLES": 4096, "GD_MAX_CLOSURES": 65536,
             "GD_MAIN_STACK": "(8ULL<<20)", "GD_THREAD_STACK": "(8ULL<<20)", "GD_CB_STACK": "(8ULL<<20)",
             "GD_MIN_HOST_STACK": "(16ULL<<20)", "GD_STACK_PAD": 4096, "GD_REDZONE": 256, "GD_ARGS": 1024, "GD_COPY": 4096}
HOST_MAIN_STACK = "0x20000000"                                         # 512 MB host main stack: one host frame per guest frame
BUILD_JOBS = 8
RAM_GB = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") >> 30
LIFT_JOBS = int(os.environ.get("GDYLD_LIFT_JOBS") or max(1, min(8, (os.cpu_count() or 2) // 2, RAM_GB // 8)))   # lift processes (1: serial streamed lift); one per 2 cores, per 8 GB
LIFT_MIN_CHUNKS = 16                                                   # fewer chunks in all images: lift serially (forking costs more)
LIFT_TASK_CHUNKS = 4                                                   # chunks per worker task
LIFT_CTX = {}                                                          # a forked lift worker's context (lift_worker_init); empty in the parent
NO_FLAGS = {"local": frozenset(), "ret": frozenset(), "sites": {}, "tails": set(), "stails": set(), "itail": False}   # recompile.flag_facts of a function no NZCV use leaves
HOST_FLAGS = {**NO_FLAGS, "ret": frozenset(["E"])}                    # an intrinsic (host code) returns the NZCV it was called with
NZCV_MODE = os.environ.get("GDYLD_NZCV", "nob")                        # flag_needs: exact | nob | direct
CHUNK_CXX = os.environ.get("GDYLD_CHUNK_LANG", "c++") == "c++"         # chunks as C++: resumable functions' try/catch wrappers sit beside their bodies
CXX_HEADERS = ["stdint.h", "string.h", "math.h", "wmmintrin.h"]        # every header recompile's prelude includes: outside extern "C" in a C++ chunk
INLINE_BODY = "static inline __attribute__((always_inline)) "          # a C++ chunk's resumable body: one copy, inside its only wrapper
CHUNK_CFLAGS = ["-O2", "-fno-strict-aliasing", "-ffp-contract=off",   # guest memory is untyped: no TBAA; no fused multiply-add
                "-fno-stack-protector",                               # host frames hold only spills; guest code keeps its own canaries
                *os.environ.get("GDYLD_CHUNK_XFLAGS", "").split(),    # experiments only (empty in every bed)
                "-mllvm", "-combiner-store-merging=false",            # an ldp pair stored as one 16-byte write is read back 8 bytes at a time and
                                                                       # vice versa: a wide load over two narrow stores stalls store forwarding
                "-mllvm", "-slp-threshold=1",                         # SLP only when clearly profitable: else adjacent spills of two guest pointers
                                                                       # turn their loop recurrences into a vector (vmovq/vpextrq every use)
                "-mavx2", "-mfma", "-mbmi", "-mbmi2", "-mlzcnt", "-mpopcnt", "-mf16c", "-maes", "-mpclmul"]   # Haswell-era x86-64 or newer
PGO = os.environ.get("GDYLD_PGO", "")                                  # generate: instrument the chunks; else an llvm-profdata profile they are optimized with
PGO_FLAGS = [] if not PGO else ["-fprofile-instr-generate"] if PGO == "generate" else [
    "-fprofile-instr-use=" + os.path.abspath(PGO),
    "-DGD_PGO=" + hashlib.sha256(open(PGO, "rb").read()).hexdigest()[:16]]   # the profile's hash is part of the object cache key
LTO = os.environ.get("GDYLD_LTO", "") == "thin"                        # ThinLTO across the chunks: inlining between them, at link time
TIME_REAL_RE = re.compile(r"^\s+([\d.]+) real\s")                    # first line of /usr/bin/time -l
NORETURN_RE = re.compile(r"\s*__attribute__\(\(noreturn\)\)$")        # not valid in an alias; the cast drops it implicitly
MH_MAGIC_64, CPU_ARM64, MH_DYLIB, MH_WEAK_DEFINES = 0xFEEDFACF, 0x0100000C, 6, 0x8000
CPU_X86_64, FAT_MAGIC, FAT_MAGIC_64 = 0x01000007, 0xCAFEBABE, 0xCAFEBABF
LC_SEGMENT_64, LC_ID_DYLIB, LC_RPATH, LC_MAIN, LC_ROUTINES_64 = 0x19, 0xD, 0x8000001C, 0x80000028, 0x1A
LC_FUNCTION_STARTS, LC_DYLD_CHAINED_FIXUPS, LC_DYLD_EXPORTS_TRIE = 0x26, 0x80000034, 0x80000033
LC_DYLD_INFO, LC_DYLD_INFO_ONLY = 0x22, 0x80000022
DYLIB_CMDS = {0xC: "load", 0x80000018: "weak", 0x8000001F: "reexport", 0x20: "load", 0x80000023: "upward"}
S_SYMBOL_STUBS, S_MOD_INIT_FUNC_POINTERS, S_INTERPOSING = 0x8, 0x9, 0xD
S_ATTR_INSTRUCTIONS = 0x80000400                                       # pure | some instructions
VM_PROT_WRITE = 2
S_THREAD_LOCAL_REGULAR, S_THREAD_LOCAL_ZEROFILL, S_THREAD_LOCAL_VARIABLES, S_INIT_FUNC_OFFSETS = 0x11, 0x12, 0x13, 0x16
CHAINED_PTR_64, CHAINED_PTR_64_OFFSET = 2, 6
EXPORT_KIND_MASK, EXPORT_ABSOLUTE, EXPORT_WEAK, EXPORT_REEXPORT, EXPORT_RESOLVER = 0x3, 0x2, 0x4, 0x8, 0x10
BIND_FLAT, BIND_WEAK = -2, -3                                          # special library ordinals
LDBL_MATH = {"acosl", "asinl", "atanl", "atan2l", "cosl", "sinl", "tanl", "acoshl", "asinhl", "atanhl", "coshl", "sinhl",
             "tanhl", "expl", "exp2l", "expm1l", "logl", "log10l", "log2l", "log1pl", "logbl", "modfl", "ldexpl", "frexpl",
             "ilogbl", "scalbnl", "scalblnl", "cbrtl", "fabsl", "hypotl", "powl", "sqrtl", "erfl", "erfcl", "lgammal",
             "tgammal", "ceill", "floorl", "nearbyintl", "rintl", "lrintl", "llrintl", "roundl", "lroundl", "llroundl",
             "truncl", "fmodl", "remainderl", "remquol", "copysignl", "nanl", "nextafterl", "nexttowardl", "fdiml", "fmaxl",
             "fminl", "fmal"}                                          # Apple arm64: long double == double, these are the double functions
LDBL_ALIAS = {"strtold": "strtod", "wcstold": "wcstod", "strtold_l": "strtod_l", "wcstold_l": "wcstod_l", "nexttowardl": "nextafter"}
SYSTEM_PREFIXES = ("/usr/lib/", "/System/")
BASE_HEADERS = ["stdio.h", "stdlib.h", "string.h", "strings.h", "math.h", "pthread.h", "unistd.h", "time.h",
                "errno.h", "fcntl.h", "signal.h", "setjmp.h", "ctype.h", "wchar.h", "locale.h", "dlfcn.h",
                "sys/socket.h", "sys/select.h", "sys/mman.h", "sys/stat.h", "sys/time.h", "arpa/inet.h",
                "netinet/in.h", "dispatch/dispatch.h", "xlocale.h", "wctype.h", "nl_types.h", "dirent.h",
                "sys/statvfs.h", "copyfile.h", "objc/runtime.h", "objc/message.h", "objc/objc-sync.h", "objc/objc-exception.h",
                "Block.h", "CommonCrypto/CommonDigest.h", "CommonCrypto/CommonCryptor.h", "CommonCrypto/CommonRandom.h",
                "mach-o/dyld.h", "aio.h", "libgen.h", "fnmatch.h", "ifaddrs.h", "sys/mount.h", "fts.h", "pwd.h", "iconv.h",
                "net/if.h", "sys/event.h", "malloc/malloc.h", "poll.h", "sys/sysctl.h", "termios.h",
                "IOKit/ps/IOPowerSources.h"]                           # prototypes of imports no other base header declares
EXTRA_DECLS = ('extern "C" int __cxa_atexit(void (*)(void *), void *, void *);\n'
               'extern "C" { id objc_retain(id); void objc_release(id); id objc_autorelease(id); id objc_retainAutorelease(id);\n'
               'id objc_retainAutoreleasedReturnValue(id); id objc_autoreleaseReturnValue(id); id objc_retainAutoreleaseReturnValue(id);\n'
               'id objc_unsafeClaimAutoreleasedReturnValue(id); id objc_claimAutoreleasedReturnValue(id); void objc_storeStrong(id*, id);\n'
               'id objc_alloc(Class); id objc_alloc_init(Class); id objc_allocWithZone(Class); id objc_opt_new(Class); id objc_opt_self(id);\n'
               'Class objc_opt_class(id); BOOL objc_opt_isKindOfClass(id, Class); BOOL objc_opt_respondsToSelector(id, SEL);\n'
               'void* objc_autoreleasePoolPush(void); void objc_autoreleasePoolPop(void*); id objc_retainBlock(id);\n'
               'id objc_getProperty(id, SEL, ptrdiff_t, BOOL); void objc_setProperty(id, SEL, ptrdiff_t, id, BOOL, signed char);\n'
               'void objc_setProperty_atomic(id, SEL, id, ptrdiff_t); void objc_setProperty_nonatomic(id, SEL, id, ptrdiff_t);\n'
               'void objc_setProperty_atomic_copy(id, SEL, id, ptrdiff_t); void objc_setProperty_nonatomic_copy(id, SEL, id, ptrdiff_t);\n'
               'void objc_copyStruct(void*, const void*, ptrdiff_t, BOOL, BOOL); id objc_initWeak(id*, id); id objc_storeWeak(id*, id);\n'
               'id objc_loadWeakRetained(id*); id objc_loadWeak(id*); void objc_destroyWeak(id*); void objc_copyWeak(id*, id*);\n'
               'void objc_moveWeak(id*, id*); int __ulock_wait(uint32_t, void*, uint64_t, uint32_t); int __ulock_wake(uint32_t, void*, uint64_t);\n'
               'void* __memcpy_chk(void*, const void*, size_t, size_t); void* __memmove_chk(void*, const void*, size_t, size_t);\n'
               'void* __memset_chk(void*, int, size_t, size_t); char* __strcpy_chk(char*, const char*, size_t);\n'
               'char* __stpcpy_chk(char*, const char*, size_t); char* __strcat_chk(char*, const char*, size_t);\n'
               'char* __strncpy_chk(char*, const char*, size_t, size_t); char* __stpncpy_chk(char*, const char*, size_t, size_t);\n'
               'char* __strncat_chk(char*, const char*, size_t, size_t); size_t __strlcpy_chk(char*, const char*, size_t, size_t);\n'
               'size_t __strlcat_chk(char*, const char*, size_t, size_t);\n'
               'void* voucher_adopt(void*); bool _availability_version_check(uint32_t, const void*); }\n')
# fortified string functions; libdispatch's voucher_adopt (voucher_t in, retained voucher_t out) and libSystem's
# _availability_version_check (count, dyld_build_version_t[]: @available), neither in a public header
HOST_LANG = "objective-c++"                                            # host.cpp: ObjC runtime, blocks, Foundation headers
NOESCAPE = "__attribute__((noescape))"                                 # a parameter attribute the bridge templates cannot match
TRAIL_ATTR_RE = re.compile(r"(\s*__attribute__\(\(\w+\)\))+$")         # nothrow etc.: not valid at the end of an alias
OBJC_SECTS = ("__objc_classlist", "__objc_catlist", "__objc_protolist", "__objc_selrefs", "__objc_nlclslist", "__objc_nlcatlist",
              "__objc_protorefs")                                      # order of the per-image OCI row (gobjc.hpp)
HOST_LINK = ["-lobjc", "-lffi"]                                        # gobjc.hpp: the ObjC runtime and typed closures
SPECIAL = {"_printf": "sp_printf", "_fprintf": "sp_fprintf", "_vprintf": "sp_vprintf", "_vfprintf": "sp_vfprintf",
           "_sprintf": "sp_sprintf", "_vsprintf": "sp_vsprintf", "_snprintf": "sp_snprintf", "_vsnprintf": "sp_vsnprintf",
           "_asprintf": "sp_asprintf", "_vasprintf": "sp_vasprintf", "_dprintf": "sp_dprintf", "_vdprintf": "sp_vdprintf",
           "_syslog": "sp_syslog", "_sscanf": "sp_sscanf", "_vsscanf": "sp_vsscanf", "_fscanf": "sp_fscanf",
           "_vfscanf": "sp_vfscanf", "_scanf": "sp_scanf", "_vscanf": "sp_vscanf", "_open": "sp_open",
           "_openat": "sp_openat", "_fcntl": "sp_fcntl", "_ioctl": "sp_ioctl", "_pthread_create": "sp_pthread_create",
           "___chkstk_darwin": "sp_chkstk", "__tlv_bootstrap": "sp_tlv", "___stack_chk_fail": "sp_stack_chk_fail",
           "dyld_stub_binder": "sp_stub_binder",                      # lazy pointers are bound eagerly
           "_sigaction": "sp_sigaction", "_dlsym": "sp_dlsym",        # handler inside a struct; code pointers become handles
           "_dlopen": "sp_dlopen", "_dlclose": "sp_dlclose", "_dlerror": "sp_dlerror",   # guest images get guest handles
           "_setjmp": "sp_setjmp", "__setjmp": "sp__setjmp", "_sigsetjmp": "sp_sigsetjmp", "_longjmp": "sp_longjmp",
           "__longjmp": "sp__longjmp", "_siglongjmp": "sp_siglongjmp", "__tlv_atexit": "sp_tlv_atexit", "_exit": "sp_exit",
           "__dyld_find_unwind_sections": "sp_find_unwind", "__dyld_register_func_for_remove_image": "sp_nop",
           "_dladdr": "sp_dladdr", "_snprintf_l": "sp_snprintf_l", "_asprintf_l": "sp_asprintf_l",
           "_sscanf_l": "sp_sscanf_l", "_syslog$DARWIN_EXTSN": "sp_syslog",   # guest images never unload
           "___cxa_atexit": "sp_cxa_atexit", "___udivti3": "sp_udivti3", "___umodti3": "sp_umodti3",
           "___divti3": "sp_divti3", "___modti3": "sp_modti3",                # compiler-rt 128-bit division: no header prototype
           "_objc_msgSend": "sp_objc_msgSend", "_objc_msgSendSuper2": "sp_objc_msgSendSuper2",   # typed from the runtime
           "_objc_msgSendSuper": "sp_objc_msgSendSuper", "_objc_retainBlock": "sp_objc_retainBlock",
           "__Block_copy": "sp_Block_copy", "__Block_object_assign": "sp_Block_object_assign",    # guest blocks become host blocks
           "_NSLog": "sp_NSLog", "_NSLogv": "sp_NSLogv", "_swprintf": "sp_swprintf", "_vswprintf": "sp_vswprintf",
           "___sprintf_chk": "sp_sprintf_chk", "___snprintf_chk": "sp_snprintf_chk", "___vsprintf_chk": "sp_vsprintf_chk",
           "___vsnprintf_chk": "sp_vsnprintf_chk", "__NSGetExecutablePath": "sp_NSGetExecutablePath",   # the guest's path
           "_objc_autoreleaseReturnValue": "sp_objc_autoreleaseReturnValue",                 # ARC return handoff, guest to guest
           "_objc_retainAutoreleaseReturnValue": "sp_objc_retainAutoreleaseReturnValue",
           "_objc_retainAutoreleasedReturnValue": "sp_objc_retainAutoreleasedReturnValue",
           "_objc_claimAutoreleasedReturnValue": "sp_objc_retainAutoreleasedReturnValue",
           "_objc_unsafeClaimAutoreleasedReturnValue": "sp_objc_unsafeClaimAutoreleasedReturnValue",
           "_class_addMethod": "sp_class_addMethod", "_class_replaceMethod": "sp_class_replaceMethod",   # guest IMPs: typed
           "_method_setImplementation": "sp_method_setImplementation", "_imp_implementationWithBlock": "sp_imp_implementationWithBlock",
           "_objc_disposeClassPair": "sp_objc_disposeClassPair",                              # moves the send cache epoch
           "___objc_personality_v0": "sp_objc_personality", "_objc_begin_catch": "sp_objc_begin_catch",   # guest @catch: the
           "_objc_end_catch": "sp_objc_end_catch", "_objc_exception_rethrow": "sp_objc_exception_rethrow"}   # guest libc++abi
HEAP_ROUTE = {"_malloc": "gd_heap_malloc", "_calloc": "gd_heap_calloc", "_aligned_alloc": "gd_heap_aligned_alloc",
              "_malloc_zone_malloc": "gd_heap_zone_malloc", "_malloc_zone_free": "gd_heap_zone_free",
              "_malloc_zone_realloc": "gd_heap_zone_realloc"}   # gbridge GDYLD_HEAP_GUARD; the system calls when it is unset
ABI_ROUTE = {"_SSLGetSupportedCiphers": "AbiNarrowGet<uint16_t, &::SSLGetSupportedCiphers>",   # SSLCipherSuite: uint16_t
             "_SSLGetEnabledCiphers": "AbiNarrowGet<uint16_t, &::SSLGetEnabledCiphers>",       # on arm64 macOS, uint32_t on
             "_SSLSetEnabledCiphers": "AbiWidenSet<uint16_t, &::SSLSetEnabledCiphers>",        # x86_64 (CipherSuite.h); the
             "_SSLGetNegotiatedCipher": "AbiNarrowOne<uint16_t, &::SSLGetNegotiatedCipher>"}   # guest's arrays are converted
TRAPS = {"___cxa_throw", "___cxa_rethrow", "___cxa_allocate_exception", "___cxa_begin_catch", "___cxa_end_catch",
         "__Unwind_Resume", "__Unwind_RaiseException", "_vfork", "_makecontext", "_swapcontext", "_getcontext",
         "_setcontext"}                                                # C++ EH symbols trap only when no guest runtime serves them
LEAF_IMPORTS = frozenset("_" + n for n in (                            # gbridge_leaf: never call back, never raise, never read tls_cur
    "memcmp bcmp memcpy memmove memset bzero memchr memset_pattern4 memset_pattern8 memset_pattern16 "
    "strlen strnlen strcmp strncmp strcpy strncpy strlcpy strlcat strcat strncat strchr strrchr strstr "
    "strcasecmp strncasecmp wcslen wmemcmp wmemcpy wmemmove wmemset abs labs llabs "
    "sqrt sqrtf sin sinf cos cosf tan tanf asin asinf acos acosf atan atanf atan2 atan2f exp expf exp2 exp2f "
    "log logf log2 log2f log10 log10f pow powf floor floorf ceil ceilf round roundf trunc truncf fmod fmodf "
    "sinh sinhf cosh coshf tanh tanhf hypot hypotf cbrt cbrtf lround lroundf llround llroundf expm1 expm1f "
    "log1p log1pf __sincos_stret __sincosf_stret").split())
GUEST_UNWINDER = ("__Unwind_RaiseException", "_unw_step", "__Unwind_Backtrace")   # exports of a guest unwinder (recompile GD_CSE)
LEAF_DIRECT = {"_memcpy": "c->X[0]=(uint64_t)(uintptr_t)memcpy(GDL_P(0),GDL_P(1),(size_t)c->X[2])",
               "_memmove": "c->X[0]=(uint64_t)(uintptr_t)memmove(GDL_P(0),GDL_P(1),(size_t)c->X[2])",
               "_memset": "c->X[0]=(uint64_t)(uintptr_t)memset(GDL_P(0),(int)c->X[1],(size_t)c->X[2])",
               "_memchr": "c->X[0]=(uint64_t)(uintptr_t)memchr(GDL_P(0),(int)c->X[1],(size_t)c->X[2])",
               "_memcmp": "c->X[0]=(uint64_t)(int64_t)memcmp(GDL_P(0),GDL_P(1),(size_t)c->X[2])",
               "_strlen": "c->X[0]=(uint64_t)strlen((const char*)GDL_P(0))",
               "_strcmp": "c->X[0]=(uint64_t)(int64_t)strcmp((const char*)GDL_P(0),(const char*)GDL_P(1))",
               "_strncmp": "c->X[0]=(uint64_t)(int64_t)strncmp((const char*)GDL_P(0),(const char*)GDL_P(1),(size_t)c->X[2])"}
                                                                       # LEAF_IMPORTS a stub call runs in place (recompile GD_LEAF), as
                                                                       # put_ret and hold encode them: int sign-extended, pointers as is
LIBOBJC, LIBCXXABI = "/usr/lib/libobjc.A.dylib", "/usr/lib/libc++abi.dylib"   # ObjC exceptions run in the guest libc++abi
VK = {"nil": 1, "fmt": 2, "valist": 3, "unknown": 4}                    # gobjc.hpp VK_* (variadic host method kinds)
UI_LIB_RE = re.compile(r"/(AppKit|Metal|MetalKit|MetalFX|MetalPerformanceShaders\w*)\.framework/|/libswift(AppKit|Metal|MetalKit|QuartzCore)\.dylib$")
UI_SYM_RE = re.compile(r"_(CGS|SLS|CGDisplay|CGMainDisplayID|CGGetActiveDisplayList|CGGetOnlineDisplayList|CGGetDisplays|CGWindow|"
                       r"CGWarpMouse|CGAssociateMouse|CGEvent(Post|Tap|Source)|CGCursor|CGSession|CGShield|CGCapture|CGRelease|"
                       r"CGConfigure|CGBeginDisplay|CGCompleteDisplay|CGCancelDisplay|CGAcquireDisplay|CGSetDisplay|CGRestore|"
                       r"CGRequestScreen|CGPreflightScreen|CVDisplayLink|CVMetal|NSApplication|NSBeep|NSRectFill|"
                       r"CFUserNotification)")                         # window server, displays, GPU; CF modal alerts (assert reporters)
UI_RECV = {"_objc_alloc", "_objc_alloc_init", "_objc_allocWithZone", "_objc_opt_new", "_objc_opt_self", "_objc_opt_class",
           "_objc_opt_isKindOfClass", "_objc_opt_respondsToSelector"}   # receiver in x0: an AppKit/Metal class stops (gobjc ui_check)
PRELUDE_BASE = "#define GUEST_BASE 0x200000000ULL"
MASK64 = 2 ** 64 - 1

###############
# Mach-O parsing
###############
def cstr(b: bytes, i: int) -> str:
    return b[i:b.index(b"\0", i)].decode()

def parse_image(path: str) -> dict:
    """Load commands of one thin arm64 Mach-O: segments, sections (with flags), dylib deps, rpaths, LC_MAIN, fixup info."""
    data = open(path, "rb").read()
    magic, cpu, _, filetype, ncmds = struct.unpack_from("<5I", data, 0)
    if magic != MH_MAGIC_64 or cpu != CPU_ARM64:
        raise ValueError("%s: not a thin arm64 Mach-O" % path)
    m = {"path": os.path.realpath(path), "data": data, "filetype": filetype, "segs": [], "sects": [], "deps": [],
         "rpaths": [], "main_off": None, "chained": None, "dyld_info": None, "exports_lc": None, "fstarts_lc": None,
         "flags": struct.unpack_from("<I", data, 24)[0], "routines": None, "id": None, "symtab": None, "sect_align": {}, "ro_segs": set()}
    i = 32
    for _ in range(ncmds):
        cmd, sz = struct.unpack_from("<II", data, i)
        if cmd == LC_ID_DYLIB:
            m["id"] = cstr(data, i + struct.unpack_from("<I", data, i + 8)[0])
        elif cmd == LC_SYMTAB:
            m["symtab"] = struct.unpack_from("<4I", data, i + 8)
        elif cmd == LC_SEGMENT_64:
            m["segs"].append((cstr(data[i + 8:i + 24] + b"\0", 0),) + struct.unpack_from("<4Q", data, i + 24))
            if not struct.unpack_from("<I", data, i + 60)[0] & VM_PROT_WRITE: m["ro_segs"].add(m["segs"][-1][0])   # initprot
            for k in range(struct.unpack_from("<I", data, i + 64)[0]):
                s = i + 72 + 80 * k
                addr, size, off, align = struct.unpack_from("<QQII", data, s + 32)
                flags, _r1, r2 = struct.unpack_from("<3I", data, s + 64)
                m["sects"].append((cstr(data[s + 16:s + 32] + b"\0", 0), cstr(data[s:s + 16] + b"\0", 0), addr, size, off, flags, r2))
                m["sect_align"][m["sects"][-1][:2]] = 1 << align       # (segment, section) -> bytes
        elif cmd in DYLIB_CMDS:
            m["deps"].append((cstr(data, i + struct.unpack_from("<I", data, i + 8)[0]), DYLIB_CMDS[cmd]))
        elif cmd == LC_RPATH:
            m["rpaths"].append(cstr(data, i + struct.unpack_from("<I", data, i + 8)[0]))
        elif cmd == LC_MAIN:
            m["main_off"] = struct.unpack_from("<Q", data, i + 8)[0]
        elif cmd == LC_DYLD_CHAINED_FIXUPS:
            m["chained"] = struct.unpack_from("<II", data, i + 8)
        elif cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
            m["dyld_info"] = struct.unpack_from("<10I", data, i + 8)
        elif cmd == LC_DYLD_EXPORTS_TRIE:
            m["exports_lc"] = struct.unpack_from("<II", data, i + 8)
        elif cmd == LC_FUNCTION_STARTS:
            m["fstarts_lc"] = struct.unpack_from("<II", data, i + 8)
        elif cmd == LC_ROUTINES_64:
            m["routines"] = struct.unpack_from("<Q", data, i + 8)[0]   # -init function, unslid vmaddr
        i += sz
    m["segs"] = [s for s in m["segs"] if s[0] != "__PAGEZERO"]
    m["vm_base"] = next(s[1] for s in m["segs"] if s[0] == "__TEXT")
    m["vm_size"] = max(s[1] + s[2] for s in m["segs"]) - m["vm_base"]
    return m

def section_symbols(m: dict) -> dict[str, int]:
    """LC_SYMTAB section symbols (local ones too) -> vmaddr; for intrinsics that the export trie does not list."""
    if not m["symtab"]: return {}
    symoff, nsyms, stroff, _strsize = m["symtab"]
    out = {}
    for k in range(nsyms):
        strx, ntype, _sect, _desc, value = struct.unpack_from("<IBBHQ", m["data"], symoff + 16 * k)
        if ntype & N_TYPE == N_SECT and not ntype & N_STAB: out.setdefault(cstr(m["data"], stroff + strx), value)
    return out

def all_segments(data: bytes) -> list:
    """Every LC_SEGMENT_64 incl. __PAGEZERO, in load order (segment indexes used by fixup encodings)."""
    ncmds = struct.unpack_from("<I", data, 16)[0]
    i, out = 32, []
    for _ in range(ncmds):
        cmd, sz = struct.unpack_from("<II", data, i)
        if cmd == LC_SEGMENT_64: out.append(struct.unpack_from("<4Q", data, i + 24))
        i += sz
    return out

def function_starts(m: dict) -> list[int]:
    off, size = m["fstarts_lc"]
    b, a, j, out = m["data"][off:off + size], m["vm_base"], 0, []
    while j < len(b):
        d, j = macho.uleb(b, j)
        if d == 0: break
        a += d; out.append(a)
    return out

def chained_fixups(m: dict) -> tuple[list, list]:
    """LC_DYLD_CHAINED_FIXUPS -> ([(vmaddr, target_vmaddr)], [(vmaddr, ordinal, name, weak, addend)]), import formats 1-3."""
    data, (off, size) = m["data"], m["chained"]
    cf = data[off:off + size]
    _, starts_off, imports_off, syms_off, count, fmt, _ = struct.unpack_from("<7I", cf, 0)
    imports = []
    for k in range(count):
        if fmt == 1:
            v = struct.unpack_from("<I", cf, imports_off + 4 * k)[0]; ordv, weak, name_off, add = v & 0xFF, (v >> 8) & 1, v >> 9, 0
            ordv = ordv - 0x100 if ordv > 0xF0 else ordv
        elif fmt == 2:
            v, add = struct.unpack_from("<Ii", cf, imports_off + 8 * k); ordv, weak, name_off = v & 0xFF, (v >> 8) & 1, v >> 9
            ordv = ordv - 0x100 if ordv > 0xF0 else ordv
        elif fmt == 3:
            v, name_off, add = struct.unpack_from("<IIq", cf, imports_off + 16 * k); ordv, weak = v & 0xFFFF, (v >> 16) & 1
            ordv = ordv - 0x10000 if ordv > 0xFFF0 else ordv
        else:
            raise NotImplementedError("chained import format %d" % fmt)
        imports.append((ordv, cstr(cf, syms_off + name_off), weak, add))
    segs = all_segments(data)
    rebases, binds = [], []
    for si in range(struct.unpack_from("<I", cf, starts_off)[0]):
        so = struct.unpack_from("<I", cf, starts_off + 4 + 4 * si)[0]
        if so == 0: continue
        p = starts_off + so
        _, page_size, pfmt = struct.unpack_from("<IHH", cf, p)
        page_count = struct.unpack_from("<H", cf, p + 20)[0]
        if pfmt not in (CHAINED_PTR_64, CHAINED_PTR_64_OFFSET):
            raise NotImplementedError("chained pointer format %d" % pfmt)
        vmaddr, _, fileoff, _ = segs[si]
        for pi, ps in enumerate(struct.unpack_from("<%dH" % page_count, cf, p + 22)):
            if ps == macho.PAGE_NO_FIXUPS: continue
            o = pi * page_size + ps
            while True:
                v = struct.unpack_from("<Q", data, fileoff + o)[0]
                if v >> 63:
                    ordv, name, weak, add = imports[v & 0xFFFFFF]
                    binds.append((vmaddr + o, ordv, name, weak, add + ((v >> 24) & 0xFF)))
                else:
                    high8 = (v >> 36) & 0xFF                                   # top byte, e.g. the non-unique RTTI name bit
                    rebases.append((vmaddr + o, (v & 0xFFFFFFFFF) + (m["vm_base"] if pfmt == CHAINED_PTR_64_OFFSET else 0) + (high8 << 56)))
                nxt = (v >> 51) & 0xFFF
                if nxt == 0: break
                o += nxt * 4
    return rebases, binds

def sleb(b: bytes, i: int) -> tuple[int, int]:
    r = s = 0
    while True:
        c = b[i]; i += 1; r |= (c & 0x7F) << s; s += 7
        if c < 0x80: return (r - (1 << s) if c & 0x40 else r), i

def seg_word(data: bytes, segs: list, a: int) -> int:
    """The 8 file bytes backing vmaddr a."""
    seg = next(s for s in segs if s[0] <= a < s[0] + s[1])
    return struct.unpack_from("<Q", data, seg[2] + a - seg[0])[0]

def classic_rebases(m: dict, segs: list) -> list:
    """LC_DYLD_INFO rebase opcodes -> [(vmaddr, target_vmaddr)] (target = unslid pointer stored in the file)."""
    data = m["data"]; off, size = m["dyld_info"][0:2]
    b, i, out, addr = data[off:off + size], 0, [], 0
    while i < len(b):
        op, imm = b[i] & 0xF0, b[i] & 0x0F; i += 1
        if op == 0x00: break
        elif op == 0x10: pass
        elif op == 0x20: v, i = macho.uleb(b, i); addr = segs[imm][0] + v
        elif op == 0x30: v, i = macho.uleb(b, i); addr = (addr + v) & MASK64
        elif op == 0x40: addr += imm * 8
        elif op in (0x50, 0x60):
            n = imm
            if op == 0x60: n, i = macho.uleb(b, i)
            for _ in range(n): out.append((addr, seg_word(data, segs, addr))); addr += 8
        elif op == 0x70: v, i = macho.uleb(b, i); out.append((addr, seg_word(data, segs, addr))); addr = (addr + 8 + v) & MASK64
        elif op == 0x80:
            n, i = macho.uleb(b, i); skip, i = macho.uleb(b, i)
            for _ in range(n): out.append((addr, seg_word(data, segs, addr))); addr += 8 + skip
        else: raise NotImplementedError("rebase opcode 0x%x" % op)
    return out

def classic_binds(stream: bytes, segs: list, lazy: bool, ordv0: int = 0) -> list:
    """Bind opcodes -> [(vmaddr, ordinal, name, weak, addend)]; a lazy stream keeps going past BIND_OPCODE_DONE; the weak stream (ordv0 = BIND_WEAK) carries no ordinals and names without a bind are strong-definition markers."""
    i, out, addr, ordv, name, weak, add = 0, [], 0, ordv0, "", 0, 0
    while i < len(stream):
        op, imm = stream[i] & 0xF0, stream[i] & 0x0F; i += 1
        if op == 0x00:
            if not lazy: break
        elif op == 0x10: ordv = imm
        elif op == 0x20: ordv, i = macho.uleb(stream, i)
        elif op == 0x30: ordv = imm - 16 if imm else 0
        elif op == 0x40: weak = imm & 1; name = cstr(stream, i); i += len(name.encode()) + 1
        elif op == 0x50: pass
        elif op == 0x60: add, i = sleb(stream, i)
        elif op == 0x70: v, i = macho.uleb(stream, i); addr = segs[imm][0] + v
        elif op == 0x80: v, i = macho.uleb(stream, i); addr = (addr + v) & MASK64      # uleb deltas wrap: negative steps
        elif op == 0x90: out.append((addr, ordv, name, weak, add)); addr += 8
        elif op == 0xA0: v, i = macho.uleb(stream, i); out.append((addr, ordv, name, weak, add)); addr = (addr + 8 + v) & MASK64
        elif op == 0xB0: out.append((addr, ordv, name, weak, add)); addr += 8 + imm * 8
        elif op == 0xC0:
            n, i = macho.uleb(stream, i); skip, i = macho.uleb(stream, i)
            for _ in range(n): out.append((addr, ordv, name, weak, add)); addr += 8 + skip
        else: raise NotImplementedError("bind opcode 0x%x" % op)
    return out

def fixups(m: dict) -> tuple[list, list]:
    if m["chained"]: return chained_fixups(m)
    if not m["dyld_info"]: return [], []
    segs, data, d = all_segments(m["data"]), m["data"], m["dyld_info"]
    binds = (classic_binds(data[d[2]:d[2] + d[3]], segs, False) + classic_binds(data[d[6]:d[6] + d[7]], segs, True)
             + classic_binds(data[d[4]:d[4] + d[5]], segs, False, BIND_WEAK))   # weak binds apply last, as in dyld
    return classic_rebases(m, segs), binds

def export_trie(m: dict) -> dict:
    """name -> (kind, value, reexport_name, weak_def) from LC_DYLD_EXPORTS_TRIE or LC_DYLD_INFO's export trie."""
    off, size = m["exports_lc"] or ((m["dyld_info"][8], m["dyld_info"][9]) if m["dyld_info"] else (0, 0))
    b, out, stack = m["data"][off:off + size], {}, [(0, "")]
    while stack and size:
        node, prefix = stack.pop()
        term, j = macho.uleb(b, node)
        if term:
            flags, k = macho.uleb(b, j)
            if flags & EXPORT_REEXPORT:
                ordv, k = macho.uleb(b, k); out[prefix] = ("reexport", ordv, cstr(b, k) or prefix, False)
            elif flags & EXPORT_RESOLVER:
                v, k = macho.uleb(b, k); out[prefix] = ("resolver", v, "", False)
            else:
                v, k = macho.uleb(b, k)
                out[prefix] = ("absolute" if flags & EXPORT_KIND_MASK == EXPORT_ABSOLUTE else "regular", v, "", bool(flags & EXPORT_WEAK))
        j += term
        n, j = b[j], j + 1
        for _ in range(n):
            edge = cstr(b, j); j += len(edge.encode()) + 1
            child, j = macho.uleb(b, j)
            stack.append((child, prefix + edge))
    return out

###############
# load graph and symbol resolution
###############
def expand(path: str, loader: dict, exe: dict) -> str:
    return path.replace("@executable_path", os.path.dirname(exe["path"])).replace("@loader_path", os.path.dirname(loader["path"]))

def locate(name: str, images: list, chain: list[int]) -> str | None:
    """Guest file for a dylib load name requested by images[chain[-1]]; @rpath walks the LC_RPATHs of the load chain innermost first, each expanded against the image that declares it (dyld's rpath stack)."""
    if name.startswith(SYSTEM_PREFIXES): return None
    exe, loader = images[0], images[chain[-1]]
    if name.startswith("@rpath/"):
        cands = [os.path.join(expand(rp, images[j], exe), name[len("@rpath/"):]) for j in reversed(chain) for rp in images[j]["rpaths"]]
    else:
        cands = [expand(name, loader, exe)]
    return next((os.path.realpath(c) for c in cands if os.path.isfile(c)), None)

def host_slice(path: str) -> bool:
    """True for a file with an x86_64 slice (universal or thin): a host image, bound and run natively, never translated."""
    with open(path, "rb") as f: head = f.read(4096)
    if struct.unpack_from("<II", head, 0) == (MH_MAGIC_64, CPU_X86_64): return True
    magic, n = struct.unpack_from(">II", head, 0)
    step = {FAT_MAGIC: 20, FAT_MAGIC_64: 32}.get(magic)
    return bool(step) and any(struct.unpack_from(">I", head, 8 + step * i)[0] == CPU_X86_64 for i in range(min(n, 64)))

def load_images(exe_path: str, host_names: frozenset = frozenset()) -> list[dict]:
    """Main executable then guest dylibs in dyld's load order (each image's direct deps, then a depth-first walk); deps resolved to ('guest', i) / ('host', name) / ('missing', name). host_names are install names served by the host; a dependency found on disk with an x86_64 slice is a host image too (images[0]['host_files']: install name -> path)."""
    images = [parse_image(exe_path)]
    images[0]["host_files"] = {}
    by_path, done, stack = {images[0]["path"]: 0}, set(), [(0, [0])]
    while stack:
        i, chain = stack.pop()
        if i in done: continue
        done.add(i)
        img, resolved = images[i], []
        if any(d[0] == LIBOBJC for d in img["deps"]) and not any(d[0] in RUNTIME for d in img["deps"]):
            img["deps"] = img["deps"] + [(LIBCXXABI, "load")]           # appended: existing library ordinals keep their index
        for name, kind in img["deps"]:
            rt = os.path.realpath(os.path.join(GUESTRT, RUNTIME[name])) if name in RUNTIME else None
            if rt is None and (name.startswith(SYSTEM_PREFIXES) or name in host_names):
                resolved.append(("host", name)); continue
            f = rt or locate(name, images, chain)
            if f is None:
                if kind != "weak": raise FileNotFoundError("%s: required dylib %s not found" % (img["path"], name))
                resolved.append(("missing", name)); continue
            if rt is None and host_slice(f):
                images[0]["host_files"].setdefault(name, f); resolved.append(("host", name)); continue
            if f not in by_path:
                by_path[f] = len(images); images.append(parse_image(f))
            resolved.append(("guest", by_path[f]))
        img["resolved"] = resolved
        stack += [(d[1], chain + [d[1]]) for d in reversed(resolved) if d[0] == "guest" and d[1] not in done]
    base, rt_dir = GUEST_BASE, os.path.realpath(GUESTRT)
    for img in images:
        img["runtime"] = os.path.dirname(img["path"]) == rt_dir and img["id"] in RUNTIME_LOAD
        img["load"] = RUNTIME_LOAD[img["id"]] if img["runtime"] else base
        img["slide"] = (img["load"] - img["vm_base"]) & (2 ** 64 - 1)
        img["exports"] = export_trie(img)
        img["rebases"], img["binds"] = fixups(img)
        img["fstarts"] = sorted(set(function_starts(img) if img["fstarts_lc"] else []) | set(objc_stub_starts(img)))
        if not img["runtime"]: base = (base + img["vm_size"] + IMAGE_ALIGN - 1) // IMAGE_ALIGN * IMAGE_ALIGN + IMAGE_ALIGN
    if base > min(RUNTIME_LOAD.values()): raise MemoryError("guest images reach the fixed runtime bases at 0x%x" % base)
    return images

def find_export(images: list, j: int, name: str, shallow: bool = False, depth: int = 0) -> tuple | None:
    """('guest', abs, weak_def) | ('host', (install name, name), False) for `name` exported by guest image j; the host install name is '' when no single library is named (flat, weak). Explicit re-export entries are followed; whole re-exported dylibs only in a deep (two-level) lookup, never in a shallow (flat/weak) one."""
    if depth > 16: raise RecursionError("re-export cycle for %s" % name)
    img = images[j]
    e = img["exports"].get(name)
    if e:
        kind, val, other, weak = e
        if kind == "reexport": return lookup_dep(images, img["resolved"][val - 1], other, shallow and other == name, depth + 1)
        if kind == "resolver": raise NotImplementedError("stub-and-resolver export %s" % name)
        return ("guest", val if kind == "absolute" else img["load"] + val, weak)
    if shallow: return None
    for dep, (_, kind) in zip(img["resolved"], img["deps"]):
        if kind == "reexport":
            r = lookup_dep(images, dep, name, False, depth + 1)
            if r: return r
    return None

def lookup_dep(images: list, dep: tuple, name: str, shallow: bool, depth: int) -> tuple | None:
    """A libSystem bind that the loaded guest libunwind exports goes to it (Apple's libSystem re-exports libunwind)."""
    if dep[0] == "guest": return find_export(images, dep[1], name, shallow, depth)
    if dep[0] == "host" and dep[1] == LIBSYSTEM:
        u = next((j for j, img in enumerate(images) if img["runtime"] and img["id"] == LIBUNWIND), None)
        r = find_export(images, u, name, True) if u is not None else None
        if r: return r
    if dep[0] == "host": return ("host", (dep[1], name), False)        # two-level: the library stays with the name
    return None

def weak_lookup(images: list, name: str) -> tuple:
    """Ordinal -3 (weak-def coalescing): over guest images with MH_WEAK_DEFINES in load order, the first definition, replaced by the first non-weak one if that comes later (dyld Loader::resolveSymbol). Host definitions live in a different ABI realm and never coalesce with guest ones; a symbol no guest defines resolves to the host."""
    found = [r for j, img in enumerate(images) if img["flags"] & MH_WEAK_DEFINES for r in [find_export(images, j, name, True)] if r]
    return next((r for r in found if not r[2]), found[0]) if found else ("host", ("", name), False)

def resolve_bind(images: list, i: int, ordv: int, name: str) -> tuple | None:
    """Two-level (ordinal > 0), self (0), main executable (-1), flat (-2: shallow, load order, host last), weak (-3)."""
    if ordv > 0: return lookup_dep(images, images[i]["resolved"][ordv - 1], name, False, 0)
    if ordv == 0: return find_export(images, i, name)
    if ordv == -1: return find_export(images, 0, name)
    if ordv == BIND_FLAT:
        return next((r for j in range(len(images)) for r in [find_export(images, j, name, True)] if r), ("host", ("", name), False))
    if ordv == BIND_WEAK: return weak_lookup(images, name)
    raise ValueError("%s: unknown library ordinal %d binding %s" % (images[i]["path"], ordv, name))

def ikey(r: tuple) -> tuple:
    """Interposing key of a resolution: a guest address, or a host symbol by name (a flat-namespace interposer names no library, and its replacee is the one every two-level bind of that name reaches)."""
    return r[:2] if r[0] == "guest" else ("host", r[1][1])

def sections_of(img: dict, stype: int) -> list:
    return [s for s in img["sects"] if s[5] & 0xFF == stype]

def interposes(images: list) -> tuple[dict, dict]:
    """dyld's interposing tables from the __interpose sections of dylibs, in load order: generic {replacee: replacement} for every image, specific {(interposer, replacee): next} so each interposer calls through to the previous one and the first to the original. Keys are resolutions without the weak flag."""
    generic, specific = {}, {}
    for j, img in enumerate(images):
        if img["filetype"] != MH_DYLIB: continue
        rb = dict(img["rebases"]); bd = {a: (o, n) for a, o, n, _w, _ad in img["binds"]}
        tuples = [s for s in img["sects"] if s[5] & 0xFF == S_INTERPOSING or (s[1] == "__interpose" and s[0].startswith("__DATA"))]
        for _seg, _sec, addr, size, _off, _fl, _r2 in tuples:                    # dyld also matches by name
            for t in range(addr, addr + size, 16):
                orig = resolve_bind(images, j, *bd[t + 8]) if t in rb and t + 8 in bd else None
                if orig is None: continue
                prev = generic.get(ikey(orig))
                generic[ikey(orig)] = ("guest", rb[t] - img["vm_base"] + img["load"], False)
                specific[(j, ikey(orig))] = prev or orig
    return generic, specific

def link(images: list) -> tuple[list, list, list]:
    """Flat images with rebases + guest binds applied; host binds [(abs, name, addend, weak)]; resolution report lines. The last bind to an address wins (weak binds come last), as when dyld applies them in order. Each image gets img["gbinds"]: bind vmaddr -> the absolute guest address it holds (abi_plan)."""
    flats, host_binds, report = [], [], []
    generic, specific = interposes(images)
    for i, img in enumerate(images):
        flat = bytearray(img["vm_size"])
        for _n, vmaddr, _vs, fileoff, filesize in img["segs"]:
            flat[vmaddr - img["vm_base"]:vmaddr - img["vm_base"] + filesize] = img["data"][fileoff:fileoff + filesize]
        for a, tgt in img["rebases"]:
            struct.pack_into("<Q", flat, a - img["vm_base"], (tgt + img["slide"]) & (2 ** 64 - 1))
        final = {}
        for a, ordv, name, weak, add in img["binds"]:
            r = resolve_bind(images, i, ordv, name)
            r = r and specific.get((i, ikey(r)), generic.get(ikey(r), r))
            if r is None and not weak:
                raise LookupError("%s: symbol %s (ordinal %d) not found" % (os.path.basename(img["path"]), name, ordv))
            final[a] = (r, name, add, weak)
        img["gbinds"] = {a: r[1] + add for a, (r, _n, add, _w) in final.items() if r is not None and r[0] == "guest"}
        for a, (r, name, add, weak) in final.items():
            if r is None: struct.pack_into("<Q", flat, a - img["vm_base"], 0)
            elif r[0] == "guest": struct.pack_into("<Q", flat, a - img["vm_base"], (r[1] + add) & (2 ** 64 - 1))
            else: host_binds.append((a - img["vm_base"] + img["load"], r[1], add, weak))
        flats.append(bytes(flat))
        report.append("%s @0x%x: %d rebases, %d binds (%d host), %d exports, deps %s" % (
            os.path.basename(img["path"]), img["load"], len(img["rebases"]), len(img["binds"]),
            sum(1 for b in host_binds if img["load"] <= b[0] < img["load"] + img["vm_size"]), len(img["exports"]),
            [d[0] + ":" + (os.path.basename(images[d[1]]["path"]) if d[0] == "guest" else os.path.basename(d[1])) for d in img["resolved"]]))
    report += ["interpose: %s replaces %s for every image but its interposers" % (rep, orig) for orig, rep in generic.items()]
    return flats, host_binds, report

def bottom_up(images: list, root: int, seen: frozenset) -> tuple[list, list, frozenset]:
    """dyld runInitializersBottomUp from root: (images in initializer order, upward-linked danglers, visited)."""
    if root in seen: return [], [], seen
    visited, order, dangling, stack = set(seen) | {root}, [], [], [(root, 0)]
    while stack:
        i, k = stack.pop()
        deps = [(d, kind) for d, (_n, kind) in zip(images[i]["resolved"], images[i]["deps"]) if d[0] == "guest"]
        if k == len(deps): order.append(i); continue
        stack.append((i, k + 1))
        (_g, child), kind = deps[k]
        if kind == "upward": dangling += [] if child in dangling else [child]
        elif child not in visited: visited.add(child); stack.append((child, 0))
    return order, dangling, frozenset(visited)

def init_order(images: list) -> list[int]:
    """Initializer order of dyld's runInitializersBottomUpPlusUpwardLinks: dependencies before dependents, upward links skipped, then the dangling upward-linked images (and their danglers once more)."""
    order, dangling, seen = bottom_up(images, 0, frozenset())
    extra = []
    for d in dangling:
        o, x, seen = bottom_up(images, d, seen); order += o; extra += [e for e in x if e not in extra]
    for d in extra:
        o, _x, seen = bottom_up(images, d, seen); order += o
    return order

def initializers(img: dict, flat: bytes) -> list[int]:
    """LC_ROUTINES_64 (-init) first, then __mod_init_func pointers and __init_offsets, in section order."""
    out = [img["load"] + img["routines"] - img["vm_base"]] if img["routines"] is not None else []
    for _seg, _sec, addr, size, _off, flags, _r2 in img["sects"]:
        o = addr - img["vm_base"]
        if flags & 0xFF == S_MOD_INIT_FUNC_POINTERS:
            out += [struct.unpack_from("<Q", flat, o + 8 * k)[0] for k in range(size // 8)]
        elif flags & 0xFF == S_INIT_FUNC_OFFSETS:
            out += [img["load"] + struct.unpack_from("<I", flat, o + 4 * k)[0] for k in range(size // 4)]
    return out

def tlv_info(img: dict) -> tuple | None:
    """(template abs, initialised bytes, total bytes, [descriptor abs], alignment) or None; every thread's block is allocated at the template's alignment (the largest of its sections', at least 16)."""
    regs = sections_of(img, S_THREAD_LOCAL_REGULAR); zf = sections_of(img, S_THREAD_LOCAL_ZEROFILL)
    descs = [img["load"] + a - img["vm_base"] + 24 * k for _g, _s, a, size, _o, _f, _r in sections_of(img, S_THREAD_LOCAL_VARIABLES)
             for k in range(size // 24)]
    if not descs: return None
    tsects = regs + zf
    start = min(s[2] for s in tsects) if tsects else 0
    init = (max(s[2] + s[3] for s in regs) - start) if regs else 0
    total = (max(s[2] + s[3] for s in tsects) - start) if tsects else 0
    align = max([16] + [img["sect_align"][s[:2]] for s in tsects])
    return (img["load"] + start - img["vm_base"], init, total, descs, align)

def stub_gots(img: dict) -> dict[int, int]:
    """__stubs entry vmaddr -> GOT/lazy-pointer vmaddr, decoded from each adrp/ldr/br stub."""
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM); md.detail = True
    out = {}
    for _seg, _sec, addr, size, off, _fl, r2 in sections_of(img, S_SYMBOL_STUBS):
        step = r2 or macho.STUB_SIZE
        for a in range(addr, addr + size, step):
            ins = list(md.disasm(img["data"][off + a - addr:off + a - addr + step], a))
            if [x.mnemonic for x in ins[:3]] != ["adrp", "ldr", "br"]:
                raise NotImplementedError("stub shape at 0x%x: %s" % (a, [x.mnemonic for x in ins]))
            out[a] = ins[0].operands[1].imm + ins[1].operands[1].mem.disp
    return out

###############
# exception tables: LSDAs from __unwind_info and __eh_frame, landing pads from their call-site tables
###############
def section(img: dict, seg: str, name: str) -> tuple | None:
    """(vmaddr, size, fileoff) of one section or None."""
    return next(((s[2], s[3], s[4]) for s in img["sects"] if s[0] == seg and s[1] == name), None)

def objc_stub_starts(img: dict) -> list[int]:
    """Entry of every __objc_stubs selector stub (each starts with adrp x1; LC_FUNCTION_STARTS does not list them)."""
    s = section(img, "__TEXT", "__objc_stubs")
    if not s: return []
    addr, size, off = s
    words = struct.unpack_from("<%dI" % (size // 4), img["data"], off)
    return [addr + 4 * i for i, w in enumerate(words) if w & 0x9F00001F == 0x90000001]

def objc_info(images: list) -> list:
    """Per image, (absolute address, entry count) of each OBJC_SECTS pointer-list section, (0, 0) when absent."""
    return [[next(((img["load"] + s[2] - img["vm_base"], s[3] // 8) for s in img["sects"] if s[1] == n and s[0].startswith("__DATA")), (0, 0))
             for n in OBJC_SECTS] for img in images]

def read_enc(b: bytes, i: int, enc: int, here: int) -> tuple[int, int]:
    """One DW_EH_PE-encoded value at b[i] whose vmaddr is `here` -> (value, next index). Indirect values are left as the address of the pointer (only personality pointers use it; they are skipped)."""
    fmt, app = enc & 0x0F, enc & 0x70
    if fmt == 0x1: v, j = macho.uleb(b, i)
    elif fmt == 0x9: v, j = sleb(b, i)
    else:
        f = {0x0: "<Q", 0x2: "<H", 0x3: "<I", 0x4: "<Q", 0xA: "<h", 0xB: "<i", 0xC: "<q"}.get(fmt)
        if f is None: raise NotImplementedError("DW_EH_PE format 0x%x" % fmt)
        v, j = struct.unpack_from(f, b, i)[0], i + struct.calcsize(f)
    if app == 0x10: v += here
    elif app: raise NotImplementedError("DW_EH_PE application 0x%x" % app)
    return v & MASK64, j

def eh_frame_lsdas(img: dict) -> dict[int, int]:
    """FDE pc_begin -> LSDA vmaddr for FDEs whose CIE has an 'L' augmentation."""
    s = section(img, "__TEXT", "__eh_frame")
    if not s: return {}
    addr, size, off = s
    b, i, cies, out = img["data"][off:off + size], 0, {}, {}
    while i + 4 <= size:
        ln = struct.unpack_from("<I", b, i)[0]
        if ln == 0: break
        if ln == 0xFFFFFFFF: raise NotImplementedError("64-bit DWARF eh_frame record")
        start, end = i + 4, i + 4 + ln
        cid = struct.unpack_from("<I", b, start)[0]
        if cid == 0:
            j = start + 5; aug = cstr(b, j); j += len(aug) + 1
            _, j = macho.uleb(b, j); _, j = sleb(b, j)
            j = j + 1 if b[start + 4] == 1 else macho.uleb(b, j)[1]
            fde_enc, lsda_enc = 0, None
            if aug.startswith("z"):
                _, j = macho.uleb(b, j)
                for ch in aug[1:]:
                    if ch == "P": _, j = read_enc(b, j + 1, b[j] & 0x7F, addr + j + 1)
                    elif ch == "L": lsda_enc = b[j]; j += 1
                    elif ch == "R": fde_enc = b[j]; j += 1
                    elif ch != "S": break
            cies[i] = (fde_enc, lsda_enc, aug)
        else:
            fde_enc, lsda_enc, aug = cies[start - cid]
            pc, j = read_enc(b, start + 4, fde_enc, addr + start + 4)
            _, j = read_enc(b, j, fde_enc & 0x0F, addr + j)
            if aug.startswith("z") and lsda_enc is not None and lsda_enc != 0xFF:
                alen, j = macho.uleb(b, j)
                lsda = read_enc(b, j, lsda_enc, addr + j)[0] if alen else 0
                if lsda: out[pc] = lsda
        i = end
    return out

def unwind_info_lsdas(img: dict) -> dict[int, int]:
    """Compact unwind LSDA index: function vmaddr -> LSDA vmaddr."""
    s = section(img, "__TEXT", "__unwind_info")
    if not s: return {}
    b = img["data"][s[2]:s[2] + s[1]]
    _v, _ce, _cc, _po, _pc, idx_off, idx_cnt = struct.unpack_from("<7I", b, 0)
    if idx_cnt < 2: return {}
    first = struct.unpack_from("<I", b, idx_off + 8)[0]
    last = struct.unpack_from("<I", b, idx_off + 12 * (idx_cnt - 1) + 8)[0]
    pairs = (struct.unpack_from("<II", b, o) for o in range(first, last, 8))
    return {img["vm_base"] + f: img["vm_base"] + l for f, l in pairs}

def vm_bytes(img: dict, a: int) -> tuple[bytes, int]:
    """(file bytes, index) backing vmaddr a."""
    seg = next(s for s in img["segs"] if s[1] <= a < s[1] + s[4])
    return img["data"], seg[3] + a - seg[1]

def landing_pads(img: dict, lsda: int, fstart: int) -> list[int]:
    """Non-zero landing pads of one LSDA's call-site table (lpStart defaults to the function start)."""
    b, i = vm_bytes(img, lsda)
    i0 = i
    lp_enc = b[i]; i += 1
    lp_start = fstart
    if lp_enc != 0xFF: lp_start, i = read_enc(b, i, lp_enc, lsda + i - i0)
    tt_enc = b[i]; i += 1
    if tt_enc != 0xFF: _, i = macho.uleb(b, i)
    cs_enc = b[i]; i += 1
    cs_len, i = macho.uleb(b, i)
    end, pads = i + cs_len, set()
    while i < end:
        _, i = read_enc(b, i, cs_enc, lsda + i - i0)
        _, i = read_enc(b, i, cs_enc, lsda + i - i0)
        lp, i = read_enc(b, i, cs_enc, lsda + i - i0)
        _, i = macho.uleb(b, i)
        if lp: pads.add(lp_start + lp)
    return sorted(pads)

def code_sections(img: dict) -> list[tuple[int, int, int]]:
    """(vmaddr, size, fileoff) of every instruction section but the stubs (__text, __lcxx_override, ...)."""
    return [(s[2], s[3], s[4]) for s in img["sects"] if s[5] & S_ATTR_INSTRUCTIONS and s[5] & 0xFF != S_SYMBOL_STUBS and s[3]]

def function_bounds(img: dict) -> list[tuple[int, int]]:
    """(start, end) of every LC_FUNCTION_STARTS function, each ending at the next start or at its section's end."""
    out = []
    for addr, size, _off in code_sections(img):
        starts = sorted(a for a in img["fstarts"] if addr <= a < addr + size)
        out += list(zip(starts, starts[1:] + [addr + size]))
    return sorted(out)

def eh_resume_points(img: dict, bounds: list[tuple[int, int]]) -> dict[int, list[int]]:
    """Lifted function start -> landing pads of every LSDA whose function lies in it (pads must stay inside)."""
    out, starts = {}, [b[0] for b in bounds]
    for fn, lsda in sorted({**eh_frame_lsdas(img), **unwind_info_lsdas(img)}.items()):
        k = bisect.bisect_right(starts, fn) - 1
        if k < 0 or fn >= bounds[k][1]: raise LookupError("%s: LSDA for 0x%x outside every function" % (os.path.basename(img["path"]), fn))
        lo, hi = bounds[k]
        pads = landing_pads(img, lsda, fn)
        if any(not lo <= p < hi for p in pads):
            raise LookupError("%s: landing pad of 0x%x outside its function [0x%x,0x%x): %s" % (
                os.path.basename(img["path"]), fn, lo, hi, [hex(p) for p in pads]))
        out[lo] = sorted(set(out.get(lo, [])) | set(pads))
    return out

###############
# C / C++ emission
###############
def read_vm(img: dict, a: int, n: int) -> bytes | None:
    """n file bytes at vmaddr a in a segment the program cannot write (initprot without write), else None: the lifter's jump-table reader, whose decoded targets are taken as complete (a writable table may be rewritten before the br)."""
    s = next((s for s in img["segs"] if s[1] <= a and a + n <= s[1] + s[4] and s[0] in img["ro_segs"]), None)
    return None if s is None else img["data"][s[3] + a - s[1]:s[3] + a - s[1] + n]

def pointer_refs(img: dict) -> list[tuple[int, int]]:
    """Sorted [lo, hi) ranges a code pointer may hold: every data rebase target, adr target and adrp page use (recompile.code_refs)."""
    data = img["data"]
    return sorted({(t, t + 1) for _a, t in img["rebases"]} | {r for a, n, o in code_sections(img) for r in R.code_refs(a, data[o:o + n])})

def address_taken(img: dict, refs: list, addrs: set) -> set:
    """The addresses among addrs that a pointer_refs range covers or an export names (callable from elsewhere than a direct branch)."""
    exported = {img["vm_base"] + e[1] for e in img["exports"].values() if e[0] == "regular"}
    taken = set()
    for a in addrs:
        k = bisect.bisect_right(refs, (a, MASK64))
        while k > 0 and refs[k - 1][0] > a - 0x1000:                   # ranges are at most one 4 KB page long
            k -= 1
            if refs[k][0] <= a < refs[k][1]: taken.add(a); break
    return taken | (addrs & exported)

def interior_pointers(img: dict, fset: set | None = None, refs: list | None = None) -> list:
    """Sorted witnesses for decoded_lift's `inside`: one address in (start, end) of every function that some pointer_refs range may point into, other than at its start (a range at a start is not inside); refs: pointer_refs(img) when the caller has it (fset is unused, kept for census_m3a)."""
    refs = pointer_refs(img) if refs is None else refs
    bounds = function_bounds(img)
    starts = [b[0] for b in bounds]
    out = set()
    for lo, hi in refs:
        for k in range(max(0, bisect.bisect_right(starts, lo) - 1), bisect.bisect_left(starts, hi)):
            w = max(lo, starts[k] + 1)                                 # the range's first address past this function's start
            if w < min(hi, bounds[k][1]): out.add(w)
    return sorted(out)

def decoded_lift(read: object, ptrs: list, gots: dict, insns: list, fstarts: set, cname: str, resume: list | None = None,
                 msg: dict | None = None, abi: bool = False, noret: frozenset = frozenset()) -> tuple:
    """R.lift_function with the jump-table reader, the per-function proof that no code pointer lands in its interior, and inline-cached indirect and import-stub calls (gots: stub vmaddr -> GOT vmaddr; msg: GOT vmaddr -> objc_msgSend family member, msg_gots; abi: not abi_ok; noret: noreturn_starts)."""
    k = bisect.bisect_right(ptrs, insns[0].address)
    inside = k < len(ptrs) and ptrs[k] < insns[-1].address + insns[-1].size
    return R.lift_function_x(insns, fstarts, cname, resume, read, inside, stubs=gots, ic=True, msg=msg, abi=abi, noret=noret)

def abi_ok(img: dict) -> str:
    """Why the image's code may not run under the AAPCS64 register contract (recompile localize abi), before its lift: it links a Swift library (Swift returns errors in x21 and passes self and async contexts in x20 and x22, registers C keeps across calls) or GDYLD_ABI=0; else ''."""
    if os.environ.get("GDYLD_ABI") == "0": return "GDYLD_ABI=0"
    return "links Swift" if any("/libswift" in name for name, _kind in img["deps"]) else ""

def noreturn_starts(img: dict) -> frozenset:
    """Function starts whose words hold no way back to a caller: no ret or br (any key) and no b, b.cond, cbz/cbnz or tbz/tbnz out of the function; a word of data that decodes as one only makes the function count as returning. The word after a bl to one is another path's code (recompile abi_check)."""
    out = []
    for addr, size, off in code_sections(img):
        starts = sorted(a for a in img["fstarts"] if addr <= a < addr + size)
        for lo, hi in zip(starts, starts[1:] + [addr + size]):
            back = False
            for pc in range(lo, hi - 3, 4):
                w = int.from_bytes(img["data"][off + pc - addr:off + pc - addr + 4], "little")
                if w & 0xFE000000 == 0xD6000000 and (w >> 21) & 0xF in (0, 2): back = True; break   # br / ret (and their pointer-auth forms)
                d = (w & 0x3FFFFFF) << 2 if w & 0xFC000000 == 0x14000000 else (w >> 5 & 0x7FFFF) << 2 if w & 0xFF000010 == 0x54000000 \
                    or w & 0x7E000000 == 0x34000000 else (w >> 5 & 0x3FFF) << 2 if w & 0x7E000000 == 0x36000000 else None
                if d is None: continue
                bits = 28 if w & 0xFC000000 == 0x14000000 else 21 if w & 0x7E000000 != 0x36000000 else 16
                t = pc + (d - (1 << bits) if d >> (bits - 1) & 1 else d)
                if not lo <= t < hi: back = True; break
            if not back: out.append(lo)
    return frozenset(out)

def abi_returns(rows: list, late: set) -> set:
    """Function starts whose returns and tail calls keep every store under GD_ABI: the direct callees some caller reads past the results of (recompile abi_check), closed over direct tail calls (an indirect or stub tail call stores everything there too, and neither host code nor a function under the contract changes the registers it does not return), from the image's flag rows ([(addresses defined, flag_facts)])."""
    tails = {ads[0]: fc.get("tails", ()) for ads, fc in rows if fc}
    out, work = set(), sorted(late)
    while work:
        f = work.pop()
        if f not in out: out.add(f); work += sorted(tails.get(f, ()))
    return out

def abi_plan(images: list, lifts: list) -> list[tuple[str, set, set, set, set]]:
    """Per image (why its code keeps full register sync, else ''; GDA_X_ callees; GDA_G_ GOT slots; GDA_RET_ functions; GDA_K_ functions: those storing every register at a return or at one of their call sites, whose prologue saves recompile saved_reads would drop stay). A function breaks the AAPCS64 register contract when it reads registers no call passes (its entry's, and a callee's that may reach the call unchanged) or leaves callee-saved registers changed (its own writes before any save, and a callee's it saved nothing over), closed over the direct calls and tail calls of each image and the stub and GOT calls between images (recompile abi_check facts; a GOT bound into guest code calls that function). A GOT call passes on only what its callee leaves changed: an export that reads registers no call passes has a convention of its own (sp_chkstk's x9) or captures its caller's registers (the unwinder's unw_getcontext), which the site honours by storing everything (GDA_G_) and which its own image's callers cannot see (an export is address_taken). Calls into one store and reload every register, and its returns store every register, as do those of the direct callees some caller reads past the results of (abi_returns). An image keeps full sync when one of its own is reached through a pointer or an export (address_taken: an indirect call cannot tell), or when abi_ok says so. The GOT slots bound to FULL_SPILL host routines are GDA_G_ too."""
    at = lambda k, a: a - images[k]["vm_base"] + images[k]["load"]     # absolute guest address
    fns = {at(k, a): (k, a, f) for k, li in enumerate(lifts) for a, f in li["abi_fn"].items()}
    ins, outs = {g: f[0] for g, (_k, _a, f) in fns.items()}, {g: f[1] for g, (_k, _a, f) in fns.items()}
    calls = {g: [(at(k, r[1]), e, s) if r[0] == "d" else (images[k]["gbinds"].get(r[1]), 0, s) for r, e, s in f[2]] for g, (k, _a, f) in fns.items()}
    users = {}
    for g, cs in calls.items():
        for t, _e, _s in cs: users.setdefault(t, []).append(g)
    work = list(fns)
    while work:
        g = work.pop()
        i, o = ins[g], outs[g]
        for t, e, s in calls[g]:
            if t in ins: i |= ins[t] & e; o |= outs[t] & ~s
        if (i, o) != (ins[g], outs[g]): ins[g], outs[g] = i, o; work += users.get(g, [])
    plan = []
    for k, (img, li) in enumerate(zip(images, lifts)):
        bad = {a for g, (j, a, _f) in fns.items() if j == k and (ins[g] or outs[g])}
        say = lambda a: "0x%x %s" % (a, " and ".join(p for p in ("reads %s at entry" % R.reg_names(ins[at(k, a)]) if ins[at(k, a)] else "",
                                                               "leaves %s changed" % R.reg_names(outs[at(k, a)]) if outs[at(k, a)] else "") if p))
        taken = sorted(bad & li["abi_taken"])
        why = abi_ok(img) or ("%s, and a pointer or an export reaches it%s" % (say(taken[0]), " (%d more)" % (len(taken) - 1) if len(taken) > 1 else "")
                              if taken else "")
        xg = {s for s, t in img["gbinds"].items() if t in fns and fns[t][2][0] & R.ABI_NOT_IN or outs.get(t)} | full_gots(img)
        rets = abi_returns(li["flags"], li["abi_late"] | {a for a in bad if outs[at(k, a)]})
        keep = rets | {a for _g, (j, a, f) in fns.items() if j == k and any(r[1] in (bad if r[0] == "d" else xg) for r, _e, _s in f[2])}
        plan.append((why, bad, xg, rets, keep))
    return plan

def full_gots(img: dict) -> frozenset:
    """GOT vmaddrs bound to FULL_SPILL imports."""
    return frozenset(a for a, _o, n, _w, _ad in img["binds"] if n in FULL_SPILL)

def msg_gots(img: dict) -> dict[int, int]:
    """GOT vmaddr -> MSG_SENDS index for the image's words bound to objc_msgSend, objc_msgSendSuper or objc_msgSendSuper2."""
    return {a: MSG_SENDS[n] for a, _o, n, _w, _ad in img["binds"] if n in MSG_SENDS}

def setjmp_stubs(img: dict) -> set:
    """Stub addresses bound to setjmp-family imports (their return sites are resume points)."""
    bound = {a: n for a, _o, n, _w, _ad in img["binds"]}
    return {s for s, g in stub_gots(img).items() if bound.get(g) in SETJMP}

def resume_points(insns: list, pads: list, sj: set) -> list[int]:
    """Landing pads plus the return sites of setjmp-family calls, sorted."""
    return sorted(set(pads) | {i.address + 4 for i in insns if i.mnemonic == "bl" and i.operands[0].imm in sj})

def raw_branch_target(w: int, a: int) -> int | None:
    """Target of the direct branch word w at a (b, bl, b.cond, bc.cond, cbz/cbnz, tbz/tbnz), else None."""
    sx = lambda v, bits: v - (1 << bits) if v >> (bits - 1) & 1 else v
    if w & 0x7C000000 == 0x14000000: return a + 4 * sx(w & 0x3FFFFFF, 26)
    if w & 0xFF000000 == 0x54000000 or w & 0x7E000000 == 0x34000000: return a + 4 * sx((w >> 5) & 0x7FFFF, 19)
    if w & 0x7E000000 == 0x36000000: return a + 4 * sx((w >> 5) & 0x3FFF, 14)
    return None

def interior_candidates(img: dict, bounds: list) -> dict[int, list[tuple[int, int]]]:
    """Function start -> [(site, target)] for every word in it that decodes (raw) as a direct branch into another function's interior."""
    starts, out = [b[0] for b in bounds], {}
    for addr, size, off in code_sections(img):
        words = struct.unpack_from("<%dI" % (size // 4), img["data"], off)
        for n, w in enumerate(words):
            t = raw_branch_target(w, addr + 4 * n)
            if t is None: continue
            g, f = bisect.bisect_right(starts, addr + 4 * n) - 1, bisect.bisect_right(starts, t) - 1
            if g >= 0 and f >= 0 and f != g and t != starts[f] and t < bounds[f][1] and addr + 4 * n < bounds[g][1]:
                out.setdefault(starts[g], []).append((addr + 4 * n, t))
    return out

def interior_entries(img: dict, bounds: list, pads: dict, sj: set, ptrs: list) -> dict[int, list[int]]:
    """Function start -> sorted extra entry points: interior targets of direct branches that gdyld's lift reaches in another function (roots: entry, resume points, extra entries; grown to a fixed point)."""
    cands, starts = interior_candidates(img, bounds), [b[0] for b in bounds]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM); md.detail = True; md.skipdata = True
    read = lambda a, n: read_vm(img, a, n)
    ents, todo = {}, set(cands)
    while todo:
        g = min(todo); todo.discard(g)
        lo, hi = bounds[bisect.bisect_left(starts, g)]
        data, i = vm_bytes(img, lo)
        insns = list(md.disasm(data[i:i + hi - lo], lo))
        roots = [lo] + resume_points(insns, pads.get(lo, []), sj) + ents.get(lo, [])
        k = bisect.bisect_right(ptrs, lo)
        reached, _brs, _fb = R.reach(insns, roots, read, k < len(ptrs) and ptrs[k] < hi)
        at = {x.address: x for x in insns}
        for s, t in cands[g]:
            x = at.get(s)
            if s not in reached or x is None or not x.operands or x.operands[-1].type != R.ARM64_OP_IMM or x.operands[-1].imm != t: continue
            if not (x.mnemonic in R.BRANCH_IMM or x.mnemonic == "bl" or x.mnemonic.startswith(("b.", "bc."))): continue
            f = starts[bisect.bisect_right(starts, t) - 1]
            if t not in ents.get(f, []):
                ents[f] = sorted(ents.get(f, []) + [t])
                if f in cands: todo.add(f)                             # new roots in f may reach more of its branches
    return ents

def function_sources(img: dict, k: int, lift: object, entries: dict, cxx: bool = False) -> object:
    """Yield (addresses defined, C source, instructions, unsupported, resumable, flag facts, C++ wrapper source) per function (flag facts: R.lift_function_x's flag_facts; None, unknown, when lift does not give them). A function with resume points (landing pads, setjmp return sites) or extra entry points is a body func(c, entry) plus wrappers: func_<start> and one func_<entry> per extra entry; with resume points the wrappers are C++ (eh_wrappers: the body under try/catch, gd_eh_run_at's semantics) and the body and its resume table are external, else they are C and the body static (an extra entry's code may return past its host caller, e.g. through an epilogue of a frame an earlier call made: gd_ent_ret then sets c->unw to the real return address and every call site on the host stack returns until it matches, recompile GD_RC); an intrinsic replaces the whole function with a host call."""
    sc = source_context(img, entries)
    sections = [macho.iter_functions(a, img["data"][o:o + n], img["fstarts"]) for a, n, o in code_sections(img)]
    for start, insns in (f for fs in sections for f in fs):
        yield function_source(img, k, lift, entries, cxx, sc, start, insns)

def source_context(img: dict, entries: dict) -> dict:
    """What function_source needs of the whole image: 'fset' (function starts and extra entry points), 'sj' (setjmp stubs), 'pads' (eh_resume_points), 'intr' (intrinsic start -> host function)."""
    bounds = function_bounds(img)
    fset, sj, pads = {b[0] for b in bounds} | {e for es in entries.values() for e in es}, setjmp_stubs(img), eh_resume_points(img, bounds)
    syms = section_symbols(img) if img["id"] in INTRINSICS else {}
    intr = {}
    for name, host in INTRINSICS.get(img["id"], {}).items():
        if name not in syms: raise LookupError("%s: intrinsic symbol %s missing" % (img["path"], name))
        intr[syms[name]] = host
    return {"fset": fset, "sj": sj, "pads": pads, "intr": intr}

def function_source(img: dict, k: int, lift: object, entries: dict, cxx: bool, sc: dict, start: int, insns: list) -> tuple:
    """function_sources' tuple for the one function at start (insns: its capstone instructions; sc: source_context)."""
    fset, sj, pads, intr = sc["fset"], sc["sj"], sc["pads"], sc["intr"]
    rp, ents = resume_points(insns, pads.get(start, []), sj), entries.get(start, [])
    roots = rp + [e for e in ents if e not in rp]                      # resume points first: gd_eh_run searches only those
    if start in intr:
        if ents: raise LookupError("%s: branch into the interior of intrinsic 0x%x" % (img["path"], start))
        return [start], "void func_%x(CPU *c) { %s(c); }\n" % (start, intr[start]), len(insns), [], False, HOST_FLAGS, ""   # host code: guest NZCV untouched
    if rp and not ents:
        r = lift(insns, fset, "m%d_b_%x" % (k, start), rp)
        b, arr = "m%d_b_%x" % (k, start), "m%d_rp_%x" % (k, start)
        tab = "const uint64_t %s[] = {%s};\n" % (arr, ", ".join("0x%xULL" % ((a + img["slide"]) & MASK64) for a in rp))
        if cxx: return [start], INLINE_BODY + r[0] + "static " + tab + eh_wrappers_cxx(b, arr, len(rp), [(start, -1)]), \
            len(insns), r[1], True, r[4] if len(r) > 4 else None, ""
        return [start], r[0] + tab, len(insns), r[1], True, r[4] if len(r) > 4 else None, eh_wrappers(k, b, arr, len(rp), [(start, -1)])
    if ents:
        r = lift(insns, fset, "m%d_b_%x" % (k, start), roots)
        body, uns = r[0], r[1]
        b = "m%d_b_%x" % (k, start)
        if rp:                                                         # the body and its resume table are called from the C++ wrappers
            arr = "m%d_rp_%x" % (k, start)
            tab = "const uint64_t %s[] = {%s};\n" % (arr, ", ".join("0x%xULL" % ((a + img["slide"]) & MASK64) for a in roots))
            wr = [(start, -1)] + [(e, roots.index(e)) for e in ents]
            if cxx: return [start] + ents, "static " + body + "static " + tab + eh_wrappers_cxx(b, arr, len(rp), wr), len(insns), uns, True, \
                r[4] if len(r) > 4 else None, ""
            return [start] + ents, body + tab, len(insns), uns, True, r[4] if len(r) > 4 else None, eh_wrappers(k, b, arr, len(rp), wr)
        wrap = ["void func_%x(CPU *c) { %s(c, -1); }" % (start, b)] + [
            "void func_%x(CPU *c) { uint64_t ra = c->X[30]; %s(c, %d); gd_ent_ret(c, ra); }" % (e, b, roots.index(e)) for e in ents]
        return [start] + ents, "static " + body + "\n".join(wrap) + "\n", len(insns), uns, False, r[4] if len(r) > 4 else None, ""
    r = lift(insns, fset, "func_%x" % start)
    return [start], r[0], len(insns), r[1], False, r[4] if len(r) > 4 else None, ""

def eh_wrappers(k: int, body: str, arr: str, nrp: int, entries: list[tuple[int, int]]) -> str:
    """C++ (an image<k>_<j>_eh.cpp unit) defining func_<entry> for a function with resume points: gd_eh_drive calls the C body directly under try/catch (gbridge gd_eh_run_at's semantics, without its indirect call); entry index -1 is the function start, an extra entry also does gd_ent_ret."""
    out = ['extern "C" void %s(CPU*, int); extern "C" const uint64_t %s[];' % (body, arr)]
    for a, e in entries:
        call = "gd_eh_drive<%s>(c, %s, %d, %d);" % (body, arr, nrp, e)
        out.append('extern "C" void m%d_%x(CPU* c) { %s }' % (k, a, call) if e < 0 else
                   'extern "C" void m%d_%x(CPU* c) { uint64_t ra = c->X[30]; %s if (!c->unw && c->X[30] != ra) c->unw = c->X[30]; }' % (k, a, call))
    return "\n".join(out) + "\n"

def eh_wrappers_cxx(body: str, arr: str, nrp: int, entries: list[tuple[int, int]]) -> str:
    """eh_wrappers for a C++ chunk: func_<entry> defined beside its static body and resume table (gd_eh_drive from chunk_text's C++ head), so clang can merge the wrapper with its body and inline both into callers in the chunk."""
    return "".join("void func_%x(CPU* c) { gd_eh_drive<%s>(c, %s, %d, %d); }\n" % (a, body, arr, nrp, e) if e < 0 else
                   "void func_%x(CPU* c) { uint64_t ra = c->X[30]; gd_eh_drive<%s>(c, %s, %d, %d); if (!c->unw && c->X[30] != ra) c->unw = c->X[30]; }\n"
                   % (a, body, arr, nrp, e) for a, e in entries)

def write_chunk(out_dir: str, k: int, j: int, text: str, addrs: list) -> list[tuple[str, int, list[int]]]:
    """Write chunk j of image k (nothing for empty text; a C++ chunk, chunk_text's '#define GD_CXX', as .cc); [(path, j, addresses)] or []."""
    if not text: return []
    path = os.path.join(out_dir, "image%d_%d.%s" % (k, j, "cc" if text.startswith("#define GD_CXX") else "c"))
    with open(path, "w") as f: f.write(text)
    return [(path, j, addrs)]

def write_chunks(out_dir: str, k: int, sources: object, emit: object) -> tuple[list, dict]:
    """Stream function_sources tuples into chunk files of CHUNK_INSNS instructions as they fill (one chunk in memory), each with its C++ wrapper unit image<k>_<j>_eh.cpp when it has resumable functions; emit(index, sources, addresses) -> chunk text, '' for no file. Returns ([(path, index, addresses)], {'unsupported', 'instructions', 'resumable', 'flags': [(addresses defined, flag facts)] of every function with a non-empty or unknown flag_facts, 'eh_units': wrapper unit paths, 'abi_fn': {function start: recompile abi_check facts}, 'abi_late': direct callees whose callers read registers past their results})."""
    out, cur, addrs, ehs, n, j = [], [], [], [], 0, 0
    tot = {"unsupported": [], "instructions": 0, "resumable": 0, "flags": [], "eh_units": [], "abi_fn": {}, "abi_late": set()}
    for ads, src, ni, uns, res, fc, eh in sources:
        cur.append(src); addrs += ads; n += ni; ehs += [eh] if eh else []
        tot["unsupported"] += uns; tot["instructions"] += ni; tot["resumable"] += res
        if fc and "abi_fn" in fc: tot["abi_fn"][ads[0]] = fc.pop("abi_fn"); tot["abi_late"] |= set(fc.pop("abi_late"))
        if fc is None or any(fc.values()): tot["flags"].append((ads, fc))   # absent: no NZCV use crosses anything
        if n >= CHUNK_INSNS:
            out += write_chunk(out_dir, k, j, emit(j, cur, addrs), addrs); tot["eh_units"] += write_eh(out_dir, k, j, ehs)
            j += 1; cur, addrs, ehs, n = [], [], [], 0
    tot["eh_units"] += write_eh(out_dir, k, j, ehs)
    return out + write_chunk(out_dir, k, j, emit(j, cur, addrs), addrs), tot   # the last chunk, empty or not (as image_chunks did)

def eh_prelude() -> str:
    """Head of every image<k>_<j>_eh.cpp: the CPU types, GuestResume (the same type gbridge.hpp throws) and gd_eh_drive, gbridge gd_eh_run_at's loop with the body called directly. The call that throws nothing is one try around one call (a loop around the try makes clang hoist the catch path's setup into every call); claiming a GuestResume (gd_eh_take, run inside the handler: `throw;` passes it on) and re-entering the body at the resume point (gd_eh_loop, after the handler ends, so repeated throws do not nest) are out of line."""
    return "\n".join(["/* generated by gdyld.py: C++ wrappers of translated functions with resume points */", "#include <stdint.h>",
                      cpu_typedefs(), 'extern "C" void gd_die(const char*, uint64_t);', eh_helpers()])

def eh_helpers() -> str:
    """GuestResume (the same type gbridge.hpp throws) and gd_eh_take / gd_eh_loop / gd_eh_drive (eh_prelude), after CPU and gd_die are declared."""
    return "\n".join(["struct GuestResume { uint64_t sp, pc; CPU regs; };",
                      "static __attribute__((noinline, cold)) int gd_eh_take(CPU* c, GuestResume& r, const uint64_t* rp, int n, int e0, uint64_t sp0) {",
                      "  if (r.sp > sp0 || (r.sp == sp0 && e0 < 0)) throw;",
                      "  int e = -1;",
                      "  for (int i = 0; i < n; i++) if (rp[i] == r.pc) e = i;",
                      "  if (e < 0 && r.sp == sp0) throw;",
                      '  if (e < 0) gd_die("non-local transfer: target pc is not a resume point of the frame that owns the target SP", r.pc);',
                      "  *c = r.regs;",
                      "  return e;",
                      "}",
                      "static __attribute__((noinline, cold)) void gd_eh_loop(void (*b)(CPU*, int), CPU* c, const uint64_t* rp, int n, int e0, uint64_t sp0, int e) {",
                      "  for (;;) {",
                      "    try { b(c, e); return; }",
                      "    catch (GuestResume& r) { e = gd_eh_take(c, r, rp, n, e0, sp0); }",
                      "  }",
                      "}",
                      "template<void (*B)(CPU*, int)> static inline __attribute__((always_inline)) void gd_eh_drive(CPU* c, const uint64_t* rp, int n, int e0) {",
                      "  uint64_t sp0 = c->SP; int e;",
                      "  try { B(c, e0); return; }",
                      "  catch (GuestResume& r) { e = gd_eh_take(c, r, rp, n, e0, sp0); }",
                      "  gd_eh_loop(B, c, rp, n, e0, sp0, e);                  /* by pointer: B keeps one direct call, which a C++ chunk can inline */",
                      "}", ""])

def write_eh(out_dir: str, k: int, j: int, ehs: list[str]) -> list[str]:
    """Write chunk j's C++ wrapper unit when it has wrappers; [path] or []."""
    if not ehs: return []
    path = os.path.join(out_dir, "image%d_%d_eh.cpp" % (k, j))
    with open(path, "w") as f: f.write(eh_prelude() + "".join(ehs))
    return [path]

def chunk_prelude(img: dict, k: int) -> list[str]:
    """Lines every chunk of image k starts with: extern_stub's image name, the C prelude at the image's slide, runtime hooks."""
    assert R.C_PRELUDE.count(PRELUDE_BASE) == 1, "recompile.C_PRELUDE changed shape"
    return ["#define extern_stub m%d_extern_stub" % k, R.C_PRELUDE.replace(PRELUDE_BASE, "#define GUEST_BASE 0x%xULL" % img["slide"]),
            "void gd_die(const char*, uint64_t);", "typedef void (*gfn)(CPU*);",
            "void gd_eh_run(CPU*, void (*)(CPU*, int), const uint64_t*, int);", "void gd_jumpto(CPU*);"]

def optnone(src: str) -> str:
    """A function whose every-instruction br switch has more than OPTNONE_CASES cases (with guest registers in locals) or FLAT_O2_CASES (state in c->, recompile.HUGE_SWITCH) is compiled without optimization (clang -O1/-O2 spends minutes on it; an always-inline body drops that, optnone excludes it)."""
    if src.count("ULL: goto L_") <= (OPTNONE_CASES if "gr_" in src else FLAT_O2_CASES): return src
    if src.startswith(INLINE_BODY): return "static __attribute__((optnone)) " + src[len(INLINE_BODY):]
    return "static __attribute__((optnone)) " + src[len("static "):] if src.startswith("static ") else "__attribute__((optnone)) " + src

UNDECODED_FN = re.compile(r"(optnone\)\) )?void (\w+?_([0-9a-f]+))\(CPU \*restrict c[^)]*\) \{\n  " + re.escape(R.UNDECODED_MARK))

def undecoded(img: dict, units: list) -> list[tuple[str, bool]]:
    """(name, compiled without optimization) of img's functions lifted with fallback (an undecoded br: every instruction is a
    case of their switch and guest state stays in c->), by guest symbol where the symbol table has one, else by C name."""
    found = []
    for path in units:
        if path.endswith((".c", ".cc")) and os.path.exists(path):
            with open(path) as f: found += UNDECODED_FN.findall(f.read())
    names = {v: n for n, v in section_symbols(img).items()} if found else {}
    return [(names.get(int(a, 16), fn), bool(o)) for o, fn, a in found]

def chunk_text(img: dict, k: int, j: int, srcs: list, addrs: list, cxx: bool = False) -> str:
    """One chunk: the prelude, declarations of only the func_ names it references, its functions (huge br switches unoptimized), and its slice of the lookup (GPair rows sorted by absolute guest address; an inline cache keeps a pointer to a row). cxx: the same code as C++ (every name C linkage; the prelude's headers first, outside extern "C"; eh_helpers for the resumable functions' wrappers)."""
    if not srcs: return ""
    ads = sorted(addrs)
    table = "%sconst GPair m%d_p%d[] = {%s};\n" % ("extern " if cxx else "", k, j, ", ".join("{0x%xULL + GUEST_BASE, func_%x}" % (a, a) for a in ads))
    body = "\n".join(optnone(s) for s in srcs) + "\n" + table
    names = sorted(set(FUNC_RE.findall(body)), key=lambda h: int(h, 16))
    decls = ['void func_%s(CPU*) __asm__("_m%d_%s");' % (h, k, h) for h in names]
    eh = ["void gd_eh_run_at(CPU*, void (*)(CPU*, int), const uint64_t*, int, int);"] if "gd_eh_run_at(" in body else []
    if not cxx: return "\n".join(chunk_prelude(img, k) + eh + decls) + "\n" + body
    return "\n".join(["#define GD_CXX 1", "#define restrict __restrict"] + ["#include <%s>" % h for h in CXX_HEADERS]
                     + ['extern "C" {'] + chunk_prelude(img, k) + ["}", eh_helpers(), 'extern "C" {'] + eh + decls) + "\n" + body + "}\n"

def tail_text(img: dict, k: int, chunks: list) -> str:
    """image<k>_t.c: m<k>_lookup_p / m<k>_lookup (binary search over the chunks' first addresses, then in the chunk's sorted GPair rows) and m<k>_extern_stub (binary search over the stubs, a call through the bound GOT, else a loud stop)."""
    rows = sorted(((j, min(a), max(a), len(a)) for _p, j, a in chunks), key=lambda r: r[1])
    if any(rows[i][2] >= rows[i + 1][1] for i in range(len(rows) - 1)): raise ValueError("image %d: chunk address ranges overlap" % k)
    gots = sorted(stub_gots(img).items())
    tab = lambda name, vals: "static const uint64_t %s[] = {%s};" % (name, ", ".join("0x%xULL" % v for v in vals) or "0")
    return "\n".join(chunk_prelude(img, k) + [
        "".join("extern const GPair m%d_p%d[];\n" % (k, j) for j, _lo, _hi, _n in rows),
        tab("m%d_lo" % k, [r[1] for r in rows]),
        "static const GPair* const m%d_cp[] = {%s};" % (k, ", ".join("m%d_p%d" % (k, r[0]) for r in rows) or "0"),
        "static const int m%d_cn[] = {%s};" % (k, ", ".join("%d" % r[3] for r in rows) or "0"),
        tab("m%d_sa" % k, [a for a, _g in gots]), tab("m%d_sg" % k, [(g - img["vm_base"] + img["load"]) & MASK64 for _a, g in gots]),
        "static long gd_bs(const uint64_t* t, long n, uint64_t a) { long lo = 0, hi = n; while (lo < hi) { long m = (lo + hi) / 2;"
        " if (t[m] <= a) lo = m + 1; else hi = m; } return lo - 1; }   /* last index with t[i] <= a, -1 if none */",
        "static long gd_bsp(const GPair* t, long n, uint64_t a) { long lo = 0, hi = n; while (lo < hi) { long m = (lo + hi) / 2;"
        " if (t[m].a <= a) lo = m + 1; else hi = m; } return lo - 1; }",
        "const GPair* m%d_lookup_p(uint64_t a) { long j = gd_bs(m%d_lo, %d, a); if (j < 0) return 0; uint64_t g = a + GUEST_BASE;"
        " long i = gd_bsp(m%d_cp[j], m%d_cn[j], g); return i >= 0 && m%d_cp[j][i].a == g ? &m%d_cp[j][i] : 0; }" % (k, k, len(rows), k, k, k, k),
        "gfn m%d_lookup(uint64_t a) { const GPair* p = m%d_lookup_p(a); return p ? p->f : 0; }" % (k, k),
        "void m%d_extern_stub(CPU* c, uint64_t a) { long i = gd_bs(m%d_sa, %d, a);"
        " if (i >= 0 && m%d_sa[i] == a) { uint64_t t = *(volatile uint64_t*)m%d_sg[i]; c->X[16] = t; dispatch(c, t); return; }"
        " gd_die(\"call to an address that is neither a function start, an entry point nor a stub\", a); }" % (k, k, len(gots), k, k), ""])

def lift_image(img: dict, k: int, out_dir: str, host_gots: frozenset = frozenset()) -> dict:
    """Lift image k into out_dir/image<k>_<j>.c chunks, streamed one function at a time, plus image<k>_t.c (lookup, stubs). Returns {'units', 'unsupported', 'instructions', 'resumable', 'entries', 'flags', 'flag_readers_taken': functions with flag rows and extra entry points that may be called other than by a direct branch (flag_plan stores everywhere when one of them must read NZCV at entry), 'flag_extra': the extra entry points, 'flag_host': the stubs whose GOT word is in host_gots (bound to a host import)}."""
    pre = lift_prep(img)
    chunks, tot = write_chunks(out_dir, k, function_sources(img, k, pre["lift"], pre["ents"], CHUNK_CXX), functools.partial(chunk_text, img, k, cxx=CHUNK_CXX))
    return lift_finish(img, k, out_dir, pre, chunks, tot, host_gots)

def lift_prep(img: dict) -> dict:
    """The whole-image facts every function's lift reads: 'refs' (pointer_refs), 'ents' (interior_entries), 'lift' (decoded_lift bound to the image)."""
    bounds = function_bounds(img)
    refs = pointer_refs(img)
    ptrs = interior_pointers(img, refs=refs)
    ents = interior_entries(img, bounds, eh_resume_points(img, bounds), setjmp_stubs(img), ptrs)
    return {"refs": refs, "ents": ents, "lift": functools.partial(decoded_lift, functools.partial(read_vm, img), ptrs, stub_gots(img), msg=msg_gots(img),
                                     abi=not abi_ok(img), noret=noreturn_starts(img) if not abi_ok(img) else frozenset())}

def lift_finish(img: dict, k: int, out_dir: str, pre: dict, chunks: list, tot: dict, host_gots: frozenset) -> dict:
    """lift_image's result from the written chunks ([(path, index, addresses)]) and their totals: writes image<k>_t.c."""
    ents, refs = pre["ents"], pre["refs"]
    tail = os.path.join(out_dir, "image%d_t.c" % k)
    with open(tail, "w") as f: f.write(tail_text(img, k, chunks))
    extra = frozenset(e for es in ents.values() for e in es)
    flagged = {ads[0] for ads, _fc in tot["flags"]} | extra
    return {**tot, "units": [p for p, _j, _a in chunks] + tot["eh_units"] + [tail], "entries": sum(len(e) for e in ents.values()),
            "flag_readers_taken": sorted(address_taken(img, refs, flagged)), "flag_extra": extra, "abi_taken": address_taken(img, refs, set(tot["abi_fn"])),
            "flag_host": frozenset(s for s, g in stub_gots(img).items() if g in host_gots)}

###############
# parallel lift: the same chunks as write_chunks, cut from the function sizes, lifted by forked workers
###############
def function_plan(img: dict) -> list[list[tuple[int, int, int]]] | None:
    """function_sources' functions as write_chunks would cut them, each (start, end, file offset); an instruction is 4 bytes (iter_functions with skipdata), checked again in lift_chunk; the last chunk may be empty. None when a function is not whole instructions (lift_images then lifts serially)."""
    out, cur, n = [], [], 0
    for addr, size, off in code_sections(img):
        starts = sorted(a for a in img["fstarts"] if addr <= a < addr + size)
        for s, e in zip(starts, starts[1:] + [addr + size]):
            if (e - s) % 4: return None
            cur.append((s, e, off + s - addr)); n += (e - s) // 4
            if n >= CHUNK_INSNS: out.append(cur); cur, n = [], 0
    return out + [cur]

def lift_chunk(img: dict, k: int, out_dir: str, pre: dict, sc: dict, j: int, recs: list) -> tuple[list, dict]:
    """Chunk j of image k from its function records (function_plan): writes it and its C++ wrapper unit as write_chunks would; ([(path, j, addresses)] or [], totals as write_chunks')."""
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM); md.detail = True; md.skipdata = True   # macho.iter_functions' decoder
    cur, addrs, ehs = [], [], []
    tot = {"unsupported": [], "instructions": 0, "resumable": 0, "flags": [], "eh_units": [], "abi_fn": {}, "abi_late": set()}
    for s, e, o in recs:
        insns = list(md.disasm(img["data"][o:o + e - s], s))
        if len(insns) != (e - s) // 4: raise ValueError("%s: function 0x%x decoded to %d items, planned %d" % (img["path"], s, len(insns), (e - s) // 4))
        ads, src, ni, uns, res, fc, eh = function_source(img, k, pre["lift"], pre["ents"], CHUNK_CXX, sc, s, insns)
        cur.append(src); addrs += ads; ehs += [eh] if eh else []
        tot["unsupported"] += uns; tot["instructions"] += ni; tot["resumable"] += res
        if fc and "abi_fn" in fc: tot["abi_fn"][ads[0]] = fc.pop("abi_fn"); tot["abi_late"] |= set(fc.pop("abi_late"))
        if fc is None or any(fc.values()): tot["flags"].append((ads, fc))   # absent: no NZCV use crosses anything
    tot["eh_units"] += write_eh(out_dir, k, j, ehs)
    return write_chunk(out_dir, k, j, chunk_text(img, k, j, cur, addrs, cxx=CHUNK_CXX), addrs), tot

def merge_totals(parts: list[dict]) -> dict:
    """write_chunks' totals from per-chunk totals, in chunk order."""
    return {"unsupported": [u for p in parts for u in p["unsupported"]], "instructions": sum(p["instructions"] for p in parts),
            "resumable": sum(p["resumable"] for p in parts), "flags": [f for p in parts for f in p["flags"]],
            "eh_units": [u for p in parts for u in p["eh_units"]], "abi_fn": {a: f for p in parts for a, f in p["abi_fn"].items()},
            "abi_late": {a for p in parts for a in p["abi_late"]}}

def lift_task(ctx: dict, task: tuple[int, int, int]) -> tuple[list, list, int, int]:
    """Worker: chunks [j0, j1) of image k -> (chunk rows, per-chunk totals, pid, this worker's peak RSS bytes)."""
    k, j0, j1 = task
    img, pre, sc, plan = ctx["images"][k], ctx["pre"][k], ctx["sc"][k], ctx["plan"][k]
    done = [lift_chunk(img, k, ctx["out_dir"], pre, sc, j, plan[j]) for j in range(j0, j1)]
    return [c for rows, _t in done for c in rows], [t for _r, t in done], os.getpid(), resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

def lift_worker_init(ctx: dict) -> None:
    """Pool initializer (fork: ctx is inherited, not pickled): keep ctx for lift_task_forked."""
    LIFT_CTX.update(ctx)

def lift_task_forked(task: tuple[int, int, int]) -> tuple[list, list, int, int]:
    """lift_task on the context lift_worker_init kept."""
    return lift_task(LIFT_CTX, task)

def lift_tasks(plans: list[list]) -> list[tuple[int, int, int]]:
    """(image, first chunk, end chunk) tasks of at most LIFT_TASK_CHUNKS chunks, every image's chunks in order."""
    return [(k, j, min(j + LIFT_TASK_CHUNKS, len(p))) for k, p in enumerate(plans) for j in range(0, len(p), LIFT_TASK_CHUNKS)]

def lift_images(images: list, out_dir: str, host_gots: list[frozenset], jobs: int = LIFT_JOBS) -> tuple[list[dict], dict]:
    """lift_image of every image, in jobs forked worker processes when jobs > 1 and there are at least LIFT_MIN_CHUNKS chunks (files, totals and order identical to the serial lift: each chunk's functions come from function_plan, results merge in chunk order); ([lift_image result], worker stats)."""
    plans = [function_plan(img) for img in images] if jobs > 1 else []
    if jobs <= 1 or None in plans or sum(len(p) for p in plans) < LIFT_MIN_CHUNKS:
        return [lift_image(img, k, out_dir, g) for k, (img, g) in enumerate(zip(images, host_gots))], {"jobs": 1}
    pres = [lift_prep(img) for img in images]
    ctx = {"images": images, "pre": pres, "sc": [source_context(img, p["ents"]) for img, p in zip(images, pres)], "plan": plans, "out_dir": out_dir}
    tasks = lift_tasks(plans)
    with concurrent.futures.ProcessPoolExecutor(min(jobs, len(tasks)), mp_context=multiprocessing.get_context("fork"),
                                                initializer=lift_worker_init, initargs=(ctx,)) as pool:
        done = list(pool.map(lift_task_forked, tasks))
    rss = {}
    for _c, _t, pid, r in done: rss[pid] = max(rss.get(pid, 0), r)
    by_img = [[d for t, d in zip(tasks, done) if t[0] == k] for k in range(len(images))]
    out = [lift_finish(img, k, out_dir, pres[k], [c for d in ds for c in d[0]], merge_totals([t for d in ds for t in d[1]]), host_gots[k])
           for k, (img, ds) in enumerate(zip(images, by_img))]
    return out, {"jobs": len(rss), "tasks": len(tasks), "worker_peak_rss_mb": sorted(round(v / 2 ** 20) for v in rss.values())}

def host_gots_of(img: dict, host_binds: list) -> frozenset:
    """vmaddrs of image img's words that link bound to host imports (host_binds hold absolute addresses)."""
    return frozenset(a - img["load"] + img["vm_base"] for a, _n, _ad, _w in host_binds if img["load"] <= a < img["load"] + img["vm_size"])

def flag_needs(f: int, origins: frozenset, owner: dict, extra: frozenset = frozenset(), mode: str = NZCV_MODE,
               host: frozenset = frozenset()) -> list[tuple[str, object]]:
    """What a flag sink in function f needs, per origin of the value it sees: ('R', f) f must get NZCV from its callers, ('R', e) extra entry point e must get it from the direct branches into it, ('T', g) callee g must store NZCV at its returns, ('ALL', why) unplaceable (a resume point, an indirect call's or a stub call's return). An origin carried through an undecoded br's edges to every word (recompile flag_origins ('B', o)) counts as o in every mode: the br may really land there. mode (NZCV_MODE): 'exact' every origin counts; 'nob' (name kept from a first version that dropped 'B' origins, which lost real needs) not the return of a stub bound to a host import (host: those stubs; the arm64 host code's NZCV has no x86-64 counterpart); 'direct' (a model, not sound) only entries, extra entries and direct callees count."""
    out = []
    for o in origins:
        if isinstance(o, tuple) and o[0] == "B": o = o[1]
        if o == "E": out.append(("R", f))
        elif isinstance(o, int): out.append(("T", owner.get(o, o)))
        elif isinstance(o, tuple) and o[0] == "N" and o[1] in extra: out.append(("R", o[1]))
        elif mode == "direct" or (mode == "nob" and isinstance(o, tuple) and o[0] == "S" and o[1] in host): continue
        else: out.append(("ALL", "flags read after a resume point" if isinstance(o, tuple) and o[0] == "N" else
                          "flags read after a call through a stub into another guest image" if isinstance(o, tuple) else "flags read after an indirect call"))
    return out

def flag_plan(rows: list, taken: list, extra: frozenset = frozenset(), mode: str = NZCV_MODE, host: frozenset = frozenset()) -> tuple[bool, set, set, str]:
    """(store NZCV everywhere, R: function starts and extra entry points that read NZCV at entry, T: function starts whose returns must store NZCV, why everywhere or '') for one image from its flag rows ([(addresses defined, flag_facts)], absent = nothing crosses), taken (row functions and extra entries callable other than by a direct branch), extra (the image's extra entry points: only direct branches from other functions enter them) and host (its stubs bound to host imports), under mode (flag_needs). Closed over the image: a function's own reads need their origins; a T member's returns need theirs and make its direct tail-call targets T; a call or tail-call site into an R member needs its origins (a thunk or a wrapper that forwards its caller's flags joins R). Everywhere when some fact is unknown, a needed value comes from a resume point, an indirect call's or a guest stub's return, or (unless mode is 'direct') an R member may be called indirectly or a T member leaves through an indirect tail exit or a tail call through a stub ('nob': into another guest image)."""
    strict = mode != "direct"
    owner = {a: ads[0] for ads, _fc in rows for a in ads}
    facts = {ads[0]: fc for ads, fc in rows}
    if any(fc is None for fc in facts.values()): return True, set(), set(), "a function's flag facts are unknown"
    callers = {}
    for f, fc in facts.items():
        for g, o in fc["sites"].items(): callers.setdefault(g if g in extra else owner.get(g, g), []).append((f, o))
    r_set, t_set, taken_set = set(), set(), set(taken)
    work = [w for f, fc in facts.items() for w in flag_needs(f, fc["local"], owner, extra, mode, host)]
    while work:
        kind, f = work.pop()
        if kind == "ALL": return True, set(), set(), f
        if kind == "R" and f not in r_set:
            if strict and f in taken_set: return True, set(), set(), "a function or entry point that reads flags at entry may be called indirectly"
            r_set.add(f)
            work += [w for c, o in callers.get(f, []) for w in flag_needs(c, o, owner, extra, mode, host)]
        elif kind == "T" and f not in t_set:
            t_set.add(f)
            fc = facts.get(f, NO_FLAGS)
            if strict and (fc["itail"] or any(mode == "exact" or s not in host for s in fc.get("stails", ()))):
                return True, set(), set(), "a function that returns flags leaves through an indirect tail call or a stub's"
            work += flag_needs(f, fc["ret"], owner, extra, mode, host) + [("T", owner.get(t, t)) for t in fc["tails"]]
    return False, r_set, t_set, ""

def flags_header(everywhere: bool, readers: set, returners: set, msg_slots: dict | None = None, abi: bool = False,
                 rets: set = frozenset(), xd: set = frozenset(), xg: set = frozenset(), leaf: dict | None = None,
                 cse: bool = False, keep: set = frozenset(), norc: bool = False) -> str:
    """gd_flags_<k>.h text (passed with -include to the image's chunks): GD_FLAGS_ALL and the GDF_IN_ / GDF_RET_ names recompile.flag_wrap tests, GD_MSG_SLOT<k> (msg_slots: MSG_SENDS index -> its import slot address; recompile GD_MSGSEND) GD_ABI (abi: the image runs under the AAPCS64 register contract, recompile localize) the GDA_RET_, GDA_X_ and GDA_G_ names (rets, xd, xg: abi_plan) GDL_<got> (leaf: GOT vmaddr -> (import slot address, LEAF_DIRECT name); recompile got_call), GD_CSE (cse: no guest unwinder reads saved registers off the guest stack), the GDA_K_ names (keep: abi_plan; recompile CSE_KEEP) and GD_NORC (norc: no guest image in the process has an extra entry point, whose wrappers are the only code that sets c->unw; recompile GD_RC)."""
    slots = [] if not msg_slots else ["#define GD_MSG_SLOT%d 0x%xULL\n" % (k, (msg_slots or {}).get(k, 1)) for k in range(3)]
    return "".join(["/* generated by gdyld.py: NZCV stores at calls and returns (recompile.flag_wrap) */\n#define GD_FLAGS_ALL %d\n#define GD_ABI %d\n" % (int(everywhere), int(abi))]
                   + ["#define GDF_IN_%x 1\n" % a for a in sorted(readers)] + ["#define GDF_RET_%x 1\n" % a for a in sorted(returners)] + slots
                   + ["#define GDA_RET_%x 1\n" % a for a in sorted(rets)] + ["#define GDA_X_%x 1\n" % a for a in sorted(xd)]
                   + ["#define GDA_G_%x 1\n" % a for a in sorted(xg)]
                   + ["#define GDL_%x GD_LEAF(0x%xULL, %s)\n" % (g, t, LEAF_DIRECT[n]) for g, (t, n) in sorted((leaf or {}).items())]
                   + ["#define GD_CSE 1\n"] * cse + ["#define GDA_K_%x 1\n" % a for a in sorted(keep)] + ["#define GD_NORC 1\n"] * norc)

def dispatch_text(images: list, nimp: int, leaf: frozenset = frozenset()) -> str:
    """gd_disp.c: gd_icall_slow, the miss path of every GD_ICALL inline cache: a guest function start (m<k>_lookup_p of the image whose range holds it) or a host import slot (a gbridge thunk per import, gbridge_leaf for the slots in leaf: LEAF_IMPORTS bridged by prototype) is cached at the call site and called, and so is a host function a typed native slot bridges (gbridge gd_native_pair: a malloc zone's slots); anything else goes to dispatch()."""
    find = " else ".join("if (t - 0x%xULL < 0x%xULL) p = m%d_lookup_p(t - 0x%xULL);" % (img["load"], img["vm_size"], k, img["slide"])
                         for k, img in enumerate(images))
    imps = "else if (t - 0x%xULL < 0x%xULL && (t - 0x%xULL) %% %d == 0) p = &gd_impp[(t - 0x%xULL) / %d];" % (
        IMPORT_BASE, nimp * IMP_SLOT, IMPORT_BASE, IMP_SLOT, IMPORT_BASE, IMP_SLOT)
    return "\n".join([R.C_PRELUDE, "void gbridge(CPU*, int);", "void gbridge_leaf(CPU*, int);", "const GPair* gd_native_pair(uint64_t);",
                      "const GPair gd_nopair = {1, 0};   /* matches no target: odd */"]
                     + ["const GPair* m%d_lookup_p(uint64_t);" % k for k in range(len(images))]
                     + ["static void gd_imp_%d(CPU* c) { gbridge%s(c, %d); }" % (k, "_leaf" if k in leaf else "", k) for k in range(nimp)]
                     + ["static const GPair gd_impp[] = {%s};" % (", ".join("{0x%xULL, gd_imp_%d}" % (IMPORT_BASE + k * IMP_SLOT, k)
                                                                          for k in range(nimp)) or "{1, 0}"),
                        "static const GPair* gd_gic[1 << 16];   /* shared cache of resolved targets: polymorphic sites skip the search */",
                        "void gd_icall_slow(CPU* c, uint64_t t, const GPair** ic) {"
                        " const GPair** e = &gd_gic[(uint32_t)((t >> 2) ^ (t >> 18)) & 0xffff];"
                        " const GPair* p = __atomic_load_n(e, __ATOMIC_RELAXED);"
                        " if (!p || p->a != t) { p = 0; %s %s if (!p) p = gd_native_pair(t); if (p) __atomic_store_n(e, p, __ATOMIC_RELAXED); }"
                        " if (p) { __atomic_store_n(ic, p, __ATOMIC_RELAXED); p->f(c); return; } dispatch(c, t); }" % (find, imps), ""])

def cpu_typedefs() -> str:
    lines = [ln for ln in R.C_PRELUDE.splitlines() if ln.startswith(("typedef float gv4f", "typedef union {", "typedef struct { uint64_t X[31]"))]
    assert len(lines) == 3, "recompile.C_PRELUDE CPU typedefs changed shape"
    return "\n".join(lines)

def host_libs(images: list) -> list[str]:
    return sorted({d[1] for img in images for d in img["resolved"] if d[0] == "host"})

def framework_headers(sdk: str, libs: list, extra: dict) -> tuple[list, list]:
    """(umbrella headers usable from C++, link flags) for the host frameworks/libraries the guest loads; `extra` maps an install name to (header path, x86-64 dylib path) for a host library outside the SDK."""
    headers, flags = [], []
    for lib in libs:
        fw = re.search(r"/([^/]+)\.framework/", lib)
        if lib in extra:                                               # header None: a host image (C++ API bridged separately)
            headers += [extra[lib][0]] if extra[lib][0] else []
            flags += [extra[lib][1], "-Wl,-rpath," + os.path.dirname(extra[lib][1])]
        elif fw:
            flags += ["-framework", fw.group(1)]
            h = "%s/%s.h" % (fw.group(1), fw.group(1))
            if os.path.isfile(os.path.join(sdk, "System", "Library", "Frameworks", fw.group(1) + ".framework", "Headers", fw.group(1) + ".h")):
                headers.append(h)
        else:
            base = os.path.basename(lib).split(".")[0]
            if base not in ("libSystem", "libc++", "libc++abi"): flags.append("-l" + base[3:])
    return headers, flags

def include_lines(headers: list) -> list[str]:
    """#include lines as host.cpp has them: an extra host library's header (absolute path) gets C linkage."""
    return [('extern "C" {\n#include "%s"\n}' if os.path.isabs(h) else "#include <%s>") % h for h in headers]

def host_clang(sdk: str, headers: list, mode: str) -> subprocess.CompletedProcess:
    """The headers in host.cpp's C++ dialect: mode -E preprocesses, -fsyntax-only parses."""
    src = "\n".join(include_lines(headers)) + "\n" + EXTRA_DECLS
    return subprocess.run([CLANGXX, mode] + (["-P"] if mode == "-E" else []) + ["-x", HOST_LANG, "-std=c++17", "-nostdinc++", "-isysroot",
                          sdk, "-arch", "x86_64", "-"], input=src, capture_output=True, text=True)

def declared_names(sdk: str, headers: list) -> tuple[set, list]:
    """C identifiers declared as functions or extern data by the umbrella headers (x86-64 view); usable headers: those that parse as C++ next to the base headers (an Objective-C umbrella such as Foundation.h preprocesses but does not)."""
    with concurrent.futures.ThreadPoolExecutor(BUILD_JOBS) as pool:
        ok = list(pool.map(lambda h: h in BASE_HEADERS or host_clang(sdk, BASE_HEADERS + [h], "-fsyntax-only").returncode == 0, headers))
    usable = [h for h, good in zip(headers, ok) if good]
    r = host_clang(sdk, BASE_HEADERS + [h for h in usable if h not in BASE_HEADERS], "-E")
    if r.returncode: raise RuntimeError("umbrella headers do not preprocess: " + r.stderr[-800:])
    fn = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", r.stdout))
    data = set(re.findall(r"\bextern\b[^;(){}]*?\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:__attribute__|__asm|;)", r.stdout))
    return fn | data, usable

def c_prototypes(sdk: str, headers: list) -> dict[str, str]:
    """C function name -> type spelling as the umbrella headers declare it (libclang, C++ view without libc++). A V8 build's host TU includes libc++, whose C wrapper headers overload some C names (sqrt, abs, memchr), so its bridges select the C declaration by this type."""
    import clang.cindex as ci
    src = "".join("#include <%s>\n" % h for h in headers) + EXTRA_DECLS
    res = run([CLANG, "-print-resource-dir"]).stdout.strip()
    tu = ci.Index.create().parse("protos.cpp", args=["-x", HOST_LANG, "-std=c++17", "-nostdinc++", "-isysroot", sdk, "-target", "x86_64-apple-macos11",
                                                     "-resource-dir", res], unsaved_files=[("protos.cpp", src)],
                                 options=ci.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)
    out, todo = {}, list(tu.cursor.get_children())
    while todo:
        c = todo.pop(0)
        if c.kind == ci.CursorKind.LINKAGE_SPEC: todo = list(c.get_children()) + todo
        elif c.kind == ci.CursorKind.FUNCTION_DECL: out.setdefault(c.spelling, NORETURN_RE.sub("", c.type.spelling))
    return out

def unavailable_names(sdk: str, headers: list) -> set[str]:
    """C names (functions, extern data) the headers mark unavailable on macOS (API_UNAVAILABLE(macos)): bound by name at start, never through their declaration."""
    import clang.cindex as ci
    src = "".join("#include <%s>\n" % h for h in headers) + EXTRA_DECLS
    res = run([CLANG, "-print-resource-dir"]).stdout.strip()
    tu = ci.Index.create().parse("unavail.cpp", args=["-x", HOST_LANG, "-std=c++17", "-nostdinc++", "-isysroot", sdk, "-target", "x86_64-apple-macos11",
                                                      "-resource-dir", res], unsaved_files=[("unavail.cpp", src)],
                                 options=ci.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)
    out, todo = set(), list(tu.cursor.get_children())
    while todo:
        c = todo.pop()
        if c.kind == ci.CursorKind.LINKAGE_SPEC: todo += list(c.get_children())
        elif c.kind in (ci.CursorKind.FUNCTION_DECL, ci.CursorKind.VAR_DECL) and c.availability == ci.AvailabilityKind.NOT_AVAILABLE:
            out.add(c.spelling)
    return out

def method_variadic(m: object, owner: str, cmeth: int) -> tuple | None:
    """(class, selector, class method?, VK kind, format index, va_list index) of a variadic or va_list ObjC method cursor, else None; indexes count parameters from 1."""
    params = [(c.spelling, c.type.spelling) for c in m.get_children() if c._kind_id == 10]     # PARM_DECL
    toks = [t.spelling for t in m.get_tokens()]
    va = next((i + 1 for i, (_n, t) in enumerate(params) if "va_list" in t), 0)
    if "..." not in toks and not va: return None
    fmt = next((int(toks[i + 2]) for i in range(len(toks) - 5) if toks[i] in ("NS_FORMAT_FUNCTION", "CF_FORMAT_FUNCTION")
                and toks[i + 1] == "(" and toks[i + 2].isdigit()), 0)
    fmt = fmt or next((i + 1 for i, (n, _t) in enumerate(params) if "format" in n.lower()), 0)
    nil = any(t in ("NS_REQUIRES_NIL_TERMINATION", "sentinel") for t in toks)
    kind = "valist" if va and fmt else "nil" if nil and not va else "fmt" if fmt and not va else "unknown"
    return (owner, m.spelling, cmeth, VK[kind], fmt, va)

def objc_variadics(sdk: str, headers: list) -> list[tuple]:
    """Variadic and va_list methods the SDK's ObjC headers declare (libclang, x86-64 view), sorted by selector: the runtime's type encodings name only the fixed parameters."""
    import clang.cindex as ci
    if not headers: return []
    res = run([CLANG, "-print-resource-dir"]).stdout.strip()
    tu = ci.Index.create().parse("vmeth.m", args=["-x", "objective-c", "-isysroot", sdk, "-target", "x86_64-apple-macos11", "-resource-dir", res],
                                 unsaved_files=[("vmeth.m", "".join("#import <%s>\n" % h for h in headers))],
                                 options=ci.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)
    out = set()
    for c in tu.cursor.get_children():
        if c._kind_id not in (11, 12, 14): continue                    # @interface, category, @protocol
        owner = "" if c._kind_id == 14 else c.spelling if c._kind_id == 11 else next((k.spelling for k in c.get_children() if k._kind_id == 42), "")
        if c._kind_id == 12 and not owner: continue                    # a category without its class reference
        for m in c.get_children():
            if m._kind_id in (16, 17):                                 # instance / class method
                v = method_variadic(m, owner, int(m._kind_id == 17))
                if v: out.add(v)
    return sorted(out, key=lambda v: (v[1], v[0], v[2]))

def fn_pointer(t: object) -> bool:
    """True for a libclang type that is (a typedef of) a pointer to a function."""
    import clang.cindex as ci
    c = t.get_canonical()
    return c.kind == ci.TypeKind.POINTER and c.get_pointee().kind in (ci.TypeKind.FUNCTIONPROTO, ci.TypeKind.FUNCTIONNOPROTO)

def prop_setter(p: object) -> str | None:
    """Setter selector of an ObjC property cursor (setter= attribute or set<Name>:), None when readonly."""
    toks = [t.spelling for t in p.get_tokens()]
    if "readonly" in toks: return None
    i = next((i for i in range(len(toks) - 3) if toks[i] == "setter" and toks[i + 1] == "="), None)
    return toks[i + 2] + ":" if i is not None else "set%s%s:" % (p.spelling[:1].upper(), p.spelling[1:])

def vec_record(t: object, depth: int = 0) -> bool:
    """True for a libclang type that is a struct/union (or array of them) holding a SIMD vector anywhere inside: ObjC type encodings drop the vector, so the encoded record is smaller than the real one."""
    import clang.cindex as ci
    c = t.get_canonical()
    if depth > 16: return False
    if c.kind in (ci.TypeKind.VECTOR, ci.TypeKind.EXTVECTOR): return depth > 0   # a bare vector encodes as nothing: its parse refuses it
    if c.kind == ci.TypeKind.CONSTANTARRAY: return vec_record(c.element_type, depth + 1)
    if c.kind != ci.TypeKind.RECORD: return False
    return any(vec_record(f.type, depth + 1) for f in c.get_fields())

def enc_key(enc: str) -> str:
    """An ObjC method encoding without offsets and qualifiers (gobjc.hpp enc_key() is the same): the header's and the runtime's spelling of one method agree on it."""
    return "".join(ch for ch in enc if not ch.isdigit() and ch not in "rnNoORV+")

def vec_rows(m: object) -> set[tuple]:
    """(selector, enc_key) of an ObjC method or property cursor whose return or parameter type is a record holding a SIMD vector; empty otherwise."""
    if m._kind_id in (16, 17):                                         # method: its encoding names every type in order
        parms = [p.type for p in m.get_children() if p._kind_id == 10]
        return {(m.spelling, enc_key(m.objc_type_encoding))} if any(vec_record(t) for t in [m.result_type] + parms) else set()
    if m._kind_id != 13 or not vec_record(m.type): return set()       # property: its getter and setter
    t = m.objc_type_encoding[1:].split(",")[0]                         # attribute string "T<type>,R,N,..."
    toks = [x.spelling for x in m.get_tokens()]
    g = next((toks[i + 2] for i in range(len(toks) - 3) if toks[i] == "getter" and toks[i + 1] == "="), m.spelling)
    s = prop_setter(m)
    return {(g, enc_key(t + "@:"))} | ({(s, enc_key("v@:" + t))} if s else set())

def objc_vecrecs(sdk: str, headers: list) -> list[tuple]:
    """Sorted (selector, enc_key) rows of vec_rows() for every ObjC method and property the framework umbrellas and extra host headers (absolute paths) declare (libclang, objective-c x86-64 view: in C no extern "C" block hides an @interface and simd needs no libc++)."""
    import clang.cindex as ci
    if not headers: return []
    res = run([CLANG, "-print-resource-dir"]).stdout.strip()
    tu = ci.Index.create().parse("vecrec.m", args=["-x", "objective-c", "-isysroot", sdk, "-target", "x86_64-apple-macos11", "-resource-dir", res],
                                 unsaved_files=[("vecrec.m", "".join(('#import "%s"\n' if os.path.isabs(h) else "#import <%s>\n") % h for h in headers))],
                                 options=ci.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)
    fatal = [str(d) for d in tu.diagnostics if d.severity >= ci.Diagnostic.Fatal]
    if fatal: raise LookupError("SIMD record scan: the framework headers do not parse: %s" % fatal[0])
    return sorted({r for c in tu.cursor.get_children() if c._kind_id in (11, 12, 14) for m in c.get_children() for r in vec_rows(m)})

def objc_fnparams(sdk: str, headers: list) -> list[tuple]:
    """(class, selector, class method?, parameter index, C++ type) of every ObjC method or property setter the SDK headers declare with a function-pointer parameter (libclang, host.cpp's objective-c++ x86-64 view), sorted by selector: the runtime's encoding calls it an untyped ^?."""
    import clang.cindex as ci
    if not headers: return []
    res = run([CLANG, "-print-resource-dir"]).stdout.strip()
    tu = ci.Index.create().parse("fparam.mm", args=["-x", HOST_LANG, "-std=c++17", "-nostdinc++", "-isysroot", sdk, "-target", "x86_64-apple-macos11",
                                                    "-resource-dir", res], unsaved_files=[("fparam.mm", "".join("#import <%s>\n" % h for h in headers))],
                                 options=ci.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)
    out = set()
    for c in tu.cursor.get_children():
        if c._kind_id not in (11, 12, 14): continue                    # @interface, category, @protocol
        owner = "" if c._kind_id == 14 else c.spelling if c._kind_id == 11 else next((k.spelling for k in c.get_children() if k._kind_id == 42), "")
        if c._kind_id == 12 and not owner: continue
        for m in c.get_children():
            if m._kind_id in (16, 17):                                 # instance / class method: PARM_DECL children
                parms = [p for p in m.get_children() if p._kind_id == 10]
                out |= {(owner, m.spelling, int(m._kind_id == 17), i, p.type.get_canonical().spelling) for i, p in enumerate(parms) if fn_pointer(p.type)}
            elif m._kind_id == 13 and fn_pointer(m.type) and prop_setter(m):   # property: its setter's only parameter
                out.add((owner, prop_setter(m), int("class" in [t.spelling for t in m.get_tokens()]), 0, m.type.get_canonical().spelling))
    generic = ("void (*)()", "void (*)(void)")                         # IMP-like: the real type comes from elsewhere, stays loud
    return sorted((v for v in out if v[4] not in generic), key=lambda v: (v[1], v[0], v[2], v[3]))

def compiling_types(sdk: str, headers: list, types: list[str]) -> set[str]:
    """The C++ type spellings that compile after host.cpp's headers (one alias per line; a failing line drops its type)."""
    head = "\n".join(include_lines(headers)) + "\n" + EXTRA_DECLS + "\n"
    src = head + "".join("using gd_fpt_%d = %s;\n" % (i, t) for i, t in enumerate(types))
    r = subprocess.run([CLANGXX, "-fsyntax-only", "-x", HOST_LANG, "-std=c++17", "-nostdinc++", "-isysroot", sdk, "-arch", "x86_64", "-"],
                       input=src, capture_output=True, text=True)
    first = head.count("\n") + 1                                       # 1-based line of gd_fpt_0
    bad = {int(n) - first for n in re.findall(r"^<stdin>:(\d+):\d+: error", r.stderr, re.M)}
    return {t for i, t in enumerate(types) if i not in bad}

def dl_search(images: list, k: int, first: bool, hidx: dict) -> list[int]:
    """dyld's dlsym search through image k's handle (Loader::hasExportedSymbol): the image, then its dependencies depth first in load-command order, each once, upward links skipped; first (RTLD_FIRST): re-exported ones only. A host library is -1 - hidx[install name]; the host's own dlsym searches its dependencies."""
    order, seen, stack = [], set(), [("guest", k)]
    while stack:
        d = stack.pop()
        if d in seen: continue
        seen.add(d)
        order.append(d[1] if d[0] == "guest" else -1 - hidx[d[1]])
        if d[0] == "host": continue
        img = images[d[1]]
        stack += reversed([r for r, (_n, kind) in zip(img["resolved"], img["deps"]) if r[0] in ("guest", "host") and kind != "upward" and (kind == "reexport" or not first)])
    return order

def dl_rows(images: list) -> tuple[list[tuple], list[str]]:
    """Per guest image (install name or None, LC_RPATHs as written, dlsym search list, RTLD_FIRST search list, guest dependencies in order with an upward link as ~index); and the host libraries those lists name, as paths the host can dlopen."""
    hosts = list(dict.fromkeys(d[1] for img in images for d in img["resolved"] if d[0] == "host"))
    hidx = {n: i for i, n in enumerate(hosts)}
    rows = [(img["id"], img["rpaths"], dl_search(images, k, False, hidx), dl_search(images, k, True, hidx),
             [d[1] if kind != "upward" else ~d[1] for d, (_n, kind) in zip(img["resolved"], img["deps"]) if d[0] == "guest"])
            for k, img in enumerate(images)]
    return rows, [images[0]["host_files"].get(n, n) for n in hosts]

def gen_hpp(dl: list, dlhost: list, fparams: list, vecs: list | None = None) -> str:
    """gdyld_gen.hpp: GD_DLI and GD_DLHOST (guest dlopen, dlsym, initializers on dlopen), GD_FPARAM (typed ^? method parameters) and GD_VECREC (methods with a record holding a SIMD vector, sorted by selector), included by gbridge.hpp."""
    if len(dl) > 250: raise ValueError("more than 250 guest images: gbridge's dlopen handle page holds 250")
    types = sorted({r[4] for r in fparams})
    out = ["/* generated by gdyld.py: guest dlopen images, typed function-pointer parameters of ObjC methods */", "#define GD_HAVE_GEN 1"]
    out += ["static const int gd_dl%s_%d[] = {%s};" % (t, k, ", ".join(str(d) for d in row[j] + [0])) for k, row in enumerate(dl)
            for t, j in (("s", 2), ("f", 3), ("i", 4))]                # each list ends in a 0 that is not counted (no empty array)
    out.append("static const DlImg GD_DLI[] = {\n%s\n};\nstatic const int GD_NDLI = %d;" % (",\n".join(
        "  {%s, %s, gd_dls_%d, %d, gd_dlf_%d, %d, gd_dli_%d, %d}" % (json.dumps(i) if i else "nullptr", json.dumps("\n".join(r)), k, len(s), k, len(f), k, len(d))
        for k, (i, r, s, f, d) in enumerate(dl)), len(dl)))
    out.append("static const char* const GD_DLHOST[] = {%s};\nstatic const int GD_NDLHOST = %d;" % (", ".join([json.dumps(h) for h in dlhost] + ["nullptr"]), len(dlhost)))
    out += ["static uint64_t gd_fpm_%d(uint64_t g) { return (uint64_t)(uintptr_t)gd::to_host_fn<%s>(g); }" % (i, t) for i, t in enumerate(types)]
    out.append("static const FParam GD_FPARAM[] = {\n%s\n};\nstatic const int GD_NFPARAM = %d;" % (",\n".join(
        ["  {%s, %s, %d, %d, gd_fpm_%d}" % (json.dumps(c), json.dumps(s), cm, a, types.index(t)) for c, s, cm, a, t in fparams]
        + ["  {nullptr, nullptr, 0, 0, nullptr}"]), len(fparams)))
    out.append("static const VecRec GD_VECREC[] = {\n%s\n};\nstatic const int GD_NVECREC = %d;" % (",\n".join(
        ["  {%s, %s}" % (json.dumps(s), json.dumps(e)) for s, e in vecs or []] + ["  {nullptr, nullptr}"]), len(vecs or [])))
    return "\n".join(out) + "\n"

def fn_ref(name: str, k: int, protos: dict | None) -> tuple[str, str]:
    """(pointer expression, alias declaration) naming C function `name`: &::name, or cast to its C type in a V8 build."""
    if protos is None or name not in protos: return "&::" + name, ""
    return "static_cast<gdt_%d*>(&::%s)" % (k, name), "using gdt_%d = %s;" % (k, TRAIL_ATTR_RE.sub("", protos[name]))   # nothrow: not valid in an alias

def import_keys(host_binds: list) -> dict[tuple, tuple]:
    """(install name, symbol) of every host bind -> its import key: (install name, symbol) only for a symbol that two or more host libraries are asked for (each resolved in its own library), else ('', symbol), one shared import."""
    libs = {}
    for _a, (lib, n), _ad, _w in host_binds: libs.setdefault(n, set()).update([lib] if lib else [])
    return {(lib, n): (lib, n) if lib and len(libs[n]) > 1 else ("", n) for _a, (lib, n), _ad, _w in host_binds}

def v8_libs(host_files: dict) -> list[str]:
    """Install names of the host V8 libraries (libv8, libv8_libbase, libv8_libplatform) among the host images."""
    return sorted(n for n in host_files if V8_LIB_RE.search(n))

def v8_generate(gen: str, guests: list[str], host_dir: str) -> tuple[dict, list[str]]:
    """Per-build V8 tables in gen/ for the guest images that import libv8*: typed wrappers (v8_bridges.inc), the entry catalog and marshalling (v8_marshal.inc: Fix/After, GD_VTABS, GD_NSLOTS). Returns (mangled import -> wrapper index, generator report lines). Raises LookupError for an import the pinned headers cannot bind."""
    if not os.path.isdir(V8DIR): raise LookupError("guest images import libv8*, and this tree has no V8 bridge generators (%s)" % V8DIR)
    os.makedirs(gen, exist_ok=True)
    env = dict(os.environ, GDYLD_V8_HOST_DIR=host_dir)
    log = []
    for script, args in (("gen_v8_bridges.py", [gen] + guests), ("catalog_v8_entries.py", [gen] + guests), ("gen_v8_marshal.py", [gen])):
        r = subprocess.run([sys.executable, os.path.join(V8DIR, script)] + args, capture_output=True, text=True, env=env)
        open(os.path.join(gen, script + ".log"), "w").write(r.stdout + r.stderr)
        if r.returncode: raise RuntimeError("%s failed: %s" % (script, (r.stdout + r.stderr)[-2000:]))
        log += [ln for ln in r.stdout.splitlines() if ln.startswith(("records:", "pass 2", "nm -u", "guest sub-vtables", "native vtable", "wrote"))]
    imp = json.load(open(os.path.join(gen, "v8_imports.json")))
    if imp["unbound_with_fork_headers"]: raise LookupError("V8 imports the pinned headers do not declare: %s" % imp["unbound_with_fork_headers"])
    return {r["mangled"]: k for k, r in enumerate(imp["records"])}, log

def ui_import(lib: str, name: str) -> bool:
    """True for a host import that reaches the window server, AppKit UI or the GPU (gbridge sp_ui_stop: a loud stop, never called)."""
    return bool(UI_LIB_RE.search(lib or "") or UI_SYM_RE.match(name))

def bridge_entry(key: tuple, declared: set, k: int, lib_path: str, weak: bool, v8idx: dict | None = None,
                 protos: dict | None = None, noesc: dict | None = None, ui: bool = False, fns: frozenset = frozenset()) -> tuple[str, str, str]:
    """(C++ table entry, class, declaration) for host import k = (install name, symbol). A $-suffixed variant is called by its exact symbol through an asm label (the link fails if the x86-64 host lacks it); Apple-arm64 long double math is the double math, with no host function of the guest's type; a per-library symbol is looked up in lib_path at start; a weakly bound one is redeclared weak_import (its absence reads as NULL). protos (V8 builds): C functions are named through their C type (fn_ref)."""
    lib, name = key
    lit = json.dumps(name)
    base0 = name[1:] if name.startswith("_") else ""
    if ui and base0 in fns: return "GD_S(sp_ui_stop, %s)" % lit, "ui-guard", ""          # a header function: never called
    if ui and base0 not in declared: return "GD_UIU(%s)" % lit, "ui-guard", ""            # resolved at start: data as data, code stops
    if name in UI_RECV and base0 in declared:
        return ("GD_S(gd_uia_%d, %s)" % (k, lit), "prototype+ui-check",
                "static void gd_uia_%d(CPU* c, int k) { go::ui_check(c->X[0], ENT[k].name); Gen<&::%s>::call(c, k); }" % (k, base0))
    if name in SPECIAL: return "GD_S(%s, %s)" % (SPECIAL[name], lit), "special", ""
    if name in HEAP_ROUTE and not lib: return "GD_ER(%s, %s, %s)" % (HEAP_ROUTE[name], base0, lit), "prototype", ""
    if name in ABI_ROUTE and not lib and base0 in declared:
        return "GD_ERP(&gd_abi_%d::fn, %s, %s)" % (k, base0, lit), "prototype", "using gd_abi_%d = %s;" % (k, ABI_ROUTE[name])
    sw = gswift.bridge_entry(name, lib, lib_path, weak, name[1:] in declared)   # Swift import or undeclared C: IR-typed bridge, Swift data
    if sw: return sw
    if name in TRAPS: return "GD_S(sp_trap, %s)" % lit, "trap", ""
    if v8idx and name in V8_STACK_ARGS and name in v8idx:             # V8 compares the address with its own (host) stack
        x = V8_STACK_ARGS[name]
        return ("GD_S(gd_v8s_%d, %s)" % (k, lit), "v8",
                "static void gd_v8s_%d(CPU* c, int k) { c->X[%d] = stack_to_host(c->X[%d]); Gen<v8b::b_%d>::call(c, k); }" % (k, x, x, v8idx[name]))
    if v8idx and name in v8idx: return "GD_V8(%d, %s)" % (v8idx[name], lit), "v8", ""
    base, _, suffix = (name[1:] if name.startswith("_") else "").partition("$")
    if noesc and base in noesc and not lib and not suffix:            # called through its type without the noescape attribute
        return "GD_EH(gdt_%d, %s, %s)" % (k, base, lit), "prototype", "using gdt_%d = %s;" % (k, noesc[base])
    wk = " __attribute__((weak_import))" if weak else ""
    ref, alias = fn_ref(base, k, protos)
    ctype = "gdt_%d" % k if alias else "decltype(::%s)" % base
    if lib and base in declared and not suffix:
        if alias: return "GD_QT(gdt_%d, %s, %s)" % (k, lit, json.dumps(lib_path)), "per-library", alias
        return "GD_Q(%s, %s, %s)" % (base, lit, json.dumps(lib_path)), "per-library", ""
    if lib: return "GD_U(%s)" % lit, "dynamic", ""
    if base and not suffix and (base in LDBL_ALIAS or base in LDBL_MATH):
        dbl = LDBL_ALIAS.get(base, base[:-1])
        dref, dalias = fn_ref(dbl, k, protos)
        if dbl in declared: return ("GD_LP(%s, %s)" % (dref, lit) if dalias else "GD_L(%s, %s)" % (dbl, lit)), "long-double-as-double", dalias
    if base and base in declared and suffix:
        return ("GD_E(gd_sym_%d, %s)" % (k, lit), "suffixed",
                alias + 'extern "C" %s gd_sym_%d __asm(%s)%s;' % (ctype, k, json.dumps(name), wk))
    if base and base in declared:
        link = 'extern "C"' if not fns or base in fns else "extern"   # data: inherit the header's linkage (Metal's constants are C++)
        decl = alias + ('%s %s %s%s;' % (link, ctype, base, wk) if weak else "")
        return ("GD_EP(%s, %s)" % (ref, lit) if alias else "GD_E(%s, %s)" % (base, lit)), "prototype", decl
    return "GD_U(%s)" % lit, "dynamic", ""

def bridge_hpp(keys: list, declared: set, lib_paths: dict, weak: set, v8idx: dict | None = None,
               protos: dict | None = None, noesc: dict | None = None, ui: frozenset = frozenset(), fns: frozenset = frozenset(),
               ext: dict | None = None) -> tuple[str, dict]:
    """bridge.hpp text and class -> import names; ui: import keys behind the window-server / UI / GPU guard; fns: C functions the headers declare; ext: import key -> bridge entry from a host-library extension (EXTENSIONS)."""
    ents = [(ext or {}).get(n) or bridge_entry(n, declared, k, lib_paths.get(n[0], n[0]), n in weak, v8idx, protos, noesc, n in ui, fns)
            for k, n in enumerate(keys)]
    classes = {}
    for n, (_e, cls, _d) in zip(keys, ents): classes.setdefault(cls, []).append(n[1])
    body = ",\n".join("  " + e for e, _c, _d in ents + [("GD_U(\"<sentinel>\")", "", "")])
    return ("/* generated by gdyld.py: one entry per host import, slot k at GD_IMPORT_BASE + k*GD_IMP_SLOT */\n"
            + "".join(d + "\n" for _e, _c, d in ents if d)
            + "extern const Ent ENT[] = {\n%s\n};\nextern const int NIMP = %d;\n" % (body, len(keys))), classes

def link_errors(err: str) -> str:
    """Host-link failures that are guest/host incompatibilities, as one message ('' when the error is something else)."""
    asserts = sorted(set(re.findall(r"static assertion failed[^\n]*?': (GDYLD_LINK_ERROR:[^\n]*)", err)))
    where = sorted(set(re.findall(r"in instantiation of template class 'Gen<&(\w+)>'", err)))
    undef = sorted(set(re.findall(r'"(_[^"]+)", referenced from', err)))
    return "; ".join(asserts + (["in host bridges %s" % where] if asserts else [])
                     + (["the x86-64 host has no symbol %s (exact variant requested by the guest)" % undef] if undef else []))

def unwind_sections(img: dict) -> tuple[int, int, int, int]:
    """Guest (__eh_frame address, size, __unwind_info address, size); 0, 0 when absent."""
    out = []
    for name in ("__eh_frame", "__unwind_info"):
        s = section(img, "__TEXT", name)
        out += [(s[0] + img["slide"]) & MASK64, s[1]] if s else [0, 0]
    return tuple(out)

def layout_hpp(images: list, files: list, host_binds: list, names: list, inits: list, tlvs: list, v8: bool = False,
               order: tuple = ((), ()), oc: list | None = None, vmeth: list | None = None) -> str:
    """order: (image init order, image of each initializer); oc: objc_info(); vmeth: objc_variadics() rows."""
    idx = {n: k for k, n in enumerate(names)}
    out = ["/* generated by gdyld.py: guest images, host binds, initializers, TLV, entry point */"]
    out += ['extern "C" gfn m%d_lookup(uint64_t);' % k for k in range(len(images))]
    out.append("extern const Img IMG[] = {\n%s\n};\nextern const int NIMG = %d;" % (",\n".join(
        "  {0x%xULL, 0x%xULL, 0x%xULL, %s, m%d_lookup, %s, 0x%xULL, 0x%xULL, 0x%xULL, 0x%xULL}" % (
            img["load"], img["vm_size"], img["slide"], json.dumps(f), k, json.dumps(img["path"]), *unwind_sections(img))
        for k, (img, f) in enumerate(zip(images, files))), len(images)))
    out.append("extern const HBind HB[] = {\n%s\n};\nextern const int NHB = %d;" % (",\n".join(
        ["  {0x%xULL, %d, %dLL, %d}" % (a, idx[n], add, weak) for a, n, add, weak in host_binds] + ["  {0, 0, 0, 0}"]), len(host_binds)))
    out.append("extern const uint64_t INITS[] = {%s};\nextern const int NINIT = %d;" % (", ".join(["0x%xULL" % a for a in inits] + ["0"]), len(inits)))
    out.append("extern const TlvImg TLVI[] = {%s};\nextern const int NTLV = %d;" % (", ".join(
        ["{0x%xULL, %d, %d, %d}" % (t[0], t[1], t[2], t[4]) for t in tlvs] + ["{0, 0, 0, 16}"]), len(tlvs)))
    exports = [(k, n[1:], e[1] if e[0] == "absolute" else img["load"] + e[1]) for k, img in enumerate(images)
               for n, e in sorted(img["exports"].items()) if e[0] in ("regular", "absolute") and n.startswith("_")]
    out.append("extern const GExp GEXP[] = {\n%s\n};\nextern const int NGEXP = %d;" % (",\n".join(
        ["  {%d, %s, 0x%xULL}" % (k, json.dumps(n), a) for k, n, a in exports] + ["  {0, nullptr, 0}"]), len(exports)))
    descs = [(d, t) for t, tv in enumerate(tlvs) for d in tv[3]]
    out.append("extern const uint64_t TLVD[] = {%s};\nextern const int TLVD_IMG[] = {%s};\nextern const int NTLVD = %d;" % (
        ", ".join(["0x%xULL" % d for d, _ in descs] + ["0"]), ", ".join(["%d" % t for _, t in descs] + ["0"]), len(descs)))
    out.append("extern const uint64_t GD_MAIN_ADDR = 0x%xULL;" % (images[0]["load"] + images[0]["main_off"]))
    out.append("extern const int ORDER[] = {%s};\nextern const int NORDER = %d;\nextern const int INIT_IMG[] = {%s};" % (
        ", ".join(["%d" % i for i in order[0]] + ["0"]), len(order[0]), ", ".join(["%d" % i for i in order[1]] + ["0"])))
    out.append("extern const uint64_t OCI[] = {%s};" % ", ".join("0x%xULL, %d" % p for row in (oc or objc_info(images)) for p in row))
    out.append("extern const VMeth GD_VMETH[] = {\n%s\n};\nextern const int GD_NVMETH = %d;" % (",\n".join(   # gobjc.hpp vmeth()
        ["  {%s, %s, %d, %d, %d, %d}" % (json.dumps(c), json.dumps(sl), cm, k, f, v) for c, sl, cm, k, f, v in vmeth or []]
        + ["  {nullptr, nullptr, 0, 0, 0, 0}"]), len(vmeth or [])))
    if not v8:                                                       # a V8 build gets them from gen/v8_marshal.inc
        out.append("extern const VTab GD_VTABS[] = {{nullptr, 0, 0, 0, 0, nullptr}};\nextern const int GD_NVTAB = 0;\n"
                   "extern const NSlot GD_NSLOTS[] = {{nullptr, nullptr, 0, 0, 0, nullptr, nullptr, nullptr}};\nextern const int GD_NNSLOT = 0;")
    return "\n".join(out) + "\n"

def host_cpp(headers: list, v8: bool = False, ui_guard: bool = True, ext_headers: list | None = None) -> str:
    """host.cpp: constants, SDK headers, C headers of extra host libraries (absolute paths) with C linkage, runtime; a V8 build adds the pinned V8 headers first and the generated wrappers + marshalling before the bridge table; each host-library extension's generated header (ext_headers) follows them; ui_guard False defines GD_NO_UI_GUARD (windowed/GPU test runs)."""
    return "\n".join(["/* generated by gdyld.py: host side of the translated program */"]
                     + ["#define %s %s" % kv for kv in RT_CONSTS.items()]
                     + ([] if ui_guard else ["#define GD_NO_UI_GUARD 1"])
                     + (["#include <%s>" % h for h in V8_HEADERS] if v8 else [])
                     + include_lines(headers)
                     + [EXTRA_DECLS, cpu_typedefs(), '#include "gbridge.hpp"']
                     + (['#include "v8_bridges.inc"', '#include "v8_marshal.inc"'] if v8 else [])
                     + ['#include "%s"' % h for h in ext_headers or []]
                     + ['#include "bridge.hpp"', '#include "layout.hpp"', ""])

###############
# build
###############
def run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)

def peak_rss_mb() -> int:
    """This process's peak RSS so far, MB (macOS ru_maxrss is bytes)."""
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2 ** 20)

def run_timed(cmd: list) -> subprocess.CompletedProcess:
    """run() under /usr/bin/time -l; the job's peak RSS (bytes) and wall seconds land in .rss / .secs, not in stderr."""
    r = run(["/usr/bin/time", "-l"] + cmd)
    lines = r.stderr.splitlines()
    cut = next((i for i, ln in enumerate(lines) if TIME_REAL_RE.match(ln)), len(lines))
    tail = "\n".join(lines[cut:])
    rss, real = re.search(r"(\d+)\s+maximum resident set size", tail), TIME_REAL_RE.match(lines[cut]) if cut < len(lines) else None
    out = subprocess.CompletedProcess(cmd, r.returncode, r.stdout, "\n".join(lines[:cut]))
    out.rss, out.secs = int(rss.group(1)) if rss else 0, float(real.group(1)) if real else 0.0
    return out

def cached_compile(cmd: list) -> subprocess.CompletedProcess:
    """Compile one C chunk through the content-addressed object cache (key: flags + source text)."""
    src, obj = cmd[-3], cmd[-1]
    key = hashlib.sha256((" ".join(cmd[:-4]) + "\0" + open(src).read()).encode()).hexdigest()
    hit = os.path.join(OBJ_CACHE, key + ".o")
    if os.path.isfile(hit):
        shutil.copyfile(hit, obj); r = subprocess.CompletedProcess(cmd, 0, "", ""); r.rss, r.secs = 0, 0.0; return r
    r = run_timed(cmd)
    if r.returncode == 0:
        os.makedirs(OBJ_CACHE, exist_ok=True); shutil.copyfile(obj, hit + ".tmp%d" % os.getpid()); os.replace(hit + ".tmp%d" % os.getpid(), hit)
    return r

def v8_host_flags(sdk: str, gen: str) -> list[str]:
    """host.cpp of a V8 build: host libc++ headers, the pinned fork headers in config 3, private members reachable."""
    return ["-isystem", os.path.join(sdk, "usr", "include", "c++", "v1"), "-fno-access-control", "-fno-rtti",
            "-I", os.path.join(V8DIR, "fork", "include"), "-I", gen] + V8_DEFINES

def c_compile_cmd(u: str, extra: list | None = None) -> list[str]:
    """clang command for one image chunk (C, or C++ for a .cc chunk; unwind tables so host exceptions cross it) -> u.o."""
    lang = [CLANGXX, "-arch", "x86_64", "-x", "c++", "-std=c++17"] if u.endswith(".cc") else [CLANG, "-arch", "x86_64"]
    return lang + CHUNK_CFLAGS + PGO_FLAGS + ["-flto=thin"] * LTO + (extra or []) + ["-w", "-funwind-tables", "-c", u, "-o", u + ".o"]

def compile_all(out_dir: str, units: list, link_flags: list, exe: str, host_flags: list | None = None,
                unit_flags: dict | None = None) -> tuple[str, list]:
    """Compile image chunks (C or C++, cached, unwind tables so host exceptions cross them; unit_flags: extra flags per unit) and host.cpp (C++; no libc++ headers unless host_flags bring them) with at most BUILD_JOBS jobs; link. Returns ('' or the error, [(unit, secs, peak RSS)])."""
    cmds = [c_compile_cmd(u, (unit_flags or {}).get(u)) if u.endswith((".c", ".cc")) else
            [CLANGXX, "-arch", "x86_64", "-std=c++17", "-O2", "-w", "-funwind-tables", "-c", u, "-o", u + ".o"] if u.endswith("_eh.cpp") else
            [CLANGXX, "-arch", "x86_64", "-std=c++17", "-nostdinc++", "-O1", "-w", "-I", HERE, "-I", out_dir] + (host_flags or [])
            + ["-x", HOST_LANG, "-c", u, "-o", u + ".o"] for u in units]
    with concurrent.futures.ThreadPoolExecutor(BUILD_JOBS) as pool:
        results = list(pool.map(lambda c: cached_compile(c) if c[-3].endswith((".c", ".cc", "_eh.cpp")) else run_timed(c), cmds))
    stats = [(os.path.basename(c[-3]), r.secs, r.rss) for c, r in zip(cmds, results)]
    bad = [r for r in results if r.returncode]
    if bad: return bad[0].stderr[-3000:], stats
    lk = [CLANGXX, "-arch", "x86_64"] + [u + ".o" for u in units] + link_flags + ["-Wl,-stack_size," + HOST_MAIN_STACK, "-o", exe]
    json.dump({"host": next((c for c in cmds if c[-3].endswith("host.cpp")), []), "link": lk}, open(os.path.join(out_dir, "host_link_cmds.json"), "w"))
    r = run_timed(lk)                                                 # host_link_cmds.json: tools/relink_host.py redoes these two steps
    return (r.stderr[-3000:] if r.returncode else ""), stats + [("link", r.secs, r.rss)]

def translate(exe_path: str, out_dir: str, sdk: str, host_extra: dict | None = None, ui_guard: bool = True) -> dict:
    """Load, link, lift and build one guest program. Returns {'exe', 'report', 'error', 'unsupported', 'classes'}. host_extra: install name -> (header, x86-64 dylib) for host libraries outside the SDK. ui_guard False (an explicit runner option for windowed/GPU tests only): window-server / AppKit / GPU imports and sends get their ordinary bridges. Raises LookupError when the guest needs something the host cannot provide faithfully (reported by the bridge templates or the host linker)."""
    host_extra = host_extra or {}
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    images = load_images(exe_path, frozenset(host_extra))
    if images[0]["main_off"] is None: raise ValueError("%s has no LC_MAIN" % exe_path)
    host_files = images[0]["host_files"]
    v8 = v8_libs(host_files)
    flats, host_binds, report = link(images)
    report += ["host image %s -> %s (x86_64 slice)" % (n, p) for n, p in sorted(host_files.items())]
    gen = os.path.join(out_dir, "gen")
    v8guests = [img["path"] for img in images if any(d[0] == "host" and d[1] in v8 for d in img["resolved"])]
    v8idx, v8log = v8_generate(gen, v8guests, os.path.dirname(host_files[v8[0]])) if v8 else ({}, [])
    report += ["v8: " + ln for ln in v8log]
    files = []
    for k, flat in enumerate(flats):
        files.append(os.path.join(out_dir, "image%d.bin" % k))
        open(files[-1], "wb").write(flat)
    keys = import_keys(host_binds)
    ui = frozenset(keys[n] for _a, n, _ad, _w in host_binds if ui_guard and ui_import(*n))   # by install name: before keys drop it
    exts = [(e, ks) for e, ks in ((e, frozenset(keys[n] for _a, n, _ad, _w in host_binds if e.LIB_RE.search(n[0] or "")))
                                  for e in EXTENSIONS) if ks]       # (extension, the import keys it bridges)
    report.append("UI guard: %s" % ("on (headless)" if ui_guard else "OFF (runner option: window and GPU allowed)"))
    host_binds = [(a, keys[n], ad, w) for a, n, ad, w in host_binds]
    names = sorted(set(keys.values()))
    weak = {n for _a, n, _ad, w in host_binds if w}
    extra = {**{n: (None, p) for n, p in host_files.items()}, **host_extra}
    hdrs, link_flags = framework_headers(sdk, host_libs(images), extra)
    declared, usable = declared_names(sdk, hdrs)
    allp = c_prototypes(sdk, BASE_HEADERS + [h for h in usable if h not in BASE_HEADERS])
    gone = unavailable_names(sdk, BASE_HEADERS + [h for h in usable if h not in BASE_HEADERS])
    declared = declared - {n[1][1:] for n in names if n[1][1:] in gone}  # an import the SDK marks unavailable: resolved by name
    noesc = {n: TRAIL_ATTR_RE.sub("", t.replace(NOESCAPE + " ", "").replace(NOESCAPE, "")) for n, t in allp.items() if NOESCAPE in t}
    protos = allp if v8 else None
    report += gswift.augment(images, [n for _l, n in names], sdk)       # Swift signatures the corpus lacks, from the SDK interfaces
    ext_out = [e.prepare(names, ks, out_dir, sdk) for e, ks in exts]   # (key -> entry, host flags, report) per extension
    report += [ln for _e, _f, rep in ext_out for ln in rep]
    bridge, classes = bridge_hpp(names, declared, {lib: p for lib, (_h, p) in extra.items()}, weak, v8idx, protos, noesc, ui, frozenset(allp),
                                 {k: v for ents, _f, _r in ext_out for k, v in ents.items()})
    link_flags += ["-Wl,-U," + n[1] for n in sorted(weak) if n[1] in classes.get("prototype", []) + classes.get("suffixed", [])]
    link_flags += HOST_LINK
    link_flags += ["-fprofile-instr-generate"] * (PGO == "generate") + ["-flto=thin", "-Wl,-cache_path_lto," + os.path.join(OBJ_CACHE, "lto")] * LTO
    link_flags += ["-Wl,-mllvm," + f for k, f in enumerate(CHUNK_CFLAGS[1:], 1) if CHUNK_CFLAGS[k - 1] == "-mllvm"] * LTO   # ThinLTO generates code at link time
    sw_flags, sw_report = gswift.prepare(images, names, out_dir, sdk, declared | {n[1:] for n in SPECIAL}, weak)   # swift_gen.hpp
    link_flags += sw_flags; report += sw_report
    order = init_order(images)
    inits = [a for i in order for a in initializers(images[i], flats[i])]
    init_img = [i for i in order for _a in initializers(images[i], flats[i])]
    oc = objc_info(images)
    tlvs = [t for t in (tlv_info(img) for img in images) if t]
    units, unsupported, ninsn, nres, plans = [], [], 0, 0, []
    t_lift = time.time()
    lifts, lstats = lift_images(images, out_dir, [host_gots_of(img, host_binds) for img in images])
    report.append("lift: %.0f s, %s" % (time.time() - t_lift, lstats))
    for k, (img, li, (why, xd, xg, rets, keep)) in enumerate(zip(images, lifts, abi_plan(images, lifts))):
        units += li["units"]; ninsn += li["instructions"]; nres += li["resumable"]
        plans.append((li["units"], flag_plan(li["flags"], li["flag_readers_taken"], li["flag_extra"], host=li["flag_host"]), (not why, rets, xd, xg, keep)))
        report.append("register contract %s: %s" % (os.path.basename(img["path"]), "full sync at every call (%s)" % why if why else
                                                     "AAPCS64 (callee-saved registers stay in locals; calls store arguments, returns results; "
                                                     "full stores at calls into %d functions and %d import slots outside the contract, full returns "
                                                     "from %d)" % (len(xd), len(xg), len(rets))))
        unsupported += [(os.path.basename(img["path"]), hex(u[0]), u[1]) for u in li["unsupported"]]
        report.append("lift %s: %d instructions, %d chunks, %d extra entry points, NZCV: %s, peak RSS %d MB" % (
            os.path.basename(img["path"]), li["instructions"], len(li["units"]), li["entries"],
            "unplaceable (stores everywhere: %s)" % plans[-1][1][3] if plans[-1][1][0] else "%d functions or entry points read it at entry, %d return it" % (
                len(plans[-1][1][1]), len(plans[-1][1][2])), peak_rss_mb()))
        if slow := undecoded(img, li["units"]):
            shown = ["%s%s" % (n, " (optnone)" if o else "") for n, o in slow]  # not `names`: the import list below
            report.append("WARNING: %s: %d function%s with an undecoded br run slower (every instruction a branch target, state in "
                          "memory): %s" % (os.path.basename(img["path"]), len(slow), "" if len(slow) == 1 else "s",
                                           ", ".join(shown[:8]) + (", ..." if len(shown) > 8 else "")))
    proto = frozenset(classes.get("prototype", []))
    leaf = frozenset(j for j, n in enumerate(names) if not n[0] and n[1] in LEAF_IMPORTS and n[1] in proto)
    slot = {n: j for j, n in enumerate(names)}
    direct = [{a - img["load"] + img["vm_base"]: (IMPORT_BASE + slot[n] * IMP_SLOT, n[1]) for a, n, ad, _w in host_binds
               if img["load"] <= a < img["load"] + img["vm_size"] and not ad and slot[n] in leaf and n[1] in LEAF_DIRECT} for img in images]
    everywhere, unit_flags = any(p[0] for _u, p, _a in plans), {}
    msg_slots = {MSG_SENDS[n[1]]: IMPORT_BASE + j * IMP_SLOT for j, n in enumerate(names) if n[1] in MSG_SENDS}   # the slots gbridge binds them to
    unwinder = any(n in img["exports"] for img in images for n in GUEST_UNWINDER)   # it reads saved registers off the guest stack
    for k, (us, (_e, readers, returners, _why), (abi, rets, xd, xg, keep)) in enumerate(plans):
        hdr = os.path.abspath(os.path.join(out_dir, "gd_flags_%d.h" % k))
        text = flags_header(everywhere, set() if everywhere else readers, set() if everywhere else returners, msg_slots, abi, rets, xd, xg,
                            direct[k], abi and not unwinder, keep, not any(li["entries"] for li in lifts))
        open(hdr, "w").write(text)
        unit_flags.update({u: ["-include", hdr, "-DGDF_H=%s" % hashlib.sha256(text.encode()).hexdigest()[:16]] for u in us if u.endswith((".c", ".cc"))})
    report.append("NZCV stores at calls and returns: %s" % ("everywhere" if everywhere else "only into flag-reading callees and out of flag-returning ones"))
    units.append(os.path.join(out_dir, "gd_disp.c"))
    open(units[-1], "w").write(dispatch_text(images, len(names), leaf))
    open(os.path.join(out_dir, "bridge.hpp"), "w").write(bridge)
    vmeth = objc_variadics(sdk, [h for h in hdrs if not os.path.isabs(h)]) if LIBOBJC in host_libs(images) else []   # framework umbrellas
    open(os.path.join(out_dir, "layout.hpp"), "w").write(layout_hpp(images, files, host_binds, names, inits, tlvs, bool(v8),
                                                                    (order, init_img), oc, vmeth))
    host_hdrs = BASE_HEADERS + [h for h in usable if h not in BASE_HEADERS]
    fp = objc_fnparams(sdk, [h for h in usable if not os.path.isabs(h) and h not in BASE_HEADERS]) if LIBOBJC in host_libs(images) else []
    vecs = objc_vecrecs(sdk, hdrs) if LIBOBJC in host_libs(images) else []   # every framework umbrella and extra host header
    ok = compiling_types(sdk, host_hdrs, sorted({r[4] for r in fp})) if fp else set()
    open(os.path.join(out_dir, "gdyld_gen.hpp"), "w").write(gen_hpp(*dl_rows(images), [r for r in fp if r[4] in ok], vecs))
    report.append("objc: %d guest classes, %d categories, %d protocols, %d selector refs, %d variadic host methods, %d typed ^? "
                  "parameters (%d dropped: type not spellable in host.cpp)" % (*tuple(sum(row[j][1] for row in oc) for j in range(4)), len(vmeth),
                                                                               sum(r[4] in ok for r in fp), sum(r[4] not in ok for r in fp)))
    units.append(os.path.join(out_dir, "host.cpp"))
    open(units[-1], "w").write(host_cpp(BASE_HEADERS + [h for h in usable if h not in BASE_HEADERS], bool(v8), ui_guard, [e.HEADER for e, _ks in exts]))
    exe = os.path.join(out_dir, "translated")
    for n, p in sorted(host_files.items()):                            # dyld resolves these next to the translated executable
        if n.startswith(("@loader_path/", "@executable_path/")):
            ln = os.path.join(out_dir, n.split("/", 1)[1])
            if os.path.lexists(ln): os.remove(ln)
            os.symlink(p, ln)
    t1 = time.time()
    err, stats = compile_all(out_dir, units, link_flags, exe, (v8_host_flags(sdk, gen) if v8 else []) + [f for _e, fl, _r in ext_out for f in fl] or None, unit_flags)
    json.dump(stats, open(os.path.join(out_dir, "compile_stats.json"), "w"))
    if link_errors(err): raise LookupError("gdyld link: " + link_errors(err))
    report.append("init order: %s | %d initializers | TLV images %d | instructions lifted %d | resumable functions %d"
                  % ([os.path.basename(images[i]["path"]) for i in order], len(inits), len(tlvs), ninsn, nres))
    return {"exe": exe, "report": report, "error": err, "unsupported": unsupported, "classes": classes, "stats": stats,
            "lift_secs": t1 - t0, "build_secs": time.time() - t1, "host_files": host_files, "units": len(units)}
