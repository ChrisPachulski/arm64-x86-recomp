// Protocols with associated types, generics, existentials (any P), protocol extensions, generic structs with
// conditional conformances, and a conformance found only through the registered records (dynamic casts from Any).
protocol Container {
    associatedtype Item
    var items: [Item] { get }
    mutating func push(_ i: Item)
    func top() -> Item?
}
extension Container { func top() -> Item? { items.last }; var size: Int { items.count } }
struct Stack<T>: Container {
    var items: [T] = []
    mutating func push(_ i: T) { items.append(i) }
}
extension Stack: Equatable where T: Equatable {}
extension Stack: CustomStringConvertible { var description: String { "Stack\(items)" } }
protocol Shape { func area() -> Double; var name: String { get } }
struct Square: Shape { var s: Double; func area() -> Double { s * s }; var name: String { "square" } }
struct Circle: Shape { var r: Double; func area() -> Double { 3 * r * r }; var name: String { "circle" } }
final class Tri: Shape { let b, h: Double; init(b: Double, h: Double) { self.b = b; self.h = h }
    func area() -> Double { b * h / 2 }; var name: String { "tri" } }
protocol Hidden { func secret() -> String }                    // only casts from Any find these conformances
struct Agent: Hidden { var id: Int; func secret() -> String { "agent \(id)" } }
enum Mode: Hidden { case a, b(Int); func secret() -> String { if case .b(let v) = self { return "mode b \(v)" }; return "mode a" } }
struct Pair<A, B> { var a: A; var b: B }
extension Pair: Hidden where A: CustomStringConvertible { func secret() -> String { "pair \(a.description)" } }

@inline(never) func fill<C: Container>(_ c: inout C, _ xs: [C.Item]) { for x in xs { c.push(x) } }
@inline(never) func total(_ shapes: [any Shape]) -> Double { shapes.reduce(0) { $0 + $1.area() } }
@inline(never) func names(_ shapes: [any Shape]) -> String { shapes.map { $0.name }.joined(separator: ",") }
@inline(never) func reveal(_ xs: [Any]) -> [String] { xs.map { ($0 as? Hidden)?.secret() ?? "none:\(type(of: $0))" } }
@inline(never) func biggest<S: Shape>(_ xs: [S]) -> S? { xs.max { $0.area() < $1.area() } }
@inline(never) func opaque(_ k: Int) -> some Shape { Square(s: Double(k)) }

let n = CommandLine.arguments.count
var s = Stack<Int>()
fill(&s, [1, 2, 3 * n])
var t = Stack<String>()
fill(&t, ["x", "y"])
print(s, t, s.top() as Any, t.size, s == Stack(items: [1, 2, 3]), s == Stack(items: [1]))
let shapes: [any Shape] = [Square(s: 2), Circle(r: Double(n)), Tri(b: 3, h: 4)]
print("total", total(shapes), names(shapes), opaque(3).area())
print("biggest", biggest([Square(s: 1), Square(s: 5), Square(s: 2)])!.s)
let anys: [Any] = [Agent(id: 7), Mode.b(n), Mode.a, Pair(a: 3, b: "q"), Pair(a: Square(s: 1), b: 2), 42, "str"]
print("reveal", reveal(anys))
let boxed: Any = Stack(items: [9, 8])
if let c = boxed as? Stack<Int> { print("cast back", c.items) }
print("is", boxed is Stack<String>, (anys[0] as? Agent)?.id as Any, anys.compactMap { $0 as? Hidden }.count)
