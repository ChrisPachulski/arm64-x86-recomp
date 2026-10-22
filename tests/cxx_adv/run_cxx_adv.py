"""Adversarial C++ runtime + exceptions bed for gdyld (lane C break test): builds every tests/cxx_adv program for arm64
(guest) and x86_64 (oracle), runs the native build for stdout+exit, translates the arm64 build with sbt/gdyld.py and
runs it; prints MATCH or DIFF with a unified diff and the translated stderr. Outputs land in build/{expected,translated}."""

###############
# Imports and constants

from __future__ import annotations

import difflib
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(LANE, "sbt"))
import gdyld  # noqa: E402  (lane library under test)
BUILD = os.path.join(HERE, "build")
ARCHES = ("x86_64", "arm64")
RUN_TIMEOUT = 300                                                      # s per program run
DIFF_LINES = 14

###############
# Functions


def run(cmd: list[str], cwd: str | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    """Run a command, capturing text output."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout)


def plan(root: str) -> dict[str, list[tuple[str, list[str], list[str]]]]:
    """Build steps per test: (output, sources, flags); the executable is always <test>/run/<test>."""
    exe = lambda t, srcs: [(os.path.join(root, t, "run", t), srcs, ["-Wl,-rpath,@executable_path"])]
    lib = lambda t, n: os.path.join(root, t, "run", "lib%s.dylib" % n)
    dylib = lambda t, n, srcs: [(lib(t, n), srcs, ["-dynamiclib", "-install_name", "@rpath/lib%s.dylib" % n, "-Wl,-rpath,@loader_path"])]
    single = ["deep_mixed", "dtor_throw", "nested", "qsort_throw", "longjmp_dtor", "threads8", "promise", "vla",
              "bigframe", "iofmt", "sort_throw", "ftry", "stack_probe"]
    steps = {t: exe(t, [t + ".cpp"]) for t in single}
    steps["qsort_longjmp"] = exe("qsort_longjmp", ["qsort_longjmp.c"])
    steps["rethrow3"] = (dylib("rethrow3", "r3a", ["r3_a.cpp"]) + dylib("rethrow3", "r3b", ["r3_b.cpp", lib("rethrow3", "r3a")])
                         + dylib("rethrow3", "r3c", ["r3_c.cpp", lib("rethrow3", "r3b"), lib("rethrow3", "r3a")])
                         + exe("rethrow3", ["r3_main.cpp", lib("rethrow3", "r3c"), lib("rethrow3", "r3b"), lib("rethrow3", "r3a")]))
    steps["typeid_x"] = dylib("typeid_x", "tid", ["tid_lib.cpp"]) + exe("typeid_x", ["tid_main.cpp", lib("typeid_x", "tid")])
    return steps


def build_test(steps: list[tuple[str, list[str], list[str]]], arch: str, sdk: str) -> list[str]:
    """Compile+link every step for one arch; error lines."""
    errs = []
    for out, srcs, flags in steps:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cxx = any(s.endswith(".cpp") for s in srcs)
        cc = ["/usr/bin/clang++", "-std=c++17", "-nostdinc++", "-isystem", sdk + "/usr/include/c++/v1"] if cxx else ["/usr/bin/clang"]
        r = run(cc + ["-O1", "-isysroot", sdk, "-arch", arch, "-o", out] + flags + srcs, cwd=HERE)
        errs += ["%s: %s" % (os.path.basename(out), r.stderr.strip()[:600])] if r.returncode else []
    return errs


def program_run(exe: str, cwd: str) -> tuple[str, str, float]:
    """stdout + 'EXIT n', stderr, wall seconds of one run."""
    t0 = time.time()
    try:
        r = run([exe], cwd=cwd, timeout=RUN_TIMEOUT)
        return r.stdout + "EXIT %d\n" % r.returncode, r.stderr.strip(), time.time() - t0
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return out + "TIMEOUT\n", "timeout after %d s" % RUN_TIMEOUT, time.time() - t0


def save(kind: str, name: str, text: str) -> None:
    """Write one output under build/<kind>/<name>.txt."""
    os.makedirs(os.path.join(BUILD, kind), exist_ok=True)
    with open(os.path.join(BUILD, kind, name + ".txt"), "w") as fh:
        fh.write(text)


def one_test(name: str, sdk: str) -> list[str]:
    """Build both arches, run native, translate + run arm64, compare; a status line plus detail lines."""
    errs = {a: build_test(plan(os.path.join(BUILD, a))[name], a, sdk) for a in ARCHES}
    exe = {a: os.path.join(BUILD, a, name, "run", name) for a in ARCHES}
    if errs["x86_64"] or errs["arm64"]:
        return ["%-14s BUILD FAIL" % name] + ["    " + e for e in errs["x86_64"] + errs["arm64"]]
    want, werr, wt = program_run(exe["x86_64"], os.path.dirname(exe["x86_64"]))
    save("expected", name, want)
    t0 = time.time()
    try:
        res = gdyld.translate(exe["arm64"], os.path.join(BUILD, "gdyld", name), sdk)
    except (OSError, ValueError, LookupError, NotImplementedError, RuntimeError, MemoryError) as e:
        return ["%-14s translate BLOCKED: %s: %s" % (name, type(e).__name__, str(e)[:600])]
    if res["error"]:
        return ["%-14s translated BUILD FAIL" % name] + ["    build: " + ln for ln in res["error"].strip().splitlines()[:15]]
    tt = time.time() - t0
    got, err, gt = program_run(res["exe"], os.path.dirname(exe["arm64"]))
    save("translated", name, got)
    diff = list(difflib.unified_diff(want.splitlines(), got.splitlines(), "native", "translated", n=1, lineterm=""))
    status = "MATCH" if got == want else "DIFF"
    return (["%-14s %s | native %d lines %s %.1f s | translated %s %.1f s | translate+build %.0f s" % (
                name, status, want.count("\n"), want.splitlines()[-1], wt, got.splitlines()[-1] if got else "<none>", gt, tt)]
            + ["    " + ln for ln in diff[2:2 + DIFF_LINES]]
            + (["    ... %d more diff lines" % (len(diff) - 2 - DIFF_LINES)] if len(diff) > 2 + DIFF_LINES else [])
            + (["    native stderr: " + werr[-300:].replace("\n", " | ")] if werr and got != want else [])
            + (["    translated stderr: " + err[-500:].replace("\n", " | ")] if err else [])
            + (["    unsupported insns %d %s" % (len(res["unsupported"]), res["unsupported"][:3])] if res["unsupported"] else []))


###############
# Run

SDK = run(["/usr/bin/xcrun", "--show-sdk-path"]).stdout.strip()
SELECTED = sys.argv[1:] or list(plan(BUILD))
for n in SELECTED:
    shutil.rmtree(os.path.join(BUILD, "x86_64", n), ignore_errors=True)
    shutil.rmtree(os.path.join(BUILD, "arm64", n), ignore_errors=True)
print("guest runtime: %s" % gdyld.GUESTRT)
LINES = []
for n in SELECTED:
    out = one_test(n, SDK)
    print("\n".join(out), flush=True)
    LINES += out
STATUS = [ln for ln in LINES if not ln.startswith(" ")]
print("summary: %d/%d MATCH; not matching: %s" % (
    sum(1 for ln in STATUS if " MATCH " in ln), len(SELECTED), [ln.split()[0] for ln in STATUS if " MATCH " not in ln]))
