// Throwing closures passed to host map / filter / compactMap / reduce / sorted(by:) / first(where:) / allSatisfy,
// rethrows, Result, errors bridged to NSError (domain, code, userInfo via CustomNSError / LocalizedError) and back.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
enum GameErr: Error, Equatable { case bad(Int), worse(String), plain }
struct CodedErr: Error, CustomNSError, LocalizedError { var n: Int
    static var errorDomain: String { "civ.coded" }; var errorCode: Int { 100 + n }
    var errorUserInfo: [String: Any] { ["n": n, "why": "because"] }
    var errorDescription: String? { "coded error \(n)" } }
@inline(never) func check(_ x: Int) throws -> Int { if x == 7 { throw GameErr.bad(x) }; if x < 0 { throw CodedErr(n: -x) }; return x * 2 }
@inline(never) func run(_ xs: [Int]) -> String {
    do {
        let m = try xs.map { try check($0) }
        let f = try xs.filter { try check($0) > 4 }
        let c = try xs.compactMap { x -> Int? in x == 3 ? nil : try check(x) }
        let r = try xs.reduce(0) { try $0 + check($1) }
        let s = try xs.sorted { a, b in _ = try check(a); return a > b }
        let fw = try xs.first { try check($0) == 8 }
        let al = try xs.allSatisfy { try check($0) >= 0 }
        let lz = try xs.lazy.map { $0 + 1 }.filter { try check($0) > 0 }.count
        return "ok \(m) \(f) \(c) \(r) \(s) \(fw ?? -1) \(al) \(lz)"
    } catch let e as GameErr { return "GameErr \(e)" } catch { return "other \(error)" }
}
print(run([1, 2, 3, 4]))
print(run([1, 7, 3]))
print(run([5, -2]))
func twice<T>(_ f: () throws -> T) rethrows -> [T] { [try f(), try f()] }
var k = 0
print("rethrows", twice { k += 1; return k }, (try? twice { () throws -> Int in throw GameErr.plain }) == nil)
let results: [Result<Int, Error>] = [1, 7, -3].map { x in Result { try check(x) } }
for r in results { switch r { case .success(let v): print("success", v); case .failure(let e): print("failure", e) } }
let ns1 = GameErr.worse("deep") as NSError
print("ns1", ns1.domain, ns1.code, ns1.userInfo.count)
let ns2 = CodedErr(n: 5) as NSError
print("ns2", ns2.domain, ns2.code, ns2.userInfo["why"] as? String ?? "nil", ns2.userInfo["n"] as? Int ?? -1, ns2.localizedDescription)
let anyErr: Error = ns1
print("back", (anyErr as? GameErr).map { "\($0)" } ?? "nil", (ns2 as Error as? CodedErr)?.n ?? -1)
let fileErr: Error = NSError(domain: NSCocoaErrorDomain, code: NSFileNoSuchFileError, userInfo: [NSFilePathErrorKey: "/nope"])
print("cocoa", (fileErr as? CocoaError)?.code == .fileNoSuchFile, (fileErr as NSError).userInfo[NSFilePathErrorKey] as? String ?? "nil")
do { _ = try String(contentsOfFile: "/definitely/not/here.txt", encoding: .utf8) }
catch let e as CocoaError { print("host threw CocoaError", e.code.rawValue, e.filePath ?? "nil") }
catch { print("host threw other", type(of: error)) }
let errs: [Error] = [GameErr.bad(1), CodedErr(n: 2), GameErr.plain]
print("errs", errs.map { ($0 as NSError).code }, errs.map { String(describing: $0) }, errs.compactMap { $0 as? GameErr }.count)
