"""gswift_iface: swiftcc signatures of Swift symbols that no corpus program calls, from the SDK's own interfaces. Each mangled
name is demangled (swift-demangle -tree-only) into a small Swift probe that references exactly that declaration through the
SDK's .swiftinterface files; swiftc lowers it, and the signature is read from the probe's LLVM IR (x86_64 and arm64 must
agree), so the ABI comes from the compiler, never from a guess. Library; gswift.augment calls it for
every Swift import the corpus database lacks, so the Swift beds run it."""
###############
# imports and constants
###############
from __future__ import annotations
import concurrent.futures, hashlib, os, re, subprocess
import gswift

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "build", "swift_iface")                    # probe sources and their IR, by content
JOBS = 8
TRIES = 9                                                              # compiles per symbol (each compiler error may teach one fix)
FLAGS = ["-Onone", "-parse-as-library", "-Xfrontend", "-disable-access-control"]   # internal @usableFromInline decls are reachable
NODE_RE = re.compile(r'^(\s*)kind=(\w+)(?:, text="(.*)")?(?:, index=(\d+))?$')
NOMINAL = {"Structure", "Class", "Enum", "Protocol", "TypeAlias", "OtherNominalType"}
BOUND = {"BoundGenericStructure", "BoundGenericClass", "BoundGenericEnum", "BoundGenericOtherNominalType", "BoundGenericTypeAlias"}
FNTYPES = {"FunctionType", "NoEscapeFunctionType", "AutoClosureType", "EscapingAutoClosureType", "ObjCBlock", "EscapingObjCBlock",
           "CFunctionPointer", "ThinFunctionType"}
AUTOCLOSURE = {"AutoClosureType", "EscapingAutoClosureType"}
PASS = {"Type", "Shared", "Owned", "Isolated", "NoDerivative", "Sending", "ReturnType"}
ACCESSORS = {"Getter": "get", "Setter": "set", "ModifyAccessor": "modify", "ReadAccessor": "read", "Modify2Accessor": "modify",
             "Read2Accessor": "read", "UnsafeMutableAddressor": "modify", "UnsafeAddressor": "read"}
OPERATORS = ("InfixOperator", "PrefixOperator", "PostfixOperator")
KEYWORDS = {"default", "self", "Self", "Type", "in", "is", "as", "func", "var", "let", "init", "deinit", "subscript", "protocol",
            "extension", "where", "return", "repeat", "operator", "Any", "class", "struct", "enum", "throws", "rethrows", "true",
            "false", "nil", "super", "if", "else", "for", "while", "switch", "case", "do", "catch", "try", "import", "static"}
RULES = {"MethodLookupFunction": "swift|ptr|ptr,ptr", "Destructor": "swift|ptr|ptr:self"}   # fixed by the Swift ABI (checked vs the corpus)
FIX_RES = [(re.compile(r"reference to generic type '(\w+)' requires arguments"), "more"),
           (re.compile(r"generic type '(\w+)' specialized with too (?:few|many) type parameters \(got \d+, but expected (\d+)\)"), "set"),
           (re.compile(r"cannot specialize non-generic type '(\w+)'"), "zero"),
           (re.compile(r"requires that '(T\d+_\d+(?:\.\w+)*)' conform to '([\w.]+)'"), "req"),
           (re.compile(r"type '(T\d+_\d+(?:\.\w+)*)' does not conform to protocol '([\w.]+)'"), "req"),
           (re.compile(r"'(\w+)' has been renamed to '([\w.]+)'"), "ren")]   # an imported clang type's Swift name
