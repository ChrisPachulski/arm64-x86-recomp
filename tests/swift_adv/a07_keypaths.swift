// KeyPaths on guest structs and classes: read, WritableKeyPath / ReferenceWritableKeyPath writes, appending, optional
// chains, \.self, keypaths as functions (map(\.x)), keypaths as Hashable dictionary keys, and generic keypath algorithms.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
struct Stats: Hashable { var hp: Int; var atk: Double; var name: String }
struct Unit { var stats: Stats; var tags: [String]; var leader: Leader?; subscript(i: Int) -> String { tags[i] } }
final class Leader { var title: String; var unit: Unit?; init(_ t: String) { title = t } }
@inline(never) func get<R, V>(_ r: R, _ kp: KeyPath<R, V>) -> V { r[keyPath: kp] }
@inline(never) func set<R, V>(_ r: inout R, _ kp: WritableKeyPath<R, V>, _ v: V) { r[keyPath: kp] = v }
@inline(never) func sortBy<T, V: Comparable>(_ xs: [T], _ kp: KeyPath<T, V>) -> [T] { xs.sorted { $0[keyPath: kp] < $1[keyPath: kp] } }
var u = Unit(stats: Stats(hp: 10, atk: 2.5, name: "warrior"), tags: ["melee", "land"], leader: Leader("Gen"))
let hp = \Unit.stats.hp
let atk: KeyPath<Unit, Double> = \Unit.stats.atk
print("get", get(u, hp), get(u, atk), get(u, \.stats.name.count), get(u, \.tags[1]), get(u, \.[0]))
set(&u, hp, 99); set(&u, \.stats.name, "hero"); set(&u, \Unit.tags[0], "ranged")
print("set", u.stats, u.tags)
let lt = \Unit.leader?.title
print("optchain", get(u, lt) ?? "nil", get(Unit(stats: u.stats, tags: [], leader: nil), lt) ?? "nil")
let rw: ReferenceWritableKeyPath<Leader, String> = \Leader.title
let L = u.leader!; L[keyPath: rw] = "Marshal"; print("refwrite", u.leader!.title)
let app = (\Unit.stats).appending(path: \Stats.atk)
print("append", get(u, app), app == atk, hp == \Unit.stats.hp, hp.hashValue == (\Unit.stats.hp).hashValue)
let units = (0..<5).map { Unit(stats: Stats(hp: (7 * $0) % 5, atk: Double($0), name: "u\($0)"), tags: [], leader: nil) }
print("asfunc", units.map(\.stats.hp), units.map(\.stats.name).joined(), sortBy(units, \.stats.hp).map(\.stats.name))
let table: [PartialKeyPath<Stats>: String] = [\Stats.hp: "hp", \Stats.atk: "atk", \Stats.name: "name"]
print("dictkeys", table[\Stats.atk] ?? "nil", table[\Stats.hp] ?? "nil", table.count)
let pkps: [PartialKeyPath<Stats>] = [\Stats.hp, \Stats.atk, \Stats.name]
print("partial", pkps.map { "\(u.stats[keyPath: $0])" })
print("self", [3, 1, 2].map(\.self), get(u.stats, \.self).name)
let anyKp: AnyKeyPath = \Unit.stats.hp
print("anykp", (u[keyPath: anyKp] as? Int) ?? -1, anyKp is KeyPath<Unit, Int>, type(of: anyKp))
