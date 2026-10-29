// Performance: a guest loop that copies and destroys existentials of guest classes 200k times. Each copy and destroy goes
// through the value witness table every Swift class metadata shares ($sBoWV, host libswiftCore), so the guest calls the
// same few host functions through a pointer over and over (run_swift_adv.py INSN_BOUND: translated / native instructions).
protocol Shape { func area() -> Int }
final class Sq: Shape { let s: Int; init(_ s: Int) { self.s = s }; func area() -> Int { s &* s } }
final class Rect: Shape { let w: Int, h: Int; init(_ w: Int, _ h: Int) { self.w = w; self.h = h }; func area() -> Int { w &* h } }
@inline(never) func pick(_ xs: [Shape], _ i: Int) -> Shape { xs[i % xs.count] }
let n = CommandLine.arguments.count > 1 ? Int(CommandLine.arguments[1])! : 200_000
var xs: [Shape] = []
for i in 0..<64 { xs.append(i % 3 == 0 ? Sq(i) : Rect(i, i + 1)) }
var total = 0
for i in 0..<n { total &+= pick(xs, i &* 7).area() }
print("total", total)
