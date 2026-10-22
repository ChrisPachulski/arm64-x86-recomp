"""Objective-C / blocks bed: every tests/objc/t*.m|.c (or the names given) is built for x86_64 (native oracle, run 3 times,
must be stable) and arm64 (headless Foundation, ARC unless the first line says // flags: ...); a <name>.lib.m next to it is
built as the guest dylib lib<name>.dylib and linked. gdyld translates the arm64 build; its stdout + exit must equal the
oracle's (MATCH), or a LOUD test must stop with its text. Full outputs land in build/<name>/."""
###############
# imports and constants
###############
from __future__ import annotations
import difflib, glob, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld  # noqa: E402  (library under test)

SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
CC = ["clang", "-isysroot", SDK, "-O1", "-w", "-framework", "Foundation"]
RUN_TIMEOUT = 120                                              # seconds per run
LOUD = {"t18_loud_packed": "packed struct", "t19_loud_ldbl_ptr": "pointer to a long double",
        "t20_loud_struct_fnptr": "function-pointer field",
        "t23_loud_simd": "empty type encoding (a SIMD vector)"}     # test -> text the translated stderr must carry
SRCS = sorted(p for p in glob.glob(os.path.join(HERE, "t*.[mc]")) if not p.endswith(".lib.m"))
NAMES = sys.argv[1:] or [os.path.basename(p)[:-2] for p in SRCS]

###############
# functions
###############
def flags_of(src: str) -> list[str]:
    """ARC for Objective-C unless the first line is '// flags: ...'."""
    first = open(src).readline()
    return first.split("flags:", 1)[1].split() if "flags:" in first else (["-fobjc-arc"] if src.endswith(".m") else [])

def build(name: str, arch: str, out: str) -> tuple[str, str]:
    """(executable, error text) for one arch; the optional .lib.m becomes @rpath/lib<name>.dylib beside it."""
    src = next(p for p in SRCS if os.path.basename(p)[:-2] == name)
    d = os.path.join(out, arch)
    os.makedirs(d, exist_ok=True)
    lib, extra = src[:-2] + ".lib.m", []
    if os.path.isfile(lib):
        dl = os.path.join(d, "lib%s.dylib" % name)
        r = subprocess.run(CC + flags_of(lib) + ["-arch", arch, "-dynamiclib", "-install_name", "@rpath/lib%s.dylib" % name, lib, "-o", dl],
                           capture_output=True, text=True)
        if r.returncode: return "", r.stderr[-1500:]
        extra = [dl, "-Wl,-rpath,@executable_path"]
    exe = os.path.join(d, name)
    r = subprocess.run(CC + flags_of(src) + ["-arch", arch, src] + extra + ["-o", exe], capture_output=True, text=True)
    return exe, r.stderr[-1500:] if r.returncode else ""

def run_exe(exe: str) -> tuple[int, str, str]:
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=RUN_TIMEOUT, errors="replace", cwd=os.path.dirname(exe))
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -999, "", "TIMEOUT"

def save(out: str, tag: str, r: tuple[int, str, str]) -> None:
    open(os.path.join(out, tag + ".txt"), "w").write("exit %d\n--- stdout\n%s--- stderr\n%s" % r)

def verdict(name: str) -> str:
    out = os.path.join(HERE, "build", name)
    x86, ex = build(name, "x86_64", out)
    arm, ea = build(name, "arm64", out)
    if ex or ea: return "BUILD-FAIL %s" % (ex + ea)
    oracle = [run_exe(x86) for _ in range(3)]
    for i, r in enumerate(oracle): save(out, "native_%d" % i, r)
    if name not in LOUD and len({(r[0], r[1]) for r in oracle}) != 1:      # a LOUD verdict never reads the oracle (t18's native output is undefined)
        return "UNSTABLE-ORACLE exits %s" % [r[0] for r in oracle]
    t0 = time.time()
    try:
        res = gdyld.translate(arm, os.path.join(out, "gdyld"), SDK)
    except Exception as e:                                    # the translator refused the program: that is the verdict
        return "TRANSLATE-FAIL %s: %s" % (type(e).__name__, str(e)[-2000:])
    if res["error"]: return "TRANSLATE-FAIL build error: %s" % res["error"][-2500:]
    objc = next((ln for ln in res["report"] if ln.startswith("objc:")), "")
    info = "gdyld %.0f s, %s, classes %s, unsupported insns %d" % (time.time() - t0, objc, {k: len(v) for k, v in sorted(res["classes"].items())},
                                                                  len(res["unsupported"]))
    got = run_exe(res["exe"])
    save(out, "translated", got)
    if name in LOUD:
        ok = got[0] != 0 and LOUD[name] in got[2]
        return "%s exit %d | %s\n  translated stderr tail: %s" % ("LOUD-OK" if ok else "LOUD-MISSING", got[0], info, got[2].strip()[-600:])
    if (got[0], got[1]) == (oracle[0][0], oracle[0][1]):
        return "MATCH (exit %d, %d lines) | %s" % (got[0], len(got[1].splitlines()), info)
    diff = "".join(difflib.unified_diff(oracle[0][1].splitlines(True), got[1].splitlines(True), "native", "translated"))
    return "MISMATCH exit native %d translated %d | %s\n%s\n  translated stderr tail: %s" % (
        oracle[0][0], got[0], info, diff[-3000:], got[2].strip()[-1500:])

###############
# run
###############
results = {}
for n in NAMES:
    t = time.time()
    results[n] = verdict(n)
    print("== %s (%.0f s): %s" % (n, time.time() - t, results[n]), flush=True)
print("summary: %s" % {n: v.split()[0] for n, v in results.items()})
