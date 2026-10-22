// Structs, payload enums (incl. indirect), Optional, tuples, switch, a RawRepresentable Int32 enum (a cursor type).
struct Point: Equatable { var x: Int; var y: Int; var name: String }
enum Shape { case circle(r: Double), rect(w: Double, h: Double), label(String), none }
indirect enum Expr { case num(Int), add(Expr, Expr), mul(Expr, Expr) }
enum CursorType: Int { case cursorDefault, cursorWait, cursorText, cursorCrosshair, cursorGrab, cursorHelp, cursorURL }

@inline(never) func area(_ s: Shape) -> Double {
    switch s {
    case .circle(let r): return 3.0 * r * r
    case .rect(let w, let h): return w * h
    case .label(let t): return Double(t.count)
    case .none: return 0
    }
}
@inline(never) func eval(_ e: Expr) -> Int {
    switch e { case .num(let n): return n; case .add(let a, let b): return eval(a) + eval(b); case .mul(let a, let b): return eval(a) * eval(b) }
}
@inline(never) func find(_ ps: [Point], _ n: String) -> Point? { ps.first { $0.name == n } }
@inline(never) func minmax(_ a: [Int]) -> (lo: Int, hi: Int)? {                        // no SIMD reduction: the lifter
    guard var lo = a.first else { return nil }                                            // has no scalar cmgt d (lane M4B
    var hi = lo                                                                           // open issue)
    for x in a.dropFirst() { if x < lo { lo = x } else if x > hi { hi = x } }
    return (lo, hi)
}

let n = CommandLine.arguments.count                                   // 1: keeps values opaque to the optimizer
let shapes: [Shape] = [.circle(r: 1.5 * Double(n)), .rect(w: 2, h: 3.5), .label("hello"), .none]
for s in shapes { print("area", area(s)) }
print("eval", eval(.add(.num(2 * n), .mul(.num(3), .num(4)))))
let pts = [Point(x: 1, y: 2, name: "a"), Point(x: n, y: 9, name: "b")]
print("find", find(pts, "b") as Any, find(pts, "zz") as Any)
print("eq", pts[0] == Point(x: 1, y: 2, name: "a"), pts[0] == pts[1])
print("minmax", minmax([5, 3, 9, n]) as Any, minmax([]) as Any)
let c = CursorType(rawValue: 3 + n - 1)
print("cursor", c as Any, c?.rawValue as Any, CursorType(rawValue: 99) as Any, CursorType.cursorURL.hashValue == CursorType.cursorURL.hashValue)
var opt: Int? = n > 5 ? 1 : nil
print("opt", opt ?? -1, opt.map { $0 + 1 } as Any)
opt = 41 + n
if let v = opt { print("unwrapped", v) }
print("point", pts[1], shapes[2])
