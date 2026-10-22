"""Mach-O arm64 loader for the recompiler: segments, sections, __text + LC_FUNCTION_STARTS,
chained fixups (rebases and binds) with the import table, and __stubs -> GOT -> import name.
Builds the flat guest image with fixups applied. Library; proven by tests/adv/run_adv.py and the other gdyld beds."""
###############
# imports and constants
###############
from __future__ import annotations
import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

LC_SEGMENT_64 = 0x19
LC_FUNCTION_STARTS = 0x26
LC_DYLD_CHAINED_FIXUPS = 0x80000034
CHAINED_PTR_64, CHAINED_PTR_64_OFFSET = 2, 6
CHAINED_IMPORT, CHAINED_IMPORT_ADDEND, CHAINED_IMPORT_ADDEND64 = 1, 2, 3
IMPORT_FORMATS = (CHAINED_IMPORT, CHAINED_IMPORT_ADDEND, CHAINED_IMPORT_ADDEND64)
PAGE_NO_FIXUPS = 0xFFFF
STUB_SIZE = 12                                                         # adrp x16 / ldr x16,[x16,#o] / br x16

###############
# parsing
###############
def uleb(b: bytes, i: int) -> tuple[int, int]:
    """Decode one ULEB128 at b[i]; return (value, next index)."""
    r = s = 0
    while True:
        c = b[i]; i += 1; r |= (c & 0x7F) << s; s += 7
        if c < 0x80: return r, i

def chained_fixups(data: bytes, segs: list, off: int, size: int, base: int) -> tuple[list, list]:
    """Walk LC_DYLD_CHAINED_FIXUPS. Returns ([(vmaddr, 'rebase'|'bind', target_or_ordinal, addend)], import_names)."""
    cf = data[off:off + size]
    _, starts_off, imports_off, syms_off, imports_count, imports_fmt, _ = struct.unpack_from("<7I", cf, 0)
    assert imports_fmt in IMPORT_FORMATS, imports_fmt
    names, imp_add = [], []
    for k in range(imports_count):
        if imports_fmt == CHAINED_IMPORT:
            name_off, add = struct.unpack_from("<I", cf, imports_off + 4 * k)[0] >> 9, 0
        elif imports_fmt == CHAINED_IMPORT_ADDEND:
            v, add = struct.unpack_from("<Ii", cf, imports_off + 8 * k); name_off = v >> 9
        else:
            _, name_off, add = struct.unpack_from("<IIq", cf, imports_off + 16 * k)
        start = syms_off + name_off
        names.append(cf[start:cf.index(b"\0", start)].decode()); imp_add.append(add)
    fixups = []
    seg_count = struct.unpack_from("<I", cf, starts_off)[0]
    for si in range(seg_count):
        so = struct.unpack_from("<I", cf, starts_off + 4 + 4 * si)[0]
        if so == 0: continue
        p = starts_off + so
        _, page_size, pfmt = struct.unpack_from("<IHH", cf, p)
        page_count = struct.unpack_from("<H", cf, p + 20)[0]
        pages = struct.unpack_from("<%dH" % page_count, cf, p + 22)
        assert pfmt in (CHAINED_PTR_64, CHAINED_PTR_64_OFFSET), pfmt
        vmaddr, _, fileoff, _ = segs[si]
        for pi, ps in enumerate(pages):
            if ps == PAGE_NO_FIXUPS: continue
            assert not ps & 0x8000, "multi-start pages are 32-bit formats only"
            o = pi * page_size + ps
            while True:
                v = struct.unpack_from("<Q", data, fileoff + o)[0]
                if v >> 63:
                    fixups.append((vmaddr + o, "bind", v & 0xFFFFFF, ((v >> 24) & 0xFF) + imp_add[v & 0xFFFFFF]))
                else:
                    tgt = (v & 0xFFFFFFFFF) + (base if pfmt == CHAINED_PTR_64_OFFSET else 0)
                    fixups.append((vmaddr + o, "rebase", tgt | (((v >> 36) & 0xFF) << 56), 0))
                nxt = (v >> 51) & 0xFFF
                if nxt == 0: break
                o += nxt * 4
    return fixups, names

