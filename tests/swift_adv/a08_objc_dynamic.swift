// @objc dynamic overrides called from Objective-C: a Swift subclass chain overriding methods and properties of a Swift
// NSObject base, reached through perform(_:), NSInvocation-free KVC, NSArray sorting through compare:, isEqual:/hash
// used by NSSet and NSDictionary, KVO on dynamic properties, and method_exchangeImplementations swizzling.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
class Piece: NSObject {
    @objc dynamic var rank: Int
    @objc dynamic var label: String { "piece\(rank)" }
    init(_ r: Int) { rank = r; super.init() }
    @objc dynamic func move(_ n: Int) -> Int { rank + n }
    @objc dynamic func speak() -> String { "piece" }
    @objc func compare(_ o: Piece) -> ComparisonResult { rank < o.rank ? .orderedAscending : rank > o.rank ? .orderedDescending : .orderedSame }
    override func isEqual(_ o: Any?) -> Bool { (o as? Piece)?.rank == rank }
    override var hash: Int { rank }
    override var description: String { "<\(type(of: self)) \(rank)>" }
}
class Knight: Piece {
    override func move(_ n: Int) -> Int { super.move(n) * 10 }
    override func speak() -> String { "knight<" + super.speak() + ">" }
    override var label: String { "knight" + super.label }
}
final class Queen: Knight { override func speak() -> String { "queen/" + super.speak() } }
let ps: [Piece] = [Queen(3), Piece(1), Knight(2), Piece(3)]
for p in ps {
    let r = p.perform(#selector(Piece.speak))!.takeUnretainedValue() as! String
    print("perform", p, r, p.value(forKey: "label") as! String, p.move(1))
}
let arr = NSArray(array: ps)
print("sortedArray", (arr.sortedArray(using: #selector(Piece.compare(_:))) as! [Piece]).map { $0.rank })
print("kvc", arr.value(forKey: "rank") as! [Int], (arr.value(forKeyPath: "@max.rank") as! NSNumber).intValue)
let set = NSSet(array: ps)
print("nsset", set.count, set.contains(Piece(2)), set.contains(Piece(9)))
let cs = NSCountedSet(array: ps); let ma = NSMutableArray(array: ps)
print("counted", cs.count(for: Piece(3)), cs.count, ma.index(of: Knight(2)), ma.contains(Queen(1)))
ps[1].setValue(7, forKey: "rank"); print("setValue", ps[1].rank, ps[1].label)
final class Watcher: NSObject { var seen: [String] = []
    override func observeValue(forKeyPath k: String?, of o: Any?, change: [NSKeyValueChangeKey: Any]?, context: UnsafeMutableRawPointer?) {
        seen.append("\(k!)=\(change?[.newKey] ?? "?")") } }
let wt = Watcher(); let q = ps[0]
q.addObserver(wt, forKeyPath: "rank", options: [.new], context: nil)
q.rank = 11; q.setValue(12, forKey: "rank")
q.removeObserver(wt, forKeyPath: "rank")
q.rank = 13
print("kvo", wt.seen, String(cString: object_getClassName(q)))
var obs: [String] = []
let tok = ps[2].observe(\.rank, options: [.old, .new]) { p, ch in obs.append("\(ch.oldValue!)->\(ch.newValue!)") }
ps[2].rank = 20; ps[2].rank = 21; tok.invalidate(); ps[2].rank = 22
print("kvo block", obs)
let m1 = class_getInstanceMethod(Knight.self, #selector(Piece.speak))!
let m2 = class_getInstanceMethod(Piece.self, #selector(Piece.move(_:)))!
print("imp types", String(cString: method_getTypeEncoding(m1)!), String(cString: method_getTypeEncoding(m2)!))
let swz = class_getInstanceMethod(Knight.self, #selector(Knight.speak))!
let blockImp: @convention(block) (Knight) -> String = { k in "swizzled \(k.rank)" }
method_setImplementation(swz, imp_implementationWithBlock(blockImp))
print("swizzled", ps[2].speak(), ps[0].speak(), Piece(0).speak())
