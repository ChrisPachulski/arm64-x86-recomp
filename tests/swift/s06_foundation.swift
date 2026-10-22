// Foundation: Data (inline, large, slices), Data <-> NSData bridging, String <-> NSString, NSArray -> [String],
// NSDictionary -> [String: Any] (conditional bridging), JSONEncoder / JSONDecoder of guest Codable types
// (host Foundation calls the guest's encode(to:) / init(from:) and CodingKey witnesses), Date / UUID / URL basics.
import Foundation

struct Pet: Codable, Equatable { var name: String; var age: Int; var tags: [String]; var vet: String? }
struct Owner: Codable { var id: Int; var pets: [Pet]; var score: Double; var meta: [String: Int]; var kind: Kind
    enum Kind: String, Codable { case person, company } }
struct Custom: Codable {
    var x: Int; var label: String
    enum CodingKeys: String, CodingKey { case x = "the_x", label }
    init(x: Int, label: String) { self.x = x; self.label = label }
    init(from d: Decoder) throws { let c = try d.container(keyedBy: CodingKeys.self); x = try c.decode(Int.self, forKey: .x) * 2; label = try c.decode(String.self, forKey: .label) }
    func encode(to e: Encoder) throws { var c = e.container(keyedBy: CodingKeys.self); try c.encode(x, forKey: .x); try c.encode(label.uppercased(), forKey: .label) }
}

let n = CommandLine.arguments.count
var small = Data([1, 2, 3, UInt8(n)])
small.append(contentsOf: [9, 9])
let bytes: [UInt8] = (0..<300).map { UInt8($0 % 251) }
let big = bytes.withUnsafeBytes { Data(bytes: $0.baseAddress!, count: $0.count) }
let slice = big[10..<20]
print("data", small.count, Array(small), big.count, big[299], slice.count, slice.first!, big.base64EncodedString().prefix(16))
let ns = big as NSData                                         // Data._bridgeToObjectiveC
let back = Data(referencing: ns)
print("nsdata", ns.length, back == big, (small as NSData).isEqual(to: small), ns.description.count > 10)
let nsstr: NSString = "Hello, NSString"
let swstr = nsstr as String
print("nsstring", swstr.count, (swstr as NSString).length, nsstr.uppercased, nsstr.components(separatedBy: ", "))
let arr = NSArray(array: ["en-US", "fr-FR", "de"])
let langs = arr as! [String]                                   // Array._unconditionallyBridgeFromObjectiveC
print("nsarray", langs, langs.map { $0.count })
let dict: NSDictionary = ["Power Source State": "AC Power", "Current Capacity": 87, "Is Present": true]
if let d = dict as? [String: Any] {                            // Dictionary._conditionallyBridgeFromObjectiveC
    print("nsdict", d.keys.sorted(), d["Current Capacity"] as? Int as Any, d["Power Source State"] as? String as Any, d["Is Present"] as? Bool as Any)
}
print("nsdict fail", (dict as? [String: Int]) == nil)
let owner = Owner(id: 7, pets: [Pet(name: "Rex", age: 3 * n, tags: ["a", "b"], vet: nil), Pet(name: "Mia", age: 1, tags: [], vet: "Dr. K")],
                  score: 4.5, meta: ["k": 1], kind: .company)
let enc = JSONEncoder()
enc.outputFormatting = [.sortedKeys]
let json = try! enc.encode(owner)
print("json", String(data: json, encoding: .utf8)!)
let dec = try! JSONDecoder().decode(Owner.self, from: json)
print("decoded", dec.id, dec.pets == owner.pets, dec.pets[1].vet as Any, dec.kind, dec.meta)
let cj = try! enc.encode([Custom(x: 21, label: "abc")])
print("custom", String(data: cj, encoding: .utf8)!, try! JSONDecoder().decode([Custom].self, from: cj).map { "\($0.x) \($0.label)" })
do { _ = try JSONDecoder().decode(Pet.self, from: Data("{\"name\": 3}".utf8)) } catch { print("decode error", type(of: error)) }
let u = URL(string: "https://example.com/a/b?q=1")!
print("url", u.host ?? "", u.pathComponents, u.query ?? "")
let date = Date(timeIntervalSince1970: 86400 * 365)
print("date", date.timeIntervalSince1970, Calendar(identifier: .gregorian).component(.year, from: date) > 1969)
print("uuid", UUID(uuidString: "E621E1F8-C36C-495A-93FC-0C247A3E6E5F")!.uuidString.count)
