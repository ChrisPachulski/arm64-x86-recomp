// swiftc: -Onone
// More host-stdlib -> guest witness calls, unspecialized: a guest RandomNumberGenerator driving shuffled(using:) and
// random(in:using:), a guest Sequence / IteratorProtocol and Collection consumed by host generics, a guest TextOutputStream
// receiving print(_:to:), a guest Equatable in Array ==, contains, firstIndex, and a guest Hashable boxed in AnyHashable.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
struct LCG: RandomNumberGenerator { var s: UInt64; mutating func next() -> UInt64 { s = s &* 6364136223846793005 &+ 1442695040888963407; return s } }
struct Countdown: Sequence, IteratorProtocol { var n: Int; mutating func next() -> Int? { if n == 0 { return nil }; n -= 1; return n } }
struct Ring: Collection { let base: [String]; let start: Int
    var startIndex: Int { 0 }; var endIndex: Int { base.count }
    func index(after i: Int) -> Int { i + 1 }
    subscript(i: Int) -> String { base[(i + start) % base.count] } }
struct Sink: TextOutputStream { var parts: [String] = []; mutating func write(_ s: String) { parts.append(s) } }
struct Tok: Equatable { var a: Int; var b: String }
struct HKey: Hashable { var k: Int; var tag: String }
var g = LCG(s: 42)
print("shuffled", Array(0..<10).shuffled(using: &g), Int.random(in: 0..<1000, using: &g), Bool.random(using: &g))
print("seq", Array(Countdown(n: 5)), Countdown(n: 4).map { $0 * 2 }, Countdown(n: 6).reduce(0, +), Set(Countdown(n: 3)).count)
let r = Ring(base: ["a", "b", "c", "d"], start: 2)
print("coll", Array(r), r.count, r.first ?? "-", r.joined(separator: "+"), r.contains("b"), r.firstIndex(of: "a") ?? -1, r.reversed().first ?? "-")
var sink = Sink()
print("to sink", 1, "two", 3.5, to: &sink); print(Tok(a: 1, b: "x"), to: &sink)
print("sink", sink.parts.count, sink.parts.joined().debugDescription)
let toks = [Tok(a: 1, b: "x"), Tok(a: 2, b: "y")]
print("eq", toks == [Tok(a: 1, b: "x"), Tok(a: 2, b: "y")], toks.contains(Tok(a: 2, b: "y")), toks.firstIndex(of: Tok(a: 2, b: "y")) ?? -1, toks != [])
let ah: [AnyHashable: Int] = [AnyHashable(HKey(k: 1, tag: "a")): 1, AnyHashable(HKey(k: 2, tag: "b")): 2, AnyHashable(5): 5]
print("anyhashable", ah[AnyHashable(HKey(k: 2, tag: "b"))] ?? -1, ah[HKey(k: 9, tag: "z")] ?? -1, ah.count)
let ns = NSMutableSet(); ns.add(HKey(k: 1, tag: "a")); ns.add(HKey(k: 1, tag: "a")); ns.add(HKey(k: 2, tag: "a"))
print("nsset of swift values", ns.count, ns.contains(HKey(k: 2, tag: "a")))
