// Closures capturing context (escaping, mutated captures, captured classes, autoclosures), throws / try / catch with
// payload error enums, rethrows, defer, try?, Result, errors stored and copied.
enum ParseError: Error, Equatable { case empty, bad(String), tooLong(Int) }
struct Wrapped: Error { var inner: ParseError; var line: Int }
final class Counter { var hits = 0; deinit { print("deinit Counter", hits) } }

@inline(never) func parse(_ s: String) throws -> Int {
    if s.isEmpty { throw ParseError.empty }
    if s.count > 4 { throw ParseError.tooLong(s.count) }
    guard let v = Int(s) else { throw Wrapped(inner: .bad(s), line: 7) }
    return v
}
@inline(never) func mapAll(_ xs: [String], _ f: (String) throws -> Int) rethrows -> [Int] { try xs.map(f) }
@inline(never) func makeAdder(_ k: Int) -> (Int) -> Int { { $0 + k } }
@inline(never) func makeCounter() -> (() -> Int, () -> Int) { var c = 0; return ({ c += 1; return c }, { c }) }
@inline(never) func apply(_ fs: [(Int) -> Int], _ x: Int) -> [Int] { fs.map { $0(x) } }
@inline(never) func lazyCheck(_ c: Bool, _ msg: @autoclosure () -> String) -> String { c ? msg() : "skipped" }

let n = CommandLine.arguments.count
var log: [String] = []
for s in ["12", "", "abcde", "x1", "\(40 + n)"] {
    do {
        defer { log.append("done \(s)") }
        print("parsed", try parse(s))
    } catch ParseError.tooLong(let k) { print("too long", k)
    } catch let e as ParseError { print("parse error", e, e == .empty)
    } catch { print("other", error, type(of: error)) }
}
print("log", log.count, log.last!)
print("try?", (try? parse("7")) as Any, (try? parse("")) as Any)
do { print(try mapAll(["1", "2", "3"], parse)); print(try mapAll(["1", "zz"], parse)) } catch { print("mapAll failed:", error) }
let r1: Result<Int, Error> = Result { try parse("99") }
let r2: Result<Int, Error> = Result { try parse("") }
print("result", (try? r1.get()) as Any, { if case .failure(let e) = r2 { return "\(e)" }; return "ok" }())
var saved: [Error] = []
for s in ["", "q"] { do { _ = try parse(s) } catch { saved.append(error) } }
let copy = saved
print("saved", copy.map { "\($0)" }, saved.count)
let adders = (1...3).map(makeAdder)
print("adders", apply(adders, 10 * n))
let (inc, get) = makeCounter()
_ = inc(); _ = inc()
print("counter", inc(), get())
do {
    let k = Counter()
    let hit: () -> Void = { k.hits += 1 }
    var stored: [() -> Void] = [hit, hit]
    stored.append { k.hits += 10 }
    for f in stored { f() }
    print("hits", k.hits)
}
print("lazy", lazyCheck(n > 0, "evaluated"), lazyCheck(false, "never"))
let sorted = ["pear", "fig", "banana", "kiwi"].sorted { $0.count != $1.count ? $0.count < $1.count : $0 < $1 }
print("sorted", sorted)