NO_IMPORT = {"Swift", "__C", "Foundation"}                             # the probe imports Foundation (and so Swift) itself
FIRST = {"ctx": {}, "ren": {}, "flat": [], "reqs": [], "self": "", "conf": ""}   # nothing learned yet
INFER_RE = re.compile(r"generic parameter '\w+' could not be inferred")
# a protocol extension's default implementation of a requirement: a generic call reaches the requirement's dispatch thunk, so
# the probe calls it on a concrete conformer instead (T0_0 becomes a typealias of it), which dispatches to the default statically
CONFORMERS = {
    "Sequence": ["public struct GswSelfIter: Sequence, IteratorProtocol { public mutating func next() -> Int? { nil } }",
                 "public struct GswColl: Collection { public var startIndex: Int { 0 }; public var endIndex: Int { 1 }\n"
                 "  public subscript(i: Int) -> Int { i }; public func index(after i: Int) -> Int { i + 1 } }"],
    "Collection": ["public struct GswColl: Collection { public var startIndex: Int { 0 }; public var endIndex: Int { 1 }\n"
                   "  public subscript(i: Int) -> Int { i }; public func index(after i: Int) -> Int { i + 1 } }"],
    "Comparable": ["public struct GswCmp: Comparable { var x = 0; public static func < (a: GswCmp, b: GswCmp) -> Bool { a.x < b.x } }"],
    "Hashable": ["public struct GswHash: Hashable { var x = 0 }"],
    "LocalizedError": ["public struct GswLErr: LocalizedError {}"],
    "Error": ["public struct GswNSErr: CustomNSError {}"],
    "_SwiftNewtypeWrapper": ["public struct GswNewtype: _SwiftNewtypeWrapper, Hashable { public var rawValue: Int\n"
                             "  public init(rawValue: Int) { self.rawValue = rawValue } }"],
    "TextOutputStream": ["public struct GswOut: TextOutputStream { public mutating func write(_ s: String) {} }"],
}
# runtime entry points have no interface: each gets a snippet whose -Onone (or -O) IR calls it
RUNTIME = {
    "_swift_dynamicCastClassUnconditional": "final class C {}\npublic func probe(_ x: AnyObject) -> AnyObject { x as! C }",
    "_swift_getAtKeyPath": "public func probe<R, V>(_ r: R, _ k: KeyPath<R, V>) -> V { r[keyPath: k] }",
    "_swift_setAtWritableKeyPath": "public func probe<R, V>(_ r: inout R, _ k: WritableKeyPath<R, V>, _ v: V) { r[keyPath: k] = v }",
    "_swift_setAtReferenceWritableKeyPath": "public func probe<R, V>(_ r: R, _ k: ReferenceWritableKeyPath<R, V>, _ v: V) { r[keyPath: k] = v }",
    "_swift_getObjCClassFromObject": "// swiftc: -O\nimport Foundation\npublic final class Box<T>: NSObject { let v: T; init(_ v: T) { self.v = v } }\n"
                                     "@inline(never) public func probe(_ b: Box<Int>) -> AnyObject { type(of: b) as AnyObject }",
    "_swift_getAssociatedConformanceWitness": "public func probe<C: Collection>(_ c: C) -> Bool { c.startIndex < c.endIndex }",
    "_swift_projectBox": "// swiftc: -O\npublic indirect enum L<T> { case e; case c(T, L<T>) }\n"
                         "public func probe<T>(_ l: L<T>) -> T? { if case .c(let x, _) = l { return x }; return nil }",
    "_swift_isUniquelyReferenced_native": "// swiftc: -O\npublic final class C {}\npublic func probe(_ c: inout C?) -> Bool { isKnownUniquelyReferenced(&c) }",
    "_swift_isUniquelyReferenced_nonNull_native": "// swiftc: -O\npublic final class C {}\npublic func probe(_ c: inout C) -> Bool { isKnownUniquelyReferenced(&c) }",
    "_swift_isClassType": "// swiftc: -O\n@inline(never) public func probe<T>(_ x: T) -> [T] { [x, x] }",
    "_swift_copyKeyPathTrivialIndices": "public struct S { public subscript(i: Int) -> Int { i } }\npublic func probe() -> AnyKeyPath { \\S.[3] }",
    "_swift_allocObject": "public final class C { var x = 1 }\npublic func probe() -> AnyObject { C() }",
    "_swift_retain": "public final class C {}\npublic func probe(_ c: C) -> (C, C) { (c, c) }",
    "_swift_release": "// swiftc: -O\npublic final class C { var x = 1 }\n@inline(never) public func mk() -> C { C() }\npublic func probe() -> Int { let c = mk(); return c.x }",
    "_swift_beginAccess": "public final class C { public var x = 0 }\npublic func probe(_ c: C) { c.x += 1 }",
    "_swift_endAccess": "public final class C { public var x = 0 }\npublic func probe(_ c: C) { c.x += 1 }",
    "_swift_bridgeObjectRetain": "public func probe(_ s: String) -> (String, String) { (s, s) }",
    "_swift_bridgeObjectRelease": "// swiftc: -O\n@inline(never) public func ms() -> String { String(repeating: \"a\", count: 40) }\n"
                                  "public func probe() -> Int { ms().utf8.count }",
    "_swift_errorRetain": "public func probe(_ e: Error) -> (Error, Error) { (e, e) }",
    "_swift_unknownObjectRetain": "public func probe(_ x: AnyObject) -> (AnyObject, AnyObject) { (x, x) }",
    "_swift_unknownObjectRelease": "// swiftc: -O\npublic final class C { var x = 1 }\n@inline(never) public func mo() -> AnyObject { C() as AnyObject }\n"
                                   "public func probe() -> Int { let o = mo(); return ObjectIdentifier(o).hashValue }",
    "_swift_getObjectType": "public func probe(_ x: AnyObject) -> AnyObject.Type { type(of: x) }",
    "_swift_dynamicCast": "public func probe<T>(_ x: Any) -> T? { x as? T }",
    "_swift_dynamicCastObjCClass": "import Foundation\npublic func probe(_ x: AnyObject) -> NSString? { x as? NSString }",
    "_swift_getObjCClassMetadata": "import Foundation\npublic func probe() -> Any.Type { NSString.self }",
    "_swift_getWitnessTable": "// swiftc: -O\n@inline(never) public func eq<E: Equatable>(_ a: E, _ b: E) -> Bool { a == b }\n"
                              "public func probe<T: Equatable>(_ x: [T], _ y: [T]) -> Bool { eq(x, y) }",
    "_swift_once": "public let g = [1, 2, 3].map { $0 * 2 }\npublic func probe() -> Int { g.count }",
    "_swift_arrayDestroy": "// swiftc: -O\npublic func probe(_ q: UnsafeMutablePointer<String>, _ n: Int) { q.deinitialize(count: n) }",
    "_swift_deallocClassInstance": "public final class C { var x = 1 }",
    "_swift_deallocObject": "public func probe() -> () -> Int { var x = 0; return { x += 1; return x } }",
    "_swift_getTypeByMangledNameInContext": "// swiftc: -O\npublic func probe() -> Any.Type { [Int: [String]].self }",
    "_swift_getTypeByMangledNameInContextInMetadataState": "public func probe() -> Int { [1, 2, 3].lazy.map { $0 * 2 }.count }",
    "_swift_initStackObject": "// swiftc: -O\npublic final class D { var x = 1; deinit { print(\"d\", x) } }\n"
                              "@inline(never) public func use(_ d: D) -> Int { d.x }\npublic func probe() -> Int { let c = D(); return use(c) }\n"
                              "public func probe2() -> Int { let c = D(); c.x = 3; return c.x }",
    "_swift_setDeallocating": "// swiftc: -O\npublic final class D { var x = 1; deinit { print(\"d\", x) } }\n"
                              "@inline(never) public func use(_ d: D) -> Int { d.x }\npublic func probe() -> Int { let c = D(); return use(c) }",
    "__swift_stdlib_operatingSystemVersion": "import SwiftShims\npublic func probe() -> Int { _swift_stdlib_operatingSystemVersion().majorVersion }",
}

