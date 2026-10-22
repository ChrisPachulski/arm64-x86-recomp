"""gswift: Swift for gdyld. A signature database read from swiftc's own LLVM IR (x86_64 and arm64 must agree), C++ bridges
for Swift imports (guest Apple-arm64 swiftcc/C registers -> clang swiftcall on the host), host->guest swiftcall entries,
and the static map of a guest image's Swift records: every relative function pointer the host runtime can call
(metadata accessors, resilient witnesses, generic instantiation/completion, witness-table instantiators) and every value
witness table / heap destroyer reached from them. Writes out_dir/swift_gen.hpp. Library; proven by tests/swift/run_swift.py."""
###############
# imports and constants
###############
from __future__ import annotations
import concurrent.futures, functools, hashlib, json, os, re, struct, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(HERE)
SIGDB = os.path.join(HERE, "swift_sigs.json")                         # merged signature database (build_sigdb)
DERIVED = os.path.join(HERE, "build", "swift_derived.json")           # signatures derived from the SDK interfaces (augment)
CORPUS = sorted([os.path.join(HERE, "swift_corpus", f) for f in os.listdir(os.path.join(HERE, "swift_corpus")) if f.endswith(".swift")]
                + [os.path.join(LANE, "tests", "swift", f) for f in os.listdir(os.path.join(LANE, "tests", "swift")) if f.endswith(".swift")])
IR_CACHE = os.path.join(HERE, "build", "swift_ir")
TARGET = "%s-apple-macos13"
JOBS = 8
SCALARS = {"i1": ("bool", 1), "i8": ("uint8_t", 1), "i16": ("uint16_t", 2), "i32": ("uint32_t", 4), "i64": ("uint64_t", 8),
           "ptr": ("void*", 8), "float": ("float", 4), "double": ("double", 8)}
SIGNED = {"i8": "int8_t", "i16": "int16_t", "i32": "int32_t"}
MASK = {"i1": "1ULL", "i8": "0xFFULL", "i16": "0xFFFFULL", "i32": "0xFFFFFFFFULL"}
PRE_WORDS = {"declare", "define", "internal", "hidden", "private", "linkonce_odr", "weak_odr", "extern_weak", "dso_local",
             "protected", "local_unnamed_addr", "unnamed_addr", "noundef", "noalias", "nonnull", "zeroext", "signext", "swiftcc",
             "swifttailcc", "available_externally", "external", "weak", "linkonce", "inreg"}
RET_EXT = {"zeroext": "z", "signext": "s"}
LIB_DIR = "usr/lib/swift"                                              # SDK .tbd stubs of the host Swift libraries
# fixed conventions of the Swift ABI, as swiftc emits them (IR: value witnesses and Mi are C, Ma / Mr / fD are swiftcc)
VWT_SIGS = {0: "c|ptr|ptr,ptr,ptr", 1: "c||ptr,ptr", 2: "c|ptr|ptr,ptr,ptr", 3: "c|ptr|ptr,ptr,ptr", 4: "c|ptr|ptr,ptr,ptr",
            5: "c|ptr|ptr,ptr,ptr", 6: "c|i32|ptr,i32,ptr", 7: "c||ptr,i32,i32,ptr", 11: "c|i32|ptr,ptr", 12: "c||ptr,ptr",
            13: "c||ptr,i32,ptr"}
CORE = {"heapdestroy": "swift||ptr:self", "access0": "swift|ptr,i64|i64", "access1": "swift|ptr,i64|i64,ptr",
        "access2": "swift|ptr,i64|i64,ptr,ptr", "access3": "swift|ptr,i64|i64,ptr,ptr,ptr", "accessN": "swift|ptr,i64|i64,ptr",
        "instantiate": "c|ptr|ptr,ptr,ptr", "complete": "swift|ptr,i64|ptr,ptr,ptr", "wtinst": "c||ptr,ptr,ptr",
        "confaccess": "swift|ptr|ptr,ptr,ptr", "assocty": "swift|ptr,i64|i64,ptr,ptr", "relocate": "c|ptr|ptr,ptr",
        # key path pattern functions (stdlib KeyPath.swift; IR of '...TK' getters, '...Tk' setters, '...TH' / '...Th')
        "kpget": "swift||ptr:sret,ptr,ptr,i64", "kpset": "swift||ptr,ptr,ptr,i64", "kplayout": "swift|i64,i64|ptr",
        "kpinit": "swift||ptr,ptr", "kpdestroy": "swift||ptr,i64", "kpcopy": "swift||ptr,ptr,i64", "kpequals": "swift|i1|ptr,ptr,i64",
        "kphash": "swift|i64|ptr,i64", "cptr1": "c|ptr|ptr", "corocont": "swift||ptr,i1",
        **{"vwt%d" % k: v for k, v in VWT_SIGS.items()}}
# imports whose parameters carry guest code or guest metadata: IR parameter index -> conversion
HOOKS = {"_swift_once": {1: "cfn"}, "_swift_allocObject": {0: "heapmd"}, "_swift_initStackObject": {0: "heapmd"},
         "_swift_getKeyPath": {0: "keypath"}}
BLOCK_MANGLING = "XB"                                                  # @convention(block) in a parameter type
CFN_MANGLING = "XC"                                                    # @convention(c) in a parameter type
ABI_SIGS = {"_swift_deletedMethodError": "swift||",                    # no parameters, never returns: every convention agrees
            "_swift_getKeyPath": "c|ptr|ptr,ptr"}                       # runtime entry point (pattern, arguments) -> key path
KIND_STRUCT, KIND_ENUM, KIND_CLASS = 17, 18, 16
SWIFT_SECTS = ("__swift5_types", "__swift5_proto", "__swift5_protos")
MASK64 = 2 ** 64 - 1
DATA_SUFFIX = re.compile(r"(N|Mn|Mp|Mc|MP|Mf|Mm|MV|Mo|TL|Tq|Tl|Tb|Tn|WP|WV|WC)$")   # Swift entity kinds that are data, not code
DATA_PREFIXES = ("__swiftEmpty", "__swift_FORCE_LOAD_", "_swift_isaMask")
S_ATTR_INSTRUCTIONS = 0x80000400
ACCESSOR_REQS = {"Tb": "confaccess", "Tn": "confaccess", "Tl": "assocty"}   # base / associated conformance, associated type
CORO_RE = re.compile(r"[vi][rM](?:TW|Tj)?$")                           # read / modify accessor of a var or subscript (yield-once)
CORO_CONT = {"cc": "swift", "ret": [], "rx": "", "params": [{"t": "ptr", "a": "", "x": ""}, {"t": "i1", "a": "", "x": ""}]}   # CORE corocont

