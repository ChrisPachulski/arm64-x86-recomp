// swiftc: -Onone
// Opaque result types (some P) resolved by the runtime at -Onone (swift_getOpaqueTypeMetadata / Conformance), opaque
// types nested in generics, and an opaque type whose underlying type is a guest generic struct.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
protocol Unit { var hp: Int { get }; func describe() -> String }
struct Archer: Unit { var hp = 7; func describe() -> String { "archer \(hp)" } }
struct Squad<U: Unit>: Unit { var members: [U]; var hp: Int { members.reduce(0) { $0 + $1.hp } }; func describe() -> String { "squad of \(members.count): \(hp)" } }
func makeUnit() -> some Unit { Archer(hp: 9) }
func makeSquad<U: Unit>(_ u: U, _ n: Int) -> some Unit { Squad(members: Array(repeating: u, count: n)) }
func collection() -> some Collection<Int> { [3, 1, 2].lazy.map { $0 * 10 } }
func eqThing() -> some Hashable & CustomStringConvertible { "opaque-string" }
let u = makeUnit()
print("opaque", u.describe(), u.hp, type(of: u))
let s = makeSquad(makeUnit(), 3)
print("nested", s.describe(), s.hp, type(of: s))
print("coll", Array(collection()), collection().count, type(of: collection()))
print("hashable", eqThing().description, eqThing() == eqThing(), Set([eqThing(), eqThing()]).count)
