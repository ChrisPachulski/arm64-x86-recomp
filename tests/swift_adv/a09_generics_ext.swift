// Generic classes specialized on guest types (and kept generic with @_optimize(none)), generic subclasses, conditional
// conformances, protocol extensions with default implementations vs overrides, static vs dynamic dispatch of extension
// methods, class-bound protocols, associated types with defaults, and runtime type names of generic instantiations.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
protocol Describer { func describe() -> String; func kind() -> String }
extension Describer { func describe() -> String { "default(\(kind()))" }; func kind() -> String { "generic" }
    func extOnly() -> String { "extOnly-default" } }
struct A: Describer {}
struct B: Describer { func describe() -> String { "B custom" }; func extOnly() -> String { "B extOnly" } }
struct C: Describer { func kind() -> String { "C-kind" } }
class Animal: Describer { func kind() -> String { "animal" } }
class Dog: Animal { override func kind() -> String { "dog" } }
@inline(never) func viaP(_ d: any Describer) -> String { d.describe() + "|" + d.extOnly() }
@inline(never) func viaG<T: Describer>(_ d: T) -> String { d.describe() + "|" + d.extOnly() }
print("ext", [viaP(A()), viaP(B()), viaP(C()), viaP(Dog())], viaG(B()), B().extOnly())
class Box<T> { var v: T; init(_ v: T) { self.v = v }; func show() -> String { "Box<\(T.self)>(\(v))" }; func map<U>(_ f: (T) -> U) -> Box<U> { Box<U>(f(v)) } }
final class Pair<K: Hashable, V>: Box<[K: V]> { let first: K; init(_ k: K, _ v: V) { first = k; super.init([k: v]) }
    override func show() -> String { "Pair<\(K.self),\(V.self)> " + super.show() } }
struct Pt: Hashable, CustomStringConvertible { var x, y: Int; var description: String { "(\(x),\(y))" } }
enum Color: String { case red, blue }
@_optimize(none) func opaque<T>(_ x: T) -> Box<T> { Box(x) }
let boxes: [AnyObject] = [Box(Pt(x: 1, y: 2)), opaque(Color.red), Box([Pt(x: 0, y: 0)]), Pair(Pt(x: 3, y: 4), "four"), opaque(Box(1.5)), Pair(Color.blue, Pt(x: 9, y: 9))]
for b in boxes {
    if let x = b as? Box<Pt> { print("Box<Pt>", x.show(), x.map { $0.x + $0.y }.show()) }
    else if let p = b as? Pair<Pt, String> { print("Pair", p.show(), p.first) }
    else if let p = b as? Box<[Color: Pt]> { print("as base", p.show(), p is Pair<Color, Pt>) }
    else { print("other", String(describing: type(of: b))) }
}
print("names", String(reflecting: Pair<Pt, Color>.self), String(describing: Box<Box<Color>>.self), _typeName(Box<[Pt?]>.self))
protocol Store { associatedtype Item = Int; var items: [Item] { get set } }
extension Store { mutating func add(_ i: Item) { items.append(i) }; var n: Int { items.count } }
extension Store where Item: Comparable { var top: Item? { items.max() } }
struct IntStore: Store { var items: [Int] = [] }
struct PtStore: Store { var items: [Pt] = [] }
var s1 = IntStore(); s1.add(5); s1.add(9); s1.add(1)
var s2 = PtStore(); s2.add(Pt(x: 1, y: 1))
print("store", s1.n, s1.top ?? -1, s2.n, s2.items)
protocol Named: AnyObject { var name: String { get set } }
final class Hero: Named { var name = "h" }
@inline(never) func rename(_ n: Named, _ s: String) { n.name = s }
let h = Hero(); rename(h, "renamed"); print("classbound", h.name)
extension Array where Element: Describer { func allDescribed() -> [String] { map { $0.describe() } } }
print("cond", [C(), C()].allDescribed(), [Dog(), Animal()].allDescribed())
extension Optional: Describer where Wrapped: Describer { func kind() -> String { self.map { "some " + $0.kind() } ?? "none" } }
print("optional conf", viaP(Optional(C())), viaP(Optional<C>.none), ([Optional(Dog())] as [any Describer]).map { $0.describe() })
@inline(never) func generic3<X, Y, Z>(_ x: X, _ y: Y, _ z: Z) -> String { "\(type(of: (x, y, z)))" }
print("tuple type", generic3(Pt(x: 0, y: 0), Color.red, Box(3)))
