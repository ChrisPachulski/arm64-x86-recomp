// Host Swift APIs whose lowered signatures stress the bridge: Decimal (20-byte struct, 9 scalars per argument, stack
// spill, indirect result), UUID (16 x UInt8 tuple), CGRect / CGPoint overlay methods (4 doubles), Optional<Double> /
// Optional<Float> results ({double, i1}), Int8/Int16 sign extension, Float32 math, and Character / Unicode scalars.
import Foundation
import CoreGraphics
setvbuf(stdout, nil, _IOLBF, 0)
@inline(never) func dec(_ s: String) -> Decimal { Decimal(string: s)! }
let a = dec("12.345"), b = dec("-0.0005"), c = dec("1e-3")
print("decimal", a + b, a * c, (a - b) / dec("3"), a < b, (a * a).description, Decimal(17).description)
var r = Decimal(); var x = a; NSDecimalRound(&r, &x, 1, .bankers); print("round", r, x.exponent, x.isSignMinus, x.significand)
let u = UUID(uuidString: "E621E1F8-C36C-495A-93FC-0C247A3E6E5F")!
let t = u.uuid
print("uuid", u.uuidString, t.0, t.7, t.15, UUID(uuid: t) == u, u.hashValue == UUID(uuid: t).hashValue)
let rect = CGRect(x: 1.5, y: -2, width: 10, height: 4)
print("cg", rect.insetBy(dx: 1, dy: 0.5), rect.union(CGRect(x: 20, y: 20, width: 1, height: 1)), rect.contains(CGPoint(x: 2, y: 0)), rect.midX, rect.applying(CGAffineTransform(a: 2, b: 0, c: 0, d: -1, tx: 0, ty: 0)))
print("optdouble", Double("3.25") ?? -1, Double("x") ?? -1, Float("1.5e3") ?? -1, Int8("-100") ?? 0, Int16("-30000") ?? 0, UInt8("255") ?? 0)
@inline(never) func f32(_ v: Float) -> Float { (v * 1.5).squareRoot() + Float.pi.rounded(.down) }
print("f32", f32(6), Float(1) / 3, Double(Float(0.1)), (-7 as Int8) >> 1, Int16.min &+ 1, (1.0 as Double).nextUp)
let s = "naïve café 🇫🇷 e\u{301}"
print("unicode", s.count, s.unicodeScalars.count, s.utf16.count, s.reversed().map(String.init).joined(), s.uppercased(), Character("é") == Character("e\u{301}"))
print("measure", Measurement(value: 3, unit: UnitLength.kilometers).converted(to: .meters).value, String(format: "%.3f|%5d|%@|%c", 3.14159, 42, "obj", 65))
var cal = Calendar(identifier: .gregorian); cal.timeZone = TimeZone(identifier: "UTC")!
let d = cal.date(from: DateComponents(year: 2024, month: 2, day: 29, hour: 13))!
print("date", d.timeIntervalSince1970, cal.component(.weekday, from: d), cal.date(byAdding: .day, value: 1, to: d)!.timeIntervalSince1970, ISO8601DateFormatter().string(from: d))
