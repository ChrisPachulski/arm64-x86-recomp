// swiftc: -Onone -parse-as-library
// IR-only corpus at -Onone: the unspecialized stdlib entry points every -Onone program calls (array literals, string
// interpolation, print, reflection, Mirror, common error types).
import Foundation

public struct RtPair { public var a: Int; public var b: String }
@inline(never) public func literals() -> [Int] { [1, 2, 3] }
@inline(never) public func strings(_ p: RtPair) -> String { "\(p.a) \(p.b) \(p)" + String(reflecting: p) + String(describing: p) }
@inline(never) public func printing(_ p: RtPair) { var s = ""; print(p, 1, separator: ",", terminator: "", to: &s); print(s); debugPrint(p) }
@inline(never) public func mirror(_ x: Any) -> Int { Mirror(reflecting: x).children.count }
@inline(never) public func errors(_ e: Error) -> String {
    if let d = e as? DecodingError { return "\(d)" }
    if let c = e as? CocoaError { return "\(c.code)" }
    return "\(e)"
}
