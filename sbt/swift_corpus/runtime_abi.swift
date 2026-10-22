// swiftc: -parse-as-library
// IR-only corpus: everyday Swift that makes swiftc call the runtime's fixed-ABI entry points (class casts, unowned
// references, tuple / foreign / singleton metadata, boxes, uniqueness checks, random, key paths, float parsing), so
// programs outside the corpus find them typed.
import Foundation

public final class RtOwner { public var kids: [RtNode] = []; public init() {} }
public final class RtNode { unowned(safe) public var owner: RtOwner; public init(_ o: RtOwner) { owner = o } }
public class RtBase {}
public final class RtDerived: RtBase { public var v = 1 }
public struct RtResilient { public var date: Date; public var url: URL? }          // a resilient field: singleton metadata
@inline(never) public func casts(_ b: RtBase, _ o: AnyObject) -> Int { (b as! RtDerived).v + ((o as! NSString).length) }
@inline(never) public func unowned(_ n: RtNode) -> RtOwner { n.owner }
@inline(never) public func tuples<T>(_ t: T.Type) -> [Any.Type] { [(T, Int).self, (T, Int, String).self] }
@inline(never) public func foreign() -> Any.Type { CGRect.self }
@inline(never) public func singleton() -> Any.Type { RtResilient.self }
@inline(never) public func boxed() -> () -> Int { var n = 0; return { n += 1; return n } }
@inline(never) public func unique(_ a: inout RtDerived) -> Bool { isKnownUniquelyReferenced(&a) }
@inline(never) public func grow(_ a: inout [RtNode], _ n: RtNode) { a.append(n) }   // [class] storage is a bridge object
@inline(never) public func random() -> Int { Int.random(in: 0..<100) }
@inline(never) public func parse(_ s: String) -> (Double?, Float?) { (Double(s), Float(s)) }
public struct RtKP { public var a: Int; public var b: [String: Int] }
@inline(never) public func keypaths(_ k: inout RtKP, _ c: RtDerived) -> (Int, Int) {
    let r: KeyPath<RtKP, Int> = \.a, w: WritableKeyPath<RtKP, Int> = \.a, rw: ReferenceWritableKeyPath<RtDerived, Int> = \.v
    k[keyPath: w] = 3; c[keyPath: rw] = 4
    let p: PartialKeyPath<RtKP> = \.b, any: AnyKeyPath = \RtKP.a
    return (k[keyPath: r] + c[keyPath: rw], (k[keyPath: p] as! [String: Int]).count + ((k[keyPath: any] as? Int) ?? 0))
}
@inline(never) public func classes(_ o: AnyObject) -> (Bool, AnyClass) { (o is NSObject, object_getClass(o)!) }