###############
# signatures from LLVM IR
###############
def split_top(s: str) -> list[str]:
    """Comma-separated items at bracket depth 0 (brackets and commas inside a quoted LLVM name do not count)."""
    out, depth, cur, quoted = [], 0, "", False
    for ch in s:
        quoted ^= ch == '"'                                            # LLVM escapes a quote inside a name as \22
        if not quoted: depth += ch in "({[<"; depth -= ch in ")}]>"
        if ch == "," and depth == 0 and not quoted: out.append(cur.strip()); cur = ""
        else: cur += ch
    return out + ([cur.strip()] if cur.strip() else [])

def matching(s: str, i: int) -> int:
    """Index of the parenthesis closing the one at s[i] (parentheses inside a quoted LLVM name do not count)."""
    depth, quoted = 0, False
    for j in range(i, len(s)):
        quoted ^= s[j] == '"'
        if quoted: continue
        depth += s[j] == "("; depth -= s[j] == ")"
        if depth == 0: return j
    raise ValueError("unbalanced: " + s[:120])

def named_types(ll: str) -> dict[str, str]:
    return dict(re.findall(r'^(%[\w.$"<>]+) = type (\{.*\})$', ll, re.M))

def ret_types(t: str, named: dict[str, str]) -> list[str] | None:
    """IR return type -> scalar list ([] for void), None when not expressible."""
    t = named.get(t, t).strip()
    if t == "void": return []
    if t.startswith("{"):
        parts = [p.strip() for p in split_top(t.strip("{} "))]
        return parts if all(p in SCALARS for p in parts) else None
    return [t] if t in SCALARS else None

def param_of(p: str) -> dict | None:
    t = p.split()[0]
    if t not in SCALARS: return None
    a = "sret" if "sret(" in p else "self" if "swiftself" in p else "error" if "swifterror" in p else "async" if "swiftasync" in p else ""
    return {"t": t, "a": a, "x": "s" if " signext" in " " + p else "z" if " zeroext" in " " + p else ""}

def ir_functions(ll: str) -> dict[str, dict]:
    """'_symbol' -> {cc, ret, rx, params} for every declare / define whose types are all scalars."""
    named, out = named_types(ll), {}
    for ln in ll.splitlines():
        if not ln.startswith(("declare ", "define ")): continue
        at = ln.find(" @")
        m = re.match(r'@"([^"]+)"\(|@([\w$.]+)\(', ln[at + 1:])
        if not m: continue
        name = m.group(1) or m.group(2)
        if name.startswith("llvm."): continue
        lp = at + 1 + m.end() - 1
        params = [param_of(p) for p in split_top(ln[lp + 1:matching(ln, lp)])]
        pre = ln[:at]
        brace = pre.find("{")
        rt = pre[brace:pre.rfind("}") + 1] if brace >= 0 else next((w for w in reversed(pre.split()) if w not in PRE_WORDS and not w.startswith(("dereferenceable", "range(", "align"))), "")
        ret = ret_types(rt, named)
        if ret is None or any(p is None for p in params) or "..." in ln[lp:matching(ln, lp)]: continue
        rx = next((RET_EXT[w] for w in pre.split() if w in RET_EXT), "")
        out["_" + name] = {"cc": "swift" if " swiftcc " in " " + pre + " " else "c", "ret": ret, "rx": rx, "params": params}
        if CORO_RE.search(name) and ret[:1] == ["ptr"] and params[:1] and params[0]["t"] == "ptr":
            out["_" + name]["coro"] = True                            # yield-once ramp: buffer in, (continuation, yielded...) out
    return out

def witness_pairs(ll: str) -> dict[str, str]:
    """Requirement method descriptor ('_$s...Tq') -> witness thunk ('_$s...TW') from every conformance descriptor (Mc)."""
    out = {}
    for ln in ll.splitlines():
        if not re.match(r'^@"\$s[^"]*Mc" = ', ln): continue
        refs = re.findall(r'ptrtoint \(ptr @"(?:got\.)?(\$s[^"]+)"', ln)
        for i, r in enumerate(refs):
            if r.endswith("Tq"):
                tw = next((x for x in refs[i + 1:i + 2] if x.endswith("TW")), None)
                if tw: out["_" + r] = "_" + tw
    return out

def swiftc_flags(src: str) -> list[str]:
    """Extra swiftc flags named on a source's first line ('// swiftc: ...')."""
    first = open(src).readline()
    return first.split("swiftc:", 1)[1].split() if "swiftc:" in first else []

def closure_args(ll: str, funcs: dict) -> dict[str, dict[int, dict]]:
    """Import -> {IR parameter index: signature of the function passed there} from every call whose argument is a function of this module (a closure, thunk or partial-application forwarder): how the host will call it back. A Swift function value always carries its context in the self register, so a signature without one gets it appended."""
    defined = set(re.findall(r'^define [^@]*@"?([\w$.]+)"?\(', ll, re.M))
    out = {}
    for ln in ll.splitlines():
        m = re.search(r'\bcall [^@]*@"?([\w$.]+)"?\(', ln)
        if not m or m.group(1) in defined or "_" + m.group(1) not in funcs: continue
        lp = m.end() - 1
        for i, a in enumerate(split_top(ln[lp + 1:matching(ln, lp)])):
            r = re.search(r'ptr(?: [\w()]+)* @"?([\w$.]+)"?(?: to i64\))?$', a)
            if not r or r.group(1) not in defined or "_" + r.group(1) not in funcs: continue
            s = funcs["_" + r.group(1)]
            if s["cc"] == "swift" and not any(p["a"] == "self" for p in s["params"]):
                s = {**s, "params": s["params"] + [{"t": "ptr", "a": "self", "x": ""}]}
            out.setdefault("_" + m.group(1), {})[i] = s
    return out

def emit_ir(src: str, arch: str, sdk: str) -> str:
    """swiftc -O -emit-ir for one source and arch (cached by content); IR text."""
    os.makedirs(IR_CACHE, exist_ok=True)
    key = hashlib.sha256((open(src).read() + arch + sdk).encode()).hexdigest()[:20]
    out = os.path.join(IR_CACHE, "%s.%s.%s.ll" % (os.path.basename(src)[:-6], arch, key))
    if not os.path.isfile(out):
        r = subprocess.run(["xcrun", "swiftc", "-O", "-target", TARGET % arch, "-sdk", sdk, "-emit-ir"] + swiftc_flags(src) + [src, "-o", out + ".tmp"],
                           capture_output=True, text=True, timeout=900)
        if r.returncode: raise RuntimeError("swiftc -emit-ir %s %s: %s" % (src, arch, r.stderr[-1500:]))
        os.replace(out + ".tmp", out)
    return open(out).read()

