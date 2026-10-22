// Array, Dictionary, Set, String: value semantics, copy-on-write, sorting with closures, hashing of guest Hashable
// types in host generic code, Unicode strings, Substring, Character, common String / Dictionary entry points.
struct Key: Hashable, Comparable, CustomStringConvertible {
    var a: Int; var b: String
    static func < (l: Key, r: Key) -> Bool { (l.a, l.b) < (r.a, r.b) }
    var description: String { "\(b)\(a)" }
}
enum Color: String, CaseIterable { case red, green, blue }

@inline(never) func histogram(_ s: String) -> [Character: Int] { var h: [Character: Int] = [:]; for c in s { h[c, default: 0] += 1 }; return h }
@inline(never) func lastChar(_ s: String) -> Character? { s.isEmpty ? nil : s[s.index(before: s.endIndex)] }
@inline(never) func prefixUpTo(_ s: String, _ c: Character) -> String { s.firstIndex(of: c).map { String(s[s.startIndex..<$0]) } ?? s }

let n = CommandLine.arguments.count
var a = [5, 3, 9, 1, 7, n]
var b = a                                                      // copy-on-write
b.append(100)
a.sort()
print("arrays", a, b.count, a.map { $0 * 2 }.filter { $0 > 5 }, a.reduce(0, +), b.sorted(by: >).prefix(3))
var d: [String: [Int]] = ["x": [1], "y": [2, 3]]
d["z", default: []].append(n)
d["x"] = nil
print("dict", d.keys.sorted(), d.values.map { $0.count }.sorted(), d.count)
var shared = d                                                 // copy-on-write of a dictionary: _DictionaryStorage.copy
shared["w"] = [n]
print("cow", d.count, shared.count, d["w"] == nil)
var keyed: [Key: Color] = [:]
for (i, c) in Color.allCases.enumerated() { keyed[Key(a: i, b: c.rawValue)] = c }
keyed.removeValue(forKey: Key(a: 1, b: "green"))
print("keyed", keyed.keys.sorted(), keyed[Key(a: 2, b: "blue")] as Any, keyed.count)
let s1: Set<Key> = [Key(a: 1, b: "p"), Key(a: 2, b: "q"), Key(a: 1, b: "p")]
let s2: Set<Key> = [Key(a: 2, b: "q"), Key(a: 3, b: "r")]
print("sets", s1.count, s1.union(s2).sorted(), s1.intersection(s2).sorted(), s1.isSubset(of: s1.union(s2)))
var ints: [Int: String] = [:]
for i in 0..<200 { ints[i * 7 % 101] = "v\(i)" }                // resize, collisions
for i in stride(from: 0, to: 101, by: 3) { ints.removeValue(forKey: i) }
print("ints", ints.count, ints[14] as Any, ints.keys.sorted().prefix(5))
let text = "Grüße, 世界! café \u{1F600} naïve"
print("string", text.count, text.utf8.count, text.uppercased(), text.reversed().prefix(4).map(String.init), lastChar(text) as Any)
print("histogram", histogram("mississippi").sorted { $0.key < $1.key }.map { "\($0.key)\($0.value)" }.joined())
print("prefix", prefixUpTo("en-US", "-"), prefixUpTo("fr", "-"), "en-GB".split(separator: "-").map(String.init))
var built = ""
for i in 0..<50 { built.append("item\(i);") }                  // _StringGuts.grow
print("built", built.count, built.hasPrefix("item0;"), built.contains("item49;"))
print("cstr", Array("héllo".utf8CString.prefix(7)), String(cString: Array("abc".utf8CString)))
