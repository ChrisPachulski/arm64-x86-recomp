"""Bounded disassembly of one function of one Mach-O slice (capstone; never a whole binary): from a symbol or address to the
next symbol / function start, at most MAX_INSNS instructions, with call targets named from the symbol table. In a main
executable it refuses any range that overlaps a protected range from tools/protected_ranges.txt (local and git-ignored:
one "start end" hex pair per line, '#' comments).
Run bare: sbtenv/bin/python tools/xdis.py <file> <x86_64|arm64> <symbol|0xaddr> [max instructions]"""
###############
# imports and constants
###############
from __future__ import annotations
import bisect, os, struct, sys
import capstone

MAX_INSNS = 400
RANGES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "protected_ranges.txt")
PROTECTED = [tuple(int(x, 16) for x in l.split()[:2]) for l in (open(RANGES_FILE) if os.path.exists(RANGES_FILE) else [])
             if l.strip() and not l.lstrip().startswith("#")]                 # never disassembled
CPU = {"x86_64": 0x01000007, "arm64": 0x0100000C}
FAT_MAGIC, MH64 = 0xCAFEBABE, 0xFEEDFACF

###############
# functions
###############
def slice_of(data: bytes, arch: str) -> bytes:
    """The thin Mach-O of `arch` inside a universal file (or the file itself)."""
    if struct.unpack_from(">I", data, 0)[0] != FAT_MAGIC: return data
    n = struct.unpack_from(">I", data, 4)[0]
    for i in range(n):
        cpu, _sub, off, size, _al = struct.unpack_from(">5I", data, 8 + 20 * i)
        if cpu == CPU[arch]: return data[off:off + size]
    raise ValueError("no %s slice" % arch)

def macho(d: bytes) -> tuple[list, list, dict]:
    """(sections [(seg, sect, addr, size, off)], sorted function starts, symbols {addr: name}) of a thin 64-bit Mach-O."""
    if struct.unpack_from("<I", d, 0)[0] != MH64: raise ValueError("not a thin 64-bit Mach-O")
    ncmds = struct.unpack_from("<I", d, 16)[0]
    i, sects, syms, fstarts, linkedit, text = 32, [], {}, [], None, 0
    for _ in range(ncmds):
        cmd, sz = struct.unpack_from("<II", d, i)
        if cmd == 0x19:                                                # LC_SEGMENT_64
            seg = d[i + 8:i + 24].split(b"\0")[0].decode()
            vm, _vs, fo = struct.unpack_from("<3Q", d, i + 24)
            if seg == "__LINKEDIT": linkedit = (vm, fo)
            if seg == "__TEXT": text = vm
            for k in range(struct.unpack_from("<I", d, i + 64)[0]):
                s = i + 72 + 80 * k
                sects.append((d[s + 16:s + 32].split(b"\0")[0].decode(), d[s:s + 16].split(b"\0")[0].decode()) + struct.unpack_from("<QQI", d, s + 32))
        elif cmd == 0x2:                                               # LC_SYMTAB
            symoff, nsyms, stroff, _ss = struct.unpack_from("<4I", d, i + 8)
            for k in range(nsyms):
                strx, ntype, _sect, _desc, val = struct.unpack_from("<IBBHQ", d, symoff + 16 * k)
                if ntype & 0xE0 == 0 and ntype & 0x0E == 0x0E and val:
                    nm = d[stroff + strx:d.index(b"\0", stroff + strx)].decode("latin-1")
                    syms.setdefault(val, nm)
                    syms.setdefault(nm, val)                           # name -> address too (aliases share an address)
        elif cmd == 0x26:                                              # LC_FUNCTION_STARTS
            off, size = struct.unpack_from("<II", d, i + 8)
            a, j = text, off
            while j < off + size:
                v, shift = 0, 0
                while True:
                    b = d[j]; j += 1; v |= (b & 0x7F) << shift; shift += 7
                    if b < 0x80: break
                if not v: break
                a += v; fstarts.append(a)
        i += sz
    return sects, sorted(set(fstarts) | {a for a in syms if isinstance(a, int)}), syms

def disasm(d: bytes, arch: str, start: int, limit: int) -> list[str]:
    """Lines of one function from `start` to the next function start."""
    sects, starts, syms = macho(d)
    k = bisect.bisect_right(starts, start)
    end = starts[k] if k < len(starts) else start + 4 * limit
    if d is not None and struct.unpack_from("<I", d, 12)[0] == 2 and any(start < hi and end > lo for lo, hi in PROTECTED):
        raise PermissionError("range overlaps a protected range (tools/protected_ranges.txt): refused")
    sec = next(s for s in sects if s[2] <= start < s[2] + s[3])
    code = d[sec[4] + start - sec[2]:sec[4] + min(end, sec[2] + sec[3]) - sec[2]]
    md = capstone.Cs(capstone.CS_ARCH_X86 if arch == "x86_64" else capstone.CS_ARCH_ARM64,
                     capstone.CS_MODE_64 if arch == "x86_64" else capstone.CS_MODE_ARM)
    out = ["%s @ 0x%x .. 0x%x" % (syms.get(start, "?"), start, end)]
    for n, ins in enumerate(md.disasm(code, start)):
        if n >= limit: out.append("... (limit)"); break
        tgt = ""
        if ins.mnemonic in ("call", "jmp", "bl", "b") and ins.op_str.startswith(("0x", "#0x")):
            t = int(ins.op_str.lstrip("#"), 16)
            tgt = "  ; " + syms.get(t, "") if t in syms else ""
        out.append("  %x: %-8s %s%s" % (ins.address, ins.mnemonic, ins.op_str, tgt))
    return out

def words(d: bytes, start: int, n: int) -> list[str]:
    """n pointer-sized words at start (a vtable, a data table), each named when it points at a symbol; a chained-fixup rebase keeps its target in the low 36 bits."""
    sects, _starts, syms = macho(d)
    sec = next(s for s in sects if s[2] <= start < s[2] + s[3])
    out = []
    for k in range(n):
        raw = struct.unpack_from("<Q", d, sec[4] + start - sec[2] + 8 * k)[0]
        t = raw & ((1 << 36) - 1) if raw >> 63 == 0 and raw >> 36 else raw
        out.append("  +0x%02x: 0x%016x -> 0x%x %s" % (8 * k, raw, t, syms.get(t, "")))
    return out

def resolve(d: bytes, what: str) -> int:
    """An address from 0x... or a symbol name (leading underscore optional)."""
    if what.startswith("0x"): return int(what, 16)
    _s, _f, syms = macho(d)
    hit = syms.get(what, syms.get("_" + what))
    if hit is None: raise KeyError("no symbol %s" % what)
    return hit

###############
# run
###############
_d = slice_of(open(sys.argv[1], "rb").read(), sys.argv[2])
if len(sys.argv) > 5 and sys.argv[4] == "words":
    for _ln in words(_d, resolve(_d, sys.argv[3]), int(sys.argv[5])): print(_ln)
else:
    for _ln in disasm(_d, sys.argv[2], resolve(_d, sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else MAX_INSNS): print(_ln)
