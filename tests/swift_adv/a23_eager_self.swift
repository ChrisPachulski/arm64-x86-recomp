// An otherwise unused NSObject subclass overriding +self: nothing may call it before main runs (natively the class is
// never realized). Loading must not run guest class code.
import Foundation
class Quiet: NSObject {
    @objc(self) class func classSelf() -> AnyClass { print("Quiet +self ran"); return self }
}
print("main")
