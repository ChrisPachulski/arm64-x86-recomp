// @objc NSObject subclasses used from Objective-C: selectors performed by the runtime, KVC, description overrides read
// by -[NSString stringWithFormat:], NSSortDescriptor sorting through KVC, protocol conformance checks, an ObjC-visible
// Swift protocol, dynamic subclass lookup by name, and deinit through -dealloc.
import Foundation

@objc protocol Greeter { func greet(_ who: String) -> String; @objc optional func wave() -> Int }
@objc(SWGreeterImpl) class GreeterImpl: NSObject, Greeter {
    @objc dynamic var name: String
    @objc var count: Int = 0
    required init(name: String) { self.name = name; super.init() }
    func greet(_ who: String) -> String { count += 1; return "\(name) greets \(who)" }
    @objc func wave() -> Int { 42 }
    @objc func add(_ a: Int, _ b: Double) -> Double { Double(a) + b }
    override var description: String { "<Greeter \(name)>" }
    deinit { print("deinit Greeter", name) }
}
class Loud: GreeterImpl { override func greet(_ who: String) -> String { super.greet(who).uppercased() } }
@objc class Item: NSObject { @objc let title: String; @objc let rank: Int
    init(_ t: String, _ r: Int) { title = t; rank = r } }

let n = CommandLine.arguments.count
do {
    let g = GreeterImpl(name: "Ann")
    let any: AnyObject = g
    let r = g.perform(NSSelectorFromString("greet:"), with: "Bob")?.takeUnretainedValue() as? String
    print("perform", r as Any, g.count)
    print("responds", g.responds(to: #selector(GreeterImpl.wave)), g.responds(to: NSSelectorFromString("fly")), any.conforms(to: Greeter.self))
    print("kvc", g.value(forKey: "name") as Any, g.value(forKey: "count") as Any)
    g.setValue("Cleo", forKey: "name")
    print("kvc set", g.name, NSString(format: "%@ and %@", g, Loud(name: "Dan")))
    let p: Greeter = Loud(name: "Eve")
    print("protocol", p.greet("Fay"), p.wave?() as Any, NSStringFromClass(type(of: g)), NSStringFromClass(Loud.self).hasSuffix("Loud"))
    let cls = NSClassFromString("SWGreeterImpl") as? GreeterImpl.Type
    print("by name", cls != nil, cls.map { $0.init(name: "Gus").greet("Hal") } as Any)
    let items = NSArray(array: [Item("b", 2), Item("a", 3 * n), Item("c", 1)])
    let sorted = items.sortedArray(using: [NSSortDescriptor(key: "rank", ascending: true)]) as! [Item]
    print("sorted", sorted.map { $0.title }, (items.value(forKey: "title") as! [String]))
    let m = g.method(for: #selector(GreeterImpl.add(_:_:)))
    typealias AddF = @convention(c) (AnyObject, Selector, Int, Double) -> Double
    print("imp", unsafeBitCast(m, to: AddF.self)(g, #selector(GreeterImpl.add(_:_:)), 2, 0.5))
}
print("end")
