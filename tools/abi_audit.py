"""Audits a gdyld build's prototype-bridged host imports for types the SDK lays out differently for an arm64 macOS
build (the guest's view) and an x86_64 one (the host's view): return and parameter types, what pointers point to, and
records passed by value. The bridges pass bytes through, so a difference is a guest/host disagreement unless a route
converts it (gdyld HEAP_ROUTE / ABI_ROUTE, special bridges). Prints one line per differing function and a summary.
Usage: abi_audit.py <gdyld build dir> <classes json>   Run bare: sbtenv/bin/python tools/abi_audit.py <gdyld build dir> <classes json from tools/import_classes.py>"""
###############
# imports and constants
###############
from __future__ import annotations
import json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sbt"))
import clang.cindex as ci  # noqa: E402
import gdyld  # noqa: E402  (ABI_ROUTE, HEAP_ROUTE)

BUILD, CLASSES = sys.argv[1], sys.argv[2]
SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip()
RES = subprocess.run(["clang", "-print-resource-dir"], capture_output=True, text=True).stdout.strip()
TARGETS = {"arm64": "arm64-apple-macos11", "x86_64": "x86_64-apple-macos11"}
AUDITED = ("prototype", "prototype+ui-check", "suffixed", "long-double-as-double")
V8_HDR = re.compile(r"^(v8|libplatform/|v8-)")

###############
# functions
###############
def host_headers(build: str) -> list[str]:
    """The system headers the build's host.cpp includes, V8's excepted (V8 imports have their own marshalling)."""
    text = open(os.path.join(build, "host.cpp")).read()
    return [h for h in re.findall(r"^#include <([^>]+)>", text, re.M) if not V8_HDR.match(h)]

def imported(classes: str) -> set[str]:
    """C names of the audited bridge classes (leading underscore and $suffix removed)."""
    d = json.load(open(classes))
    return {n[1:].split("$")[0] for k in AUDITED for n in d.get(k, []) if n.startswith("_")}

def fields(t: object, base: int) -> tuple:
    """(field name, bit offset, size) rows of a record type, anonymous members flattened."""
    out = []
    for f in t.get_fields():
        off = base + f.get_field_offsetof()
        out.append((f.spelling, off, f.type.get_size()))
        if not f.spelling: out += list(fields(f.type.get_canonical(), off))
    return tuple(out)

def shape(t: object) -> tuple:
    """A comparable view of a type: canonical spelling, size, align, and the pointee's or record's layout."""
    c = t.get_canonical()
    view = (c.spelling, c.get_size(), c.get_align())
    if c.kind == ci.TypeKind.POINTER:
        p = c.get_pointee().get_canonical()
        if p.kind not in (ci.TypeKind.FUNCTIONPROTO, ci.TypeKind.FUNCTIONNOPROTO, ci.TypeKind.VOID):
            view += ("->", p.spelling, p.get_size(), fields(p, 0) if p.kind == ci.TypeKind.RECORD else ())
    elif c.kind == ci.TypeKind.RECORD:
        view += (fields(c, 0),)
    return view

def prototypes(headers: list[str], target: str, names: set[str]) -> dict[str, tuple]:
    """{name: (result shape, parameter shapes)} for the named functions as the headers declare them for one target."""
    src = "".join("#include <%s>\n" % h for h in headers)
    tu = ci.Index.create().parse("audit.mm", args=["-x", gdyld.HOST_LANG, "-std=c++17", "-nostdinc++", "-isysroot", SDK, "-target", target,
                                                   "-resource-dir", RES], unsaved_files=[("audit.mm", src)],
                                 options=ci.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)
    out, todo = {}, list(tu.cursor.get_children())
    while todo:
        c = todo.pop(0)
        if c.kind == ci.CursorKind.LINKAGE_SPEC: todo = list(c.get_children()) + todo
        elif c.kind == ci.CursorKind.FUNCTION_DECL and c.spelling in names and c.spelling not in out:
            out[c.spelling] = (shape(c.type.get_result()), tuple(shape(a) for a in c.type.argument_types()))
    return out

def differences(a: dict, x: dict) -> list[str]:
    """One line per function whose arm64 and x86_64 views differ: the first differing position and both views."""
    rows = []
    for n in sorted(set(a) & set(x)):
        if a[n] == x[n]: continue
        pa, px = (a[n][0],) + a[n][1], (x[n][0],) + x[n][1]
        i = next(i for i in range(max(len(pa), len(px))) if i >= len(pa) or i >= len(px) or pa[i] != px[i])
        where = "result" if i == 0 else "param %d" % (i - 1)
        routed = "_" + n in gdyld.ABI_ROUTE or "_" + n in gdyld.HEAP_ROUTE
        rows.append("%-8s %-40s %-9s arm64 %s | x86_64 %s" % ("ROUTED" if routed else "OPEN", n, where,
                                                             str(pa[i] if i < len(pa) else None)[:150], str(px[i] if i < len(px) else None)[:150]))
    return rows

###############
# run
###############
HEADERS = host_headers(BUILD)
NAMES = imported(CLASSES)
VIEWS = {a: prototypes(HEADERS, t, NAMES) for a, t in TARGETS.items()}
ROWS = differences(VIEWS["arm64"], VIEWS["x86_64"])
for _r in ROWS: print(_r)
print("summary: %d headers, %d audited imports, %d declared for both targets, %d differ (%d open)" % (
    len(HEADERS), len(NAMES), len(set(VIEWS["arm64"]) & set(VIEWS["x86_64"])), len(ROWS), sum(r.startswith("OPEN") for r in ROWS)))