###############
# demangle trees
###############
def parse_tree(lines: list[str]) -> dict:
    """Indented `kind=..., text=..., index=...` lines -> nested {'k', 't', 'i', 'c'}."""
    root, stack = None, []
    for ln in lines:
        m = NODE_RE.match(ln)
        if not m: continue
        node = {"k": m.group(2), "t": m.group(3), "i": int(m.group(4)) if m.group(4) else None, "c": []}
        depth = len(m.group(1)) // 2
        stack = stack[:depth]
        if stack: stack[-1]["c"].append(node)
        else: root = node
        stack.append(node)
    return root

def trees(names: list[str]) -> dict[str, dict]:
    """Mangled name ('_$s...') -> its demangle tree (Global node)."""
    r = subprocess.run(["xcrun", "swift-demangle", "-tree-only"], input="\n".join(n[1:] for n in names), capture_output=True, text=True, timeout=300)
    out, cur, buf = {}, None, []
    for ln in r.stdout.splitlines() + ["Demangling for <end>"]:
        if ln.startswith("Demangling for "):
            if cur: out["_" + cur] = parse_tree(buf)
            cur, buf = ln[len("Demangling for "):], []
        else: buf.append(ln)
    return {n: t for n, t in out.items() if t}

def kid(n: dict, kind: str) -> dict | None:
    return next((c for c in n["c"] if c["k"] == kind), None)

def walk(n: dict) -> list[dict]:
    return [n] + [x for c in n["c"] for x in walk(c)]

###############
# Swift text of mangled types (st: what compiler errors taught so far, see FIRST)
###############
def ident(n: dict) -> str:
    if n["k"] != "Identifier": raise NotImplementedError("name kind " + n["k"])
    return "`%s`" % n["t"] if n["t"] in KEYWORDS else n["t"]

def nominal(n: dict, st: dict, ctx: list | None = None) -> str:
    """Qualified name of a nominal type; ctx (the caller's list, collecting the argument count of each generic level) marks a context position, where st['ctx'] adds T<depth>_<i> arguments per level."""
    parent, name = n["c"][0], n["c"][1]
    if parent["k"] == "Module" and parent["t"].startswith("__C_"): raise NotImplementedError("synthesized clang type")
    if parent["k"] == "Module": base = "" if parent["t"] == "__C" else parent["t"] + "."
    elif parent["k"] == "Extension": base = nominal(parent["c"][1], st, ctx) + "."
    elif parent["k"] in NOMINAL: base = nominal(parent, st, ctx) + "."
    elif parent["k"] in BOUND: base = ty(parent, st) + "."
    else: raise NotImplementedError("context " + parent["k"])
    own = st["ren"].get(name["t"]) if parent["k"] == "Module" and parent["t"] == "__C" else None
    text = own or base + ident(name)
    nargs = st["ctx"].get(name["t"], 0) if ctx is not None else 0
    if nargs:
        text += "<%s>" % ", ".join("T%d_%d" % (len(ctx) - 1, i) for i in range(nargs))
        ctx.append(nargs)                                              # ctx: [marker, count at depth 0, count at depth 1, ...]
    return text

