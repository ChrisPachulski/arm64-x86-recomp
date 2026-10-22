// Swift and Objective-C mixed in one image (a11_mixed.m compiled into the same executable, -import-objc-header):
// a Swift subclass of an ObjC class overriding a method the ObjC code calls on self, a Swift class conforming to an ObjC
// protocol called from ObjC (struct argument), Swift closures passed as ObjC blocks, ObjC C functions with struct
// returns, NSClassFromString of a Swift class from ObjC, and ObjC formatting a Swift object's description.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
@objc(SwiftEngine) final class SwiftEngine: MXEngine {
    var log: [String] = []
    override func hook(_ n: Int) -> String { log.append("h\(n)"); return "swift hook \(n) / " + super.hook(n) }
    override var description: String { "SwiftEngine(\(title ?? "nil"), \(ticks))" }
}
final class Src: NSObject, MXSource {
    let base: Int; init(_ b: Int) { base = b }
    func value(at i: Int) -> Int { base + i * i }
    func name(for p: MXPoint) -> String { "pt \(Int(p.x * 100)) \(Int(p.y * 100)) \(p.tag)" }
}
let e = SwiftEngine(title: "eng")
print(e.step()); print(e.step()); print("log", e.log)
let plain = MXEngine(title: "plain"); print(plain.step())
print("sum", e.sum(from: Src(10), count: 4))
let names = e.mapNames([1, "two", Src(0), e]) { obj, idx in "\(idx):\(type(of: obj))" }
print("blocks", names)
let m = MXMid(MXPoint(x: 1, y: 2, tag: 3), MXPoint(x: 3, y: -6, tag: 4))
print("mid", Int(m.x * 100), Int(m.y * 100), m.tag)
print("describe", MXDescribe(e), MXDescribe(Src(1)).hasPrefix("[_TtC"), MXDescribe(plain).hasPrefix("[MXEngine"))
let byName = MXEngine.make(byName: "SwiftEngine")
print("byname", type(of: byName), byName.step(), (byName as? SwiftEngine)?.log ?? [])
