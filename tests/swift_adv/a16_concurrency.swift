// Concurrent guest closures, Hashable witnesses, Set / Dictionary work and deinits on Dispatch worker threads
// (concurrentPerform, a concurrent queue with a DispatchGroup).
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
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
