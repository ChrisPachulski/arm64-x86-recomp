"""Runs the main bed list in parallel workers (GPU beds afterwards, one at a time), one log per bed, and prints each
bed's exit, seconds and summary line. Extra beds (tools/beds_local.txt, optional) run after the
built-in ones. Usage: run_beds.py [--jobs=N] [--log=<dir>] [bed names ...] (default: all, 4 jobs).
Most runners exit 0 even on failure, so the printed summary lines are what to read; exit 1 if any bed exited nonzero."""
###############
# imports and constants
###############
from __future__ import annotations
import concurrent.futures, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PUBLIC_BEDS = [
    ("microtest_forms", ["sbt/microtest.py", "cases_m3a2_forms"]),                    # case sets split ~1526/1367/971/700
    ("microtest_core", ["sbt/microtest.py", "cases_scalar", "cases_neon", "cases_scalar_adv1", "cases_neon_adv1", "cases_neon_adv2"]),
    ("microtest_m45", ["sbt/microtest.py", "cases_m4a", "cases_m5a_fuse", "cases_m5a_adv1"]),
    ("microtest_m67", ["sbt/microtest.py", "cases_m6c_adv_fp", "cases_m7a", "cases_m7b"]),
    ("check_ab_exit", ["tests/perf/check_ab_exit.py"]),
    ("m3a2_cf", ["sbt/cases_m3a2_cf.py"]),
    ("adv", ["tests/adv/run_adv.py"]),
    ("cxx", ["tests/cxx/run_cxx.py"]),
    ("cxx_adv", ["tests/cxx_adv/run_cxx_adv.py"]),
    ("objc", ["tests/objc/run_objc.py"]),
    ("objc_adv", ["tests/objc_adv/run_objc_adv.py"]),
    ("m6c_objc_cache", ["tests/m6c/run_objc_cache.py"]),
    ("m6c_flags", ["tests/m6c/run_flags.py"]),
    ("swift", ["tests/swift/run_swift.py"]),
    ("swift_adv", ["tests/swift_adv/run_swift_adv.py"]),
    ("swift_adv_corpus", ["tests/swift_adv/run_swift_adv.py", "--corpus"]),
    ("swift_link", ["tests/swift_adv/run_link_checks.py"]),
    ("uiguard", ["tests/uiguard/run_uiguard.py"]),
    ("dl", ["tests/dl/run_dl.py"]),
    ("m5b_cb", ["tests/m5b_adv/cb/run_m5b_cb.py"]),
    ("m5b_dl", ["tests/m5b_adv/dl/run_m5b_dl.py"]),
    ("fp16", ["tests/fp16/run_fp16_loud.py"]),
    ("msglookup", ["tests/m7b/run_msglookup.py"]),
    ("send_cache", ["tests/m7b/run_send_cache.py"]),
    ("heapguard", ["tests/heapguard/run_heapguard.py"]),
    ("abi", ["tests/abi/run_abi.py"]),
]
LOCAL_FILE = os.path.join(ROOT, "tools", "beds_local.txt")            # optional, one per line: cpu|gpu|after <name> <args ...>
LOCAL = [l.split() for l in (open(LOCAL_FILE) if os.path.exists(LOCAL_FILE) else []) if l.strip() and not l.lstrip().startswith("#")]
BEDS = PUBLIC_BEDS + [(r[1], r[2:]) for r in LOCAL if r[0] == "cpu"]
GPU_BEDS = [(r[1], r[2:]) for r in LOCAL if r[0] == "gpu"]            # run one at a time after the CPU beds
AFTER = {r[1]: r[2:] for r in LOCAL if r[0] == "after"}                # a follow-on step that needs its bed's build
SUMMARY = re.compile(r"summary|RESULT|ALL PASS|ALL \d+|failed|byte-identical|PASS$|\d+/\d+")

###############
# functions
###############
def options(argv: list[str]) -> tuple[int, str, list[str]]:
    """(jobs, log dir, selected bed names) from the command line."""
    jobs = next((int(a.split("=", 1)[1]) for a in argv if a.startswith("--jobs=")), 4)
    log = next((a.split("=", 1)[1] for a in argv if a.startswith("--log=")), os.path.join(ROOT, "tests", "beds_logs"))
    return jobs, log, [a for a in argv if not a.startswith("--")]

def run_one(name: str, args: list[str], log: str) -> tuple[str, int, float]:
    """(name, exit status, seconds) for one bed (plus its follow-on step), output in <log>/<name>.log."""
    t0 = time.time()
    with open(os.path.join(log, name + ".log"), "w") as out:
        rc = subprocess.run([PY] + args, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT).returncode
        if rc == 0 and name in AFTER:
            out.flush()
            rc = subprocess.run([PY] + AFTER[name], cwd=ROOT, stdout=out, stderr=subprocess.STDOUT).returncode
    return name, rc, time.time() - t0

def summary_line(name: str, log: str) -> str:
    """Last summary-looking line of a bed's log, or '(no summary line)'."""
    lines = [l.rstrip() for l in open(os.path.join(log, name + ".log"), errors="replace") if SUMMARY.search(l)]
    return lines[-1][:160] if lines else "(no summary line)"

def run_all(beds: list, gpu: list, jobs: int, log: str) -> list[tuple[str, int, float]]:
    """Results of the CPU beds in a pool of `jobs` workers, then the GPU beds one at a time."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        done = list(pool.map(lambda b: run_one(b[0], b[1], log), beds))
    return done + [run_one(n, a, log) for n, a in gpu]

###############
# run
###############
JOBS, LOG, PICK = options(sys.argv[1:])
os.makedirs(LOG, exist_ok=True)
CPU_SEL = [b for b in BEDS if not PICK or b[0] in PICK]
GPU_SEL = [b for b in GPU_BEDS if not PICK or b[0] in PICK]
T0 = time.time()
RESULTS = run_all(CPU_SEL, GPU_SEL, JOBS, LOG)
for _n, _rc, _s in RESULTS: print("%-18s exit %d %5.0f s | %s" % (_n, _rc, _s, summary_line(_n, LOG)))
BAD = [n for n, rc, _ in RESULTS if rc != 0]
print("beds %d, wall %.0f s, sum %.0f s, %d jobs, nonzero exits: %s" % (len(RESULTS), time.time() - T0, sum(s for _, _, s in RESULTS), JOBS, BAD or "none"))
sys.exit(1 if BAD else 0)
