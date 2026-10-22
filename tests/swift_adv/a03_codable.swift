// Codable round-trips of nested guest types with optionals, enums (raw and with associated values), custom CodingKeys,
// arrays and dictionaries, through JSONEncoder / JSONDecoder and PropertyListEncoder; a DecodingError path.
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
enum Terrain: String, Codable { case plains, hills, coast }
enum Yield: Codable, Equatable { case food(Int), gold(Double, bonus: Bool), none }
struct Tile: Codable, Equatable { var x: Int; var y: Int; var terrain: Terrain; var yield: Yield; var owner: String?; var river: Bool? }
struct City: Codable, Equatable {
    var name: String; var pop: Int; var tiles: [Tile]; var tags: [String: Int]; var capital: [City]?
    var founded: Double?
    enum CodingKeys: String, CodingKey { case name = "city_name", pop, tiles, tags, capital, founded }
    indirect enum Box: Codable { case leaf }
}
struct Wrap: Codable, Equatable { var cities: [City]; var note: String?; var ids: [Int]; var grid: [[Int?]] }
@inline(never) func sample() -> Wrap {
    let t1 = Tile(x: 1, y: 2, terrain: .hills, yield: .food(3), owner: "rome", river: nil)
    let t2 = Tile(x: -4, y: 9, terrain: .coast, yield: .gold(2.5, bonus: true), owner: nil, river: true)
    let t3 = Tile(x: 0, y: 0, terrain: .plains, yield: .none, owner: "", river: false)
    let cap = City(name: "Roma", pop: 12, tiles: [t1], tags: ["wonder": 2], capital: nil, founded: -753)
    let c = City(name: "Ostia", pop: 3, tiles: [t2, t3], tags: [:], capital: [cap], founded: nil)
    return Wrap(cities: [c, cap], note: nil, ids: [3, 1, 2], grid: [[1, nil], [], [nil]])
}
let w = sample()
let enc = JSONEncoder(); enc.outputFormatting = [.sortedKeys]
let data = try! enc.encode(w)
print("json", String(decoding: data, as: UTF8.self))
let back = try! JSONDecoder().decode(Wrap.self, from: data)
print("roundtrip json", back == w, back.cities[0].capital?.first?.name ?? "nil", back.cities[0].tiles[0].yield, back.ids.sorted())
let pl = PropertyListEncoder(); pl.outputFormat = .xml
let pdata = try! pl.encode(w)
let pback = try! PropertyListDecoder().decode(Wrap.self, from: pdata)
print("roundtrip plist", pback == w, pdata.count > 100)
let bad = Data(#"{"cities":[{"city_name":"X","pop":"many","tiles":[],"tags":{}}],"ids":[],"grid":[]}"#.utf8)
do { _ = try JSONDecoder().decode(Wrap.self, from: bad); print("bad decoded?!") }
catch let DecodingError.typeMismatch(t, ctx) { print("typeMismatch", t, ctx.codingPath.map(\.stringValue)) }
catch { print("other error", error) }
let missing = Data(#"{"cities":[],"grid":[]}"#.utf8)
do { _ = try JSONDecoder().decode(Wrap.self, from: missing) } catch let DecodingError.keyNotFound(k, _) { print("keyNotFound", k.stringValue) } catch { print("other", error) }
print("enum alone", String(decoding: try! enc.encode([Yield.gold(1, bonus: false), .none]), as: UTF8.self))
