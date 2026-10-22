"""Swift import binding bed (C guests, so the exact imports are under control): 'weak' weak-imports a Swift-mangled function
the host lacks and must see NULL; 'twins' has the main image and a guest dylib import the same Swift-mangled data and
function symbols from two different universal host dylibs and must see each library's own definition. Both are translated
with gswift's signature database plus signatures for these symbols; MATCH when stdout + exit equal the x86_64 oracle's."""
###############
# imports and constants
###############
from __future__ import annotations
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld  # noqa: E402  (library under test)
import gswift  # noqa: E402

SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
OUT = os.path.join(HERE, "build_link")
RUN_TIMEOUT = 120                                              # seconds per run
FN = "_$s4Twin2fnSiyF"                                         # Swift-shaped: a function Twin.fn() -> Int
DATA = "_$s4Twin3TagVN"                                        # Swift-shaped: type metadata (data by mangling kind)
WEAK = "_$s4Fake5probeSiyF"                                    # absent from every host library
EXTRA_SIGS = {FN: {"cc": "swift", "ret": ["i64"], "rx": "", "params": []}, WEAK: {"cc": "swift", "ret": ["i64"], "rx": "", "params": []}}
TWIN_LIB = 'long tw_data __asm("%s") = %%d; long tw_fn(void) __asm("%s"); long tw_fn(void) { return %%d; }\n' % (DATA, FN)
TWIN_USE = 'extern long tw_data __asm("%s"); extern long tw_fn(void) __asm("%s");\n' % (DATA, FN)
SRC = {
    "libtwa.c": TWIN_LIB % (1, 10),
    "libtwb.c": TWIN_LIB % (2, 20),
    "libg.c": TWIN_USE + "long g_data(void) { return tw_data; }\nlong g_fn(void) { return tw_fn(); }\n",
    "twins.c": '#include <stdio.h>\n' + TWIN_USE + 'long g_data(void); long g_fn(void);\n'
               'int main(void) { printf("main %ld %ld | libg %ld %ld\\n", tw_data, tw_fn(), g_data(), g_fn()); return 0; }\n',
    "weak.c": '#include <stdio.h>\nextern long probe(void) __asm("%s") __attribute__((weak_import));\n'
              'int main(void) { printf("probe %%s\\n", probe ? "present" : "absent"); if (probe) printf("value %%ld\\n", probe()); return 0; }\n' % WEAK,
}

###############
# functions
###############
def cc(args: list[str], cwd: str) -> str:
    """clang with the SDK; error text or ''."""
    r = subprocess.run(["clang", "-isysroot", SDK, "-mmacosx-version-min=13", "-O1", "-w"] + args, capture_output=True, text=True, cwd=cwd, timeout=300)
    return r.stderr[-1500:] if r.returncode else ""

def build(arch: str) -> str:
    """Both programs for one arch in OUT/<arch>; the twin libraries are universal (host images), libg is thin (a guest image)."""
    d = os.path.join(OUT, arch)
    os.makedirs(d, exist_ok=True)
    for n, s in SRC.items(): open(os.path.join(d, n), "w").write(s)
    errs = [cc(["-arch", "arm64", "-arch", "x86_64", "-dynamiclib", "-install_name", "@rpath/%s.dylib" % lib, lib + ".c", "-o", lib + ".dylib"], d)
            for lib in ("libtwa", "libtwb")]                  # @rpath: the translated executable finds them through gdyld's -rpath
    errs.append(cc(["-arch", arch, "-dynamiclib", "-install_name", "@rpath/libg.dylib", "-Wl,-rpath,@loader_path", "libg.c", "libtwb.dylib", "-o", "libg.dylib"], d))
    errs.append(cc(["-arch", arch, "twins.c", "libtwa.dylib", "libg.dylib", "-Wl,-rpath,@executable_path", "-o", "twins"], d))
    errs.append(cc(["-arch", arch, "weak.c", "-Wl,-U," + WEAK, "-o", "weak"], d))
    return "".join(errs)

def run_exe(exe: str) -> tuple[int, str, str]:
    """(exit, stdout, stderr) of one bounded run."""
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=RUN_TIMEOUT, errors="replace", cwd=os.path.dirname(exe))
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -999, "", "TIMEOUT"

def entries(gd: str, names: list[str]) -> list[str]:
    """The generated ENT rows of the given symbols (bridge.hpp)."""
    return [ln.strip() for ln in open(os.path.join(gd, "bridge.hpp")) if any('"%s"' % n in ln for n in names) and ln.lstrip().startswith(("GD_", "{"))]

def verdict(name: str) -> str:
    """MATCH / MISMATCH / TRANSLATE-FAIL for one program, with its generated entries."""
    want = run_exe(os.path.join(OUT, "x86_64", name))
    gd = os.path.join(OUT, "arm64", name + "_gdyld")
    try:
        res = gdyld.translate(os.path.join(OUT, "arm64", name), gd, SDK)
    except Exception as e:                                    # the translator refused the program: that is the verdict
        return "TRANSLATE-FAIL %s: %s" % (type(e).__name__, str(e)[-1500:])
    if res["error"]: return "TRANSLATE-FAIL build error: %s" % res["error"][-1500:]
    got = run_exe(res["exe"])
    tag = "MATCH" if (got[0], got[1]) == (want[0], want[1]) else "MISMATCH"
    return "%s native %r translated %r stderr %r | entries %s" % (tag, (want[0], want[1]), (got[0], got[1]), got[2][-300:], entries(gd, [FN, DATA, WEAK]))

###############
# run
###############
errors = build("x86_64") + build("arm64")
print("build errors: %r" % errors)
base = gswift.sigdb()
db = {**base, "funcs": {**base["funcs"], **EXTRA_SIGS}}
gswift.sigdb = lambda path=gswift.SIGDB: db                   # gdyld reads gswift.sigdb() at translate time
results = {n: verdict(n) for n in ("weak", "twins")}
for n, v in results.items(): print("== %s: %s" % (n, v))
print("summary: %s" % {n: v.split()[0] for n, v in results.items()})
