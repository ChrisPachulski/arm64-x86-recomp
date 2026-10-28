"""Control-flow regression cases for lane M3a2 code-versus-data (recursive descent, br kinds, jump tables): each arm64
snippet is lifted whole (read= supplied, inside= from recompile.code_refs when the lifter has it), compiled x86-64
and diffed against Unicorn; native dispatch to anything but the caller is the production abort. Prints one line per
case and a summary. Run bare: sbtenv/bin/python sbt/cases_m3a2_cf.py [sbt dir to test, default this one]"""
###############
# imports and constants
###############
from __future__ import annotations
import os, struct, subprocess, sys, tempfile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UcError
from unicorn.arm64_const import (UC_ARM64_REG_SP, UC_ARM64_REG_X0, UC_ARM64_REG_X29, UC_ARM64_REG_X30, UC_ARM64_REG_PC,
                                 UC_ARM64_REG_NZCV, UC_CPU_ARM64_MAX)
SBT = os.path.abspath(sys.argv[1]) if sys.argv[1:] else os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SBT)
import recompile as R

GUEST_BASE, CODE, DATA, STOP = 0x200000000, 0x10000, 0x240000000, 0x500000000
HI_PAGE = 0x1000                                                       # bytes mapped at GUEST_BASE + CODE + 4 GB on both sides
CPU_BYTES = 808                                                       # sizeof(CPU): X31 SP NZCV V32 fault fpc unw (800 before lane M4a's unw)
HOOKS = r"""
#include <stdio.h>
#include <stdlib.h>
void extern_stub(CPU*c,uint64_t a){ c->fault=2; c->fpc=a; }
void unsupported(CPU*c,uint64_t a){ c->fault=3; c->fpc=a; }
void dispatch(CPU*c,uint64_t a){ if(a!=0x500000000ULL){ c->fault=4; c->fpc=a; } }
void gd_die(const char*w,uint64_t a){ fprintf(stderr,"%s %llx\n",w,(unsigned long long)a); exit(5); }
"""
MAIN = r"""
#include <sys/mman.h>
int main(int argc,char**argv){
  if(mmap((void*)0x240000000ULL,0x10000,PROT_READ|PROT_WRITE,MAP_FIXED|MAP_ANON|MAP_PRIVATE,-1,0)==MAP_FAILED) return 90;
  if(mmap((void*)0x200010000ULL,0x1000,PROT_READ|PROT_WRITE,MAP_FIXED|MAP_ANON|MAP_PRIVATE,-1,0)==MAP_FAILED) return 91;
  if(mmap((void*)0x300010000ULL,0x1000,PROT_READ|PROT_WRITE,MAP_FIXED|MAP_ANON|MAP_PRIVATE,-1,0)==MAP_FAILED) return 92;
  FILE*rf=fopen(argv[1],"rb"); fread((void*)0x200010000ULL,1,0x1000,rf); fclose(rf);
  FILE*mf=fopen(argv[4],"rb"); fread((void*)0x240000100ULL,1,0x100,mf); fclose(mf);
  FILE*hf=fopen(argv[5],"rb"); fread((void*)0x300010000ULL,1,0x1000,hf); fclose(hf);
  CPU c; memset(&c,0,sizeof c); if(sizeof c!=800&&sizeof c!=808) return 93;
  FILE*f=fopen(argv[2],"rb"); fread(&c,1,sizeof c,f); fclose(f);
  snippet(&c);
  FILE*o=fopen(argv[3],"wb"); fwrite(&c,1,sizeof c,o); fclose(o);
  return 0;
}
"""
TABLE_TAIL = "A:\nmov x0,#11\nret\nB:\nmov x0,#22\nret\nC:\nmov x0,#33\nret\n.p2align 2\ntable:\n.byte 0,2,4,0"
CASES = [
    {"name": "f1 br arg -> interior label", "asm": "br x0\ntarget:\nmov x0,#42\nret", "code_regs": {0: 4}},
    {"name": "f1 same, image proof has it", "asm": "br x0\ntarget:\nmov x0,#42\nret", "code_regs": {0: 4}, "proof": [4]},
    {"name": "f1 adr-taken label via memory", "asm": "adr x9,target\nstr x9,[x1]\nldr x0,[x1]\nbr x0\ntarget:\nmov x0,#42\nret",
     "regs": {1: DATA + 0x100}, "proof": []},
    {"name": "f2 join: other path (x0=0)", "asm": "adr x1,A\ncbz x0,join\nadr x1,B\njoin:\nbr x1\nA:\nmov x0,#11\nret\nB:\nmov x0,#22\nret",
     "regs": {0: 0}},
    {"name": "f2 join: fall path (x0=1)", "asm": "adr x1,A\ncbz x0,join\nadr x1,B\njoin:\nbr x1\nA:\nmov x0,#11\nret\nB:\nmov x0,#22\nret",
     "regs": {0: 1}},
    {"name": "f3 b.hi into the load (x0=2)", "asm": "cmp w0,#1\nb.hi load\nnop\nload:\nadr x1,table\nadr x2,A\nldrb w3,[x1,x0]\n"
     "add x2,x2,x3,lsl #2\nbr x2\n" + TABLE_TAIL, "regs": {0: 2}},
    {"name": "w bound, x index (x0=2^32+1)", "asm": "cmp w0,#1\nb.hi out\nadr x1,table\nadr x2,A\nldrb w3,[x1,x0]\n"
     "add x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\n" + TABLE_TAIL, "regs": {0: 2 ** 32 + 1}, "hi_table": {1: 4}},
    {"name": "ctl bounded table (x0=2)", "asm": "cmp w0,#2\nb.hi out\nadr x1,table\nadr x2,A\nldrb w3,[x1,w0,uxtw]\n"
     "add x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\n" + TABLE_TAIL, "regs": {0: 2}, "cases": 4},
    {"name": "ctl bounded table (x0=7)", "asm": "cmp w0,#2\nb.hi out\nadr x1,table\nadr x2,A\nldrb w3,[x1,w0,uxtw]\n"
     "add x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\n" + TABLE_TAIL, "regs": {0: 7}, "cases": 4},
    {"name": "ctl bound past a load (x0=2)", "asm": "cmp w0,#2\nldr x9,[x1]\nb.hi out\nadr x1,table\nadr x2,A\n"
     "ldrb w3,[x1,w0,uxtw]\nadd x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\n" + TABLE_TAIL, "regs": {0: 2, 1: DATA + 0x100}, "cases": 4},
    {"name": "ctl bound past a load (x0=7)", "asm": "cmp w0,#2\nldr x9,[x1]\nb.hi out\nadr x1,table\nadr x2,A\n"
     "ldrb w3,[x1,w0,uxtw]\nadd x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\n" + TABLE_TAIL, "regs": {0: 7, 1: DATA + 0x100}, "cases": 4},
    {"name": "ctl flags reset after the cmp", "asm": "cmp w0,#2\ncmn x9,#0\nb.hi out\nadr x1,table\nadr x2,A\n"
     "ldrb w3,[x1,w0,uxtw]\nadd x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\n" + TABLE_TAIL, "regs": {0: 2}, "not_cases": 4},
    {"name": "ctl index rewritten after the cmp", "asm": "cmp w0,#2\nmov w0,#1\nb.hi out\nadr x1,table\nadr x2,A\n"
     "ldrb w3,[x1,w0,uxtw]\nadd x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\n" + TABLE_TAIL, "regs": {0: 2}, "not_cases": 4},
    {"name": "ctl cmp on the copy's source", "asm": "mov x20,x0\ncmp w0,#2\nb.hi out\nmov w8,w20\nadr x1,table\nadr x2,A\n"
     "ldrb w3,[x1,x8]\nadd x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\n" + TABLE_TAIL, "regs": {0: 2}, "cases": 4},
    {"name": "ctl source rewritten after the copy", "asm": "mov x20,x0\nmov x0,#1\ncmp w0,#2\nb.hi out\nmov w8,w20\nadr x1,table\n"
     "adr x2,A\nldrb w3,[x1,x8]\nadd x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\n" + TABLE_TAIL, "regs": {0: 2}, "not_cases": 4},
    {"name": "ctl masked index, cmp on its twin", "asm": "and w8,w0,#0xffff\ncmp w8,#2\nb.hi out\nand x8,x0,#0xffff\nadr x1,table\n"
     "adr x2,A\nldrb w3,[x1,x8]\nadd x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\n" + TABLE_TAIL, "regs": {0: 2}, "cases": 4},
    {"name": "ctl masked index, other source", "asm": "and w8,w0,#0xffff\ncmp w8,#2\nb.hi out\nand x8,x9,#0xffff\nadr x1,table\n"
     "adr x2,A\nldrb w3,[x1,x8]\nadd x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\n" + TABLE_TAIL, "regs": {0: 2, 9: 2}, "not_cases": 4},
    {"name": "ctl table base set before a join", "asm": "adr x22,table\ncbz x5,loop\nnop\nloop:\ncmp w0,#2\nb.hi out\nadr x2,A\n"
     "ldrb w3,[x22,w0,uxtw]\nadd x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\n" + TABLE_TAIL, "regs": {0: 2}, "cases": 4},
    {"name": "ctl two bases into the join", "asm": "adr x22,table\ncbz x5,loop\nadr x22,A\nloop:\ncmp w0,#2\nb.hi out\nadr x2,A\n"
     "ldrb w3,[x22,w0,uxtw]\nadd x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\n" + TABLE_TAIL, "regs": {0: 2}, "not_cases": 4},
    {"name": "ctl a table target rebases the table", "asm": "adr x22,table\ncbz x5,loop\nnop\nloop:\ncmp w0,#2\nb.hi out\nadr x2,A\n"
     "ldrb w3,[x22,w0,uxtw]\nadd x2,x2,x3,lsl #2\nbr x2\nout:\nmov x0,#99\nret\nA:\nmov x0,#11\nret\nB:\nadr x22,table2\n"
     "mov w0,#0\nb loop\nC:\nmov x0,#33\nret\nD:\nmov x0,#44\nret\n.p2align 2\ntable:\n.byte 0,2,5,0\ntable2:\n.byte 7,0,0,0",
     "regs": {0: 1}, "not_cases": 4},
    {"name": "ctl const via mov", "asm": "adr x1,B\nmov x2,x1\nbr x2\nA:\nmov x0,#11\nret\nB:\nmov x0,#22\nret", "cases": 2},
    {"name": "ctl pointer tail to caller", "asm": "ldr x0,[x1]\nbr x0\nmov x0,#7\nret", "regs": {1: DATA + 0x100},
     "mem": STOP.to_bytes(8, "little"), "cases": 1, "proof": []},
    {"name": "SVE instruction -> gd_die", "asm": ".arch_extension sve\nmov x0,#1\nadd z0.d, z0.d, z1.d\nret", "trap": "add z0.d", "at": 4},
    {"name": "mrs midr_el1 -> gd_die", "asm": "mov x0,#1\nmrs x0, midr_el1\nret", "trap": "midr_el1", "at": 4},
]

