// swiftc: -parse-as-library
// System APIs that app Swift code commonly imports, used the usual way: NWPathMonitor (init, pathUpdateHandler, start(queue:),
// currentPath.status == .satisfied) on a DispatchQueue(label:qos:attributes:autoreleaseFrequency:target:), os
// Logger, Data(bytes:count:) bridged to NSData, NSArray -> [String] and NSDictionary -> [String: Any] bridging, a
// Dictionary<Int, NSObject> in a Swift class (the controller bridge), NSObject ==, as? to an ObjC class, _typeName,
// a RawRepresentable Int32 cursor enum used as a Dictionary key, String index(before:) / Substring / utf8CString + strdup,
// lazy globals behind swift_once, and @_cdecl entry points called from C the way C++ code calls them.
import Dispatch
import Foundation
import Network
import os
import SwiftShims

enum CursorType: Int32 { case cursorDefault, cursorWait, cursorText, cursorCrosshair, cursorGrab, cursorHelp, cursorURL }
var cursorUse: [CursorType: Int] = [:]
var handles: [Int: NSObject] = [:]
let netQueue = DispatchQueue(label: "network.monitor", qos: .unspecified, attributes: [], autoreleaseFrequency: .inherit, target: nil)
var monitor: NWPathMonitor?
var lastStatus = "none"
let updated = DispatchSemaphore(value: 0)
let log = Logger(subsystem: "com.example.gdyld", category: "swift-bed")

final class ControllerBridge {
    var usedControllers: [Int: NSObject] = [:]
    func attach(_ i: Int, _ o: NSObject) { usedControllers[i] = o }
    func kind(_ i: Int) -> String {
        guard let o = usedControllers[i] else { return "none" }
        if let s = o as? NSString { return "string " + (s as String) }
        return "object " + _typeName(type(of: o), qualified: false)
    }
}
let bridge = ControllerBridge()

@_cdecl("Bed_LoadPointer") public func loadPointer(_ p: UnsafeRawPointer, _ size: Int32) -> Int {
    let d = Data(bytes: p, count: Int(size))
    let ns = d as NSData
    let h = handles.count + 1
    handles[h] = ns
    return h
}
@_cdecl("Bed_SetPointer") public func setPointer(_ type: Int32, _ handle: Int) -> Int {
    guard let t = CursorType(rawValue: type) else { return -1 }
    cursorUse[t, default: 0] += 1
    return (handles[handle] as? NSData)?.length ?? 0
}
@_cdecl("Bed_GetLanguage") public func getLanguage() -> UnsafeMutablePointer<CChar>? {
    let langs = NSArray(array: ["fr-CA", "en-US"]) as! [String]
    guard let first = langs.first else { return nil }
    let code = first.firstIndex(of: "-").map { String(first[first.startIndex..<$0]) } ?? first
    let last = code[code.index(before: code.endIndex)]
    return code.utf8CString.withUnsafeBufferPointer { strdup($0.baseAddress!) }.map { last == "r" ? $0 : $0 }
}
@_cdecl("Bed_InitializeNetworkMonitor") public func initializeNetworkMonitor() {
    let m = NWPathMonitor()
    m.pathUpdateHandler = { path in lastStatus = "\(path.status)"; updated.signal() }
    m.start(queue: netQueue)
    monitor = m
}
@_cdecl("Bed_IsConnected") public func isConnected() -> Bool { monitor.map { $0.currentPath.status == .satisfied } ?? false }

@main struct Bed {
    static func main() {
        let n = CommandLine.arguments.count
        let bytes: [UInt8] = (0..<(40 * n)).map { UInt8($0) }
        let h = bytes.withUnsafeBytes { loadPointer($0.baseAddress!, Int32($0.count)) }
        print("pointer", h, setPointer(3, h), setPointer(6, h), setPointer(99, h), cursorUse.count, cursorUse[.cursorURL] as Any)
        let lang = getLanguage()!
        print("language", String(cString: lang)); free(lang)
        let info: NSDictionary = ["Power Source State": "AC Power", "Type": "InternalBattery"]
        if let d = info as? [String: Any], let s = d["Power Source State"] as? String { print("power", s == "AC Power", d.count) }
        bridge.attach(0, NSString(string: "pad"))
        bridge.attach(1, NSNumber(value: 5))
        print("bridge", bridge.kind(0), bridge.kind(1), bridge.kind(2), NSObject() == NSObject(), bridge.usedControllers[0]! == NSString(string: "pad"))
        log.info("bed logger \(n, privacy: .public)")
        log.error("bed logger error \(String(repeating: "x", count: n))")
        print("logger ok")
        print("before start", isConnected())
        initializeNetworkMonitor()
        print("handler ran", updated.wait(timeout: .now() + 20) == .success, "status", lastStatus)
        print("connected", isConnected() == (lastStatus == "satisfied"))
        monitor?.cancel()
        print("available", { if #available(macOS 13, *) { return true } else { return false } }())
        let v = _swift_stdlib_operatingSystemVersion()          // what back-deployment code asks the runtime
        print("os version", v.majorVersion >= 13, v.majorVersion == ProcessInfo.processInfo.operatingSystemVersion.majorVersion)
    }
}