def source_sigs(src: str, sdk: str) -> tuple[dict, dict, dict, list]:
    """(functions, witness signatures, closure parameters, arch disagreements) of one source; a symbol counts only when both IRs agree."""
    per = {a: emit_ir(src, a, sdk) for a in ("x86_64", "arm64")}
    fx, fa = ir_functions(per["x86_64"]), ir_functions(per["arm64"])
    bad = sorted(n for n in fx.keys() & fa.keys() if fx[n] != fa[n])
    funcs = {n: s for n, s in fx.items() if n in fa and n not in bad}
    wit = {req: funcs[tw] for req, tw in witness_pairs(per["arm64"]).items() if tw in funcs}
    clo = {n: {str(i): s for i, s in m.items()} for n, m in closure_args(per["arm64"], funcs).items()}
    return funcs, wit, clo, bad

def build_sigdb(sources: list[str], sdk: str, out: str) -> dict:
    """Merged database {'funcs', 'witness', 'closures', 'conflicts'} over the sources (two sources disagreeing on a symbol: dropped)."""
    with concurrent.futures.ThreadPoolExecutor(JOBS) as pool:
        per = list(pool.map(lambda s: source_sigs(s, sdk), sources))
    funcs, wit, clo, conflicts = {}, {}, {}, sorted({b for _f, _w, _c, bad in per for b in bad})
    for f, w, c, _b in per:
        for n, s in f.items():
            if funcs.setdefault(n, s) != s: conflicts.append(n)
        for n, s in w.items():
            if wit.setdefault(n, s) != s: conflicts.append(n)
        for n, m in c.items():
            for i, s in m.items():
                if clo.setdefault(n, {}).setdefault(i, s) != s: conflicts.append(n)
    funcs = {**{n: parse_spec(s) for n, s in ABI_SIGS.items()}, **funcs}
    db = {"funcs": {n: s for n, s in sorted(funcs.items()) if n not in conflicts},
          "witness": {n: s for n, s in sorted(wit.items()) if n not in conflicts},
          "closures": {n: m for n, m in sorted(clo.items()) if n not in conflicts}, "conflicts": sorted(set(conflicts)),
          "sources": [os.path.basename(s) for s in sources]}
    tmp = "%s.tmp%d" % (out, os.getpid())                              # whole-file replace: concurrent builders never tear it
    json.dump(db, open(tmp, "w"), indent=0, sort_keys=True)
    os.replace(tmp, out)
    return db

@functools.lru_cache(maxsize=4)
def sigdb(path: str = SIGDB) -> dict:
    """The corpus database (built first if missing), plus the interface-derived signatures (gswift_iface, written by augment) for names it lacks."""
    if path == SIGDB and not os.path.isfile(path):                    # a tree without the database builds it from its corpus once
        build_sigdb(CORPUS, subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True).stdout.strip(), path)
    db = json.load(open(path)) if os.path.isfile(path) else {"funcs": {}, "witness": {}}
    der = json.load(open(DERIVED)) if os.path.isfile(DERIVED) else {"funcs": {}, "witness": {}, "closures": {}}
    return {**db, "funcs": {**der["funcs"], **db["funcs"]}, "witness": {**der["witness"], **db.get("witness", {})},
            "closures": {**der.get("closures", {}), **db.get("closures", {})}}

def needed(images: list, names: list[str], db: dict) -> list[str]:
    """Names to derive: Swift code imports without a signature, and the dispatch thunk ('...Tj') of every host requirement ('...Tq') a guest image binds (a guest witness or override of it is lowered like that thunk)."""
    tq = {n for img in images for _a, _o, n, _w, _ad in img["binds"] if n.endswith("Tq")}
    want = {n for n in names if is_swift_import(n) and not is_swift_data(n) and n not in db["funcs"]}
    want |= {r[:-2] + "Tj" for r in tq if r not in db["witness"] or r[:-2] + "Tj" not in db["funcs"]}
    return sorted(n for n in want if n not in db["funcs"])

def augment(images: list, names: list[str], sdk: str) -> list[str]:
    """gdyld hook, before any bridge is generated: derive the missing signatures from the SDK interfaces (gswift_iface), add them to DERIVED, witness rows for their requirements; report lines."""
    import gswift_iface
    db = sigdb()
    want = needed(images, names, db)
    res = gswift_iface.derive(want, sdk) if want else {}
    got = {n: r[0] for n, r in res.items() if r[0]}
    der = json.load(open(DERIVED)) if os.path.isfile(DERIVED) else {"funcs": {}, "witness": {}, "closures": {}}
    funcs = {**der["funcs"], **got}
    wit = {**der["witness"], **{n[:-2] + "Tq": s for n, s in funcs.items() if n.endswith("Tj")}}
    clo = {**der.get("closures", {}), **{n: r[2] for n, r in res.items() if r[0] and r[2]}}
    if got:
        os.makedirs(os.path.dirname(DERIVED), exist_ok=True)
        json.dump({"funcs": funcs, "witness": wit, "closures": clo}, open(DERIVED + ".tmp%d" % os.getpid(), "w"), indent=0, sort_keys=True)
        os.replace(DERIVED + ".tmp%d" % os.getpid(), DERIVED)       # ponytail: one SDK per machine; key the file by SDK if that changes
        getattr(sigdb, "cache_clear", lambda: None)()                  # a bed may replace sigdb with its own database
    miss = sorted(n for n, r in res.items() if not r[0])
    return ["swift-iface: %d signatures missing from the corpus, %d derived from the SDK interfaces, %d not derivable (stay loud): %s" % (
        len(want), len(got), len(miss), "; ".join("%s (%s)" % (n, res[n][1][:80]) for n in miss))]

def parse_spec(spec: str) -> dict:
    """'cc|ret,ret|t:attr,t' -> signature dict (the CORE / HOOKS shorthand)."""
    cc, ret, ps = spec.split("|")
    return {"cc": cc, "ret": [r for r in ret.split(",") if r], "rx": "",
            "params": [{"t": p.split(":")[0], "a": (p.split(":") + [""])[1], "x": ""} for p in ps.split(",") if p]}

