// Large structs returned indirectly and passed by value (through generics, closures, existentials and Optionals),
// indirect enums, and existentials holding large values (boxed out of line) cast back from Any.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
struct Big: Equatable { var a, b, c, d, e, f, g, h, i, j: Int; var s: String; var r: Double; var t: (Int8, Int16, Float) 
    static func == (l: Big, r: Big) -> Bool { l.a == r.a && l.j == r.j && l.s == r.s && l.r == r.r && l.t == r.t } }
@inline(never) func make(_ k: Int) -> Big { Big(a: k, b: k + 1, c: k + 2, d: k + 3, e: k + 4, f: k + 5, g: k + 6, h: k + 7, i: k + 8, j: k + 9, s: "big\(k)", r: Double(k) / 3, t: (Int8(k), Int16(-k), Float(k) * 1.5)) }
@inline(never) func sum(_ x: Big, _ y: Big, _ z: Int8, _ w: Double, _ q: Big) -> Big {
    var o = x; o.a += y.j + Int(z) + q.a; o.r += w + y.r; o.s += y.s + q.s; o.t.0 &+= q.t.0; o.t.2 += y.t.2; return o }
@inline(never) func gen<T>(_ x: T, _ n: Int) -> [T] { Array(repeating: x, count: n) }
@inline(never) func pass<T>(_ f: (T) -> T, _ x: T) -> T { f(f(x)) }
let s = sum(make(1), make(2), -3, 0.25, make(10))
print("sum", s.a, s.j, s.s, s.r, s.t.0, s.t.1, s.t.2)
print("gen", gen(make(5), 3).map { $0.s }, gen(make(5), 2)[1] == make(5))
print("pass", pass({ var b = $0; b.j *= 2; b.s += "!"; return b }, make(3)).j, pass({ $0 + 1 }, 40))
let opt: Big? = Int.random(in: 0..<1) == 0 ? make(7) : nil
print("opt", opt?.h ?? -1, opt.map { $0.s } ?? "nil")
protocol Shape { func area() -> Double; var tag: String { get } }
struct Poly: Shape { var pts: [Double]; var a, b, c, d: Double; var name: String
    func area() -> Double { pts.reduce(0, +) + a + b + c + d }; var tag: String { "poly \(name) \(pts.count)" } }
struct Dot: Shape { var x: Int8; func area() -> Double { 0 }; var tag: String { "dot \(x)" } }
let shapes: [any Shape] = [Poly(pts: [1, 2, 3], a: 4, b: 5, c: 6, d: 7, name: "P"), Dot(x: 3), Poly(pts: [], a: 1, b: 1, c: 1, d: 1, name: "Q")]
print("exist", shapes.map { $0.tag }, shapes.map { $0.area() })
var anys: [Any] = [make(4), Dot(x: 9), "str", 42, shapes[0], (1, "tuple", 2.5), Optional<Big>.none as Any]
anys.append(make(6) as Any)
for a in anys {
    if let b = a as? Big { print("any Big", b.s, b.t.1) }
    else if let sh = a as? any Shape { print("any Shape", sh.tag) }
    else if let t = a as? (Int, String, Double) { print("any tuple", t.1) }
    else { print("any other", type(of: a)) }
}
indirect enum Expr: Equatable, CustomStringConvertible {
    case num(Int), neg(Expr), add(Expr, Expr), mul(Expr, Expr), let_(String, Expr, Expr), v(String)
    var description: String { switch self { case .num(let n): return "\(n)"; case .neg(let e): return "-\(e)"
        case .add(let a, let b): return "(\(a)+\(b))"; case .mul(let a, let b): return "\(a)*\(b)"
        case .let_(let n, let a, let b): return "let \(n)=\(a) in \(b)"; case .v(let n): return n } }
}
@inline(never) func eval(_ e: Expr, _ env: [String: Int] = [:]) -> Int {
    switch e { case .num(let n): return n; case .neg(let x): return -eval(x, env)
    case .add(let a, let b): return eval(a, env) + eval(b, env); case .mul(let a, let b): return eval(a, env) * eval(b, env)
    case .let_(let n, let a, let b): var en = env; en[n] = eval(a, env); return eval(b, en); case .v(let n): return env[n] ?? 0 } }
@inline(never) func build(_ d: Int) -> Expr { d == 0 ? .num(d + 2) : .add(.mul(build(d - 1), .num(d)), .neg(build(d - 1))) }
let ex = Expr.let_("x", build(3), .add(.v("x"), .mul(.v("x"), .num(2))))
print("expr", ex, eval(ex), ex == ex, Expr.neg(.num(1)) == .neg(.num(2)))
indirect enum List<T> { case end, cons(T, List<T>) }
@inline(never) func toArr<T>(_ l: List<T>) -> [T] { var o: [T] = []; var c = l; while case .cons(let h, let t) = c { o.append(h); c = t }; return o }
print("list", toArr(List.cons(make(1), .cons(make(2), .end))).map(\.s), toArr(List.cons("a", .cons("b", .end))))