def load_macho(path: str) -> dict:
    """Parse one arm64 Mach-O into segs/sects/text/fstarts/fixups/imports/base."""
    data = open(path, "rb").read()
    ncmds = struct.unpack_from("<I", data, 16)[0]
    i = 32; segs = []; segnames = []; sects = {}; cmds = {}
    for _ in range(ncmds):
        cmd, sz = struct.unpack_from("<II", data, i)
        if cmd == LC_SEGMENT_64:
            segnames.append(data[i + 8:i + 24].rstrip(b"\0").decode())
            segs.append(struct.unpack_from("<4Q", data, i + 24))
            for k in range(struct.unpack_from("<I", data, i + 64)[0]):
                s = i + 72 + 80 * k
                sn = data[s:s + 16].rstrip(b"\0").decode(); sg = data[s + 16:s + 32].rstrip(b"\0").decode()
                addr, size = struct.unpack_from("<2Q", data, s + 32)
                sects[(sg, sn)] = (addr, size, struct.unpack_from("<I", data, s + 48)[0])
        elif cmd in (LC_FUNCTION_STARTS, LC_DYLD_CHAINED_FIXUPS):
            cmds[cmd] = struct.unpack_from("<II", data, i + 8)
        i += sz
    base = segs[segnames.index("__TEXT")][0]
    off, size = cmds[LC_FUNCTION_STARTS]; b = data[off:off + size]; a = base; j = 0; fs = []
    while j < len(b):
        d, j = uleb(b, j)
        if d == 0: break
        a += d; fs.append(a)
    taddr, tsize, toff = sects[("__TEXT", "__text")]
    fixups, imports = chained_fixups(data, segs, *cmds[LC_DYLD_CHAINED_FIXUPS], base)
    return {"data": data, "segs": segs, "segnames": segnames, "sects": sects, "base": base,
            "text": (taddr, data[toff:toff + tsize]), "fstarts": fs, "fixups": fixups, "imports": imports}

###############
# image + stubs
###############
def build_image(m: dict, guest_base: int | None, import_addr: object) -> bytes:
    """Flat image (segments at vmaddr-base); with guest_base, rebases/binds are applied, else raw bytes."""
    base = m["base"]
    img = bytearray(max(v + vs for v, vs, _, _ in m["segs"]) - base)
    for vmaddr, _, fileoff, filesize in m["segs"]:
        img[vmaddr - base:vmaddr - base + filesize] = m["data"][fileoff:fileoff + filesize]
    if guest_base is None: return bytes(img)
    for vmaddr, kind, val, addend in m["fixups"]:
        ptr = guest_base + (val - base) if kind == "rebase" else import_addr(val) + addend
        struct.pack_into("<Q", img, vmaddr - base, ptr)
    return bytes(img)

def stub_imports(m: dict) -> dict:
    """__stubs entry vmaddr -> import ordinal, by decoding each stub's GOT load and resolving the GOT bind."""
    saddr, ssize, soff = m["sects"][("__TEXT", "__stubs")]
    binds = {v: val for v, kind, val, _ in m["fixups"] if kind == "bind"}
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM); md.detail = True
    out = {}
    for a in range(saddr, saddr + ssize, STUB_SIZE):
        adrp, ldr, br = md.disasm(m["data"][soff + a - saddr:soff + a - saddr + STUB_SIZE], a)
        assert (adrp.mnemonic, ldr.mnemonic, br.mnemonic) == ("adrp", "ldr", "br"), (hex(a), adrp.mnemonic)
        out[a] = binds[adrp.operands[1].imm + ldr.operands[1].mem.disp]
    return out

def iter_functions(text_addr: int, text_bytes: bytes, fstarts: list) -> object:
    """Yield (start, capstone insns) per LC_FUNCTION_STARTS range inside __text; undecodable words are '.byte' items."""
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM); md.detail = True; md.skipdata = True
    tend = text_addr + len(text_bytes)
    inside = sorted(a for a in fstarts if text_addr <= a < tend)
    bounds = inside + [tend]
    for idx, start in enumerate(inside):
        yield start, list(md.disasm(text_bytes[start - text_addr:bounds[idx + 1] - text_addr], start))

def decode_functions(text_addr: int, text_bytes: bytes, fstarts: list) -> tuple[dict, set]:
    """addr -> list of capstone insns for each function inside __text; plus the start set."""
    tend = text_addr + len(text_bytes)
    return dict(iter_functions(text_addr, text_bytes, fstarts)), {a for a in fstarts if text_addr <= a < tend}
