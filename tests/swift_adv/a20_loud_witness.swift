// A host stdlib function calling a guest witness whose requirement is in no corpus (TextOutputStream.write via
// print(_:to:)): must stop loudly, never jump into guest code.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
struct Sink: TextOutputStream { var parts: [String] = []; mutating func write(_ s: String) { parts.append(s) } }
@inline(never) func emit<T: TextOutputStream>(_ t: inout T) { print("a", 1, to: &t) }
print("before")
var s = Sink()
emit(&s)
print("sink", s.parts.count)
