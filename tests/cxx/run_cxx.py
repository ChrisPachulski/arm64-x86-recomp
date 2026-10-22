"""C++ runtime + exceptions bed for gdyld: checks the loader's fixups of the guest libunwind/libc++abi/libc++ against
Apple's dyld_info, then builds every tests/cxx program for arm64 (guest) and x86_64 (oracle), runs the native build
for the expected stdout+exit, translates the arm64 build with sbt/gdyld.py (guest C++ runtime included) and diffs
the translated run against it (MATCH / DIFF)."""

###############
# Imports and constants

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

CXX = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(os.path.dirname(CXX))
SBT = os.path.join(LANE, "sbt")
sys.path.insert(0, SBT)
import gdyld  # noqa: E402  (lane library under test)
BUILD = os.path.join(CXX, "build")
ARCHES = ("x86_64", "arm64")
RUN_TIMEOUT = 120                                                      # s per program run
RT_FILES = ("libunwind.1.dylib", "libc++abi.1.dylib", "libc++.1.dylib")
SPECIAL_LIBS = {-1: "main-executable", -2: "flat-namespace", -3: "<weak-def-coalesce>", 0: "this-image"}
LOUD = {"loud_ucontext": ("unsupported control transfer", 70)}         # test -> (stderr text, exit status) of the loud stop

###############
# Functions


