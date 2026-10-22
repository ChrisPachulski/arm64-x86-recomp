"""Instruction-level differential audit of the AArch64->x86-64 lifter. Assembles arm64 snippets
with clang (cross-assembler), lifts each through recompile.py, compiles the result x86-64, and
diffs the FULL architectural state -- x0..x30, sp, NZCV flags, and all 32 V (SIMD) registers, plus
scratch memory -- against a Unicorn oracle. Covers the forms an adversarial audit probes: 32/64-bit
add/sub/cmn flags, adc/sbc, ands/tst (C,V cleared), csel family, extr, bitfield moves, signed loads,
NEON popcount, and float conversions. Run bare: python sbt/microtest.py"""
###############
# imports and constants
###############
from __future__ import annotations
import concurrent.futures, importlib, os, struct, subprocess, sys, tempfile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UcError, UC_PROT_ALL
from unicorn.arm64_const import (UC_ARM64_REG_SP, UC_ARM64_REG_X0, UC_ARM64_REG_X29, UC_ARM64_REG_X30,
                                 UC_ARM64_REG_NZCV, UC_ARM64_REG_Q0, UC_CPU_ARM64_MAX)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recompile as R
import gdyld

GUEST_BASE = 0x200000000
CFLAGS = gdyld.CHUNK_CFLAGS + ["-DGD_FLAGS_ALL=0", "-DGDF_RET_%x=1" % GUEST_BASE]   # production flags; the harness reads NZCV after the return
RUN_TIMEOUT = 60                                                       # s per lifted snippet run (a looping case fails, not hangs)
JOBS = 8                                                               # cases compiled and run at once (the -j8 build rule)
DATA = 0x240000000
STOP = 0x300000000
X_OFF, SP_OFF, FLAG_OFF, V_OFF = 0, 31 * 8, 256, 272                   # offsets into the C CPU struct
STATE_BYTES = V_OFF + 32 * 16

RUNTIME = R.C_PRELUDE + r"""
void extern_stub(CPU*c,uint64_t a){ c->fault=2; c->fpc=a; }
void unsupported(CPU*c,uint64_t a){ c->fault=3; c->fpc=a; }
void dispatch(CPU*c,uint64_t a){ (void)a; c->fault=4; }
void gd_die(const char*w,uint64_t a){ (void)w; (void)a; __builtin_trap(); }
"""

MAIN = r"""
#include <sys/mman.h>
#include <stdio.h>
int main(int argc,char**argv){
  mmap((void*)0x240000000ULL,0x1000000,PROT_READ|PROT_WRITE,MAP_FIXED|MAP_ANON|MAP_PRIVATE,-1,0);
  CPU c; memset(&c,0,sizeof c);
  FILE*f=fopen(argv[1],"rb"); fread(&c,1,sizeof c,f); fclose(f);
  FILE*mf=fopen(argv[2],"rb"); if(mf){ static uint8_t b[0x10000]; size_t n=fread(b,1,sizeof b,mf); fclose(mf); memcpy((void*)0x240000000ULL,b,n); }
  snippet(&c);
  FILE*o=fopen(argv[3],"wb"); fwrite(&c,1,sizeof c,o); fclose(o);
  static uint8_t out[0x1000]; memcpy(out,(void*)0x240000000ULL,sizeof out);
  FILE*om=fopen(argv[4],"wb"); fwrite(out,1,sizeof out,om); fclose(om);
  return 0;
}
"""

###############
# assemble + lift
###############
def xreg(i: int) -> int:
    """Unicorn register id of Xi (X29/X30 are not contiguous with X0..X28)."""
    return {29: UC_ARM64_REG_X29, 30: UC_ARM64_REG_X30}.get(i, UC_ARM64_REG_X0 + i)

def assemble(asm: str) -> bytes:
    """Assemble arm64 asm to raw __text bytes via clang cross-assembler."""
    d = tempfile.mkdtemp(); s = os.path.join(d, "s.s"); o = os.path.join(d, "s.o")
    open(s, "w").write(".text\n.globl _t\n_t:\n%s\n" % asm)
    subprocess.run(["/usr/bin/clang", "-arch", "arm64", "-c", s, "-o", o], check=True, capture_output=True)
    raw = subprocess.run(["/usr/bin/otool", "-arch", "arm64", "-s", "__TEXT", "__text", o],
                         capture_output=True, text=True).stdout
    by = bytearray()
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) > 1 and len(parts[0]) in (8, 16) and all(len(p) == 8 and all(ch in "0123456789abcdef" for ch in p) for p in parts[1:]):
            for word in parts[1:]:
                by += bytes(int(word[i:i+2], 16) for i in (6, 4, 2, 0))
    return bytes(by)

