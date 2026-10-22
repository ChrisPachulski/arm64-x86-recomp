"""Where translated benchmarks spend their time, on copies of the tests/perf sources with loop counts scaled up (the bed's runs
end before `sample` attaches): builds each scaled copy for arm64, translates it with the lane's sbt/gdyld.py into
build/prof/<name>, samples it for SECONDS and prints the top-of-stack symbols (lifted code shows as m<image>_<vmaddr>)."""
###############
# imports and constants
###############
from __future__ import annotations
import os, re, subprocess, sys, time

PERF = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(PERF))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld  # noqa: E402  (lane translator)

OUT = os.path.join(PERF, "build", "prof")
SCALE = {"b15_objc.m": [("20000000", "200000000"), ("4000000", "40000000")],
         "b13_exc.cpp": [("40000000", "400000000")],
         "b16_calls.c": [("fib(35)", "fib(40)"), ("50000000", "500000000")],
         "b10_string.cpp": [("400000", "4000000")],
         "b11_vcall.cpp": [("r < 10000", "r < 100000")],
         "b06_dot.c": [("360000", "3600000")]}
TARGETS = [a for a in sys.argv[1:]] or list(SCALE)                     # source names; all by default
DELAY = 0.4                                                            # s after launch before sampling
SECONDS = 3                                                            # sampling window
TOP = 16
TOP_RE = re.compile(r"^\s+(.+?)\s+\(in (.+?)\)\s+(\d+)\s*$")

###############
# functions
###############
def scaled_source(src: str) -> str:
    """Path of the scaled copy of one benchmark source (every replacement must apply)."""
    text = open(os.path.join(PERF, src)).read()
    for old, new in SCALE[src]:
        assert old in text, (src, old)
        text = text.replace(old, new)
    path = os.path.join(OUT, "src", src)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)
    return path

def build_arm64(path: str, sdk: str) -> str:
    """arm64 -O2 executable of one scaled source (the bed's compile flags)."""
    out = os.path.join(OUT, "arm64", os.path.splitext(os.path.basename(path))[0])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    base = ["-O2", "-isysroot", sdk, "-arch", "arm64", "-I", PERF, "-o", out, path]
    cmd = (["/usr/bin/clang++", "-std=c++17", "-nostdinc++", "-isystem", sdk + "/usr/include/c++/v1"] + base if path.endswith(".cpp")
           else ["/usr/bin/clang", "-framework", "Foundation"] + base if path.endswith(".m") else ["/usr/bin/clang"] + base)
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    return out

def sample(exe: str, name: str) -> str:
    """Path of the sample report of one translated run (output discarded; the run is killed after sampling)."""
    rep = os.path.join(OUT, name + ".txt")
    p = subprocess.Popen([exe], cwd=os.path.dirname(exe), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(DELAY)
    subprocess.run(["/usr/bin/sample", str(p.pid), str(SECONDS), "1", "-mayDie", "-file", rep], capture_output=True, timeout=120)
    p.kill(); p.wait(timeout=60)
    return rep

def top_of_stack(rep: str) -> list[tuple[int, str, str]]:
    """(samples, symbol, image) rows of the report's top-of-stack section, largest first."""
    text = open(rep).read() if os.path.isfile(rep) else ""
    sec = text.split("Sort by top of stack", 1)[1].split("Binary Images:", 1)[0] if "Sort by top of stack" in text else ""
    return sorted(((int(m.group(3)), m.group(1), m.group(2)) for m in map(TOP_RE.match, sec.splitlines()) if m), reverse=True)

def report(name: str, rows: list) -> list[str]:
    """Printable lines: total samples and the TOP symbols with their share."""
    total = sum(r[0] for r in rows) or 1
    return ["%s: %d samples at the top of stack" % (name, total)] + [
        "  %5.1f%%  %-72s %s" % (100.0 * n / total, sym[:72], img) for n, sym, img in rows[:TOP]]

def profile(src: str, sdk: str) -> list[str]:
    """Scale, build, translate and sample one benchmark."""
    name = os.path.splitext(src)[0]
    res = gdyld.translate(build_arm64(scaled_source(src), sdk), os.path.join(OUT, name), sdk)
    if res["error"]: return ["%s: translated build failed: %s" % (name, res["error"][-400:])]
    return report(name, top_of_stack(sample(res["exe"], name)))

###############
# run
###############
SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
for s in TARGETS:
    for line in profile(s, SDK): print(line)
