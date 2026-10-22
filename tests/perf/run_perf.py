"""Speed bed for translated code: builds every tests/perf benchmark at -O2 for x86_64 (native) and arm64, translates the
arm64 build with sbt/gdyld.py, checks that the translated stdout equals the native one, times the kernel (PERF_NS on
stderr) RUNS times on each side, prints median, spread and slowdown per benchmark (plus the ratio to results/baseline.json
when present) and saves results/<git label>.json."""
###############
# imports and constants
###############
from __future__ import annotations
import hashlib, json, math, os, statistics, subprocess, sys, time

PERF = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(PERF))
SBT = os.path.join(LANE, "sbt")
sys.path.insert(0, SBT)
import gdyld  # noqa: E402  (lane translator under test)

BUILD = os.path.join(PERF, "build")
RESULTS = os.path.join(PERF, "results")
RUNS = 5                                                               # timed runs per side; the median is reported
RUN_TIMEOUT = 600                                                      # s per program run
BENCH = ["b01_int.c", "b02_nbody.c", "b03_spectral.c", "b04_matmul.c", "b05_vecmem.c", "b06_dot.c", "b07_filter.c",
         "b08_sort.cpp", "b09_umap.cpp", "b10_string.cpp", "b11_vcall.cpp", "b12_libc.c", "b13_exc.cpp", "b14_threads.cpp",
         "b15_objc.m", "b16_calls.c", "b17_interp.c", "b18_alias.c"]
EXTRA_FLAGS = {"b18_alias.c": ["-fno-strict-aliasing"]}               # source-level aliasing made legal on both arches
ONLY: tuple = ()                                                       # empty: every benchmark
PERF_RE = "PERF_NS "

###############
# functions
###############
def run(cmd: list[str], cwd: str | None = None, timeout: float = 900) -> subprocess.CompletedProcess:
    """Run a command, capturing text output."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout)

def compile_cmd(src: str, arch: str, sdk: str, out: str) -> list[str]:
    """clang / clang++ at -O2 for one arch; C++ against the SDK's libc++ headers, ObjC with Foundation."""
    base = ["-O2", "-isysroot", sdk, "-arch", arch, "-I", PERF] + EXTRA_FLAGS.get(src, []) + ["-o", out, os.path.join(PERF, src)]
    if src.endswith(".cpp"):
        return ["/usr/bin/clang++", "-std=c++17", "-nostdinc++", "-isystem", sdk + "/usr/include/c++/v1"] + base
    if src.endswith(".m"):
        return ["/usr/bin/clang", "-framework", "Foundation"] + base
    return ["/usr/bin/clang"] + base