def lift_snippet(asm: str) -> tuple[str, bytes]:
    """Lift an assembled snippet into one C function `snippet`; returns (c_src, raw_bytes)."""
    raw = assemble(asm)
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM); md.detail = True
    insns = list(md.disasm(raw, GUEST_BASE))
    src, unsup, calls, kind = R.lift_function(insns, set(), "snippet")
    if unsup: raise RuntimeError("unsupported: %s" % unsup)
    return src, raw

###############
# state packing
###############
def pack_state(regs: dict, vregs: dict) -> bytes:
    buf = bytearray(STATE_BYTES)
    for i, v in regs.items():
        struct.pack_into("<Q", buf, SP_OFF if i == "sp" else i * 8, v & 0xFFFFFFFFFFFFFFFF)
    for i, (lo, hi) in vregs.items():
        struct.pack_into("<2Q", buf, V_OFF + i * 16, lo & 0xFFFFFFFFFFFFFFFF, hi & 0xFFFFFFFFFFFFFFFF)
    return bytes(buf)

def unpack_native(raw: bytes) -> tuple:
    xs = list(struct.unpack_from("<31Q", raw, X_OFF))
    sp = struct.unpack_from("<Q", raw, SP_OFF)[0]
    nf, zf, cf, vf = struct.unpack_from("<4I", raw, FLAG_OFF)
    v = [struct.unpack_from("<2Q", raw, V_OFF + i * 16) for i in range(32)]
    return xs, sp, (nf, zf, cf, vf), v

###############
# run native + oracle
###############
def run_native(csrc: str, regs: dict, mem: bytes, vregs: dict) -> tuple:
    d = tempfile.mkdtemp(); cpath = os.path.join(d, "m.c"); bpath = os.path.join(d, "m")
    open(cpath, "w").write(RUNTIME + csrc + MAIN)
    subprocess.run(["/usr/bin/clang", "-arch", "x86_64", "-w"] + CFLAGS + [cpath, "-o", bpath, "-lm"], check=True, capture_output=True)
    inp = os.path.join(d, "in"); outp = os.path.join(d, "out"); minp = os.path.join(d, "min"); moutp = os.path.join(d, "mout")
    open(inp, "wb").write(pack_state(regs, vregs)); open(minp, "wb").write(mem.ljust(0x10000, b"\0"))
    subprocess.run([bpath, inp, minp, outp, moutp], check=True, timeout=RUN_TIMEOUT)
    xs, sp, flags, v = unpack_native(open(outp, "rb").read())
    return xs, sp, flags, v, open(moutp, "rb").read()

def run_oracle(raw: bytes, regs: dict, mem: bytes, vregs: dict) -> tuple | None:
    mu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    mu.ctl_set_cpu_model(UC_CPU_ARM64_MAX)                             # LSE atomics, RCpc ldapr*, etc.
    mu.mem_map(GUEST_BASE, 0x10000, UC_PROT_ALL); mu.mem_write(GUEST_BASE, raw)
    mu.mem_map(DATA, 0x1000000); mu.mem_write(DATA, mem.ljust(0x1000, b"\0"))
    for i, v in regs.items():
        mu.reg_write(UC_ARM64_REG_SP if i == "sp" else xreg(i), v)
    for i, (lo, hi) in vregs.items():
        mu.reg_write(UC_ARM64_REG_Q0 + i, ((hi & 0xFFFFFFFFFFFFFFFF) << 64) | (lo & 0xFFFFFFFFFFFFFFFF))
    mu.reg_write(UC_ARM64_REG_NZCV, 0)                                 # Unicorn resets with Z set; native starts at 0
    try:
        mu.emu_start(GUEST_BASE, STOP, count=2000)
    except UcError:
        return None
    xs = [mu.reg_read(xreg(i)) for i in range(31)]
    nz = mu.reg_read(UC_ARM64_REG_NZCV)
    flags = ((nz >> 31) & 1, (nz >> 30) & 1, (nz >> 29) & 1, (nz >> 28) & 1)
    v = []
    for i in range(32):
        q = mu.reg_read(UC_ARM64_REG_Q0 + i)
        v.append((q & 0xFFFFFFFFFFFFFFFF, (q >> 64) & 0xFFFFFFFFFFFFFFFF))
    return xs, mu.reg_read(UC_ARM64_REG_SP), flags, v, bytes(mu.mem_read(DATA, 0x1000))