def sig_key(sig: dict) -> str:
    return hashlib.sha1(json.dumps(sig, sort_keys=True).encode()).hexdigest()[:12]

def is_swift_import(name: str) -> bool:
    """Swift runtime and overlay code symbols (the weak FORCE_LOAD markers are data)."""
    return name.startswith(("_$s", "_swift_", "__swift_")) and "FORCE_LOAD" not in name

###############
# C++ generation: guest <-> host conventions
###############
def arm64_locs(sig: dict) -> list[tuple]:
    """Apple arm64 (DarwinPCS, also swiftcc) location of each ordinary parameter: ('x', n) | ('v', n) | ('s', offset)."""
    gx = gv = so = 0
    out = []
    for p in sig["params"]:
        if p["a"]: out.append(("a", p["a"])); continue
        fp, size = p["t"] in ("float", "double"), SCALARS[p["t"]][1]
        if fp and gv < 8: out.append(("v", gv)); gv += 1
        elif not fp and gx < 8: out.append(("x", gx)); gx += 1
        else: so = (so + size - 1) // size * size; out.append(("s", so)); so += size
    return out

def ctype(p: dict) -> str:
    return SIGNED[p["t"]] if p["x"] == "s" and p["t"] in SIGNED else SCALARS[p["t"]][0]

def ret_struct(sig: dict, name: str) -> str:
    """A return struct the host lowers to the same registers: every field its own 8-byte unit (no merging)."""
    return "struct %s { %s };" % (name, " ".join("alignas(8) %s f%d;" % ("float" if t == "float" else "double" if t == "double" else "uint64_t", i)
                                                 for i, t in enumerate(sig["ret"])))

def ret_ctype(sig: dict, name: str) -> str:
    if not sig["ret"]: return "void"
    if len(sig["ret"]) > 1: return name
    t = sig["ret"][0]
    return SIGNED[t] if sig["rx"] == "s" and t in SIGNED else SCALARS[t][0]

def cc_attr(sig: dict) -> str:
    return "GSW_SWIFTCC " if sig["cc"] == "swift" else ""

def c_params(sig: dict, named: bool) -> list[str]:
    """Host C parameter list in clang's required order: indirect result, ordinary, context, error."""
    nm = lambda i: (" a%d" % i) if named else ""
    ind = "void* GSW_INDIRECT" if sig["cc"] == "swift" else "void*"   # C: the hidden struct-return pointer is rdi
    out = ["%s%s" % (ind, nm(i)) for i, p in enumerate(sig["params"]) if p["a"] == "sret"]
    out += ["%s%s" % (ctype(p), nm(i)) for i, p in enumerate(sig["params"]) if not p["a"]]
    has_err = any(p["a"] == "error" for p in sig["params"])
    selfi = [i for i, p in enumerate(sig["params"]) if p["a"] == "self"]
    if selfi or has_err: out.append("void* GSW_CONTEXT%s" % (nm(selfi[0]) if selfi else (" ctx_unused" if named else "")))
    out += ["void** GSW_ERRORRESULT%s" % nm(i) for i, p in enumerate(sig["params"]) if p["a"] == "error"]
    return out

def guest_value(p: dict, loc: tuple) -> str:
    """Expression reading one ordinary parameter from the guest CPU c."""
    t = ctype(p)
    if loc[0] == "v": return "c->V[%d].%s[0]" % (loc[1], "f32" if p["t"] == "float" else "f64")
    raw = "c->X[%d]" % loc[1] if loc[0] == "x" else "*(const %s*)(uintptr_t)(c->SP + %d)" % ("uint8_t" if p["t"] == "i1" else t, loc[1])
    if p["t"] == "i1": return "(bool)(%s & 1)" % raw
    if p["t"] == "ptr": return "(void*)(uintptr_t)(%s)" % raw
    return "(%s)(%s)" % (t, raw)

def hooks_for(name: str, sig: dict, db: dict) -> dict[int, object]:
    """Parameter conversions of one import: closures seen passed at corpus call sites (their own signature), guest blocks in a @convention(block) API, a loud check on the other pointers of a @convention(c) API whose callbacks have no signature, and the fixed runtime ones (HOOKS) last."""
    out = {int(i): {"swfn": s} for i, s in db.get("closures", {}).get(name, {}).items()}
    if BLOCK_MANGLING in name:
        out.update({i: "blk" for i, p in enumerate(sig["params"]) if p["t"] == "ptr" and not p["a"] and i not in out})
    if CFN_MANGLING in name and not any(isinstance(h, dict) and h["swfn"]["cc"] == "c" for h in out.values()):
        out.update({i: "cfnraw" for i, p in enumerate(sig["params"]) if p["t"] == "ptr" and not p["a"] and i not in out})
    return {**out, **HOOKS.get(name, {})}

def hook_expr(hook: object, e: str) -> str:
    if hook == "heapmd": return "gsw::heapmd(%s)" % e
    if hook == "blk": return "gsw::blk(%s)" % e
    if hook == "cfnraw": return "gsw::cfn_raw((uint64_t)(uintptr_t)%s)" % e
    if hook == "keypath": return "gsw::keypath(%s)" % e
    if hook == "cfn": return "(void*)gd::to_host_fn<void (*)(void*)>((uint64_t)(uintptr_t)%s)" % e
    if isinstance(hook, dict): return "gsw::closure_or_host((uint64_t)(uintptr_t)%s, (void*)&swe_%s)" % (e, sig_key(hook["swfn"]))
    raise ValueError(hook)

def to_guest(t: str, rx: str, e: str) -> str:
    """A host scalar (C type of IR t) widened to a guest x register."""
    if t == "i1": return "(uint64_t)((%s) ? 1 : 0)" % e
    if t == "ptr": return "(uint64_t)(uintptr_t)(%s)" % e
    if rx == "s" and t in SIGNED: return "(uint64_t)(int64_t)(%s)(%s)" % (SIGNED[t], e)
    return "(uint64_t)(%s)" % e

def write_rets(sig: dict, src: str, multi: bool) -> list[str]:
    """Statements storing a host result into the guest return registers (x0.., v0.. counted separately)."""
    out, gx, gv = [], 0, 0
    for i, t in enumerate(sig["ret"]):
        e = "%s.f%d" % (src, i) if multi else src
        if t in ("float", "double"):
            out.append("memset(&c->V[%d], 0, 16); c->V[%d].%s[0] = %s;" % (gv, gv, "f32" if t == "float" else "f64", e)); gv += 1
        else:
            out.append("c->X[%d] = %s;" % (gx, ("(%s) & %s" % (e, MASK[t])) if multi and t in MASK else to_guest(t, sig["rx"], e))); gx += 1
    return out