def run(cmd: list[str], cwd: str | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    """Run a command, capturing text output."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout)


def dyld_info_fixups(path: str) -> set[tuple]:
    """Apple's view: (vmaddr, 'rebase', target, 0) and (vmaddr, 'bind', 'lib/name', addend)."""
    out = set()
    for ln in run(["/usr/bin/dyld_info", "-arch", "arm64", "-fixups", path]).stdout.splitlines():
        t = ln.split()
        if len(t) >= 5 and t[3] in ("rebase", "bind"):
            add = int(t[6], 16) if len(t) == 7 and t[5] == "+" else 0
            out.add((int(t[2], 16), t[3], int(t[4], 16) if t[3] == "rebase" else t[4], add))
    return out


def loader_fixups(path: str) -> set[tuple]:
    """gdyld's parse of the same file in the same shape (bind library = install-name leaf before the first dot)."""
    m = gdyld.parse_image(path)
    rebases, binds = gdyld.fixups(m)
    lib = lambda o: SPECIAL_LIBS.get(o) or os.path.basename(m["deps"][o - 1][0]).split(".")[0]
    return ({(a, "rebase", t, 0) for a, t in rebases} | {(a, "bind", "%s/%s" % (lib(o), n), add) for a, o, n, _w, add in binds})


def fixup_check() -> list[str]:
    """One line per runtime dylib: counts and whether gdyld's fixups equal dyld_info's (with addends)."""
    lines = []
    for f in RT_FILES:
        p = os.path.join(gdyld.GUESTRT, f)
        mine, ref = loader_fixups(p), dyld_info_fixups(p)
        nadd = sum(1 for x in ref if x[3])
        lines.append("fixups %-18s gdyld %5d | dyld_info %5d | with addend %3d | identical %s%s" % (
            f, len(mine), len(ref), nadd, mine == ref, "" if mine == ref else " only-gdyld %s only-dyld_info %s" % (
                sorted(mine - ref)[:3], sorted(ref - mine)[:3])))
    return lines


def plan(root: str) -> dict[str, list[tuple[str, list[str], list[str]]]]:
    """Build steps per test: (output, sources, flags); the executable is always <test>/run/<test>."""
    exe = lambda test, srcs, flags=(): [(os.path.join(root, test, "run", test), srcs, ["-Wl,-rpath,@executable_path"] + list(flags))]
    lib = lambda test, name: os.path.join(root, test, "run", "lib%s.dylib" % name)
    dylib = lambda test, name, srcs: [(lib(test, name), srcs, ["-dynamiclib", "-install_name", "@rpath/lib%s.dylib" % name])]
    return {
        "frames": exe("frames", ["frames.c"]),
        "sjlj": exe("sjlj", ["sjlj.c"]),
        "throw_basic": exe("throw_basic", ["throw_basic.cpp"]),
        "deep": exe("deep", ["deep.cpp"]),
        "eptr": exe("eptr", ["eptr.cpp"]),
        "noexcept_term": exe("noexcept_term", ["noexcept_term.cpp"]),
        "xlib": dylib("xlib", "xlib", ["xlib.cpp"]) + exe("xlib", ["xmain.cpp", lib("xlib", "xlib")]),
        "thread_exc": exe("thread_exc", ["thread_exc.cpp"]),
        "rtti": dylib("rtti", "rtti", ["rtti_lib.cpp"]) + exe("rtti", ["rtti_main.cpp", lib("rtti", "rtti")]),
        "streams": exe("streams", ["streams.cpp"]),
        "containers": exe("containers", ["containers.cpp"]),
        "threads_cv": exe("threads_cv", ["threads_cv.cpp"]),
        "tls_dtor": exe("tls_dtor", ["tls_dtor.cpp"]),
        "sinit": dylib("sinit", "sinit", ["sinit_lib.cpp"]) + exe("sinit", ["sinit_main.cpp", lib("sinit", "sinit")]),
        "uncaught": exe("uncaught", ["uncaught.cpp"]),
        "loud_ucontext": exe("loud_ucontext", ["loud_ucontext.c"], ["-Wno-deprecated-declarations"]),
        "hostframe": exe("hostframe", ["hostframe.cpp"]),
        "tls_align": exe("tls_align", ["tls_align.cpp"]),
    }


def loud_status(name: str, got: str, want: str, err: str) -> str:
    """LOUD-OK when an expected-unsupported program stopped with the expected message and exit status after printing a prefix of the native output."""
    text, code = LOUD[name]
    rc = int(got.rsplit("EXIT ", 1)[1]) if "EXIT " in got else 999
    prefix_ok = want.startswith(got[:got.rfind("EXIT")])
    return ("LOUD-OK (exit %d: %s)" % (rc, text) if rc == code and text in err and prefix_ok else
            "LOUD-MISSING exit %d, stdout prefix ok %s" % (rc, prefix_ok))


def build_test(steps: list[tuple[str, list[str], list[str]]], arch: str, sdk: str) -> list[str]:
    """Compile+link every step for one arch (C++ through clang++ with the SDK libc++ headers); error lines."""
    errs = []
    for out, srcs, flags in steps:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cxx = any(s.endswith(".cpp") for s in srcs)
        cc = ["/usr/bin/clang++", "-std=c++17", "-nostdinc++", "-isystem", sdk + "/usr/include/c++/v1"] if cxx else ["/usr/bin/clang"]
        r = run(cc + ["-O1", "-isysroot", sdk, "-arch", arch, "-o", out] + flags + srcs, cwd=CXX)
        errs += ["%s: %s" % (os.path.basename(out), r.stderr.strip()[:400])] if r.returncode else []
    return errs


def program_run(exe: str, cwd: str) -> tuple[str, str]:
    """stdout + 'EXIT n' and stderr of one run."""
    try:
        r = run([exe], cwd=cwd, timeout=RUN_TIMEOUT)
        return r.stdout + "EXIT %d\n" % r.returncode, r.stderr.strip()
    except subprocess.TimeoutExpired:
        return "TIMEOUT\n", "timeout after %d s" % RUN_TIMEOUT


def first_diff(got: str, want: str) -> str:
    """First differing line pair."""
    g, w = got.splitlines(), want.splitlines()
    k = next((i for i in range(max(len(g), len(w))) if i >= len(g) or i >= len(w) or g[i] != w[i]), 0)
    return "line %d: got %r want %r" % (k + 1, (g[k] if k < len(g) else "<eof>")[:150], (w[k] if k < len(w) else "<eof>")[:150])


def one_test(name: str, sdk: str) -> list[str]:
    """Build both arches, run native, translate + run arm64, compare; a status line plus detail lines."""
    errs = {a: build_test(plan(os.path.join(BUILD, a))[name], a, sdk) for a in ARCHES}
    exe = {a: os.path.join(BUILD, a, name, "run", name) for a in ARCHES}
    if errs["x86_64"] or errs["arm64"]:
        return ["%-14s BUILD FAIL" % name] + ["    " + e for e in errs["x86_64"] + errs["arm64"]]
    want, _ = program_run(exe["x86_64"], os.path.dirname(exe["x86_64"]))
    t0 = time.time()
    try:
        res = gdyld.translate(exe["arm64"], os.path.join(BUILD, "gdyld", name), sdk)
    except (OSError, ValueError, LookupError, NotImplementedError, RuntimeError, MemoryError) as e:
        return ["%-14s translated BLOCKED: %s: %s" % (name, type(e).__name__, str(e)[:400])]
    if res["error"]:
        return ["%-14s translated BUILD FAIL" % name] + ["    build: " + ln for ln in res["error"].strip().splitlines()[:15]]
    tt = time.time() - t0
    got, err = program_run(res["exe"], os.path.dirname(exe["arm64"]))
    for kind, text in (("expected", want), ("translated", got)):
        os.makedirs(os.path.join(BUILD, kind), exist_ok=True)
        with open(os.path.join(BUILD, kind, name + ".txt"), "w") as fh:
            fh.write(text)
    status = loud_status(name, got, want, err) if name in LOUD else "MATCH" if got == want else "DIFF " + first_diff(got, want)
    return (["%-14s %s | %d stdout lines, %s | translate+build %.0f s" % (name, status, want.count("\n") - 1, want.splitlines()[-1], tt)]
            + ["    gdyld: " + ln for ln in res["report"][-1:]]
            + ["    unsupported insns %d %s" % (len(res["unsupported"]), res["unsupported"][:3])]
            + (["    stderr: " + err[-400:].replace("\n", " | ")] if err else []))


###############
# Run

SDK = run(["/usr/bin/xcrun", "--show-sdk-path"]).stdout.strip()
shutil.rmtree(BUILD, ignore_errors=True)
print("guest runtime: %s" % gdyld.GUESTRT)
print("\n".join(fixup_check()))
SELECTED = sys.argv[1:] or list(plan(BUILD))
LINES = [ln for name in SELECTED for ln in one_test(name, SDK)]
print("\n".join(LINES))
print("summary: %d/%d MATCH, %d/%d LOUD-OK" % (
    sum(1 for ln in LINES if not ln.startswith(" ") and " MATCH " in ln), sum(1 for n in SELECTED if n not in LOUD),
    sum(1 for ln in LINES if not ln.startswith(" ") and " LOUD-OK " in ln), sum(1 for n in SELECTED if n in LOUD)))