def build(src: str, arch: str, sdk: str) -> tuple[str, str]:
    """(executable, error text or '') for one benchmark and arch."""
    name = os.path.splitext(src)[0]
    out = os.path.join(BUILD, arch, name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = run(compile_cmd(src, arch, sdk, out))
    return out, (r.stderr.strip()[-600:] if r.returncode else "")

def timed_run(exe: str) -> tuple[str, float, float, str]:
    """(stdout + exit line, kernel seconds from PERF_NS or nan, process wall seconds, stderr tail) of one run."""
    t0 = time.time()
    try:
        r = run([exe], cwd=os.path.dirname(exe), timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "TIMEOUT\n", math.nan, time.time() - t0, "timeout"
    wall = time.time() - t0
    ns = [int(ln.split()[1]) for ln in r.stderr.splitlines() if ln.startswith(PERF_RE)]
    return r.stdout + "EXIT %d\n" % r.returncode, (ns[-1] / 1e9 if ns else math.nan), wall, r.stderr.strip()[-400:]

def series(exe: str, n: int) -> dict:
    """One untimed warm-up run (a new binary's first launches are slow), then n runs: outputs seen, kernel and wall seconds lists, last stderr."""
    rs = [timed_run(exe) for _ in range(n + 1)][1:]
    return {"outs": sorted({r[0] for r in rs}), "kernel": [r[1] for r in rs], "wall": [r[2] for r in rs], "err": rs[-1][3]}

def spread(xs: list[float]) -> float:
    """(max - min) / median, as a fraction."""
    m = statistics.median(xs)
    return (max(xs) - min(xs)) / m if m else math.nan

def label() -> str:
    """Short git commit of the lane plus '+<hash of the sbt/ diff>' when sbt/ has uncommitted changes."""
    head = run(["git", "-C", LANE, "rev-parse", "--short", "HEAD"]).stdout.strip() or "nogit"
    diff = run(["git", "-C", LANE, "diff", "HEAD", "--", "sbt"]).stdout
    return head + ("+" + hashlib.sha1(diff.encode()).hexdigest()[:8] if diff else "")

def bench(src: str, sdk: str) -> dict:
    """Build, run native, translate, run translated; timings and the match verdict for one benchmark."""
    name = os.path.splitext(src)[0]
    (nexe, nerr), (aexe, aerr) = build(src, "x86_64", sdk), build(src, "arm64", sdk)
    if nerr or aerr: return {"name": name, "status": "BUILD FAIL: " + (nerr or aerr)}
    nat = series(nexe, RUNS)
    t0 = time.time()
    try:
        res = gdyld.translate(aexe, os.path.join(BUILD, "gdyld", name), sdk)
    except (OSError, ValueError, LookupError, NotImplementedError, RuntimeError, MemoryError) as e:
        return {"name": name, "status": "TRANSLATE BLOCKED: %s: %s" % (type(e).__name__, str(e)[:300])}
    if res["error"]: return {"name": name, "status": "TRANSLATED BUILD FAIL: " + res["error"][-400:]}
    secs = time.time() - t0
    tr = series(res["exe"], RUNS)
    ok = len(nat["outs"]) == 1 and tr["outs"] == nat["outs"] and "EXIT 0" in nat["outs"][0]
    return {"name": name, "status": "MATCH" if ok else "DIFF", "native": nat, "translated": tr, "translate_secs": secs,
            "exe_mb": os.path.getsize(res["exe"]) / 2 ** 20,
            "nzcv": [ln for ln in res["report"] if "NZCV" in ln]}

def row(r: dict, base: dict) -> str:
    """One table line: native and translated kernel medians (ms) with spread, slowdown, ratio to the baseline run."""
    if "native" not in r: return "%-12s %s" % (r["name"], r["status"])
    nm, tm = statistics.median(r["native"]["kernel"]), statistics.median(r["translated"]["kernel"])
    b = base.get(r["name"])
    vs = "%6.2fx" % (b / tm) if b and tm == tm else "     -"
    detail = "" if r["status"] == "MATCH" else "  native %r translated %r err %r" % (
        r["native"]["outs"][:1], r["translated"]["outs"][:1], r["translated"]["err"][-200:])
    return "%-12s %-5s native %9.1f ms (+-%4.1f%%)  translated %10.1f ms (+-%4.1f%%)  slowdown %7.2fx  speedup-vs-base %s%s" % (
        r["name"], r["status"], nm * 1e3, 50 * spread(r["native"]["kernel"]), tm * 1e3, 50 * spread(r["translated"]["kernel"]),
        tm / nm, vs, detail)

def baseline() -> dict:
    """Benchmark -> translated kernel median (s) of results/baseline.json, {} when absent."""
    p = os.path.join(RESULTS, "baseline.json")
    if not os.path.isfile(p): return {}
    return {r["name"]: statistics.median(r["translated"]["kernel"]) for r in json.load(open(p))["results"] if "translated" in r}

def geomean(results: list[dict]) -> float:
    """Geometric mean of the slowdowns of the matching benchmarks."""
    xs = [statistics.median(r["translated"]["kernel"]) / statistics.median(r["native"]["kernel"]) for r in results if r["status"] == "MATCH"]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else math.nan

###############
# run
###############
SDK = run(["xcrun", "--show-sdk-path"]).stdout.strip()
LABEL = label()
T0 = time.time()
RES = [bench(s, SDK) for s in BENCH if not ONLY or os.path.splitext(s)[0] in ONLY]
os.makedirs(RESULTS, exist_ok=True)
json.dump({"label": LABEL, "runs": RUNS, "results": RES}, open(os.path.join(RESULTS, LABEL + ".json"), "w"), indent=1)
BASE = baseline()
print("label %s, %d runs per side, kernel time median (+- half the max-min spread)" % (LABEL, RUNS))
for r in RES: print(row(r, BASE))
print("NZCV stored at every call and return (a flag use gdyld could not place) in: %s" % (
    [r["name"] for r in RES if any(ln.endswith("everywhere") for ln in r.get("nzcv", []))] or "none"))
print("matching %d/%d, geomean slowdown %.2fx, translate secs total %.0f, bed %.0f s" % (
    sum(r["status"] == "MATCH" for r in RES), len(RES), geomean(RES), sum(r.get("translate_secs", 0) for r in RES), time.time() - T0))