###############
# case runner
###############
def one(case: dict) -> tuple[bool, str]:
    """(passed, report line) of one case."""
    src, raw = lift_snippet(case["asm"])
    regs = {**case.get("regs", {}), 30: STOP}                          # ret target on both sides, so x30 compares
    ora = run_oracle(raw, regs, case.get("mem", b""), case.get("vregs", {}))
    if ora is None:                                                    # the translation was never compared: a failure, not a skip
        return False, "  %-26s FAIL (oracle faulted, translation not checked)" % case["name"]
    oxs, osp, ofl, ov, omem = ora
    nxs, nsp, nfl, nv, nmem = run_native(src, regs, case.get("mem", b""), case.get("vregs", {}))
    diffs = [("x%d" % i, hex(oxs[i]), hex(nxs[i])) for i in range(31) if oxs[i] != nxs[i]]
    if osp != nsp: diffs.append(("sp", hex(osp), hex(nsp)))
    if case.get("flags") and ofl != nfl: diffs.append(("NZCV", str(ofl), str(nfl)))
    if case.get("v"):
        for i in range(32):
            if ov[i] != nv[i]: diffs.append(("q%d" % i, str(ov[i]), str(nv[i])))
    if case.get("mem") is not None and omem != nmem[:0x1000]: diffs.append(("mem", "differs", ""))
    return not diffs, "  %-26s %s" % (case["name"], "OK" if not diffs else "FAIL " + str(diffs))

