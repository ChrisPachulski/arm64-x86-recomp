"""Where translated benchmarks spend their time: runs each translated tests/perf build (made by run_perf.py), samples it
with macOS `sample` while the kernel runs, and prints the top-of-stack symbol counts (lifted functions show as
m<image>_<vmaddr>). Full sample reports land in build/profile/<name>.txt."""
###############
# imports and constants
###############
from __future__ import annotations
import os, re, subprocess, time

PERF = os.path.dirname(os.path.abspath(__file__))
GDYLD_BUILD = os.path.join(PERF, "build", "gdyld")
OUT = os.path.join(PERF, "build", "profile")
TARGETS = ["b15_objc", "b13_exc", "b06_dot", "b16_calls", "b10_string", "b11_vcall"]
DELAY = 0.12                                                           # s after launch: past image mapping and initializers
SECONDS = 1                                                            # sampling window
TOP = 14                                                               # symbols printed per benchmark
TOP_RE = re.compile(r"^\s+(.+?)\s+\(in (.+?)\)\s+(\d+)\s*$")

###############
# functions
###############
def sample(name: str) -> str:
    """Path of the sample report for one translated benchmark (the program runs to completion, output discarded)."""
    exe = os.path.join(GDYLD_BUILD, name, "translated")
    rep = os.path.join(OUT, name + ".txt")
    p = subprocess.Popen([exe], cwd=os.path.dirname(exe), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(DELAY)
    subprocess.run(["/usr/bin/sample", str(p.pid), str(SECONDS), "-mayDie", "-file", rep], capture_output=True, timeout=120)
    p.wait(timeout=600)
    return rep

def top_of_stack(rep: str) -> list[tuple[int, str, str]]:
    """(samples, symbol, image) rows of the report's top-of-stack section, largest first."""
    text = open(rep).read() if os.path.isfile(rep) else ""
    sec = text.split("Sort by top of stack", 1)[1].split("Binary Images:", 1)[0] if "Sort by top of stack" in text else ""
    rows = [(int(m.group(3)), m.group(1), m.group(2)) for m in map(TOP_RE.match, sec.splitlines()) if m]
    return sorted(rows, reverse=True)

def report(name: str, rows: list) -> list[str]:
    """Printable lines: total samples and the TOP symbols with their share."""
    total = sum(r[0] for r in rows) or 1
    return ["%s: %d samples at the top of stack (symbols with >= 5)" % (name, total)] + [
        "  %5.1f%%  %-70s %s" % (100.0 * n / total, sym[:70], img) for n, sym, img in rows[:TOP]]

###############
# run
###############
os.makedirs(OUT, exist_ok=True)
for name in TARGETS:
    for line in report(name, top_of_stack(sample(name))): print(line)
