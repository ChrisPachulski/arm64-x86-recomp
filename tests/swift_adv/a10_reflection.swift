// Default descriptions that need the runtime's field and enum-case metadata (Mirror, print of a struct, enum or class
// without CustomStringConvertible), dump(), Mirror children, enum case names, and String(describing:) of metatypes.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
struct Plain { var x: Int; var name: String; var opt: Double? }
enum Mode { case idle, run(speed: Int), named(String, Int) }
enum Raw: Int { case one = 1, two }
final class Klass { var a = 1; let b = "bee"; var c: [Int] = [1, 2] }
struct Nested { var p: Plain; var m: Mode; var t: (Int, label: String) }
let p = Plain(x: 3, name: "n", opt: nil)
print(p)
print(Mode.idle, Mode.run(speed: 4), Mode.named("x", 2), Raw.two, Raw(rawValue: 1)!)
print(Nested(p: p, m: .run(speed: 1), t: (5, label: "L")))
print(Klass() is AnyObject, String(describing: Klass.self), String(reflecting: Plain.self))
let m = Mirror(reflecting: p)
print("mirror", m.children.count, m.children.map { $0.label ?? "?" }, m.displayStyle.map { "\($0)" } ?? "nil")
print("mirror class", Mirror(reflecting: Klass()).children.map { "\($0.label!)=\($0.value)" })
print("mirror enum", Mirror(reflecting: Mode.named("q", 9)).children.map { "\($0.label ?? "?")" })
var out = ""
dump(Nested(p: p, m: .idle, t: (1, label: "z")), to: &out)
print(out, terminator: "")
print("optional", Optional(p) as Any, [Mode.idle, .run(speed: 2)])
print("interp", "\(Mode.run(speed: 7))", "\(p.opt as Any)")
