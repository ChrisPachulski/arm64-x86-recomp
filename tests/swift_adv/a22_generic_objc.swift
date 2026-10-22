// A generic NSObject subclass with @objc methods: its class has no static __objc_classlist entry (the runtime builds it
// from the generic metadata pattern), so native Foundation dispatching the methods (perform, responds, KVC) must find
// host-callable IMPs in the pattern's class_ro_t.
import Foundation
final class Box<T>: NSObject {
    let v: T
    init(_ v: T) { self.v = v }
    @objc func answer() -> NSString { "answer \(v)" as NSString }
    @objc var label: NSString { "label \(v)" as NSString }
    @objc class func kind() -> NSString { "box kind" }
}
let b = Box(42), s = Box("x")
print("perform", b.perform(NSSelectorFromString("answer"))!.takeUnretainedValue() as! NSString)
print("perform2", s.perform(NSSelectorFromString("answer"))!.takeUnretainedValue() as! NSString)
print("kvc", b.value(forKey: "label") as! NSString)
print("responds", b.responds(to: NSSelectorFromString("answer")), b.responds(to: NSSelectorFromString("nope")))
print("class", (type(of: b) as AnyObject).perform(NSSelectorFromString("kind"))!.takeUnretainedValue() as! NSString)