def call_body(sig: dict, hooks: dict, callee: str, rs: str, post: list[str]) -> list[str]:
    """Statements of a guest -> host call: guest CPU c's arguments, a typed call to `callee`, results back, then `post`."""
    locs = arm64_locs(sig)
    args = {}
    for i, (p, loc) in enumerate(zip(sig["params"], locs)):
        e = ("(void*)(uintptr_t)c->X[8]" if p["a"] == "sret" else "(void*)(uintptr_t)c->X[20]" if p["a"] == "self" else "&err"
             if p["a"] == "error" else guest_value(p, loc))
        args[i] = e if i not in hooks else hook_expr(hooks[i], e) if p["t"] == "ptr" else "(%s)(uintptr_t)%s" % (ctype(p), hook_expr(hooks[i], e))
    order = [i for i, p in enumerate(sig["params"]) if p["a"] == "sret"] + [i for i, p in enumerate(sig["params"]) if not p["a"]]
    call = [args[i] for i in order]
    selfi = [i for i, p in enumerate(sig["params"]) if p["a"] == "self"]
    has_err = any(p["a"] == "error" for p in sig["params"])
    if selfi or has_err: call.append(args[selfi[0]] if selfi else "nullptr")
    if has_err: call.append("&err")
    lines = ["  typedef %s (*F)(%s) %s;" % (ret_ctype(sig, rs), ", ".join(c_params(sig, False)), cc_attr(sig).strip())]
    if has_err: lines.append("  void* err = (void*)(uintptr_t)c->X[21];")
    expr = "((F)(%s))(%s)" % (callee, ", ".join(call))
    lines.append(("  %s r = %s;" % (ret_ctype(sig, rs), expr)) if sig["ret"] else "  %s;" % expr)
    if has_err: lines.append("  c->X[21] = (uint64_t)(uintptr_t)err;")
    return lines + ["  " + s for s in write_rets(sig, "r", len(sig["ret"]) > 1) + post]

def returned_code(name: str, sig: dict) -> list[str]:
    """Conversions of host code a call returns to the guest: a coroutine's continuation, a class method lookup's result."""
    if sig.get("coro"): return ["c->X[0] = code_to_guest(c->X[0], &swh_%s);" % sig_key(CORO_CONT)]
    if (name.endswith("Mu") or name == "_swift_lookUpClassMethod") and sig["ret"] == ["ptr"]: return ["c->X[0] = gsw::host_method(c->X[0], c->X[1]);"]
    return []

def bridge_code(name: str, sig: dict, hooks: dict, weak: bool = False) -> str:
    """Guest -> host bridge swb_<h> of one import: calls the library-qualified address (QFN) or the symbol linked by name."""
    h = hashlib.sha1(name.encode()).hexdigest()[:12]
    if any(p["a"] == "async" for p in sig["params"]):
        return ('static void swb_%s(CPU*, int k) { die_name("async Swift import (swiftasync context) has no bridge", ENT[k].name); }\n' % h)
    rs = "gswr_" + h
    lines = ["extern \"C\" void gsws_%s() __asm(%s)%s;" % (h, json.dumps(name), " __attribute__((weak_import))" if weak else "")]
    lines += ([ret_struct(sig, rs)] if len(sig["ret"]) > 1 else []) + ["static void swb_%s(CPU* c, int k) {" % h, "  if (gsw::trace) gsw::trace_call(ENT[k].name, c);"]
    lines += call_body(sig, hooks, "QFN[k] ? QFN[k] : (void*)&gsws_%s" % h, rs, returned_code(name, sig)) + ["}"]
    return "\n".join(lines) + "\n"

def hostcall_code(sig: dict) -> str:
    """swh_<key>(CPU*, void* fn): the guest calling host code fn of this signature through a typed handle."""
    k = sig_key(sig)
    if any(p["a"] == "async" for p in sig["params"]):
        return 'static void swh_%s(CPU*, void*) { die("async Swift function pointer (swiftasync context) has no bridge", 0); }\n' % k
    rs = "gswh_" + k
    lines = ([ret_struct(sig, rs)] if len(sig["ret"]) > 1 else []) + ["static void swh_%s(CPU* c, void* fn) {" % k]
    return "\n".join(lines + call_body(sig, {}, "fn", rs, returned_code("", sig)) + ["}"]) + "\n"

def entry_code(sig: dict) -> str:
    """Host -> guest entry swe_<key>: a swiftcall/C function whose closure slot names the guest code (gd_ctramp LIFO)."""
    k = sig_key(sig)
    rs = "gswe_" + k
    locs = arm64_locs(sig)
    multi = len(sig["ret"]) > 1
    sets = []
    for i, (p, loc) in enumerate(zip(sig["params"], locs)):
        if p["a"] == "sret": continue
        if p["a"] == "self": sets.append("nc.X[20] = (uint64_t)(uintptr_t)a%d;" % i)
        elif p["a"] == "error": sets.append("nc.X[21] = (uint64_t)(uintptr_t)*a%d;" % i)
        elif p["a"] == "async": sets.append('die("host called a guest async Swift function (no bridge)", g);')
        elif loc[0] == "x": sets.append("nc.X[%d] = %s;" % (loc[1], to_guest(p["t"], p["x"], "a%d" % i)))
        elif loc[0] == "v": sets.append("memset(&nc.V[%d], 0, 16); nc.V[%d].%s[0] = a%d;" % (loc[1], loc[1], "f32" if p["t"] == "float" else "f64", i))
        else: sets.append("{ %s t = a%d; memcpy((void*)(uintptr_t)gd::wr_stk(w, %d, %d), &t, %d); }" % (ctype(p), i, SCALARS[p["t"]][1], SCALARS[p["t"]][1], SCALARS[p["t"]][1]))
    sret = next((i for i, p in enumerate(sig["params"]) if p["a"] == "sret"), None)
    erri = next((i for i, p in enumerate(sig["params"]) if p["a"] == "error"), None)
    lines = ([ret_struct(sig, rs)] if multi else []) + [
        "static %s %sswe_%s(%s) {" % (ret_ctype(sig, rs), cc_attr(sig), k, ", ".join(c_params(sig, True)) or "void"),
        "  uint64_t g = cpop()->guest;", "  CPU nc; alignas(16) unsigned char tmp[16];",
        "  gd::enter_guest_w(nc, %s, g, [&](gd::Wr& w) { (void)w; %s });" % ("a%d" % sret if sret is not None else "(void*)tmp", " ".join(sets))]
    if erri is not None: lines.append("  *a%d = (void*)(uintptr_t)nc.X[21];" % erri)
    gx = gv = 0
    vals = []
    for t in sig["ret"]:
        if t in ("float", "double"): vals.append("nc.V[%d].%s[0]" % (gv, "f32" if t == "float" else "f64")); gv += 1
        else: vals.append("nc.X[%d]" % gx); gx += 1
    if sig.get("coro"):                                                # the guest continuation the host will call
        vals[0] = "(uint64_t)(uintptr_t)gsw::closure_or_host(nc.X[0], (void*)&swe_%s)" % sig_key(CORO_CONT)
    if multi: lines.append("  %s r; %s return r;" % (rs, " ".join("r.f%d = %s;" % (i, v) for i, v in enumerate(vals))))
    elif sig["ret"]:
        t = sig["ret"][0]
        lines.append("  return %s;" % ("(nc.X[0] & 1) != 0" if t == "i1" else vals[0] if t in ("float", "double") else
                                         "(void*)(uintptr_t)nc.X[0]" if t == "ptr" else "(%s)nc.X[0]" % ret_ctype(sig, rs)))
    return "\n".join(lines + ["}"]) + "\n"

