// swiftc: -parse-as-library
// IR-only corpus: runtime entry points that statically linked back-deployment code (C++) reaches, declared here
// through the stdlib's own shim headers so swiftc states their convention (C, struct returned through sret).
import SwiftShims

@inline(never) public func osVersion() -> Int {
    let v = _swift_stdlib_operatingSystemVersion()
    return v.majorVersion &* 100 &+ v.minorVersion
}
