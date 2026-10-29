"""Adversarial Swift bed: each tests/swift_adv/a*.swift (or the names given) built for x86_64 (native oracle, run 3 times) and
arm64, the arm64 build translated by gdyld on the lane's existing signature database (not rebuilt: these sources are not
in its corpus); MATCH when stdout + exit equal the oracle's. A companion <name>.m / <name>.h is compiled into the image."""
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
CORPUS_MODE = "--corpus" in sys.argv                          # these sources join gswift's corpus (best case for the bridges)
ARGS = [a for a in sys.argv[1:] if a != "--corpus"]
NAMES = ARGS or [os.path.basename(p)[:-6] for p in sorted(glob.glob(os.path.join(HERE, "a*.swift")))]
BUILD = os.path.join(HERE, "build_corpus" if CORPUS_MODE else "build")
ADV_SIGDB = os.path.join(HERE, "swift_sigs_adv.json")
INSN_BOUND = {"a24_vwt_loop": 10}                             # test -> max translated / native instructions retired (whole process)

###############
# functions
###############
def objc_part(name: str, arch: str, d: str) -> tuple[list[str], str]:
    """(swiftc extra args, error text) for a companion ObjC file compiled into the same image."""
    m = os.path.join(HERE, name + ".m")
    if not os.path.isfile(m): return [], ""
    o = os.path.join(d, name + "_objc.o")
    r = subprocess.run(["clang", "-isysroot", SDK, "-arch", arch, "-mmacosx-version-min=13", "-fobjc-arc", "-O2", "-c", m, "-o", o],
                       capture_output=True, text=True, timeout=300)
    return ["-import-objc-header", os.path.join(HERE, name + ".h"), o], r.stderr[-1500:] if r.returncode else ""

def build(name: str, arch: str, out: str) -> tuple[str, str]:
    """(executable, error text) for one arch."""
    src = os.path.join(HERE, name + ".swift")
    d = os.path.join(out, arch)
    os.makedirs(d, exist_ok=True)
    exe = os.path.join(d, name)
    extra, err = objc_part(name, arch, d)
    if err: return exe, err
    r = subprocess.run(["xcrun", "swiftc", "-O", "-target", gswift.TARGET % arch, "-sdk", SDK] + gswift.swiftc_flags(src) + extra + [src, "-o", exe],
                       capture_output=True, text=True, timeout=900)
    return exe, r.stderr[-1500:] if r.returncode else ""

def run_exe(exe: str) -> tuple[int, str, str]:
    """(exit, stdout, stderr) of one bounded run."""
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=RUN_TIMEOUT, errors="replace", cwd=os.path.dirname(exe))
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -999, "", "TIMEOUT"

def insns(exe: str) -> int:
    """Instructions retired by one run (/usr/bin/time -l), the fewer of two runs; 0 when the count is missing."""
    got = []
    for _ in range(2):
        r = subprocess.run(["/usr/bin/time", "-l", exe], capture_output=True, text=True, timeout=RUN_TIMEOUT, errors="replace", cwd=os.path.dirname(exe))
        got += [int(l.split()[0]) for l in r.stderr.splitlines() if l.strip().endswith("instructions retired")]
    return min(got) if got else 0

def save(out: str, tag: str, r: tuple[int, str, str]) -> None:
    open(os.path.join(out, tag + ".txt"), "w").write("exit %d\n--- stdout\n%s--- stderr\n%s" % r)

def verdict(name: str) -> str:
    """MATCH / MISMATCH (with the stdout diff and the translated stderr tail) / BUILD-FAIL / TRANSLATE-FAIL."""
    out = os.path.join(BUILD, name)
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
    info = "gdyld %.0f s, %s, unsupported insns %d" % (time.time() - t0, sw, len(res["unsupported"]))
    got = run_exe(res["exe"])
    save(out, "translated", got)
    if (got[0], got[1]) == (oracle[0][0], oracle[0][1]) and name in INSN_BOUND:
        nat, tr = insns(x86), insns(res["exe"])
        ratio = tr / nat if nat and tr else float("inf")
        if ratio > INSN_BOUND[name]:
            return "SLOW translated %d / native %d instructions = %.1fx, bound %dx | %s" % (tr, nat, ratio, INSN_BOUND[name], info)
        info += ", instructions %.1fx native (bound %dx)" % (ratio, INSN_BOUND[name])
    if (got[0], got[1]) == (oracle[0][0], oracle[0][1]):
        return "MATCH (exit %d, %d lines) | %s" % (got[0], len(got[1].splitlines()), info)
    diff = "".join(difflib.unified_diff(oracle[0][1].splitlines(True), got[1].splitlines(True), "native", "translated"))
    return "MISMATCH exit native %d translated %d | %s\n%s\n  translated stderr tail: %s" % (
        oracle[0][0], got[0], info, diff[-3000:], got[2].strip()[-1200:])

###############
# run
###############
if CORPUS_MODE:
    ADV = sorted(p for p in glob.glob(os.path.join(HERE, "a*.swift")) if not os.path.isfile(p[:-6] + ".m"))   # mixed ObjC needs its header
    full = gswift.build_sigdb(gswift.CORPUS + ADV, SDK, ADV_SIGDB)
    drop = set(filter(None, os.environ.get("ADV_DROP_WITNESS", "").split(",")))   # requirements to leave unbridged (loud path)
    db = {**full, "witness": {k: v for k, v in full["witness"].items() if k not in drop}}
    gswift.sigdb = lambda path=ADV_SIGDB: db                  # gdyld reads gswift.sigdb() at translate time
    print("corpus mode: %d sources, %d functions, %d witnesses, conflicts %s" % (len(db["sources"]), len(db["funcs"]), len(db["witness"]), db["conflicts"]))
results = {}
for n in NAMES:
    t = time.time()
    results[n] = verdict(n)
    print("== %s (%.0f s): %s" % (n, time.time() - t, results[n]), flush=True)
print("summary: %s" % {n: v.split()[0] for n, v in results.items()})
