// A guest subclass of a resilient open host Swift class (JSONEncoder) whose override is reached through the host's
// dispatch thunk, a ManagedBuffer subclass (resilient generic superclass, guest deinit), and guest closures, witnesses
// and deinits running concurrently on Dispatch worker threads.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
final class LoudEncoder: JSONEncoder {
    var calls = 0
    override func encode<T: Encodable>(_ value: T) throws -> Data { calls += 1; return Data("override:".utf8) + (try super.encode(value)) }
}
@inline(never) func encodeVia(_ e: JSONEncoder, _ v: [Int]) -> String { String(decoding: try! e.encode(v), as: UTF8.self) }
let le = LoudEncoder()
print("plain", encodeVia(JSONEncoder(), [1, 2]))
print("override", encodeVia(le, [3]), le.calls)
final class Buf: ManagedBuffer<Int, Int64> {
    static func make(_ n: Int) -> Buf { let b = Buf.create(minimumCapacity: n) { _ in n } as! Buf
        b.withUnsafeMutablePointerToElements { p in for i in 0..<n { (p + i).initialize(to: Int64(i * i)) } }; return b }
    var sum: Int64 { withUnsafeMutablePointers { h, e in (0..<h.pointee).reduce(0) { $0 + e[$1] } } }
    deinit { print("deinit Buf", header) }
}
do { let b = Buf.make(5); print("managed", b.sum, b.header, b.capacity >= 5) }
print("after managed")
struct Key: Hashable { var a: Int; var s: String }
final class Tracked { static let lock = NSLock(); nonisolated(unsafe) static var dead = 0; let k: Key
    init(_ k: Key) { self.k = k }; deinit { Tracked.lock.lock(); Tracked.dead += 1; Tracked.lock.unlock() } }
let lock = NSLock()
var total = 0
var seen = Set<Key>()
DispatchQueue.concurrentPerform(iterations: 64) { i in
    var local = Set<Key>(); var objs: [Tracked] = []
    for j in 0..<200 { let k = Key(a: (i * 7 + j) % 50, s: "k\(j % 5)"); local.insert(k); objs.append(Tracked(k)) }
    let m = objs.map { $0.k.a }.reduce(0, +)
    lock.lock(); total += m; seen.formUnion(local); lock.unlock()
}
print("concurrent", total, seen.count, Tracked.dead)
let g = DispatchGroup(); let q = DispatchQueue(label: "w", attributes: .concurrent); var parts = [Int](repeating: 0, count: 8)
for w in 0..<8 { q.async(group: g) { let v = (0..<1000).map { Key(a: $0 % (w + 1), s: "") }.reduce(into: [Key: Int]()) { $0[$1, default: 0] += 1 }.count
    lock.lock(); parts[w] = v; lock.unlock() } }
print("group wait", g.wait(timeout: .now() + 30) == .success, parts)
