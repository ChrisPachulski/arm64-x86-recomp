// ManagedBuffer subclass (a guest class whose superclass is a resilient generic host class): metadata the host
// instantiates at runtime, guest deinit through the host release path.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
final class Buf: ManagedBuffer<Int, Int64> {
    static func make(_ n: Int) -> Buf { let b = Buf.create(minimumCapacity: n) { _ in n } as! Buf
        b.withUnsafeMutablePointerToElements { p in for i in 0..<n { (p + i).initialize(to: Int64(i * i)) } }; return b }
    var sum: Int64 { withUnsafeMutablePointers { h, e in (0..<h.pointee).reduce(0) { $0 + e[$1] } } }
    deinit { print("deinit Buf", header) }
}
do { let b = Buf.make(5); print("managed", b.sum, b.header, b.capacity >= 5) }
print("after managed")
