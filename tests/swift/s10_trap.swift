// A bridged-array failure path: an NSArray force-bridged to [GCController]-like [NSString] holds a foreign
// element; reading it builds "Could not cast value of type ..." (_typeName, String.append, _StringGuts.grow) and calls the
// host's _assertionFailure(_:_:flags:), which reports and traps natively (the oracle's exit signal). Output printed
// before the trap must survive.
import Foundation

@inline(never) func names(_ a: NSArray) -> [NSString] { a as! [NSString] }
@inline(never) func total(_ xs: [NSString]) -> Int { var t = 0; for x in xs { t += x.length }; return t }

let n = CommandLine.arguments.count
print("good", total(names(NSArray(array: [NSString(string: "pad"), NSString(string: "stick")]))))
let bad = names(NSArray(array: [NSString(string: "ok"), NSNumber(value: n)]))
print("lazy count", bad.count)
fflush(stdout)
print("bad", total(bad))
print("not reached")