def bound(n: dict, st: dict) -> str:
    """A bound generic type; a nested type the compiler called non-generic takes its arguments on its parent (Dictionary<K, V>.Keys)."""
    base, args = n["c"][0]["c"][0], ", ".join(ty(x, st) for x in n["c"][1]["c"])
    parent = base["c"][0]
    if base["c"][1]["t"] in st["flat"] and parent["k"] in NOMINAL: return "%s<%s>.%s" % (nominal(parent, st), args, ident(base["c"][1]))
    return "%s<%s>" % (nominal(base, st), args)

def ty(n: dict, st: dict, top: bool = False) -> str:
    """Swift spelling of a type node; top: a parameter's own type (@escaping / @autoclosure allowed)."""
    k = n["k"]
    if k in PASS: return ty(n["c"][-1], st, top)
    if k in NOMINAL: return ("any " if k == "Protocol" else "") + nominal(n, st)
    if k in BOUND: return bound(n, st)
    if k == "DependentGenericParamType": return "T%d_%d" % (n["c"][0]["i"], n["c"][1]["i"])
    if k == "DependentMemberType": return "%s.%s" % (ty(n["c"][0], st), ident(n["c"][1]["c"][0]))
    if k == "Tuple": return "(%s)" % ", ".join(tuple_elem(e, st) for e in n["c"])
    if k in FNTYPES: return fn_type(n, st, top)
    if k == "Metatype": return "%s.Type" % paren(ty(n["c"][-1], st))
    if k == "ExistentialMetatype": return "any %s.Type" % paren(ty(n["c"][-1], st).removeprefix("any "))
    if k == "ProtocolList": return protos(n, st)
    if k == "ProtocolListWithAnyObject": p = protos(n["c"][0], st); return "AnyObject" if p == "Any" else p + " & AnyObject"
    if k == "ProtocolListWithClass":
        p = protos(n["c"][0], st)
        return ty(n["c"][1], st) + ("" if p == "Any" else " & " + p.removeprefix("any "))
    if k == "SugaredOptional": return paren(ty(n["c"][0], st)) + "?"
    if k == "SugaredArray": return "[%s]" % ty(n["c"][0], st)
    if k == "SugaredDictionary": return "[%s: %s]" % (ty(n["c"][0], st), ty(n["c"][1], st))
    if k == "SugaredParen": return "(%s)" % ty(n["c"][0], st)
    if k == "DynamicSelf": return "Self"
    if k == "InOut": return "inout " + ty(n["c"][0], st)
    raise NotImplementedError("type " + k)

def paren(s: str) -> str:
    return "(%s)" % s if (" " in s and not s.startswith("[")) or "->" in s else s

def protos(n: dict, st: dict) -> str:
    names = [nominal(t["c"][0], st) for t in n["c"][0]["c"]] if n["c"] else []
    return "Any" if not names else "any " + " & ".join(names)

def tuple_elem(e: dict, st: dict) -> str:
    lbl = kid(e, "TupleElementName")
    return ("%s: " % lbl["t"] if lbl else "") + ty(e["c"][-1], st) + ("..." if kid(e, "VariadicMarker") else "")

def fn_parts(n: dict) -> tuple[list[dict], dict, bool]:
    """(argument element nodes, return type node, throws) of a function type node."""
    if kid(n, "AsyncAnnotation") or kid(n, "TypedThrowsAnnotation"): raise NotImplementedError("async or typed throws")
    at = kid(n, "ArgumentTuple")["c"][0]["c"][0]
    args = at["c"] if at["k"] == "Tuple" else [{"k": "TupleElement", "t": None, "i": None, "c": [at]}]
    return args, kid(n, "ReturnType"), kid(n, "ThrowsAnnotation") is not None

def fn_type(n: dict, st: dict, top: bool) -> str:
    args, ret, throws = fn_parts(n)
    pre = {"ObjCBlock": "@convention(block) ", "EscapingObjCBlock": "@convention(block) ", "CFunctionPointer": "@convention(c) ",
           "ThinFunctionType": "@convention(thin) "}.get(n["k"], "")
    if top: pre = {"FunctionType": "@escaping ", "AutoClosureType": "@autoclosure ", "EscapingAutoClosureType": "@autoclosure @escaping ",
                   "EscapingObjCBlock": "@escaping "}.get(n["k"], "") + pre
    elif n["k"] in AUTOCLOSURE: raise NotImplementedError("autoclosure inside a type")
    return "%s(%s)%s -> %s" % (pre, ", ".join(ty(a["c"][-1], st) for a in args), " throws" if throws else "", ty(ret, st))

