// Classes: inheritance, overrides, super calls, deinit order, final/static members, identity, weak/unowned refs,
// class-constrained protocols, a generic class, type(of:) and dynamic casts between classes.
class Animal: CustomStringConvertible {
    let name: String
    var legs: Int
    static var count = 0
    init(name: String, legs: Int) { self.name = name; self.legs = legs; Animal.count += 1 }
    func speak() -> String { "..." }
    func intro() -> String { "\(name) says \(speak()) on \(legs) legs" }
    var description: String { "Animal(\(name))" }
    deinit { print("deinit Animal \(name)") }
}
class Dog: Animal {
    var tricks: [String] = []
    init(name: String) { super.init(name: name, legs: 4) }
    override func speak() -> String { "woof" }
    override func intro() -> String { super.intro() + " and knows \(tricks.count) tricks" }
    deinit { print("deinit Dog \(name)") }
}
final class Puppy: Dog {
    override func speak() -> String { "yip " + super.speak() }
    deinit { print("deinit Puppy \(name)") }
}
protocol Owner: AnyObject { var pets: [Animal] { get set } }
final class Person: Owner {
    var pets: [Animal] = []
    weak var friend: Person?
    unowned(unsafe) var me: Person? = nil
    init() { me = self }
}
final class Box<T> {
    var items: [T] = []
    func add(_ t: T) -> Box<T> { items.append(t); return self }
    deinit { print("deinit Box<\(T.self)> with \(items.count)") }
}
@inline(never) func describe(_ a: Animal) -> String {
    if let p = a as? Puppy { return "puppy " + p.name }
    if let d = a as? Dog { return "dog \(d.tricks)" }
    return "animal \(type(of: a))"
}

let n = CommandLine.arguments.count
do {
    let d = Dog(name: "Rex")
    d.tricks = ["sit", "roll"]
    let p = Puppy(name: "Bit")
    let a = Animal(name: "Generic", legs: 2 * n)
    let zoo: [Animal] = [d, p, a]
    for z in zoo { print(z.intro(), "|", describe(z), "|", z) }
    print("count", Animal.count, "same", zoo[0] === d, zoo[1] === d)
    let owner = Person()
    owner.pets = zoo
    let other = Person(); owner.friend = other
    print("friend", owner.friend != nil, owner.me === owner)
    var box: Box<Int>? = Box<Int>().add(1).add(n)
    print("box", box!.items)
    box = nil
    let sbox = Box<String>().add("a")
    print("sbox", sbox.items, type(of: sbox))
}
print("after scope", Animal.count)