###############
# guest Swift records (static, from the image file)
###############
def img_maps(img: dict) -> tuple[dict, dict]:
    return {a: n for a, _o, n, _w, _ad in img["binds"]}, dict(img["rebases"])

def rd(img: dict, a: int, n: int) -> bytes:
    for _name, vm, _vs, off, fs in img["segs"]:
        if vm <= a < vm + fs: return img["data"][off + a - vm:off + a - vm + n]
    return b"\0" * n                                                   # zero-fill

def i32(img: dict, a: int) -> int:
    return struct.unpack("<i", rd(img, a, 4))[0]

def u32(img: dict, a: int) -> int:
    return struct.unpack("<I", rd(img, a, 4))[0]

def u16(img: dict, a: int) -> int:
    return struct.unpack("<H", rd(img, a, 2))[0]

def rel(img: dict, a: int) -> int:
    return a + i32(img, a)

def in_code(img: dict, a: int) -> bool:
    """True when vmaddr a lies in an instruction section."""
    return any(s[2] <= a < s[2] + s[3] and s[5] & S_ATTR_INSTRUCTIONS for s in img["sects"])

def section_of(img: dict, name: str) -> tuple[int, int] | None:
    return next(((s[2], s[3]) for s in img["sects"] if s[1] == name), None)