###############
# probes
###############
def unwrap(g: dict) -> tuple[dict, bool]:
    """(entity, static) under a Global node (dispatch thunks: the probe calls the requirement, so the compiler calls the thunk)."""
    e, static = g["c"][0], False
    while e["k"] in ("DispatchThunk", "Static"):
        static = static or e["k"] == "Static"
        e = e["c"][0]
    if len(g["c"]) > 1: raise NotImplementedError("suffix " + g["c"][1]["k"])
    return e, static

def ctx_info(c: dict) -> tuple[dict | None, dict | None, list[dict]]:
    """(nominal type node or None for a module, protocol node when the context is a protocol (extension), extension signatures)."""
    sigs = []
    if c["k"] == "Extension":
        sigs = [x for x in c["c"][2:] if x["k"] == "DependentGenericSignature"]
        c = c["c"][1]
    if c["k"] == "Module": return None, None, sigs
    if c["k"] not in NOMINAL: raise NotImplementedError("context " + c["k"])
    return c, (c if c["k"] == "Protocol" else None), sigs

def requirement(r: dict, st: dict) -> str:
    k = r["k"]
    if k == "DependentGenericConformanceRequirement":                 # a protocol, or a superclass (KeyPath<A, C>)
        rhs = r["c"][1]["c"][0]
        return "%s: %s" % (ty(r["c"][0], st), nominal(rhs, st) if rhs["k"] == "Protocol" else ty(r["c"][1], st))
    if k == "DependentGenericSameTypeRequirement": return "%s == %s" % (ty(r["c"][0], st), ty(r["c"][1], st))
    if k == "DependentGenericLayoutRequirement" and r["c"][1]["t"] in ("C", "R", "N", "D"): return "%s: AnyObject" % ty(r["c"][0], st)
    raise NotImplementedError("requirement " + k)

def generic_params(tree: dict, ctxcounts: list[int]) -> list[str]:
    """T<d>_<i> for every depth: the larger of the signature's own count and the indexes used (context depths: at least ctxcounts)."""
    count = dict(enumerate(ctxcounts))
    for n in walk(tree):
        if n["k"] == "DependentGenericParamType": d, i = n["c"][0]["i"], n["c"][1]["i"]; count[d] = max(count.get(d, 0), i + 1)
        if n["k"] == "DependentGenericSignature":
            pc = [x["i"] for x in n["c"] if x["k"] == "DependentGenericParamCount"]
            base = max(max(count, default=-1) + 1 - len(pc), 0) if pc else 0
            for j, c in enumerate(pc): count[base + j] = max(count.get(base + j, 0), c)
    return ["T%d_%d" % (d, i) for d in sorted(count) for i in range(count[d])]

def labels(e: dict, n: int, args: list[dict]) -> list[str | None]:
    """Argument labels: the LabelList (FirstElementMarker = none), else the tuple's element names."""
    ll = kid(e, "LabelList")
    if ll and ll["c"]: return [None if x["k"] == "FirstElementMarker" else x["t"] for x in ll["c"]]
    return [(kid(a, "TupleElementName") or {}).get("t") for a in args][:n] if args else []

def arg_kind(a: dict) -> str:
    t = a["c"][-1]
    while t["k"] in PASS and t["c"]: t = t["c"][-1]
    return t["k"]

def fn_node(a: dict) -> dict | None:
    """The Swift or C function type of an argument (also inside an Optional), None for anything else (blocks, data pointers)."""
    t = a["c"][-1]
    while t["c"] and (t["k"] in PASS | {"SugaredOptional", "TypeList"} or (t["k"] == "BoundGenericEnum" and "Optional" == (kid(t["c"][0]["c"][0], "Identifier") or {}).get("t"))):
        t = t["c"][-1]                                                 # Optional<F> is the last child chain: Type, TypeList, Type
    return t if t["k"] in ("FunctionType", "NoEscapeFunctionType", "CFunctionPointer") else None

def cfn_params(g: dict) -> int:
    """C function pointer parameters (also Optional; a setter's new value counts) of the function or accessor of tree g."""
    e, _static = unwrap(g)
    setter = ACCESSORS.get(e["k"]) == "set"
    if e["k"] in ACCESSORS: e = e["c"][0]
    t = kid(e, "Type") if e["k"] in ("Function", "Allocator", "Variable", "Subscript") else None
    if not t: return 0
    f = t["c"][0]
    if f["k"] == "DependentGenericType": f = f["c"][1]["c"][0]
    args, ret = ([], f) if e["k"] == "Variable" else fn_parts(f)[:2]
    vals = args + ([{"c": [ret]}] if setter and ret else [])
    return sum(1 for a in vals if (fn_node(a) or {}).get("k") == "CFunctionPointer")

