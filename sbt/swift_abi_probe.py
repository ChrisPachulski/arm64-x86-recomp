"""Shows the swiftcc register mapping from compiler output: one probe module compiled by swiftc -O -S for arm64 and
x86_64, and the instructions of each probe function that touch the self, error, async-context and indirect-result
registers, the result registers and the packed stack arguments. Prints the evidence per probe and arch."""
###############
# imports and constants
###############
from __future__ import annotations
import os, re, subprocess, tempfile

PROBE = """
public struct E: Error {}
public final class C { public var x = 1
  @inline(never) public func m(_ k: Int) throws -> (Int, Int, Double, Int) { if k == 7 { throw E() }; return (x &+ k, 2, 0.5, 3) } }
public struct Big { public var a, b, c, d, e: Int }
@inline(never) public func big(_ k: Int) -> Big { Big(a: k, b: 1, c: 2, d: 3, e: 4) }
@inline(never) public func many(_ a: Int, _ b: Int, _ c: Int, _ d: Int, _ e: Int, _ f: Int, _ g: Int, _ h: Int,
                                _ i: Int8, _ j: Int8, _ k: Int32, _ l: Int) -> Int { a&+b&+c&+d&+e&+f&+g&+h&+Int(i)&+Int(j)&+Int(k)&+l }
@inline(never) public func fp(_ a: Double, _ b: Float, _ c: Int) -> (Double, Float) { (a * 2, b + Float(c)) }
@inline(never) public func asy(_ k: Int) async -> Int { k &+ 1 }
"""
PROBES = {"C.m (method: self, error, 4 results)": r"_\$s5probe1CC1my", "big (indirect result)": r"_\$s5probe3bigy",
          "many (8 GPRs then the stack)": r"_\$s5probe4many", "fp (float args and results)": r"_\$s5probe2fpy",
          "asy (async context)": r"_\$s5probe3asyy"}
WATCH = {"arm64": r"\b(x20|x21|x22|x8|x[0-3]|w[0-3]|d[0-1]|s[0-1]|v[0-1]|sp|ret)\b", "x86_64": r"%(r13|r12|r14|rax|rdx|rcx|r8|rdi|rsi|xmm[0-1])\b|\bretq\b|\d+\(%rbp\)"}
MAX_LINES = 40                                                         # instructions shown per probe

###############
# functions
###############
def compile_asm(arch: str, work: str) -> str:
    src = os.path.join(work, "probe.swift")
    open(src, "w").write(PROBE)
    out = os.path.join(work, "probe.%s.s" % arch)
    subprocess.run(["xcrun", "swiftc", "-O", "-parse-as-library", "-module-name", "probe", "-target", "%s-apple-macos13" % arch,
                    "-emit-assembly", src, "-o", out], check=True, capture_output=True, text=True, timeout=600)
    return open(out).read()

def body(asm: str, sym: str) -> list[str]:
    """Instructions of the function whose label matches sym (until its first return)."""
    lines = asm.splitlines()
    start = next(i for i, ln in enumerate(lines) if re.match(sym + r"\w*:$", ln))
    out = []
    for ln in lines[start + 1:]:
        s = ln.strip()
        if not s or s.startswith((".", ";", "#", "Lloh", "Ltmp")) or s.endswith(":"): continue
        out.append(s)
        if s.split()[0] in ("ret", "retq") and len(out) > 4: break    # the method's throw path returns early: keep going once
    return out

def evidence(asm: str, sym: str, arch: str) -> list[str]:
    return [s for s in body(asm, sym) if re.search(WATCH[arch], s)][:MAX_LINES]

###############
# run
###############
work = tempfile.mkdtemp(prefix="swift_abi_")
asm = {a: compile_asm(a, work) for a in ("arm64", "x86_64")}
for title, sym in PROBES.items():
    for arch in ("arm64", "x86_64"):
        print("== %s [%s]" % (title, arch))
        for s in evidence(asm[arch], sym, arch): print("   ", s)