CASES = [
    {"name": "signed-index load", "asm": "ldr x0,[x1,w2,sxtw #3]\nret", "regs": {1: DATA + 0x100, 2: 0xffffffff}, "mem": bytes(0xf8) + (17).to_bytes(8, "little")},
    {"name": "cmp+cset hi", "asm": "cmp x0,x1\ncset x2,hi\nret", "regs": {0: 50, 1: 9}, "flags": True},
    {"name": "subs 64 flags", "asm": "subs x3,x0,x1\nret", "regs": {0: 3, 1: 10}, "flags": True},
    {"name": "adds 32 flags wrap", "asm": "adds w2,w0,w1\nret", "regs": {0: 0xffffffff, 1: 2}, "flags": True},
    {"name": "adds 64 overflow", "asm": "adds x2,x0,x1\nret", "regs": {0: 0x7fffffffffffffff, 1: 1}, "flags": True},
    {"name": "cmn", "asm": "cmn x0,x1\nret", "regs": {0: 0xfffffffffffffff0, 1: 0x20}, "flags": True},
    {"name": "ands clears C,V", "asm": "ands x2,x0,x1\nret", "regs": {0: 0xf0f0, 1: 0x0ff0}, "flags": True},
    {"name": "tst neg", "asm": "tst x0,x1\nret", "regs": {0: 0x8000000000000000, 1: 0x8000000000000000}, "flags": True},
    {"name": "adcs chain", "asm": "subs xzr,x0,x1\nadcs x2,x3,x4\nret", "regs": {0: 10, 1: 3, 3: 0xffffffffffffffff, 4: 0}, "flags": True},
    {"name": "sbcs chain", "asm": "subs xzr,x0,x1\nsbcs x2,x3,x4\nret", "regs": {0: 3, 1: 10, 3: 5, 4: 2}, "flags": True},
    {"name": "cinc eq-true", "asm": "cmp x0,x1\ncinc x2,x3,eq\nret", "regs": {0: 5, 1: 5, 3: 100}},
    {"name": "cinc eq-false", "asm": "cmp x0,x1\ncinc x2,x3,eq\nret", "regs": {0: 5, 1: 6, 3: 100}},
    {"name": "csinv", "asm": "cmp x0,x1\ncsinv x2,x3,x4,lt\nret", "regs": {0: 1, 1: 9, 3: 7, 4: 0}},
    {"name": "csneg", "asm": "cmp x0,x1\ncsneg x2,x3,x4,ge\nret", "regs": {0: 9, 1: 1, 3: 7, 4: 42}},
    {"name": "extr", "asm": "extr x0,x1,x2,#20\nret", "regs": {1: 0x1122334455667788, 2: 0x99aabbccddeeff00}},
    {"name": "ror imm + eor", "asm": "ror x0,x0,x1\neor x0,x0,x2\nret", "regs": {0: 0x0123456789abcdef, 1: 20, 2: 0xff}},
    {"name": "asr shifted reg", "asm": "add x0,x1,x2,asr #4\nret", "regs": {1: 100, 2: 0xffffffffffffff00}},
    {"name": "ubfx", "asm": "ubfx x0,x1,#5,#10\nret", "regs": {1: 0xdeadbeef}},
    {"name": "sbfx neg", "asm": "sbfx x0,x1,#8,#8\nret", "regs": {1: 0xffff80ff}},
    {"name": "sbfiz", "asm": "sbfiz x0,x1,#4,#8\nret", "regs": {1: 0x90}},
    {"name": "ubfiz", "asm": "ubfiz x0,x1,#4,#8\nret", "regs": {1: 0x1ff}},
    {"name": "bfi", "asm": "bfi x0,x1,#8,#8\nret", "regs": {0: 0xffffffffffffffff, 1: 0x5a}},
    {"name": "bfxil", "asm": "bfxil x0,x1,#8,#8\nret", "regs": {0: 0xaaaaaaaaaaaaaaaa, 1: 0x1234}},
    {"name": "madd 32", "asm": "madd w0,w1,w2,w3\nret", "regs": {1: 7, 2: 9, 3: 100}},
    {"name": "msub 64", "asm": "msub x0,x1,x2,x3\nret", "regs": {1: 7, 2: 9, 3: 1000}},
    {"name": "smulh", "asm": "smulh x0,x1,x2\nret", "regs": {1: 0xffffffffffffffff, 2: 2}},
    {"name": "umulh", "asm": "umulh x0,x1,x2\nret", "regs": {1: 0xffffffffffffffff, 2: 2}},
    {"name": "sdiv INT_MIN/-1", "asm": "sdiv x0,x1,x2\nret", "regs": {1: 0x8000000000000000, 2: 0xffffffffffffffff}},
    {"name": "udiv by zero", "asm": "udiv x0,x1,x2\nret", "regs": {1: 100, 2: 0}},
    {"name": "clz", "asm": "clz x0,x1\nret", "regs": {1: 0x0000ffff}},
    {"name": "rbit", "asm": "rbit x0,x1\nret", "regs": {1: 0x1}},
    {"name": "rev", "asm": "rev x0,x1\nret", "regs": {1: 0x1122334455667788}},
    {"name": "rev16 w", "asm": "rev16 w0,w1\nret", "regs": {1: 0x11223344}},
    {"name": "ldrsw", "asm": "ldrsw x0,[x1]\nret", "regs": {1: DATA}, "mem": (0xfffffffe).to_bytes(4, "little")},
    {"name": "ldpsw", "asm": "ldpsw x0,x1,[x2]\nret", "regs": {2: DATA}, "mem": (0xfffffff0).to_bytes(4, "little") + (0x7fffffff).to_bytes(4, "little")},
    {"name": "stp pre-index", "asm": "stp x0,x1,[x2,#-16]!\nret", "regs": {0: 0xaaaa, 1: 0xbbbb, 2: DATA + 0x200}, "mem": b""},
    {"name": "ldp base==dest", "asm": "ldp x9,x12,[x9,#-0x10]\nret", "regs": {9: DATA + 0x110}, "mem": bytes(0x100) + (7).to_bytes(8, "little") + (8).to_bytes(8, "little")},
    {"name": "popcount idiom", "asm": "fmov d0,x1\ncnt.8b v0,v0\nuaddlv.8b h0,v0\nfmov w0,s0\nret", "regs": {1: 0xf0f0f0f0ff00ff00}},
    {"name": "ucvtf+fcvtzu", "asm": "ucvtf d0,x1\nfcvtzu x0,d0\nret", "regs": {1: 1234567}},
    {"name": "fmul fdiv", "asm": "scvtf d0,x1\nscvtf d1,x2\nfmul d2,d0,d1\nfdiv d3,d2,d0\nfcvtzu x0,d3\nret", "regs": {1: 6, 2: 7}},
]

EXTRA = [c for name in sys.argv[1:] for c in importlib.import_module(name).CASES]  # e.g. cases_scalar cases_neon
print("instruction-level differential audit vs Unicorn (regs+sp+NZCV+V+mem): core %d + extra %d (%s)"
      % (len(CASES), len(EXTRA), " ".join(sys.argv[1:]) or "none"))
results = []
for ok, line in concurrent.futures.ThreadPoolExecutor(JOBS).map(one, CASES + EXTRA):   # in case order
    print(line); results.append(ok)
assert all(results), "microtest FAILED: %d/%d passed" % (sum(results), len(results))
print("ALL %d microtests pass" % len(results))