def callbacks_ok(sig: tuple, tree: dict) -> tuple:
    """A derived (signature, how, closures) unchanged when every C function pointer parameter got a callback signature, else refused (stays loud): native code must never get a raw guest address."""
    if sig[0] and sum(1 for s in sig[2].values() if s["cc"] == "c") < cfn_params(tree):
        return None, "a C function pointer parameter without a derived callback signature (stays loud)", {}
    return sig

def closure_literal(t: dict, st: dict) -> str:
    """A closure literal of function type t: the call then passes a function of the probe's module, whose IR lowering is how the host calls a guest closure there (gswift.closure_args)."""
    args, ret, throws = fn_parts(t)
    ps = ", ".join("c%d: %s" % (i, ty(a["c"][-1], st)) for i, a in enumerate(args))
    return "{ (%s)%s -> %s in fatalError() }" % (ps, " throws" if throws else "", ty(ret, st))

def call_args(names: list[str], lbls: list[str | None], args: list[dict], st: dict) -> str:
    """The call's argument list: inout passed with &, an autoclosure forwarded by calling it, a Swift function as a closure literal."""
    out = []
    for nm, lb, a in zip(names, lbls + [None] * len(names), args):
        k, f = arg_kind(a), fn_node(a)
        val = closure_literal(f, st) if f else ("&" if k == "InOut" else "") + nm + ("()" if k in AUTOCLOSURE else "")
        out.append(("%s: " % lb if lb else "") + val)
    return ", ".join(out)

def modules(g: dict) -> list[str]:
    """Modules the probe must import besides Foundation."""
    return sorted({n["t"] for n in walk(g) if n["k"] == "Module" and n["t"] not in NO_IMPORT and not n["t"].startswith("__C")})

def probe(g: dict, st: dict) -> str:
    """Swift source of a probe that references the declaration of tree g."""
    e, static = unwrap(g)
    k = e["k"]
    acc = ACCESSORS.get(k)
    if acc: e = e["c"][0]
    depth = [0]
    if k == "TypeMetadataAccessFunction":
        selfty, proto, esigs, params, throws, ret = nominal(e["c"][0]["c"][0], st, depth), None, [], [], False, "Any.Type"
        body, selfp = "return %s.self" % selfty, []
    else:
        if e["k"] not in ("Function", "Allocator", "Variable", "Subscript"): raise NotImplementedError("entity " + e["k"])
        tnode, proto, esigs = ctx_info(e["c"][0])
        selfty = ("T0_0" if proto else nominal(tnode, st, depth)) if tnode else None
        ftype = kid(e, "Type")["c"][0] if kid(e, "Type") else None
        if ftype and ftype["k"] == "DependentGenericType": esigs = esigs + [ftype["c"][0]]; ftype = ftype["c"][1]["c"][0]
        args, retn, throws = ([], ftype, False) if e["k"] == "Variable" else fn_parts(ftype)
        names = ["a%d" % i for i in range(len(args))]
        params = ["_ %s: %s" % (nm, ty(a["c"][-1], st, True)) for nm, a in zip(names, args)]
        ret = ty(retn, st) if retn else "()"
        op = e["c"][1] if e["k"] == "Function" else None
        instance = bool(tnode) and not static and e["k"] != "Allocator" and not (op and op["k"] in OPERATORS)
        recv = "s" if instance else selfty if tnode else e["c"][0]["t"]
        if e["k"] == "Allocator": call = "%s(%s)" % (selfty, call_args(names, labels(e, len(args), args), args, st))
        elif op and op["k"] == "InfixOperator": call = "%s %s %s" % (names[0], op["t"], names[1])
        elif op and op["k"] == "PrefixOperator": call = "%s%s" % (op["t"], names[0])
        elif op and op["k"] == "PostfixOperator": call = "%s%s" % (names[0], op["t"])
        elif op: call = "%s.%s(%s)" % (recv, ident(op), call_args(names, labels(e, len(args), args), args, st))
        else:                                                          # a property or subscript accessor
            target = "%s.%s" % (recv, ident(e["c"][1])) if e["k"] == "Variable" else "%s[%s]" % (recv, call_args(names, labels(e, len(args), args), args, st))
            if acc == "set":                                           # a Swift function value is stored as a closure literal
                f = fn_node({"c": [retn]}) if retn else None
                params.append("_ v: %s" % ret); call, ret = "%s = %s" % (target, closure_literal(f, st) if f else "v"), "()"
            elif acc == "modify": call, ret = "gswTouch(&%s)" % target, "()"
            else: call = target
        body = ("return " if ret != "()" else "") + ("try " if throws else "") + call
        selfp = ["_ s: %s" % selfty] if instance else []
    gen = generic_params(g, depth[1:])
    if proto and "T0_0" not in gen: gen = ["T0_0"] + gen
    where = (["T0_0: %s" % nominal(proto, st)] if proto else []) + [requirement(r, st) for s in esigs for r in s["c"] if r["k"].endswith("Requirement")]
    where += [r for r in st["reqs"] if r not in where]
    conf = ""
    if st["conf"]:                                                     # Self is a concrete conformer: its constraints hold by construction
        conf = "%s\npublic typealias T0_0 = %s\n" % (st["conf"], re.search(r"struct (\w+)", st["conf"]).group(1))
        gen, where = [p for p in gen if p != "T0_0"], [r for r in where if "T0_0" not in r]
    shown = " ".join(selfp + params) + ret
    params = params + ["_ g%d: %s.Type" % (i, p) for i, p in enumerate(gen) if not re.search(r"\b%s\b" % p, shown)]   # Swift: every parameter used
    sig = "public func gswProbe%s(%s)%s%s%s" % ("<%s>" % ", ".join(gen) if gen else "", ", ".join(selfp + params), " throws" if throws else "",
                                                "" if ret == "()" else " -> " + ret, " where " + ", ".join(where) if where else "")
    imports = "".join("import %s\n" % m for m in modules(g))
    return ("// swiftc: %s\nimport Foundation\n%s@inline(never) public func gswTouch<V>(_ x: inout V) {}\n%s%s {\n  %s%s\n}\n" % (
        " ".join(FLAGS), imports, conf, sig, "var s = s; " if selfp else "", body))

