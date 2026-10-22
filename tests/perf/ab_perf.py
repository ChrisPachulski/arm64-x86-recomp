"""Interleaved A/B speed check of two translators on tests/perf benchmarks: builds each benchmark for x86_64 and arm64 (the
bed's flags), translates the arm64 build with a base translator (--base=<sbt dir>, default ab/base/sbt) and with this tree's sbt/, then
runs native, base and lane in turn RUNS times after one warm-up each. Prints per benchmark the kernel medians (ms), the
spread (max-min over median), lane/base and lane/native, and whether all three outputs are identical; exits 1 on any DIFF
or TRANSLATE FAIL.
Usage: ab_perf.py [--base=<sbt dir>] [benchmark names without extension ...] (default: ab/base/sbt, a copy you place there; all 18)."""
###############
# imports and constants
###############
from __future__ import annotations
import math, os, statistics, subprocess, sys, time

PERF = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(PERF))
PY = sys.executable
BASE_ARG = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--base=")]
SIDES = {"base": os.path.abspath(BASE_ARG[0]) if BASE_ARG else os.path.join(LANE, "ab", "base", "sbt"), "lane": os.path.join(LANE, "sbt")}
OUT = os.path.join(PERF, "build", "ab", os.path.basename(os.path.dirname(SIDES["base"])) if BASE_ARG else "")
RUNS = 5                                                               # timed runs per side, interleaved
BENCH = ["b01_int.c", "b02_nbody.c", "b03_spectral.c", "b04_matmul.c", "b05_vecmem.c", "b06_dot.c", "b07_filter.c",
         "b08_sort.cpp", "b09_umap.cpp", "b10_string.cpp", "b11_vcall.cpp", "b12_libc.c", "b13_exc.cpp", "b14_threads.cpp",
         "b15_objc.m", "b16_calls.c", "b17_interp.c", "b18_alias.c"]
EXTRA_FLAGS = {"b18_alias.c": ["-fno-strict-aliasing"]}
ONLY = tuple(a for a in sys.argv[1:] if not a.startswith("--"))

###############
# functions
###############
def compile_cmd(src: str, arch: str, sdk: str, out: str) -> list[str]:
    """The bed's clang / clang++ command at -O2 for one arch."""
    base = ["-O2", "-isysroot", sdk, "-arch", arch, "-I", PERF] + EXTRA_FLAGS.get(src, []) + ["-o", out, os.path.join(PERF, src)]
    if src.endswith(".cpp"): return ["/usr/bin/clang++", "-std=c++17", "-nostdinc++", "-isystem", sdk + "/usr/include/c++/v1"] + base
    if src.endswith(".m"): return ["/usr/bin/clang", "-framework", "Foundation"] + base
    return ["/usr/bin/clang"] + base

def build(src: str, arch: str, sdk: str) -> str:
    """Executable of one benchmark for one arch."""
    out = os.path.join(OUT, arch, os.path.splitext(src)[0])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = subprocess.run(compile_cmd(src, arch, sdk, out), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    return out

def translate(side: str, exe: str, name: str) -> tuple[str, str]:
    """(translated executable or '', driver line) of one side's translation."""
    r = subprocess.run([PY, os.path.join(PERF, "ab_translate.py"), SIDES[side], exe, os.path.join(OUT, side, name)],
                       capture_output=True, text=True)
    line = (r.stdout.strip().splitlines() or [r.stderr.strip()[-600:]])[-1]
    return (line.split()[1] if line.startswith("EXE ") else ""), line

def timed(exe: str) -> tuple[str, float]:
    """(stdout + exit status, kernel seconds from PERF_NS) of one run."""
    r = subprocess.run([exe], cwd=os.path.dirname(exe), capture_output=True, text=True, timeout=600)
    ns = [int(ln.split()[1]) for ln in r.stderr.splitlines() if ln.startswith("PERF_NS ")]
    return r.stdout + "EXIT %d\n" % r.returncode, ns[-1] / 1e9 if ns else math.nan

def interleaved(exes: dict) -> dict:
    """side -> {'outs': set of outputs, 'k': kernel seconds}, after one warm-up run per side."""
    for e in exes.values(): timed(e)
    res = {s: {"outs": set(), "k": []} for s in exes}
    for _ in range(RUNS):
        for s, e in exes.items():
            o, k = timed(e)
            res[s]["outs"].add(o); res[s]["k"].append(k)
    return res

def spread(xs: list[float]) -> float:
    """(max - min) / median."""
    return (max(xs) - min(xs)) / statistics.median(xs)

def bench(src: str, sdk: str) -> str:
    """One A/B table line."""
    name = os.path.splitext(src)[0]
    nexe, aexe = build(src, "x86_64", sdk), build(src, "arm64", sdk)
    tr = {s: translate(s, aexe, name) for s in SIDES}
    bad = [s + ": " + line for s, (e, line) in tr.items() if not e]
    if bad: return "%-12s TRANSLATE FAIL %s" % (name, bad)
    res = interleaved({"native": nexe, **{s: e for s, (e, _l) in tr.items()}})
    outs = [r["outs"] for r in res.values()]
    same = all(len(o) == 1 for o in outs) and len(set.union(*outs)) == 1 and "EXIT 0" in next(iter(outs[0]))
    med = {s: statistics.median(r["k"]) for s, r in res.items()}
    return "%-12s %-5s native %8.1f (%4.1f%%)  base %8.1f (%4.1f%%)  lane %8.1f (%4.1f%%)  lane/base %5.3f  base/nat %5.2fx  lane/nat %5.2fx" % (
        name, "MATCH" if same else "DIFF", med["native"] * 1e3, 100 * spread(res["native"]["k"]), med["base"] * 1e3,
        100 * spread(res["base"]["k"]), med["lane"] * 1e3, 100 * spread(res["lane"]["k"]), med["lane"] / med["base"],
        med["base"] / med["native"], med["lane"] / med["native"])

###############
# run
###############
SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
T0 = time.time()
print("base %s vs lane %s: ms medians of %d interleaved runs (spread = (max-min)/median); lane/base < 1 is faster" % (
    SIDES["base"], SIDES["lane"], RUNS))
LINES = []
for s in BENCH:
    if not ONLY or os.path.splitext(s)[0] in ONLY: LINES.append(bench(s, SDK)); print(LINES[-1], flush=True)
BAD = [ln.split()[0] for ln in LINES if ln.split()[1] != "MATCH"]   # DIFF or TRANSLATE FAIL
print("total %.0f s, %d/%d MATCH%s" % (time.time() - T0, len(LINES) - len(BAD), len(LINES), ", FAILED: " + " ".join(BAD) if BAD else ""))
sys.exit(1 if BAD or not LINES else 0)