###############
# assemble, lift, run
###############
def assemble(asm: str, d: str) -> bytes:
    """clang cross-assemble; raw __text bytes from the object's section hex dump (no disassembly)."""
    s, o = os.path.join(d, "s.s"), os.path.join(d, "s.o")
    open(s, "w").write(".text\n.globl _t\n_t:\n%s\n" % asm)
    subprocess.run(["/usr/bin/clang", "-arch", "arm64", "-c", s, "-o", o], check=True, capture_output=True)
    dump = subprocess.run(["/usr/bin/otool", "-arch", "arm64", "-s", "__TEXT", "__text", o], capture_output=True, text=True).stdout
    words = [p for line in dump.splitlines()[2:] for p in line.split()[1:]]
    return b"".join(int(w, 16).to_bytes(4, "little") for w in words)

def lift(raw: bytes, ext: list | None) -> str:
    """Lift the snippet whole at CODE with read= over its bytes; with ext (interior pointers from outside the snippet, as data rebases would be) and a lifter that has code_refs, pass the image-wide inside= proof; else gdyld's default."""
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM); md.detail = True; md.skipdata = True
    insns = list(md.disasm(raw, CODE))
    read = lambda a, n: raw[a - CODE:a - CODE + n] if CODE <= a and a + n <= CODE + len(raw) else None
    refs = R.code_refs(CODE, raw) | {(CODE + o, CODE + o + 1) for o in ext} if ext is not None and hasattr(R, "code_refs") else None
    proof = {} if refs is None else {"inside": any(lo < CODE + len(raw) and hi > CODE + 1 for lo, hi in refs)}
    src, unsup, _c, _k = R.lift_function(insns, set(), "snippet", None, read, **proof)
    if unsup: raise RuntimeError("unsupported %s" % unsup)
    return src

