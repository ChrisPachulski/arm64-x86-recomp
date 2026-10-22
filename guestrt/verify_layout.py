"""Compile probe/layout_probe.cpp for arm64 against the SDK libc++ headers and the built ones, read the
sizeof/alignof/offset values back out of the two object files, and check they are identical; show the
std::string long-flag byte test from each object's -O2 code. Writes out/verify/layout.json.
Run bare: sbtenv/bin/python guestrt/verify_layout.py"""
###############
# imports and constants
###############
from __future__ import annotations
import json, os, re, struct, subprocess

LANE = os.path.dirname(os.path.abspath(__file__))
SDK = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True, check=True).stdout.strip()
SRC = os.path.join(LANE, "probe", "layout_probe.cpp")
OBJ_DIR = os.path.join(LANE, "build", "probe")
HEADERS = {"sdk": os.path.join(SDK, "usr", "include", "c++", "v1"),
           "built": os.path.join(LANE, "out", "include", "c++", "v1")}
CFLAGS = ["-isysroot", SDK, "-arch", "arm64", "-mmacosx-version-min=11.0", "-std=c++20", "-O2", "-nostdinc++"]
OUT = os.path.join(LANE, "out", "verify", "layout.json")
FLAG_FUNCS = ["_probe_string_size", "_probe_string_data"]

###############
# functions
###############
def compile_obj(tag: str) -> str:
    """Compile the probe against one header set; return the object path."""
    obj = os.path.join(OBJ_DIR, tag + ".o")
    subprocess.run(["clang++", *CFLAGS, "-isystem", HEADERS[tag], "-c", SRC, "-o", obj], check=True)
    return obj

def section_bytes(obj: str, seg: str, sect: str) -> bytes:
    """Raw bytes of one section, parsed from otool -s hex dump (little-endian 32-bit words)."""
    lines = subprocess.run(["otool", "-s", seg, sect, obj], capture_output=True, text=True, check=True).stdout
    words = [w for ln in lines.splitlines()[2:] for w in ln.split("\t", 1)[1].split()]
    return b"".join(struct.pack("<I", int(w, 16)) for w in words) if all(len(w) == 8 for w in words) \
        else bytes(int(w, 16) for w in words)

def values(obj: str) -> dict[str, int]:
    """Probe name -> value, from __probe (sizeof/alignof) then __probeoff (offsets)."""
    names = section_bytes(obj, "__TEXT", "__probenames").split(b"\0")
    raw = section_bytes(obj, "__DATA", "__probe") + section_bytes(obj, "__DATA", "__probeoff")
    nums = struct.unpack("<%dq" % (len(raw) // 8), raw)
    return dict(zip((n.decode() for n in names if n), nums))

def flag_code(obj: str) -> dict[str, list[str]]:
    """-O2 disassembly of the std::string size()/data() readers."""
    lines = subprocess.run(["otool", "-tv", obj], capture_output=True, text=True, check=True).stdout.splitlines()
    starts = {ln.rstrip(":"): i for i, ln in enumerate(lines) if ln.endswith(":")}
    def body(f: str) -> list[str]:
        rest = lines[starts[f] + 1:]
        return [re.sub(r"\s+", " ", ln.split("\t", 1)[1]) for ln in rest[:next((i for i, l in enumerate(rest) if l.endswith(":")), len(rest))]]
    return {f: body(f) for f in FLAG_FUNCS}

###############
# run
###############
os.makedirs(OBJ_DIR, exist_ok=True)
_objs = {t: compile_obj(t) for t in HEADERS}
_vals = {t: values(o) for t, o in _objs.items()}
_code = {t: flag_code(o) for t, o in _objs.items()}
_diff = sorted(k for k in _vals["sdk"].keys() | _vals["built"].keys() if _vals["sdk"].get(k) != _vals["built"].get(k))
json.dump({"values": _vals, "differences": _diff, "string_flag_code": _code}, open(OUT, "w"), indent=1)
for _k, _v in _vals["sdk"].items():
    print("%-46s sdk %4d  built %4d %s" % (_k, _v, _vals["built"].get(_k, -1), "" if _v == _vals["built"].get(_k) else "DIFF"))
print("values compared: %d, differences: %d %s" % (len(_vals["sdk"]), len(_diff), _diff))
for _t, _c in _code.items():
    for _f, _body in _c.items():
        print("[%s] %s: %s" % (_t, _f, " ; ".join(_body)))
print("long-flag read at byte 23 in both:", all("#0x17]" in " ".join(_c["_probe_string_size"]) for _c in _code.values()))
