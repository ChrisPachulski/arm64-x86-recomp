// Dispatch: the full DispatchQueue(label:qos:attributes:autoreleaseFrequency:target:), async/sync on serial and
// concurrent queues, DispatchGroup, DispatchSemaphore, concurrentPerform, asyncAfter, work items, a queue-protected
// counter mutated from many host threads (guest closures entered on host-owned threads).
import Dispatch
import Foundation

final class Tally { private var v = 0; private let q = DispatchQueue(label: "tally")
    func add(_ k: Int) { q.sync { v += k } }
    var value: Int { q.sync { v } } }

let n = CommandLine.arguments.count
let serial = DispatchQueue(label: "bed.serial", qos: .unspecified, attributes: [], autoreleaseFrequency: .inherit, target: nil)
let conc = DispatchQueue(label: "bed.conc", qos: .userInitiated, attributes: .concurrent)
let group = DispatchGroup()
let tally = Tally()
var order: [Int] = []
for i in 0..<10 { serial.async(group: group) { order.append(i) } }
for i in 1...100 { conc.async(group: group) { tally.add(i) } }
print("group wait", group.wait(timeout: .now() + 30) == .success)
print("serial order", order, "tally", tally.value)
let sem = DispatchSemaphore(value: 0)
var fromBG = ""
DispatchQueue.global(qos: .utility).async { fromBG = Thread.isMainThread ? "main" : "background"; sem.signal() }
print("semaphore", sem.wait(timeout: .now() + 30) == .success, fromBG)
var squares = [Int](repeating: 0, count: 64)
squares.withUnsafeMutableBufferPointer { buf in DispatchQueue.concurrentPerform(iterations: 64) { i in buf[i] = i * i * n } }
print("concurrentPerform", squares.reduce(0, +), squares[63])
let item = DispatchWorkItem { print("work item ran") }
serial.async(execute: item)
item.wait()
let later = DispatchSemaphore(value: 0)
serial.asyncAfter(deadline: .now() + 0.05) { print("asyncAfter ran"); later.signal() }
_ = later.wait(timeout: .now() + 30)
print("sync result", serial.sync { order.count * 2 }, conc.sync { "label=" + (conc.label) })
print("qos", DispatchQoS.unspecified == .unspecified, serial.qos.qosClass == .unspecified)
