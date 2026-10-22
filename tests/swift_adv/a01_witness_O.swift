// Host stdlib calling guest witnesses at -O: sort / min / max of a guest Comparable, Dictionary and Set keyed by a guest
// Hashable, String(describing:) and interpolation of a guest CustomStringConvertible, debugDescription.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
struct Ver: Comparable, Hashable, CustomStringConvertible, CustomDebugStringConvertible {
    var major: Int, minor: Int, tag: String
    static func < (a: Ver, b: Ver) -> Bool { (a.major, a.minor, a.tag) < (b.major, b.minor, b.tag) }
    var description: String { "v\(major).\(minor)-\(tag)" }
    var debugDescription: String { "Ver(\(major),\(minor),\(tag.debugDescription))" }
}
final class Node: Hashable, CustomStringConvertible {
    let id: Int; let label: String
    init(_ i: Int, _ l: String) { id = i; label = l }
    static func == (a: Node, b: Node) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }
    var description: String { "N\(id):\(label)" }
}
@inline(never) func vers() -> [Ver] {
    (0..<40).map { Ver(major: ($0 * 7) % 5, minor: ($0 * 13) % 11, tag: ["a", "rc", "beta", "z"][$0 % 4]) }
}
var vs = vers()
vs.sort()
print("sorted", vs.prefix(6).map { "\($0)" }.joined(separator: " "))
print("min", vs.min()!, "max", vs.max()!, "desc", vs.sorted(by: >).first!)
print("debug", String(reflecting: vs[3]), [vs[0], vs[1]])
var counts: [Ver: Int] = [:]
for v in vers() { counts[v, default: 0] += 1 }
print("dict", counts.count, counts[Ver(major: 0, minor: 0, tag: "a")] ?? -1, counts.keys.sorted().last!)
let set = Set(vers().map { Ver(major: $0.major, minor: 0, tag: $0.tag) })
print("set", set.count, set.contains(Ver(major: 4, minor: 0, tag: "z")), set.sorted().map(String.init(describing:)).joined(separator: ","))
var nodes = Set<Node>()
for i in 0..<50 { nodes.insert(Node(i % 17, "l\(i)")) }
print("nodes", nodes.count, nodes.map { $0.id }.sorted().suffix(3), nodes.first { $0.id == 5 }!.label)
let byNode = Dictionary(grouping: (0..<30).map { Node($0 % 4, "g\($0)") }, by: { $0 })
print("group", byNode.count, byNode.keys.map(\.id).sorted(), byNode.values.map(\.count).sorted())
print("describing", String(describing: Ver(major: 1, minor: 2, tag: "x")), "\(Node(9, "nine"))", [Node(1, "a")].description)
print("binsearch", vs.firstIndex(of: Ver(major: 2, minor: 5, tag: "rc")) ?? -1, vs.lexicographicallyPrecedes(vs.reversed()))