###############
# compile and read the IR
###############
def compile_ir(src: str, arch: str, sdk: str) -> tuple[str | None, str]:
    """(IR text or None, compiler errors) of one probe source for one arch; cached by content."""
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.sha256((src + arch + sdk).encode()).hexdigest()[:24]
    out, path = os.path.join(CACHE, key + ".ll"), os.path.join(CACHE, key + ".swift")
    if os.path.isfile(out): return open(out).read(), ""
    if os.path.isfile(out + ".err"): return None, open(out + ".err").read()
    open(path, "w").write(src)
    r = subprocess.run(["xcrun", "swiftc", "-target", gswift.TARGET % arch, "-sdk", sdk, "-emit-ir"] + gswift.swiftc_flags(path) + [path, "-o", out + ".tmp"],
                       capture_output=True, text=True, timeout=600)
    if r.returncode: open(out + ".err", "w").write(r.stderr); return None, r.stderr
    os.replace(out + ".tmp", out)
    return open(out).read(), ""

def learn(err: str, st: dict) -> dict | None:
    """The next state a compiler error teaches, None when it teaches nothing new."""
    for rx, what in FIX_RES:
        for m in rx.finditer(err):
            nm, ctx = m.group(1), st["ctx"]
            if what == "more" and ctx.get(nm, 0) < 4: return {**st, "ctx": {**ctx, nm: ctx.get(nm, 0) + 1}}
            if what == "set" and ctx.get(nm) != int(m.group(2)): return {**st, "ctx": {**ctx, nm: int(m.group(2))}}
            if what == "zero" and ctx.get(nm, 0): return {**st, "ctx": {**ctx, nm: 0}}
            if what == "zero" and nm not in st["flat"]: return {**st, "flat": st["flat"] + [nm]}
            if what == "req" and "%s: %s" % m.groups() not in st["reqs"]: return {**st, "reqs": st["reqs"] + ["%s: %s" % m.groups()]}
            if what == "ren" and st["ren"].get(nm) != m.group(2): return {**st, "ren": {**st["ren"], nm: m.group(2)}}
    if INFER_RE.search(err) and st["self"] and not st["ctx"].get(st["self"]): return {**st, "ctx": {**st["ctx"], st["self"]: 1}}
    return None

def first_state(g: dict) -> dict:
    """Initial state: depth-0 generic parameters used anywhere go to the outermost nominal level of the context."""
    used = [n["c"][1]["i"] for n in walk(g) if n["k"] == "DependentGenericParamType" and n["c"][0]["i"] == 0]
    e = g["c"][0]
    while e["k"] in ("DispatchThunk", "Static") or e["k"] in ACCESSORS: e = e["c"][0]
    c = e["c"][0]["c"][0] if e["k"] == "TypeMetadataAccessFunction" else e["c"][0] if e["c"] else None
    if c and c["k"] == "Extension": c = c["c"][1]
    if not c or c["k"] not in NOMINAL or c["k"] == "Protocol": return FIRST
    st = {**FIRST, "self": c["c"][1]["t"]}                             # the context's own name: a generic one may use no parameter
    if not used: return st
    while c["c"][0]["k"] in NOMINAL: c = c["c"][0]
    return {**st, "ctx": {c["c"][1]["t"]: max(used) + 1}}

def ext_protocol(g: dict) -> str:
    """Simple name of the protocol whose extension declares the entity, '' otherwise."""
    e = g["c"][0]
    while e["k"] in ACCESSORS or e["k"] in ("Static", "DispatchThunk"): e = e["c"][0]
    c = e["c"][0] if e["c"] else None
    return c["c"][1]["c"][1]["t"] if c and c["k"] == "Extension" and c["c"][1]["k"] == "Protocol" else ""