def state(regs: dict) -> bytes:
    """CPU struct bytes with X regs set and SP in the scratch area."""
    buf = bytearray(CPU_BYTES)
    for i, v in regs.items(): struct.pack_into("<Q", buf, i * 8, v)
    struct.pack_into("<Q", buf, 248, DATA + 0x8000)
    return bytes(buf)

def oracle(raw: bytes, regs: dict, mem: bytes, hi: bytes) -> dict | str:
    """Unicorn (cpu max) from the snippet start until STOP; x regs and pc, or a fault string."""
    mu = Uc(UC_ARCH_ARM64, UC_MODE_ARM); mu.ctl_set_cpu_model(UC_CPU_ARM64_MAX)
    mu.mem_map(GUEST_BASE + CODE, 0x1000); mu.mem_write(GUEST_BASE + CODE, raw)
    mu.mem_map(GUEST_BASE + CODE + 2 ** 32, HI_PAGE); mu.mem_write(GUEST_BASE + CODE + 2 ** 32, hi)
    mu.mem_map(DATA, 0x10000); mu.mem_write(DATA + 0x100, mem)
    xr = lambda i: {29: UC_ARM64_REG_X29, 30: UC_ARM64_REG_X30}.get(i, UC_ARM64_REG_X0 + i)
    for i, v in regs.items(): mu.reg_write(xr(i), v)
    mu.reg_write(UC_ARM64_REG_SP, DATA + 0x8000); mu.reg_write(UC_ARM64_REG_NZCV, 0)
    try:
        mu.emu_start(GUEST_BASE + CODE, STOP, count=1000)
    except UcError as e:
        return "oracle fault %s at %#x" % (e, mu.reg_read(UC_ARM64_REG_PC))
    return {"x": [mu.reg_read(xr(i)) for i in range(31)], "pc": mu.reg_read(UC_ARM64_REG_PC)}