def records(img: dict, name: str) -> list[int]:
    s = section_of(img, name)
    return [] if not s else [(s[0] + 4 * k + i32(img, s[0] + 4 * k)) & ~3 for k in range(s[1] // 4)]

def generic_header(img: dict, d: int, base: int) -> dict:
    """TypeGenericContextDescriptorHeader at d+base: pattern address, key-argument count, end of the generic trailers."""
    pat = rel(img, d + base + 4)
    nparams, nreq, nkey, flags = u16(img, d + base + 8), u16(img, d + base + 10), u16(img, d + base + 12), u16(img, d + base + 14)
    end = d + base + 16 + (nparams + 3) // 4 * 4 + 12 * nreq
    return {"pattern": pat, "nkey": nkey, "end": end, "packs": bool(flags & 1)}

def ptr_at(img: dict, a: int) -> int:
    """The unslid pointer stored at vmaddr a (a rebase target, else the raw word)."""
    return dict(img["rebases"]).get(a, struct.unpack("<Q", rd(img, a, 8))[0])

def generic_class_ros(img: dict, p: int) -> list[tuple[int, bool]]:
    """(class_ro_t address, is metaclass) in a generic class pattern's extra data, copied into every instantiation."""
    if not u32(img, p + 8) & 1: return []                              # GenericMetadataPatternFlags::HasExtraDataPattern
    words, off = rel(img, p + 32), u16(img, p + 36)                   # GenericMetadataPartialPattern after the 32-byte class pattern
    return [(words + 8 * (u16(img, p + o) - off), meta) for o, meta in ((24, False), (28, True))]

def override_fixups(img: dict, t: int, kf: int, binds: dict, db: dict) -> tuple[list, list]:
    """(relative-field patches, report) of a class's vtable trailers at t: overrides of host methods, typed by their '...Tj'."""
    # the host runtime copies override implementations into the vtable its own dispatch thunks call
    if kf & 0x8000: t += 8 + 8 * u32(img, t + 4)                        # VTableDescriptorHeader + MethodDescriptors
    if not kf & 0x4000: return [], []
    rels, report = [], []
    for k in range(u32(img, t)):
        e = t + 4 + 12 * k                                             # MethodOverrideDescriptor: class, method, impl
        v = i32(img, e + 4)
        req = binds.get(e + 4 + (v & ~1), "") if v & 1 else ""
        if not req.endswith("Tq") or not i32(img, e + 8): continue
        sig = db["funcs"].get(req[:-2] + "Tj")
        rels.append((e + 8, ("sig", sig) if sig else ("loud", req), "override of host method " + req))
        report.append("%s override %s" % ("bridged" if sig else "LOUD", req))
    return rels, report

def type_fixups(img: dict, d: int, binds: dict, db: dict) -> tuple[list, list, list, list, list]:
    """(relative-field patches, eager accessors, VWTs, class_ro_t to hostify, report) of one type context descriptor."""
    flags = u32(img, d); kind, kf, generic = flags & 0x1F, flags >> 16, bool(flags & 0x80)
    if kind not in (KIND_STRUCT, KIND_ENUM, KIND_CLASS): return [], [], [], [], []
    base = 44 if kind == KIND_CLASS else 28
    rels, eager, vwts, ros = [], [], [], []
    if not generic:
        rels.append((d + 12, "access0", "metadata accessor"))
        if kind != KIND_CLASS: eager.append((rel(img, d + 12), kind))   # a class accessor runs objc_opt_self (+self: user code); gobjc hostifies classes
        tail = d + base
    else:
        g = generic_header(img, d, base)
        if g["packs"]: raise NotImplementedError("generic type with parameter packs at 0x%x" % d)
        rels.append((d + 12, "access%s" % (g["nkey"] if g["nkey"] <= 3 else "N"), "generic metadata accessor"))
        p = g["pattern"]
        if i32(img, p): rels.append((p, "instantiate", "generic metadata instantiation"))
        if i32(img, p + 4): rels.append((p + 4, "complete", "generic metadata completion"))
        if kind == KIND_CLASS:
            if i32(img, p + 12): rels.append((p + 12, "heapdestroy", "generic class destroy"))
            if i32(img, p + 16): rels.append((p + 16, "heapdestroy", "generic class ivar destroyer"))
            ros += generic_class_ros(img, p)
        elif i32(img, p + 12): vwts.append(rel(img, p + 12))
        tail = g["end"]
    if kind == KIND_CLASS and kf & 0x2000: tail += 4                    # resilient superclass
    if kf & 3 == 2: tail += 4                                          # foreign metadata initialization
    if kf & 3 == 1:                                                    # singleton metadata initialization: cache, pattern, completion
        if i32(img, tail + 8): rels.append((tail + 8, "complete", "singleton metadata completion"))
        if kind == KIND_CLASS and kf & 0x2000:                         # ResilientClassMetadataPattern: the runtime builds the class
            rp = rel(img, tail + 4)
            if i32(img, rp): rels.append((rp, "relocate", "resilient class metadata relocation"))
            if i32(img, rp + 4): rels.append((rp + 4, "heapdestroy", "resilient class destroy"))
            if i32(img, rp + 8): rels.append((rp + 8, "heapdestroy", "resilient class ivar destroyer"))
            ros += [(rel(img, rp + 16), False), (ptr_at(img, rel(img, rp + 20) + 32) & ~7, True)]
        tail += 12
    if kind != KIND_CLASS: return rels, eager, vwts, ros, []
    orels, report = override_fixups(img, tail, kf, binds, db)
    return rels + orels, eager, vwts, ros, report

def conformance_fixups(img: dict, c: int, binds: dict, db: dict) -> tuple[list, list]:
    """(relative-field patches, report lines): resilient witnesses of host protocol method requirements, WT instantiator."""
    flags = u32(img, c + 12)
    p = c + 16 + (4 if flags & 0x40 else 0) + 12 * ((flags >> 8) & 0xFF)
    rels, report = [], []
    if flags & 0x10000:
        n = u32(img, p); p += 4
        for k in range(n):
            v = i32(img, p + 8 * k)
            req = binds.get(p + 8 * k + (v & ~1), "") if v & 1 else ""
            if req.endswith("Tq"):
                sig = db["witness"].get(req)
                rels.append((p + 8 * k + 4, ("sig", sig) if sig else ("loud", req), "witness " + req))
                report.append("%s %s" % ("bridged" if sig else "LOUD", req))
            elif req[-2:] in ACCESSOR_REQS and in_code(img, rel(img, p + 8 * k + 4)):   # an accessor, not a mangled name
                rels.append((p + 8 * k + 4, ACCESSOR_REQS[req[-2:]], "witness accessor " + req))
                report.append("bridged %s (accessor)" % req)
            elif req[-2:] in ("Tb", "Tn") and rd(img, rel(img, p + 8 * k + 4) & ~1, 2) == b"\xff\x07":
                t = (rel(img, p + 8 * k + 4) & ~1) + 2                 # '\xff\x07' + relative pointer to the accessor
                rels.append((t, "confaccess", "conformance accessor " + req))
                report.append("bridged %s (\\xff\\x07 accessor)" % req)
        p += 8 * n
    if flags & 0x20000 and i32(img, p + 4): rels.append((p + 4, "wtinst", "witness table instantiator"))
    return rels, report

def image_map(img: dict, db: dict) -> dict:
    """Swift records of one guest image: sections, relative-field patches, eager accessors, VWTs, report."""
    secs = {n: section_of(img, n) or (0, 0) for n in SWIFT_SECTS}
    binds, _reb = img_maps(img)
    rels, eager, vwts, ros, report = [], [], [], [], []
    for d in records(img, "__swift5_types"):
        r, e, v, o, rep = type_fixups(img, d, binds, db); rels += r; eager += e; vwts += v; ros += o; report += rep
    for c in records(img, "__swift5_proto"):
        r, rep = conformance_fixups(img, c, binds, db); rels += r; report += rep
    return {"sects": secs, "rels": rels, "eager": eager, "vwts": vwts, "ros": ros, "report": report}

###############
# swift_gen.hpp
###############
def entry_ref(kind: object, sigs: dict) -> str:
    """C++ address of the entry for a patch kind: a CORE name, ('sig', signature) or ('loud', requirement)."""
    if isinstance(kind, tuple) and kind[0] == "sig":
        sigs[sig_key(kind[1])] = kind[1]; return "(const void*)&swe_%s" % sig_key(kind[1])
    if isinstance(kind, tuple): return "nullptr"
    sig = parse_spec(CORE[kind]); sigs[sig_key(sig)] = sig
    return "(const void*)&swe_%s" % sig_key(sig)

def swift_gen(images: list, names: list, db: dict, declared: set, weak: set) -> tuple[str, list]:
    """Text of swift_gen.hpp (bridges for imports typed by db, weak: names bound weakly; entries; record tables), report."""
    sigs = {sig_key(parse_spec(s)): parse_spec(s) for s in CORE.values()}
    maps = [image_map(img, db) for img in images]
    rel_rows, sect_rows, eager_rows, vwt_rows, ro_rows, report = [], [], [], [], [], []
    for img, mp in zip(images, maps):
        sl = img["slide"]
        for f, kind, what in mp["rels"]: rel_rows.append("  {0x%xULL, %s, %s}" % ((f + sl) & MASK64, entry_ref(kind, sigs), json.dumps(what)))
        sect_rows.append("  {%s}" % ", ".join("0x%xULL, 0x%xULL" % (((mp["sects"][n][0] + sl) & MASK64 if mp["sects"][n][1] else 0), mp["sects"][n][1]) for n in SWIFT_SECTS))
        eager_rows += ["  {0x%xULL, %d}" % ((a + sl) & MASK64, kd) for a, kd in mp["eager"]]
        vwt_rows += ["  0x%xULL" % ((v + sl) & MASK64) for v in mp["vwts"]]
        ro_rows += ["  {0x%xULL, %d}" % ((a + sl) & MASK64, meta) for a, meta in mp["ros"]]
        report += ["%s: %s" % (os.path.basename(img["path"]), ln) for ln in mp["report"]]
    imports = [n for n in names if is_swift_import(n)]
    bridged = list(dict.fromkeys(n for n in names if bridged_name(n, n[1:] in declared)))   # one bridge per name, however many keys
    hooks = {n: hooks_for(n, db["funcs"][n], db) for n in bridged}
    sigs.update({sig_key(h["swfn"]): h["swfn"] for hs in hooks.values() for h in hs.values() if isinstance(h, dict)})
    bridges = "".join(bridge_code(n, db["funcs"][n], hooks[n], n in weak) for n in bridged)
    ck = sig_key(CORO_CONT)
    entries = entry_code(CORO_CONT) + "".join(entry_code(s) for k, s in sorted(sigs.items()) if k != ck)   # coroutine ramps use the first
    # host class methods the guest may look up (super calls: '...Mu'): method descriptor -> typed caller of its implementation
    methods = [(n, db["funcs"][n[:-2] + "Tj"]) for n in dict.fromkeys(names) if n.endswith("Tq") and n[:-2] + "Tj" in db["funcs"]]
    hsigs = {sig_key(s): s for s in [CORO_CONT] + [s for _n, s in methods]}
    hostcalls = hostcall_code(CORO_CONT) + "".join(hostcall_code(s) for k, s in sorted(hsigs.items()) if k != ck)
    mdesc = "".join('extern "C" char gswm_%s __asm(%s) __attribute__((weak_import));\n' % (hashlib.sha1(n.encode()).hexdigest()[:12], json.dumps(n)) for n, _s in methods)
    mdesc += "static const GswMeth GSW_MDESC[] = {\n%s\n};\nstatic const int GSW_NMDESC = %d;" % (",\n".join(
        ["  {(const void*)&gswm_%s, &swh_%s}" % (hashlib.sha1(n.encode()).hexdigest()[:12], sig_key(s)) for n, s in methods] + ["  {nullptr, nullptr}"]), len(methods))
    core = "\n".join("#define GSW_E_%s ((const void*)&swe_%s)" % (k.upper(), sig_key(parse_spec(v))) for k, v in sorted(CORE.items()))
    text = "\n".join(["/* generated by gswift.py: Swift bridges, guest->host and host->guest, and the guest Swift record map */",
                      "#define GSW_HAVE_GEN 1", entries, core, hostcalls, mdesc, bridges,
                      "static const GswRel GSW_REL[] = {\n%s\n};\nstatic const int GSW_NREL = %d;" % (",\n".join(rel_rows + ["  {0, nullptr, nullptr}"]), len(rel_rows)),
                      "static const GswSect GSW_SECT[] = {\n%s\n};" % ",\n".join(sect_rows or ["  {0, 0, 0, 0, 0, 0}"]),
                      "static const GswEager GSW_EAGER[] = {\n%s\n};\nstatic const int GSW_NEAGER = %d;" % (",\n".join(eager_rows + ["  {0, 0}"]), len(eager_rows)),
                      "static const uint64_t GSW_VWTS[] = {\n%s\n};\nstatic const int GSW_NVWT = %d;" % (",\n".join(vwt_rows + ["  0"]), len(vwt_rows)),
                      "static const GswRo GSW_RO[] = {\n%s\n};\nstatic const int GSW_NRO = %d;" % (",\n".join(ro_rows + ["  {0, 0}"]), len(ro_rows)),
                      "static const int GSW_NEED_TRAMP = %d;" % int(bool(rel_rows) or any(n in HOOKS and HOOKS[n].get(0) == "keypath" for n in bridged))])
    report.append("swift: %d imports, %d bridged from IR signatures, %d relative patches, %d eager accessors, %d pattern VWTs, %d pattern class_ro_t" % (
        len(imports), len(bridged), len(rel_rows), len(eager_rows), len(vwt_rows), len(ro_rows)))
    return text + "\n", report

def is_swift_data(name: str) -> bool:
    """Swift data by mangling kind (metadata, descriptors, witness tables, enum tags) or runtime name; much of it lives in the host's executable __TEXT segment, where gdyld's dynamic lookup would take it for code."""
    return name.startswith(DATA_PREFIXES) or (name.startswith("_$s") and bool(DATA_SUFFIX.search(name)))

def bridged_name(name: str, declared: bool) -> bool:
    """A Swift runtime / overlay function, or a C function no host header declares (os_log_type_enabled), typed by IR."""
    db = sigdb()["funcs"]
    return name in db and (is_swift_import(name) or (not declared and db[name]["cc"] == "c" and not name.startswith("_$s")))

def bridge_entry(name: str, lib: str, lib_path: str, weak: bool, declared: bool) -> tuple[str, str, str] | None:
    """gdyld hook: (ENT row, class, declaration) of a Swift import, Swift host data or IR-typed C import; None otherwise."""
    # a key naming a library (two host libraries export the name) resolves there alone at start (EK_QUAL / EK_QDATA);
    # otherwise the symbol is linked by name, weak_import when bound weakly, so an absent one reads as NULL
    h, lit = hashlib.sha1(name.encode()).hexdigest()[:12], json.dumps(name)
    data = is_swift_data(name)
    if not data and not bridged_name(name, declared): return None
    cls = "swift-data" if data else "swift" if is_swift_import(name) else "ir-c"
    call = "&sp_undeclared" if data else "&swb_%s" % h
    if lib: return "{%s, 0, nullptr, %s, %s, nullptr, %s}" % (call, lit, "EK_QDATA" if data else "EK_QUAL", json.dumps(lib_path)), cls, ""
    if data:
        return ("{&sp_undeclared, (uint64_t)(uintptr_t)&gswd_%s, nullptr, %s, EK_DATA, nullptr, nullptr}" % (h, lit), cls,
                'extern "C" char gswd_%s __asm(%s)%s;' % (h, lit, " __attribute__((weak_import))" if weak else ""))
    return "{&swb_%s, 0, nullptr, %s, EK_FN, (const void*)&gsws_%s, nullptr}" % (h, lit, h), cls, ""

def prepare(images: list, names: list, out_dir: str, sdk: str, declared: set, weak: set) -> tuple[list, list]:
    """gdyld hook: write out_dir/swift_gen.hpp; (extra link flags, report lines); weak: import keys bound weakly (-U)."""
    weak_names = {n for lib, n in weak if not lib}
    text, report = swift_gen(images, [n for _lib, n in names], sigdb(), declared, weak_names)
    open(os.path.join(out_dir, "swift_gen.hpp"), "w").write(text)
    uses = any(d[1].startswith("/usr/lib/swift/") for img in images for d in img["resolved"] if d[0] == "host")
    undef = ["-Wl,-U," + n for n in sorted(weak_names) if is_swift_data(n) or bridged_name(n, n[1:] in declared)]
    return (["-L" + os.path.join(sdk, LIB_DIR)] if uses else []) + undef, report
