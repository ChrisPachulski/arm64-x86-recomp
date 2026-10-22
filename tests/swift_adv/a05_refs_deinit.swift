// weak and unowned references, [weak self] / [unowned self] captures, class deinit order (subclass before superclass,
// members after their owner, array elements in order), weak references cleared by deinit, and a retain cycle broken.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
class Base { let name: String; init(_ n: String) { name = n; print("init", n) }; deinit { print("deinit Base", name) } }
class Mid: Base { var child: Base?; deinit { print("deinit Mid", name) } }
final class Leaf: Mid { var data = [1, 2, 3]; deinit { print("deinit Leaf", name, data.count) } }
class Owner { var pet: Pet?; let id: Int; init(_ i: Int) { id = i }; deinit { print("deinit Owner", id) } }
class Pet { weak var owner: Owner?; unowned let keeper: Owner; init(_ k: Owner) { keeper = k }; deinit { print("deinit Pet keeper", keeper.id) } }
class Timer2 { var cb: (() -> Void)?; var n = 0; let tag: String; init(_ t: String) { tag = t }
    func armWeak() { cb = { [weak self] in self?.n += 1; print("weak cb", self?.n ?? -1) } }
    func armUnowned() { cb = { [unowned self] in n += 10; print("unowned cb", n) } }
    deinit { print("deinit Timer2", tag) } }
@inline(never) func scope1() {
    let l = Leaf("leaf"); l.child = Mid("inner"); (l.child as! Mid).child = Base("innermost")
    print("scope1 end")
}
scope1()
print("after scope1")
weak var w: Base?
do { let b = Base("weakly"); w = b; print("weak alive", w?.name ?? "nil") }
print("weak after", w?.name ?? "nil")
let keeper = Owner(1)
do { let o = Owner(2); let p = Pet(keeper); p.owner = o; o.pet = p; print("pet owner", p.owner!.id, p.keeper.id); o.pet = nil }
print("after pet")
let t = Timer2("w"); t.armWeak(); t.cb!(); t.cb!()
var t2: Timer2? = Timer2("u"); t2!.armUnowned(); t2!.cb!(); let saved = t2!.cb; t2!.cb = nil; t2 = nil
print("t2 released", saved != nil)
do { var arr: [Base] = [Base("a0"), Leaf("a1"), Base("a2")]; arr.remove(at: 1); print("removed"); arr.removeAll(); print("cleared") }
final class Cycle { var other: Cycle?; let n: Int; init(_ n: Int) { self.n = n }; deinit { print("deinit Cycle", n) } }
do { let a = Cycle(1), b = Cycle(2); a.other = b; b.other = a; b.other = nil }
print("cycle broken")
var weakArr: [() -> Int?] = []
do { let objs = (0..<3).map { Base("wa\($0)") }; for o in objs { weakArr.append({ [weak o] in o?.name.count }) }; print("weak arr live", weakArr.map { $0() ?? -1 }) }
print("weak arr dead", weakArr.map { $0() ?? -1 })
print("unowned keeper still", keeper.id, isKnownUniquelyReferenced(&t2))