def native(src: str, raw: bytes, regs: dict, mem: bytes, hi: bytes, d: str) -> dict | str:
    """Compile lifted C x86-64 -O1 with the hooks and run it once; x regs and fault, or a failure string."""
    open(os.path.join(d, "m.c"), "w").write(R.C_PRELUDE + HOOKS + src + MAIN)
    r = subprocess.run(["/usr/bin/clang", "-arch", "x86_64", "-O1", "-w", os.path.join(d, "m.c"), "-o", os.path.join(d, "m"), "-lm"],
                       capture_output=True, text=True)
    if r.returncode: return "compile failed: " + r.stderr[:300]
    files = {"raw": raw, "in": state(regs), "mem": mem.ljust(0x100, b"\0"), "hi": hi}
    for k, v in files.items(): open(os.path.join(d, k), "wb").write(v)
    p = subprocess.run([os.path.join(d, k) for k in ("m", "raw", "in", "out", "mem", "hi")], capture_output=True, timeout=60)
    if p.returncode: return "native exit %d: %s" % (p.returncode, p.stderr.decode(errors="replace").strip())
    out = open(os.path.join(d, "out"), "rb").read()
    return {"x": list(struct.unpack_from("<31Q", out, 0)), "fault": struct.unpack_from("<i", out, 784)[0],
            "fpc": struct.unpack_from("<Q", out, 792)[0]}

def run_case(case: dict) -> tuple[str, bool, str]:
    """(name, ok, detail): oracle vs native x0..x30 and no native fault; optional br-switch case count check (cases: exactly;
    not_cases: anything else, the table must not be decoded)."""
    d = tempfile.mkdtemp(prefix="m3a2cf_")
    raw = assemble(case["asm"], d)
    regs = {**case.get("regs", {}), **{i: GUEST_BASE + CODE + v for i, v in case.get("code_regs", {}).items()}, 30: STOP}
    mem = case.get("mem", b"")
    hi = bytearray(HI_PAGE)
    for k, v in case.get("hi_table", {}).items(): hi[len(raw) - 4 + k] = v   # table bytes seen 4 GB above the code
    src = lift(raw, case.get("proof"))
    nat = native(src, raw, regs, mem, bytes(hi), d)
    if "trap" in case:                                                 # deliberate loud trap: gd_die names instruction and address
        want = ["native exit 5", case["trap"], "%x" % (CODE + case["at"])]
        return case["name"], isinstance(nat, str) and all(w in nat for w in want), str(nat)[:160]
    ora = oracle(raw, regs, mem, bytes(hi))
    ncases = src.count("ULL: goto L_")
    if isinstance(ora, str) or isinstance(nat, str): return case["name"], False, "%s | %s" % (ora, nat)
    bad = ["x%d %#x/%#x" % (i, ora["x"][i], nat["x"][i]) for i in range(31) if ora["x"][i] != nat["x"][i]]
    bad += ["native fault %d (dispatch abort) at %#x" % (nat["fault"], nat["fpc"])] if nat["fault"] else []
    bad += ["switch cases %d, want %d" % (ncases, case["cases"])] if "cases" in case and ncases != case["cases"] else []
    bad += ["switch cases %d, want any other count" % ncases] if "not_cases" in case and ncases == case["not_cases"] else []
    return case["name"], not bad, "x0 oracle %d native %d, switch cases %d%s" % (
        ora["x"][0], nat["x"][0], ncases, "; " + "; ".join(bad) if bad else "")

###############
# run
###############
print("== control-flow cases vs Unicorn, recompile from %s" % SBT)
_res = [run_case(c) for c in CASES]
for _n, _ok, _d in _res: print("  %-34s %-4s %s" % (_n, "OK" if _ok else "FAIL", _d))
print("summary: %d/%d OK" % (sum(ok for _n, ok, _d in _res), len(_res)))
