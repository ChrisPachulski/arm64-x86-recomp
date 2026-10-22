// Key paths with stored components only (no computed getter in the pattern): struct fields, nested struct fields, a
// final class stored property, tuple elements; read and write through host swift_getAtKeyPath / setAt*.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
struct Inner { var a: Int; var b: Double }
struct Outer { var name: String; var inner: Inner; var pair: (Int, Int8) }
final class Holder { var v: Int = 5; var o = Outer(name: "h", inner: Inner(a: 1, b: 2), pair: (3, 4)) }
@inline(never) func read<R, V>(_ r: R, _ k: KeyPath<R, V>) -> V { r[keyPath: k] }
@inline(never) func write<R, V>(_ r: inout R, _ k: WritableKeyPath<R, V>, _ v: V) { r[keyPath: k] = v }
var o = Outer(name: "o", inner: Inner(a: 7, b: 1.5), pair: (9, -2))
print("read", read(o, \.inner.a), read(o, \.inner.b), read(o, \.name), read(o, \.pair.1))
write(&o, \.inner.b, 6.25); write(&o, \.pair.0, 99); write(&o, \.name, "renamed")
print("write", o.inner.b, o.pair.0, o.name)
let h = Holder()
print("class", read(h, \.v), read(h, \.o.inner.a))
h[keyPath: \Holder.v] = 12; h[keyPath: \Holder.o.inner.a] = 13
print("class write", h.v, h.o.inner.a)