def conformer_sig(target: str, tree: dict, st: dict, sdk: str) -> tuple[dict | None, str, dict]:
    """The target from a probe on a concrete conformer of its protocol (CONFORMERS): (signature, how, closure parameters)."""
    for conf in CONFORMERS.get(ext_protocol(tree), []):
        ir, _err, clo = both_arches(probe(tree, {**st, "conf": conf}), sdk)
        if ir and target in ir: return ir[target], "probe on a conformer", {str(i): s for i, s in clo.get(target, {}).items()}
    return None, "the probe does not reference it (no conformer reaches it)", {}

def both_arches(src: str, sdk: str) -> tuple[dict | None, str, dict]:
    """(merged IR functions where x86_64 and arm64 agree, or None; the compiler errors; callee -> {IR parameter index: signature of the probe's own function passed there})."""
    x, err = compile_ir(src, "x86_64", sdk)
    if x is None: return None, err, {}
    a, err = compile_ir(src, "arm64", sdk)
    if a is None: return None, err, {}
    fx, fa = gswift.ir_functions(x), gswift.ir_functions(a)
    merged = {n: s for n, s in fx.items() if fa.get(n) == s}
    return merged, "", gswift.closure_args(a, merged)

def runtime_sig(name: str, sdk: str) -> tuple[dict | None, str, dict]:
    """A runtime entry point from its snippet (default flags -Onone)."""
    src = RUNTIME[name] if RUNTIME[name].startswith("// swiftc:") else "// swiftc: -Onone\n" + RUNTIME[name]
    if "-parse-as-library" not in src.splitlines()[0]: src = src.replace("\n", " -parse-as-library\n", 1)
    ir, err, clo = both_arches(src, sdk)
    if not (ir and name in ir): return None, "runtime probe does not call it " + err[-300:], {}
    return ir[name], "runtime probe", {str(i): s for i, s in clo.get(name, {}).items()}

def derive_one(name: str, g: dict | None, sdk: str) -> tuple[dict | None, str, dict]:
    """(signature or None, how it was derived or why not, {IR parameter index: signature of a Swift function the host is handed there}) of one symbol."""
    if name in RUNTIME: return runtime_sig(name, sdk)
    if name in gswift.ABI_SIGS: return gswift.parse_spec(gswift.ABI_SIGS[name]), "abi rule", {}
    if g is None: return None, "no demangle tree", {}
    e = g["c"][0]
    if e["k"] in RULES: return gswift.parse_spec(RULES[e["k"]]), "rule", {}
    twin = e["k"] == "Constructor"                                     # fc (initializing) is lowered like its fC (allocating) twin
    tree = {**g, "c": [{**e, "k": "Allocator"}] + g["c"][1:]} if twin else g
    target = name[:-1] + "C" if twin else name
    try:
        st = first_state(tree)
        for _ in range(TRIES):
            ir, err, clo = both_arches(probe(tree, st), sdk)
            fns = {str(i): s for i, s in clo.get(target, {}).items()}
            if ir is not None and target in ir: return callbacks_ok((ir[target], "probe" + (" (fC twin)" if twin else ""), fns), tree)
            if ir is not None:                                         # a default implementation: only a concrete conformer reaches it
                return callbacks_ok(conformer_sig(target, tree, st, sdk), tree) if ext_protocol(tree) else (None, "the probe does not reference it", {})
            nxt = learn(err, st)
            if not nxt: return None, "probe does not compile: " + " | ".join(re.findall(r"error: ([^\n]*)", err)[:3]), {}
            st = nxt
        return None, "probe did not converge", {}
    except NotImplementedError as x:                                 # a construct the generator does not spell: stays loud
        return None, "unsupported: %s" % x, {}

def derive(names: list[str], sdk: str) -> dict[str, tuple[dict | None, str, dict]]:
    """Name -> (signature or None, how / why not, closure parameters) for every name, JOBS probes at a time."""
    tr = trees([n for n in names if n not in RUNTIME])
    with concurrent.futures.ThreadPoolExecutor(JOBS) as pool:
        res = list(pool.map(lambda n: derive_one(n, tr.get(n), sdk), names))
    return dict(zip(names, res))

def same_sig(a: dict, b: dict) -> bool:
    """Equal lowering: the same convention, results and ordinary parameters in order, and the same special registers (where swiftself sits in the IR list does not matter)."""
    ordinary = lambda s: [p for p in s["params"] if not p["a"]]
    special = lambda s: sorted((p["a"], p["t"]) for p in s["params"] if p["a"])
    return a["cc"] == b["cc"] and a["ret"] == b["ret"] and a["rx"] == b["rx"] and ordinary(a) == ordinary(b) and special(a) == special(b)
