"""Swift bed: every tests/swift/s*.swift (or the names given) is built with swiftc -O for x86_64 (native oracle, run 3
times, must be stable) and arm64 (target macOS 13, first-line '// swiftc: ...' flags); gswift's signature database is
rebuilt over its corpus first. gdyld translates the arm64 build on the host Swift runtime and overlays; its stdout + exit
must equal the oracle's (MATCH). Full outputs land in build/<name>/."""
###############
# imports and constants
###############
from __future__ import annotations
import difflib, glob, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld  # noqa: E402  (library under test)
import gswift  # noqa: E402

SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
RUN_TIMEOUT = 120                                              # seconds per run
SRCS = sorted(glob.glob(os.path.join(HERE, "s*.swift")))
NAMES = sys.argv[1:] or [os.path.basename(p)[:-6] for p in SRCS]

###############
# functions
###############
def build(name: str, arch: str, out: str) -> tuple[str, str]:
    """(executable, error text) for one arch."""
    src = os.path.join(HERE, name + ".swift")
    d = os.path.join(out, arch)
    os.makedirs(d, exist_ok=True)
    exe = os.path.join(d, name)
    r = subprocess.run(["xcrun", "swiftc", "-O", "-target", gswift.TARGET % arch, "-sdk", SDK] + gswift.swiftc_flags(src) + [src, "-o", exe],
                       capture_output=True, text=True, timeout=900)
    return exe, r.stderr[-1500:] if r.returncode else ""

def run_exe(exe: str, env: dict | None = None) -> tuple[int, str, str]:
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=RUN_TIMEOUT, errors="replace", cwd=os.path.dirname(exe),
                           env=dict(os.environ, **(env or {})))
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
    if len({(r[0], r[1]) for r in oracle}) != 1: return "UNSTABLE-ORACLE exits %s" % [r[0] for r in oracle]
    t0 = time.time()
    try:
        res = gdyld.translate(arm, os.path.join(out, "gdyld"), SDK)
    except Exception as e:                                    # the translator refused the program: that is the verdict
        return "TRANSLATE-FAIL %s: %s" % (type(e).__name__, str(e)[-2000:])
    if res["error"]: return "TRANSLATE-FAIL build error: %s" % res["error"][-2500:]
    sw = next((ln for ln in res["report"] if ln.startswith("swift:")), "")
    info = "gdyld %.0f s, %s, classes %s, unsupported insns %d" % (time.time() - t0, sw, {k: len(v) for k, v in sorted(res["classes"].items())},
                                                                  len(res["unsupported"]))
    got = run_exe(res["exe"], {"GDYLD_TRACE_IMPORTS": "1"})          # stderr ends with the imports called
    save(out, "translated", got)
    open(os.path.join(out, "imports_called.txt"), "w").write("".join(ln + "\n" for ln in got[2].splitlines() if ln.startswith("import-trace ")))
    if (got[0], got[1]) == (oracle[0][0], oracle[0][1]):
        return "MATCH (exit %d, %d lines) | %s" % (got[0], len(got[1].splitlines()), info)
    diff = "".join(difflib.unified_diff(oracle[0][1].splitlines(True), got[1].splitlines(True), "native", "translated"))
    return "MISMATCH exit native %d translated %d | %s\n%s\n  translated stderr tail: %s" % (
        oracle[0][0], got[0], info, diff[-3000:], got[2].strip()[-1500:])

###############
# run
###############
db = gswift.build_sigdb(gswift.CORPUS, SDK, gswift.SIGDB)
print("signature db: %d sources, %d functions, %d witnesses, conflicts %s" % (len(db["sources"]), len(db["funcs"]), len(db["witness"]), db["conflicts"]))
results = {}
for n in NAMES:
    t = time.time()
    results[n] = verdict(n)
    print("== %s (%.0f s): %s" % (n, time.time() - t, results[n]), flush=True)
print("summary: %s" % {n: v.split()[0] for n, v in results.items()})
