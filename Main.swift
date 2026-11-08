import AppKit
import UniformTypeIdentifiers
import UserNotifications

func accountNumbers(_ accounts: [Account], saved: [String: Int]) -> [String: Int] {
    var result: [String: Int] = [:]
    for provider in ["codex", "claude"] {
        let seeds = provider == "codex" ? ["main": 1, "account2": 2, "account3": 3] : ["a": 1, "b": 2, "c": 3]
        let ids = Set(saved.keys.filter { $0.hasPrefix(provider + ":") } + accounts.filter { $0.provider == provider }.map(\.id)).sorted()
        var used = Set<Int>()
        for id in ids {
            if let number = saved[id], number > 0, !used.contains(number) { result[id] = number; used.insert(number) }
        }
        // Keep persisted identities first; legacy imports use familiar numbers when free.
        for (key, number) in seeds {
            let id = "\(provider):\(key)"
            if ids.contains(id), result[id] == nil, !used.contains(number) { result[id] = number; used.insert(number) }
        }
        var next = (used.max() ?? 0) + 1
        for id in ids where result[id] == nil { result[id] = next; next += 1 }
    }
    return result
}
struct AlertSnapshot {
    let id: String
    let remaining: Double
    let reset: Date
}
enum AccountStrategy: String, CaseIterable {
    case sequential, balance, rate
    var title: String { switch self { case .sequential: return "ตามลำดับ"; case .balance: return "กระจายโควตา"; case .rate: return "ตามรอบรีเซ็ต" } }
}
func freshWindows(_ value: QuotaViewData?, now: Date) -> [WindowQuota]? {
    guard let value, value.error == nil, let updated = value.updatedDate, (-60...900).contains(now.timeIntervalSince(updated)), let weekly = value.weekly else { return nil }
    let windows = [weekly] + (value.primary.map { [$0] } ?? [])
    guard windows.allSatisfy({ window in guard let used = window.used, used.isFinite, (0...100).contains(used), let reset = window.reset else { return false }; return reset > now }) else { return nil }
    return windows
}
func strategyWinner(_ accounts: [Account], quota: [String: QuotaViewData], numbers: [String: Int], provider: String, strategy: AccountStrategy, now: Date) -> String? {
    let eligible = accounts.filter { $0.provider == provider && freshWindows(quota[$0.id], now: now)?.allSatisfy({ $0.used! < 100 }) == true }
    return eligible.sorted { a, b in
        let av = quota[a.id]!, bv = quota[b.id]!
        let aw = freshWindows(av, now: now)!, bw = freshWindows(bv, now: now)!
        if strategy == .rate {
            func ready(_ v: QuotaViewData) -> Bool { v.weekly!.used! <= 90 && (v.primary?.used ?? 0) <= 80 }
            if ready(av) != ready(bv) { return ready(av) }
        }
        if strategy != .sequential {
            func score(_ windows: [WindowQuota]) -> Double { windows.map { (100 - $0.used!) / (strategy == .balance ? 1 : max($0.reset!.timeIntervalSince(now) / 3600, 1.0 / 60)) }.min()! }
            if score(aw) != score(bw) { return score(aw) > score(bw) }
        }
        let an = numbers[a.id] ?? Int.max, bn = numbers[b.id] ?? Int.max
        return an == bn ? a.id < b.id : an < bn
    }.first?.id
}
func avoidResetReason(_ value: QuotaViewData?, hours: Int, now: Date) -> String? {
    guard let windows = freshWindows(value, now: now) else { return "รอข้อมูลโควตาใหม่ก่อนใช้สิทธิ์" }
    let limiting = windows.sorted { $0.used! == $1.used! ? $0.reset! > $1.reset! : $0.used! > $1.used! }.first!
    return limiting.reset!.timeIntervalSince(now) <= Double(hours) * 3600 ? "เก็บสิทธิ์ไว้ · รอบที่ใช้มากสุดจะรีเซ็ตภายใน \(hours) ชม." : nil
}
struct UsageThreshold { let id: String; let window: String; let used: Double; let reset: Date }
func thresholdEvents(_ values: [UsageThreshold], enabled: Bool, now: Date, history: inout AlertHistory) -> [UsageThreshold] {
    guard enabled else { return [] }
    history.events = history.events.filter { $0.value > now }
    var pending: [UsageThreshold] = []
    for value in values.sorted(by: { ($0.id + $0.window) < ($1.id + $1.window) }) where value.used.isFinite && (50...100).contains(value.used) && value.reset > now {
        let key = "threshold:\(value.id):\(value.window):\(Int(value.reset.timeIntervalSince1970))"
        if history.events[key] == nil { history.events[key] = value.reset; pending.append(value) }
    }
    if !pending.isEmpty { history.lastSent = now }
    return pending
}
func strategyTests() {
    let now = Date(timeIntervalSince1970: 1800000000)
    let accounts = (1...3).map { Account(id: "codex:a\($0)", provider: "codex", key: "a\($0)", label: "", email: nil, usageAccount: nil) }
    let numbers = Dictionary(uniqueKeysWithValues: accounts.enumerated().map { ($0.element.id, $0.offset + 1) })
    let data = [accounts[0].id: QuotaViewData(weekly: WindowQuota(used: 90, reset: now.addingTimeInterval(86400)), updatedDate: now), accounts[1].id: QuotaViewData(weekly: WindowQuota(used: 10, reset: now.addingTimeInterval(86400)), updatedDate: now), accounts[2].id: QuotaViewData(weekly: WindowQuota(used: 40, reset: now.addingTimeInterval(7200)), primary: WindowQuota(used: 50, reset: now.addingTimeInterval(3600)), updatedDate: now)]
    assert(strategyWinner(accounts, quota: data, numbers: numbers, provider: "codex", strategy: .sequential, now: now) == accounts[0].id)
    assert(strategyWinner(accounts, quota: data, numbers: numbers, provider: "codex", strategy: .balance, now: now) == accounts[1].id)
    assert(strategyWinner(accounts, quota: data, numbers: numbers, provider: "codex", strategy: .rate, now: now) == accounts[2].id)
    assert(strategyWinner(accounts, quota: data, numbers: numbers, provider: "codex", strategy: .rate, now: now.addingTimeInterval(901)) == nil)
    assert(avoidResetReason(data[accounts[2].id], hours: 24, now: now) != nil)
    assert(avoidResetReason(data[accounts[0].id], hours: 6, now: now) == nil)
    var history = AlertHistory(lastSent: now)
    let value = UsageThreshold(id: "codex:a1", window: "weekly", used: 50, reset: now.addingTimeInterval(86400))
    assert(thresholdEvents([value], enabled: true, now: now, history: &history).first?.id == value.id, "new threshold bypasses winner cooldown")
    assert(thresholdEvents([value], enabled: true, now: now.addingTimeInterval(1800), history: &history).isEmpty)
    assert(thresholdEvents([value], enabled: true, now: now.addingTimeInterval(3600), history: &history).isEmpty)
    var batchHistory = AlertHistory(lastSent: now)
    let primary = UsageThreshold(id: value.id, window: "primary", used: 100, reset: value.reset)
    assert(thresholdEvents([value, primary], enabled: true, now: now, history: &batchHistory).count == 2)
    batchHistory = try! JSONDecoder().decode(AlertHistory.self, from: JSONEncoder().encode(batchHistory))
    assert(thresholdEvents([value, primary], enabled: true, now: now, history: &batchHistory).isEmpty)
    let nextWindow = UsageThreshold(id: value.id, window: "weekly", used: 50, reset: value.reset.addingTimeInterval(86400))
    assert(thresholdEvents([nextWindow], enabled: true, now: now, history: &batchHistory).count == 1)
    let equalUsage = QuotaViewData(weekly: WindowQuota(used: 95, reset: now.addingTimeInterval(90000)), primary: WindowQuota(used: 95, reset: now.addingTimeInterval(3600)), updatedDate: now)
    assert(avoidResetReason(equalUsage, hours: 24, now: now) == nil, "equal depletion uses later reset")
    assert(avoidResetReason(equalUsage, hours: 48, now: now) != nil, "user's two-day guard protects upcoming regular reset")
    assert(avoidResetReason(equalUsage, hours: 24, now: now.addingTimeInterval(901)) != nil)
}
struct ResetAvailability: Decodable {
    let ok: Bool
    let supported: Bool?
    let eligible: Bool?
    let availableCount: Int?
    let expiresAt: Double?
    let reason: String?
    let accountId: String?
    let accountEmail: String?
    let uncertain: Bool?
}
func canReset(_ value: ResetAvailability, fetched: Date, now: Date) -> Bool {
    value.ok && value.supported == true && value.eligible == true && value.accountId?.isEmpty == false && (value.availableCount ?? 0) > 0 && now.timeIntervalSince(fetched) >= -60 && now.timeIntervalSince(fetched) <= 900
}
func resetReasonThai(_ reason: String?) -> String {
    switch reason {
    case "Core five-hour or weekly remaining must be 10% or less": return "ใช้ได้เมื่อรอบใดรอบหนึ่งเหลือไม่เกิน 10%"
    case "Fresh core usage has 10% or less remaining; confirmation required": return "พร้อมใช้ 1 สิทธิ์ · ต้องยืนยันก่อนรีเซ็ต"
    case "No verified unexpired free reset credit": return "ยังไม่มีสิทธิ์รีเซ็ตที่ยืนยันว่าใช้ได้"
    case "No available free reset credit, or credit count unknown": return "ไม่มีสิทธิ์รีเซ็ต หรือยังตรวจจำนวนไม่ได้"
    case "Identity could not be verified": return "ยังยืนยันบัญชีไม่ได้ · ลองรีเฟรช"
    case "Unresolved reset belongs to a different saved identity": return "คำขอเดิมเป็นคนละบัญชี · ยังรีเซ็ตไม่ได้"
    case "Previous result remains uncertain; current usage is not eligible for a retry": return "ผลคำขอเดิมยังไม่ชัดเจน · ยังลองซ้ำไม่ได้"
    case "Free reset is supported only for Codex": return "รองรับรีเซ็ตฟรีเฉพาะ Codex"
    default: return "ตรวจสิทธิ์ไม่ได้ · ลองรีเฟรช"
    }
}
struct AlertHistory: Codable {
    var winner: String? = nil
    var lastSent: Date? = nil
    var events: [String: Date] = [:]
}
func alertEvent(enabled: Bool, winner: String?, snapshots: [AlertSnapshot], now: Date, history: inout AlertHistory) -> String? {
    guard enabled, let winner, snapshots.contains(where: { $0.id == winner && $0.remaining.isFinite && $0.remaining > 0 && $0.remaining <= 100 && $0.reset > now }) else { return nil }
    history.events = history.events.filter { $0.value > now }
    let changed = history.winner != nil && history.winner != winner
    if history.winner == nil { history.winner = winner }
    guard history.lastSent.map({ now.timeIntervalSince($0) >= 1800 }) ?? true else { return nil }
    let near = snapshots.filter { $0.remaining.isFinite && $0.remaining > 0 && $0.remaining <= 100 && $0.reset > now && $0.reset.timeIntervalSince(now) <= 3600 }.sorted { $0.reset == $1.reset ? $0.id < $1.id : $0.reset < $1.reset }
    func resetKey(_ item: AlertSnapshot) -> String { "reset:\(item.id):\(Int(item.reset.timeIntervalSince1970))" }
    var result: String?
    if changed && history.events["winner:" + winner] == nil {
        result = winner; history.events["winner:" + winner] = now.addingTimeInterval(86400)
        // One notice covers both reasons when the recommended account also resets soon.
        for item in near where item.id == winner { history.events[resetKey(item)] = item.reset }
    } else if let item = near.first(where: { history.events[resetKey($0)] == nil }) {
        result = item.id; history.events[resetKey(item)] = item.reset
    }
    history.winner = winner
    if result != nil { history.lastSent = now }
    return result
}
func notificationHint(enabled: Bool, nativeAllowed: Bool) -> String {
    !enabled ? "เปิดแจ้งเตือนเพื่อรู้ว่าควรใช้บัญชีไหน" : nativeAllowed ? "แจ้งเมื่อใช้ถึง 50% คำแนะนำเปลี่ยน หรือใกล้รีเซ็ต" : "แจ้งเตือนในแอปเปิดอยู่ · macOS ยังไม่อนุญาตการแจ้งเตือน"
}
func refreshDue(last: Date?, now: Date, busy: Bool) -> Bool { !busy && (last.map { now.timeIntervalSince($0) >= 300 } ?? true) }
func uiV4Tests() {
    strategyTests()
    assert(resetReasonThai("Core five-hour or weekly remaining must be 10% or less") == "ใช้ได้เมื่อรอบใดรอบหนึ่งเหลือไม่เกิน 10%")
    assert(resetReasonThai("Identity could not be verified") == "ยังยืนยันบัญชีไม่ได้ · ลองรีเฟรช")
    assert(resetReasonThai("unknown provider failure") == "ตรวจสิทธิ์ไม่ได้ · ลองรีเฟรช")
    assert(resetReasonThai(nil) == "ตรวจสิทธิ์ไม่ได้ · ลองรีเฟรช")
    let resetFixture = ResetAvailability(ok: true, supported: true, eligible: true, availableCount: 1, expiresAt: nil, reason: nil, accountId: "account", accountEmail: "test@example.invalid", uncertain: false)
    assert(canReset(resetFixture, fetched: Date(), now: Date()), "verified reset status enables explicit action")
    assert(!canReset(resetFixture, fetched: Date(timeIntervalSince1970: 0), now: Date()))
    let noCredit = ResetAvailability(ok: true, supported: true, eligible: false, availableCount: 0, expiresAt: nil, reason: nil, accountId: "account", accountEmail: nil, uncertain: true)
    assert(!canReset(noCredit, fetched: Date(), now: Date()), "uncertain result never bypasses provider eligibility")
    let accounts = ["account3", "main", "account2", "extra"].map { Account(id: "codex:\($0)", provider: "codex", key: $0, label: "rename", email: nil, usageAccount: nil) }
    let numbers = accountNumbers(accounts, saved: [:])
    assert(numbers["codex:main"] == 1, "legacy main must display account 1")
    assert(numbers["codex:account2"] == 2 && numbers["codex:account3"] == 3 && numbers["codex:extra"] == 4)
    assert(accountNumbers(Array(accounts.reversed()), saved: numbers) == numbers)
    let extra = Account(id: "codex:new", provider: "codex", key: "new", label: "new", email: nil, usageAccount: nil)
    assert(accountNumbers([extra], saved: numbers)[extra.id] == 5, "deleted numbers stay reserved")
    let claude = ["c", "b", "a"].map { Account(id: "claude:\($0)", provider: "claude", key: $0, label: $0, email: nil, usageAccount: nil) }
    assert(accountNumbers(claude, saved: numbers)["claude:a"] == 1)
    let repaired = accountNumbers(accounts, saved: ["codex:main": 1, "codex:extra": 1])
    let codexNumbers = repaired.filter { $0.key.hasPrefix("codex:") }.map(\.value)
    assert(Set(codexNumbers).count == codexNumbers.count)
    let now = Date(timeIntervalSince1970: 1_800_000_000)
    let far = AlertSnapshot(id: "one", remaining: 50, reset: now.addingTimeInterval(7200))
    let near = AlertSnapshot(id: "two", remaining: 30, reset: now.addingTimeInterval(3500))
    var history = AlertHistory()
    assert(alertEvent(enabled: false, winner: "one", snapshots: [far], now: now, history: &history) == nil && history.winner == nil)
    assert(alertEvent(enabled: true, winner: "one", snapshots: [far], now: now, history: &history) == nil && history.winner == "one")
    assert(alertEvent(enabled: true, winner: nil, snapshots: [], now: now, history: &history) == nil && history.winner == "one")
    assert(alertEvent(enabled: true, winner: "two", snapshots: [near], now: now, history: &history) == "two")
    assert(alertEvent(enabled: true, winner: "two", snapshots: [near], now: now.addingTimeInterval(1), history: &history) == nil)
    let persisted = try! JSONEncoder().encode(history)
    history = try! JSONDecoder().decode(AlertHistory.self, from: persisted)
    assert(alertEvent(enabled: true, winner: "two", snapshots: [near], now: now.addingTimeInterval(1800), history: &history) == nil, "restart preserves event dedup")
    var resetHistory = AlertHistory()
    assert(alertEvent(enabled: true, winner: "two", snapshots: [near], now: now, history: &resetHistory) == "two")
    assert(alertEvent(enabled: true, winner: "two", snapshots: [near], now: now.addingTimeInterval(1800), history: &resetHistory) == nil)
    let third = AlertSnapshot(id: "three", remaining: 20, reset: now.addingTimeInterval(8000))
    assert(alertEvent(enabled: true, winner: "three", snapshots: [third], now: now.addingTimeInterval(1799), history: &resetHistory) == nil)
    assert(alertEvent(enabled: true, winner: "three", snapshots: [third], now: now.addingTimeInterval(1800), history: &resetHistory) == "three")
    var invalid = AlertHistory()
    assert(alertEvent(enabled: true, winner: "two", snapshots: [AlertSnapshot(id: "two", remaining: 0, reset: now)], now: now, history: &invalid) == nil)
    assert(notificationHint(enabled: true, nativeAllowed: false).contains("ในแอป"))
    assert(!refreshDue(last: now, now: now.addingTimeInterval(299), busy: false))
    assert(refreshDue(last: now, now: now.addingTimeInterval(300), busy: false))
    assert(!refreshDue(last: nil, now: now, busy: true))
    assert(refreshDue(last: now, now: now.addingTimeInterval(7200), busy: false))
    let fresh = QuotaViewData(weekly: WindowQuota(used: 40, reset: now.addingTimeInterval(7200)), primary: WindowQuota(used: 95, reset: now.addingTimeInterval(3500)), updatedDate: now)
    assert(alertSnapshot(id: "one", value: fresh, now: now)?.remaining == 5, "limiting window supplies notification quota")
    var stale = fresh; stale.updatedDate = now.addingTimeInterval(-901)
    assert(alertSnapshot(id: "one", value: stale, now: now) == nil)
    var failed = fresh; failed.error = "failed"
    assert(alertSnapshot(id: "one", value: failed, now: now) == nil)
    var exhausted = fresh; exhausted.primary = WindowQuota(used: 100, reset: now.addingTimeInterval(3500))
    assert(alertSnapshot(id: "one", value: exhausted, now: now) == nil)
    var expired = fresh; expired.weekly = WindowQuota(used: 20, reset: now)
    assert(alertSnapshot(id: "one", value: expired, now: now) == nil)
    assert(alertSnapshot(id: "one", value: QuotaViewData(), now: now) == nil)
    let many = (1...50).map { Account(id: "claude:extra\($0)", provider: "claude", key: "extra\($0)", label: "name", email: nil, usageAccount: nil) }
    let manyNumbers = accountNumbers(many, saved: [:])
    assert(Set(many.map { manyNumbers[$0.id]! }).count == 50)
    assert(many.sorted { manyNumbers[$0.id]! < manyNumbers[$1.id]! }.map { manyNumbers[$0.id]! } == Array(1...50))
    assert(accountNumbers([extra], saved: [:])[extra.id] == 1, "first arbitrary import starts at 1")
}

struct Account: Codable, Equatable {
    let id: String
    let provider: String
    let key: String
    let label: String
    let email: String?
    let usageAccount: String?
}
struct Dependencies: Codable { let codexApp: Bool; let claudeApp: Bool }
struct AccountList: Codable { let accounts: [Account]; let dependencies: Dependencies; let platform: String }
func validKey(_ key: String) -> Bool {
    !key.isEmpty && key.range(of: "^[A-Za-z0-9_-]+$", options: .regularExpression) != nil
}
func parseAccounts(_ data: Data) -> AccountList? {
    guard let result = try? JSONDecoder().decode(AccountList.self, from: data),
          Set(result.accounts.map(\.id)).count == result.accounts.count,
          result.accounts.allSatisfy({ ["codex", "claude"].contains($0.provider) && validKey($0.key) && $0.id == "\($0.provider):\($0.key)" }) else { return nil }
    return result
}
struct WindowQuota { let used: Double?; let reset: Date? }
struct Recommendation {
    let score: Double?
    let hours: Double?
    let reason: String
    var usable = true
}
func recommend(weekly: WindowQuota?, primary: WindowQuota?, updated: Date?, now: Date) -> Recommendation {
    let freshnessLimit: TimeInterval = 15*60
    guard let updated, now.timeIntervalSince(updated) <= freshnessLimit, updated.timeIntervalSince(now) <= 60 else {
        return Recommendation(score: nil, hours: nil, reason: "ไม่นำมาจัดอันดับ: ข้อมูลเก่าหรือเวลาอัปเดตไม่ชัดเจน")
    }
    func score(_ window: WindowQuota?) -> (Double, Double)? {
        guard let window, let used = window.used, used.isFinite, (0..<100).contains(used), let reset = window.reset, reset > now else { return nil }
        let hours = reset.timeIntervalSince(now)/3600
        return ((100-used)/max(hours, 1.0/60), hours)
    }
    guard let week = score(weekly) else { return Recommendation(score: nil, hours: nil, reason: "ไม่นำมาจัดอันดับ: โควตาสัปดาห์หมด ขาดข้อมูล หรือเลยเวลารีเซ็ต") }
    let result = week.0
    if let primary {
        guard score(primary) != nil else { return Recommendation(score: nil, hours: week.1, reason: "ไม่นำมาจัดอันดับ: รอบหลักหมด ขาดข้อมูล หรือเลยเวลารีเซ็ต") }
    }
    return Recommendation(score: result, hours: week.1, reason: String(format: "%.2f %%/ชม. · รีเซ็ตสัปดาห์ใน %.1f ชม.", result, week.1), usable: (100 - weekly!.used!) >= 10 && (primary.map { 100 - $0.used! >= 20 } ?? true))
}
func recommendationWinner(_ accounts: [Account], values: [String: Recommendation], provider: String) -> String? {
    accounts.filter { $0.provider == provider && values[$0.id]?.score != nil }.sorted {
        if values[$0.id]!.usable != values[$1.id]!.usable { return values[$0.id]!.usable }
        let a = values[$0.id]!.score!, b = values[$1.id]!.score!
        return a == b ? $0.id < $1.id : a > b
    }.first?.id
}

func releaseTests() {
    let many = (0..<50).map { Account(id: "codex:a\($0)", provider: "codex", key: "a\($0)", label: "บัญชี \($0)", email: "user\($0)@example.invalid", usageAccount: nil) }
    let payload = AccountList(accounts: many.reversed(), dependencies: Dependencies(codexApp: true, claudeApp: false), platform: "test")
    assert(parseAccounts(try! JSONEncoder().encode(payload))?.accounts.count == 50, "dynamic list must preserve 50 accounts")
    assert(parseAccounts(Data("{}".utf8)) == nil)
    let duplicates = AccountList(accounts: [many[0], many[0]], dependencies: payload.dependencies, platform: "test")
    assert(parseAccounts(try! JSONEncoder().encode(duplicates)) == nil)
    let now = Date(timeIntervalSince1970: 1_800_000_000)
    let week = WindowQuota(used: 50, reset: now.addingTimeInterval(7200))
    let depleted = recommend(weekly: WindowQuota(used: 0, reset: now.addingTimeInterval(60)), primary: WindowQuota(used: 99, reset: now.addingTimeInterval(60)), updated: now, now: now)
    let usable = recommend(weekly: WindowQuota(used: 30, reset: now.addingTimeInterval(86400)), primary: WindowQuota(used: 30, reset: now.addingTimeInterval(7200)), updated: now, now: now)
    assert(recommendationWinner(Array(many.prefix(2)), values: [many[0].id: depleted, many[1].id: usable], provider: "codex") == many[1].id, "usable account outranks almost-depleted short reset")
    assert(recommend(weekly: week, primary: nil, updated: now, now: now).score == 25)
    assert(recommend(weekly: week, primary: WindowQuota(used: 90, reset: now.addingTimeInterval(7200)), updated: now, now: now).score == 25, "ranking uses weekly pace after primary validation")
    let shortLimited = recommend(weekly: WindowQuota(used: 60, reset: now.addingTimeInterval(3600)), primary: WindowQuota(used: 80, reset: now.addingTimeInterval(18000)), updated: now, now: now)
    let otherReady = recommend(weekly: WindowQuota(used: 40, reset: now.addingTimeInterval(7200)), primary: WindowQuota(used: 0, reset: now.addingTimeInterval(3600)), updated: now, now: now)
    assert(recommendationWinner(Array(many.prefix(2)), values: [many[0].id: shortLimited, many[1].id: otherReady], provider: "codex") == many[0].id, "same headroom tier uses weekly pace even if primary pace is lower")
    assert(recommend(weekly: week, primary: nil, updated: now.addingTimeInterval(-901), now: now).score == nil)
    assert(recommend(weekly: week, primary: nil, updated: now.addingTimeInterval(61), now: now).score == nil)
    assert(recommend(weekly: nil, primary: nil, updated: now, now: now).score == nil)
    assert(recommend(weekly: week, primary: WindowQuota(used: nil, reset: now.addingTimeInterval(30)), updated: now, now: now).score == nil)
    assert(recommend(weekly: WindowQuota(used: 100, reset: now.addingTimeInterval(10)), primary: nil, updated: now, now: now).score == nil)
    assert(recommend(weekly: WindowQuota(used: 0, reset: now), primary: nil, updated: now, now: now).score == nil)
    assert(recommend(weekly: WindowQuota(used: -1, reset: now.addingTimeInterval(20)), primary: nil, updated: now, now: now).score == nil)
    assert(recommend(weekly: WindowQuota(used: .nan, reset: now.addingTimeInterval(20)), primary: nil, updated: now, now: now).score == nil)
    assert(recommend(weekly: WindowQuota(used: 0, reset: now.addingTimeInterval(1)), primary: nil, updated: now, now: now).score == 6000)
    let scores = [many[0].id: Recommendation(score: 5, hours: 3, reason: ""), many[1].id: Recommendation(score: 5, hours: 2, reason: "")]
    assert(recommendationWinner(Array(many.reversed()), values: scores, provider: "codex") == many[0].id)
    assert(recommendationWinner(many, values: scores, provider: "claude") == nil)
    let empty = AccountList(accounts: [], dependencies: payload.dependencies, platform: "test")
    assert(parseAccounts(try! JSONEncoder().encode(empty))?.accounts.isEmpty == true)
    let one = AccountList(accounts: [many[0]], dependencies: payload.dependencies, platform: "test")
    assert(parseAccounts(try! JSONEncoder().encode(one))?.accounts.first?.id == many[0].id)
    let claude = Account(id: "claude:shared", provider: "claude", key: "shared", label: "Other provider", email: nil, usageAccount: "profile-id")
    var crossScores = scores; crossScores[claude.id] = Recommendation(score: 999, hours: 1, reason: "")
    assert(recommendationWinner(many + [claude], values: crossScores, provider: "codex") == many[0].id)
    assert(recommendationWinner(many + [claude], values: crossScores, provider: "claude") == claude.id)
}

struct Action {
    let arguments: [String]
}
func action(_ account: Account) -> Action? {
    guard ["codex", "claude"].contains(account.provider), validKey(account.key), account.id == "\(account.provider):\(account.key)" else { return nil }
    return Action(arguments: ["switch", account.provider, account.key])
}
final class SwitchState {
    var busy = false
    func start(_ account: Account, confirmed: Bool, launch: (Action) throws -> Void) -> Bool {
        guard !busy, let a = action(account), confirmed else { return false }
        busy = true
        do { try launch(a); return true } catch { busy = false; return false }
    }
    func finish() { busy = false }
}
func percentRemaining(_ value: Double?) -> Double? {
    guard let value, value.isFinite else { return nil }
    return min(100, max(0, 100-value))
}
func remaining(_ value: Double?) -> String {
    guard let value = percentRemaining(value) else { return "ไม่ทราบ" }
    return String(format: "%.0f%%", value)
}
func dateValue(_ value: String?) -> Date? {
    guard let value else { return nil }
    let f = ISO8601DateFormatter()
    if let date = f.date(from: value) { return date }
    f.formatOptions.insert(.withFractionalSeconds)
    return f.date(from: value)
}
func localDate(_ value: String?) -> String {
    guard let date = dateValue(value) else { return "ไม่ทราบ" }
    let f = DateFormatter()
    f.locale = Locale(identifier: "th_TH")
    f.timeZone = TimeZone(identifier: "Asia/Bangkok")
    f.dateFormat = "d MMM yy HH:mm"
    return f.string(from: date)
}
func number(_ value: Any?) -> String {
    guard let value = value as? Double, value.isFinite else { return "ไม่ทราบ" }
    return String(format: "%.2f", value).replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression)
}
struct QuotaViewData {
    var percent: Double? = nil
    var balance = "ไม่ทราบ"
    var resets = "ไม่ทราบ"
    var resetTime = "ไม่ทราบ"
    var updated = "ไม่ทราบ"
    var details = ""
    var error: String? = nil
    var weekly: WindowQuota? = nil
    var primary: WindowQuota? = nil
    var updatedDate: Date? = nil
    var resetCount: Int? = nil
    var resetExpiry: Date? = nil
}
func alertSnapshot(id: String, value: QuotaViewData, now: Date) -> AlertSnapshot? {
    guard value.error == nil, recommend(weekly: value.weekly, primary: value.primary, updated: value.updatedDate, now: now).score != nil else { return nil }
    let windows = [value.weekly, value.primary].compactMap { $0 }
    guard let limiting = windows.min(by: { a, b in
        (100 - a.used!) / max(a.reset!.timeIntervalSince(now), 60) < (100 - b.used!) / max(b.reset!.timeIntervalSince(now), 60)
    }), let used = limiting.used, let reset = limiting.reset else { return nil }
    return AlertSnapshot(id: id, remaining: 100 - used, reset: reset)
}
func quotaData(_ data: Data, account: Account) -> QuotaViewData {
    let provider = account.provider
    guard let rows = (try? JSONSerialization.jsonObject(with: data)) as? [[String: Any]] else { return QuotaViewData(error: "อ่านข้อมูลไม่ได้") }
    let matches = rows.filter { row in
        guard row["provider"] as? String == provider, row["error"] == nil else { return false }
        if let email = account.email, !email.isEmpty {
            return (row["usage"] as? [String: Any])?["accountEmail"] as? String == email
        }
        guard let identity = account.usageAccount, !identity.isEmpty else { return false }
        return row["account"] as? String == identity
    }.sorted { a, b in
        let ad = dateValue((a["usage"] as? [String: Any])?["updatedAt"] as? String) ?? .distantPast
        let bd = dateValue((b["usage"] as? [String: Any])?["updatedAt"] as? String) ?? .distantPast
        return ad > bd
    }
    if account.email == nil || account.email?.isEmpty == true {
        let identities = Set(matches.compactMap { ($0["usage"] as? [String: Any])?["accountEmail"] as? String })
        guard identities.count <= 1 else { return QuotaViewData(error: "ตัวตนโควตาซ้ำกัน — โปรดเชื่อมบัญชีใหม่") }
    }
    guard let row = matches.first, let usage = row["usage"] as? [String: Any] else { return QuotaViewData(error: "ไม่พบข้อมูลบัญชี — ลองรีเฟรชอีกครั้ง") }
    let week = usage["secondary"] as? [String: Any] ?? [:]
    let primary: [String: Any]? = (usage["primary"] == nil || usage["primary"] is NSNull) ? nil : ((usage["primary"] as? [String: Any]) ?? [:])
    let resets = row["resetCredits"] as? [String: Any] ?? [:]
    var balance = "ไม่ทราบ"
    if provider == "codex", let credits = row["credits"] as? [String: Any], credits["balanceReadSucceeded"] as? Bool == true {
        balance = "\(number(credits["remaining"])) Credits"
    } else if provider == "claude", let cost = usage["providerCost"] as? [String: Any] {
        balance = "\(number(cost["balance"])) \(cost["currencyCode"] as? String ?? "ไม่ทราบหน่วย")"
    }
    var line = "สัปดาห์เหลือ \(remaining(week["usedPercent"] as? Double)) · ยอดคงเหลือ \(balance) · สิทธิ์รีเซ็ต: \(number(resets["available"]))"
    line += "\nรีเซ็ตสัปดาห์ \(localDate(week["resetsAt"] as? String)) · อัปเดต \(localDate(usage["updatedAt"] as? String))"
    if let primary { line += "\nรอบหลักเหลือ \(remaining(primary["usedPercent"] as? Double)) · รีเซ็ต \(localDate(primary["resetsAt"] as? String))" }
    if let expiry = resets["nextExpiresAt"] as? String { line += " · สิทธิ์หมดอายุ \(localDate(expiry))" }
    return QuotaViewData(percent: percentRemaining(week["usedPercent"] as? Double), balance: balance,
                         resets: number(resets["available"]), resetTime: localDate(week["resetsAt"] as? String),
                         updated: localDate(usage["updatedAt"] as? String), details: line,
                         weekly: WindowQuota(used: week["usedPercent"] as? Double, reset: dateValue(week["resetsAt"] as? String)),
                         primary: primary.map { WindowQuota(used: $0["usedPercent"] as? Double, reset: dateValue($0["resetsAt"] as? String)) },
                         updatedDate: dateValue(usage["updatedAt"] as? String), resetCount: resets["available"] as? Int, resetExpiry: dateValue(resets["nextExpiresAt"] as? String))
}
func quotaData(_ data: Data, provider: String, email: String) -> QuotaViewData {
    quotaData(data, account: Account(id: "\(provider):test", provider: provider, key: "test", label: "test", email: email, usageAccount: nil))
}
func quota(_ data: Data, provider: String, email: String) -> String {
    let value = quotaData(data, provider: provider, email: email)
    return value.error ?? value.details
}
func completionStatus(_ code: Int32) -> String {
    code == 0 ? "คำสั่งเสร็จแล้ว — ยังไม่ได้ตรวจยืนยันบัญชีในแอป" : "คำสั่งไม่สำเร็จ (รหัส \(code)) — ลองอีกครั้งหรือตรวจแอป"
}
func usageResult(_ data: Data, exitCode: Int32) -> (Data?, String?) {
    // CodexBar can return successful sibling rows alongside one account failure.
    if (try? JSONSerialization.jsonObject(with: data)) is [[String: Any]] { return (data, nil) }
    return (nil, "อ่านโควตาไม่สำเร็จ (รหัส \(exitCode)) — ไม่ได้รับข้อมูลที่อ่านได้")
}

func selfTest() {
    uiV4Tests()
    releaseTests()
    assert(mutationError(Data(#"{"ok":false,"message":"login canceled"}"#.utf8)) == "login canceled")
    assert(mutationError(Data("invalid".utf8)) != nil)
    assert(mutationError(Data(#"{"ok":true,"message":"done"}"#.utf8)) == nil)
    let contextDir = FileManager.default.temporaryDirectory.appendingPathComponent("ai-accounts-context-test-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: contextDir) }
    try! saveContext("explicit user text", to: contextDir)
    assert((try? readContext(contextDir.appendingPathComponent("context.md"))) == "explicit user text", "context save must persist user text")
    let permissions = (try! FileManager.default.attributesOfItem(atPath: contextDir.appendingPathComponent("context.md").path))[.posixPermissions] as! NSNumber
    assert(permissions.intValue == 0o600)
    try! saveContext("revised user text", to: contextDir)
    assert((try? readContext(contextDir.appendingPathComponent("context.md"))) == "revised user text")
    let external = contextDir.appendingPathComponent("other.md")
    try! "keep original".write(to: external, atomically: true, encoding: .utf8)
    try! FileManager.default.removeItem(at: contextDir.appendingPathComponent("context.md"))
    try! FileManager.default.createSymbolicLink(at: contextDir.appendingPathComponent("context.md"), withDestinationURL: external)
    do { try saveContext("must not follow link", to: contextDir); assertionFailure("symlink must be rejected") } catch { }
    assert((try? String(contentsOf: external, encoding: .utf8)) == "keep original")
    let sample = Account(id: "codex:sample", provider: "codex", key: "sample", label: "Sample", email: nil, usageAccount: nil)
    assert(action(sample)?.arguments == ["switch", "codex", "sample"])
    assert(!validKey("../other") && !validKey("-bad/../key") && !validKey(""))
    let state = SwitchState()
    var calls = 0
    assert(!state.start(sample, confirmed: false) { _ in calls += 1 })
    assert(calls == 0 && !state.busy)
    assert(state.start(sample, confirmed: true) { _ in calls += 1 })
    assert(state.busy && calls == 1)
    assert(!state.start(sample, confirmed: true) { _ in calls += 1 })
    assert(calls == 1)
    state.finish()
    assert(!state.busy)
    assert(!state.start(sample, confirmed: true) { _ in throw NSError(domain: "test", code: 1) })
    assert(!state.busy)
    assert(remaining(nil) == "ไม่ทราบ" && remaining(0) == "100%")
    assert(percentRemaining(nil) == nil && percentRemaining(.nan) == nil)
    assert(percentRemaining(0) == 100 && percentRemaining(100) == 0)
    assert(percentRemaining(120) == 0 && percentRemaining(-3) == 100)
    assert(remaining(130) == "0%" && remaining(-2) == "100%")
    assert(localDate("bad") == "ไม่ทราบ")
    assert(localDate("2026-11-07T10:00:00Z").contains("17:00"))
    let fixture = Data(#"[{"provider":"codex","usage":{"accountEmail":"one","updatedAt":"2026-11-07T10:00:00Z","secondary":{"usedPercent":99}}},{"provider":"codex","usage":{"accountEmail":"one","updatedAt":"2026-11-07T11:00:00Z","secondary":{"usedPercent":0}},"credits":{"remaining":0,"balanceReadSucceeded":true},"resetCredits":{"available":0}},{"provider":"claude","usage":{"accountEmail":"one","secondary":{"usedPercent":25},"providerCost":{"balance":0}}}]"#.utf8)
    let c = quota(fixture, provider: "codex", email: "one")
    let dynamic = Account(id: "codex:a", provider: "codex", key: "a", label: "renamed", email: "one", usageAccount: "unrelated")
    assert(quotaData(fixture, account: dynamic).percent == 100, "dynamic usage matches freshest email")
    let wrong = Account(id: "codex:b", provider: "codex", key: "b", label: "second", email: "other", usageAccount: "one")
    assert(quotaData(fixture, account: wrong).percent == nil)
    let profile = Account(id: "claude:profile", provider: "claude", key: "profile", label: "Renamed profile", email: nil, usageAccount: "profile-id")
    let profileData = Data(#"[{"provider":"claude","account":"profile-id","usage":{"secondary":{"usedPercent":20},"primary":{}}}]"#.utf8)
    assert(quotaData(profileData, account: profile).percent == 80)
    assert(quotaData(profileData, account: profile).primary != nil)
    let unlinked = Account(id: "claude:unknown", provider: "claude", key: "unknown", label: "No identity", email: nil, usageAccount: nil)
    assert(quotaData(profileData, account: unlinked).percent == nil)
    let ambiguous = Data(#"[{"provider":"claude","account":"profile-id","usage":{"accountEmail":"first@example.invalid","secondary":{"usedPercent":20}}},{"provider":"claude","account":"profile-id","usage":{"accountEmail":"second@example.invalid","secondary":{"usedPercent":30}}}]"#.utf8)
    assert(quotaData(ambiguous, account: profile).percent == nil, "ambiguous fallback identity must be rejected")
    assert(c.contains("100%") && c.contains("0 Credits") && c.contains("รีเซ็ต: 0"))
    assert(quota(fixture, provider: "claude", email: "one").contains("75%"))
    assert(quota(fixture, provider: "claude", email: "one").contains("ไม่ทราบหน่วย"))
    assert(quota(fixture, provider: "codex", email: "missing").contains("ไม่พบ"))
    assert(quota(Data("bad".utf8), provider: "codex", email: "one").contains("อ่านข้อมูลไม่ได้"))
    assert(completionStatus(0).contains("คำสั่งเสร็จแล้ว"))
    assert(completionStatus(7).contains("7"))
    assert(usageResult(fixture, exitCode: 1).0 != nil)
    assert(usageResult(Data("bad".utf8), exitCode: 1).0 == nil)
    let six: [[String: Any]] = [
        ["provider": "claude", "usage": ["accountEmail": "third", "secondary": ["usedPercent": 60]]],
        ["provider": "codex", "usage": ["accountEmail": "second", "secondary": ["usedPercent": 20]]],
        ["provider": "claude", "usage": ["accountEmail": "first", "secondary": ["usedPercent": 40]]],
        ["provider": "codex", "usage": ["accountEmail": "third", "secondary": ["usedPercent": 30]]],
        ["provider": "codex", "usage": ["accountEmail": "first", "secondary": ["usedPercent": 10]]],
        ["provider": "claude", "usage": ["accountEmail": "second", "secondary": ["usedPercent": 50]]]
    ]
    let sixData = try! JSONSerialization.data(withJSONObject: six)
    assert(quota(sixData, provider: "codex", email: "first").contains("90%"))
    assert(quota(sixData, provider: "codex", email: "second").contains("80%"))
    assert(quota(sixData, provider: "codex", email: "third").contains("70%"))
    assert(quota(sixData, provider: "claude", email: "first").contains("60%"))
    assert(quota(sixData, provider: "claude", email: "second").contains("50%"))
    assert(quota(sixData, provider: "claude", email: "third").contains("40%"))
    print("PASS: dynamic 0/1/50 accounts, safe switch/cancel/busy, identity-matched quota, recommendation freshness/windows/provider ties, private atomic context, malformed helper results")
}
if CommandLine.arguments.contains("--self-test") { selfTest(); exit(0) }

// CLI output is bounded and never displayed verbatim.
final class Capture {
    let lock = NSLock()
    var data = Data()
    var overflow = false
    func append(_ chunk: Data) {
        lock.lock(); defer { lock.unlock() }
        if data.count + chunk.count > 2_000_000 { overflow = true }
        data.append(chunk.prefix(max(0, 2_000_000-data.count)))
    }
}
func runHelper(_ arguments: [String], timeout: TimeInterval, mutating: Bool = false, onTimeout: @escaping () -> Void = {}) -> (Data?, String?) {
    let p = Process(), pipe = Pipe(), capture = Capture()
    guard let resources = Bundle.main.resourceURL else { return (nil, "ไม่พบเครื่องมือภายในแอป") }
    p.executableURL = resources.appendingPathComponent("backend/aiaccounts-helper")
    p.arguments = arguments
    var environment = ProcessInfo.processInfo.environment
    environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    p.environment = environment
    p.standardInput = FileHandle.nullDevice
    p.standardOutput = pipe
    p.standardError = FileHandle.nullDevice
    let finished = DispatchSemaphore(value: 0)
    p.terminationHandler = { _ in finished.signal() }
    do { try p.run() } catch { return (nil, "เปิดเครื่องมืออ่านโควตาไม่ได้") }
    try? pipe.fileHandleForWriting.close()
    let drained = DispatchGroup()
    drained.enter()
    DispatchQueue.global().async {
        while let chunk = try? pipe.fileHandleForReading.read(upToCount: 65536), !chunk.isEmpty { capture.append(chunk) }
        drained.leave()
    }
    let timedOut = finished.wait(timeout: .now()+timeout) == .timedOut
    if timedOut {
        if mutating {
            // Do not interrupt an official login midway through credential changes.
            onTimeout(); finished.wait()
        } else {
            p.terminate()
            if finished.wait(timeout: .now()+1) == .timedOut { kill(p.processIdentifier, SIGKILL); _ = finished.wait(timeout: .now()+2) }
        }
    }
    let drainFailed = drained.wait(timeout: .now()+2) == .timedOut
    try? pipe.fileHandleForReading.close()
    if timedOut && !mutating { return (nil, "อ่านข้อมูลเกินเวลาที่กำหนด — ลองรีเฟรช") }
    if drainFailed { return (nil, "อ่านผลลัพธ์ไม่ครบ — ลองรีเฟรช") }
    capture.lock.lock(); defer { capture.lock.unlock() }
    if capture.overflow { return (nil, "ข้อมูลเกินขนาดที่รองรับ") }
    if arguments.first == "usage" { return usageResult(capture.data, exitCode: p.terminationStatus) }
    if p.terminationStatus != 0 { return (nil, safeMessage(capture.data) ?? "คำสั่งไม่สำเร็จ (รหัส \(p.terminationStatus))") }
    return (capture.data, nil)
}
func safeMessage(_ data: Data) -> String? {
    guard let result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], let message = result["message"] as? String else { return nil }
    return String(message.prefix(1600))
}
func mutationError(_ data: Data?) -> String? {
    guard let data, let result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], let ok = result["ok"] as? Bool else { return "รูปแบบผลลัพธ์ไม่ถูกต้อง — ยังยืนยันผลไม่ได้" }
    return ok ? nil : (safeMessage(data) ?? "คำสั่งไม่สำเร็จ — ยังยืนยันผลไม่ได้")
}

let contextTemplate = "# บริบทส่งต่องาน\n\n## เป้าหมาย\n\n## สถานะปัจจุบัน\n\n## สิ่งที่ต้องทำต่อ\n\n## ข้อจำกัด / ไฟล์ที่เกี่ยวข้อง\n"
func saveContext(_ text: String, to directory: URL) throws {
    guard text.utf8.count <= 2_000_000 else { throw NSError(domain: "context", code: 2) }
    let fm = FileManager.default
    if fm.fileExists(atPath: directory.path) {
        let info = try directory.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        guard info.isDirectory == true, info.isSymbolicLink != true else { throw NSError(domain: "context", code: 3) }
    } else { try fm.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]) }
    let destination = directory.appendingPathComponent("context.md")
    if let info = try? destination.resourceValues(forKeys: [.isSymbolicLinkKey]), info.isSymbolicLink == true { throw NSError(domain: "context", code: 4) }
    let temporary = directory.appendingPathComponent(".context-\(UUID().uuidString).tmp")
    let descriptor = open(temporary.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
    guard descriptor >= 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
    let file = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
    defer { try? file.close(); try? fm.removeItem(at: temporary) }
    try file.write(contentsOf: Data(text.utf8)); try file.synchronize(); try file.close()
    guard rename(temporary.path, destination.path) == 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
}
func readContext(_ url: URL) throws -> String {
    let info = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
    guard info.isRegularFile == true, info.isSymbolicLink != true, (info.fileSize ?? Int.max) <= 2_000_000 else { throw NSError(domain: "context", code: 1) }
    return try String(contentsOf: url, encoding: .utf8)
}
final class ContextEditor: NSObject, NSWindowDelegate {
    var window: NSWindow!
    let text = NSTextView()
    let status = label("บันทึกเฉพาะข้อความที่ใส่เอง · ไม่ส่งไปผู้ให้บริการอัตโนมัติ", size: 12, color: .secondaryLabelColor)
    let directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("AI Accounts", isDirectory: true)
    var lastSaved = ""
    var canSave = true
    override init() {
        super.init()
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 620), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "บริบทกลาง · ข้อความส่งต่องาน"; window.minSize = NSSize(width: 620, height: 480)
        window.isReleasedWhenClosed = false; window.delegate = self
        let explanation = label("ข้อความสำหรับคัดลอกไปวางใน Codex หรือ Claude ด้วยตนเอง\nไม่ใช่เซสชันร่วม และไม่ดึงประวัติแชต รหัสผ่าน หรือไฟล์อื่นเข้ามา", color: .secondaryLabelColor)
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.borderType = .bezelBorder
        text.isRichText = false; text.font = .systemFont(ofSize: 14); text.isVerticallyResizable = true; text.isHorizontallyResizable = false
        text.autoresizingMask = [.width]; text.textContainer?.widthTracksTextView = true; text.textContainerInset = NSSize(width: 12, height: 12)
        text.setAccessibilityLabel("ข้อความบริบทส่งต่องาน")
        scroll.documentView = text
        let save = NSButton(title: "บันทึกในแอป", target: self, action: #selector(save))
        let load = NSButton(title: "เปิด Markdown…", target: self, action: #selector(loadFile))
        let copy = NSButton(title: "คัดลอกเพื่อวางในแชต", target: self, action: #selector(copyContext))
        let reveal = NSButton(title: "แสดงไฟล์ที่บันทึก", target: self, action: #selector(revealFile))
        let buttons = NSStackView(views: [save, load, copy, reveal]); buttons.spacing = 8
        let content = window.contentView!
        for view in [explanation, scroll, buttons, status] {
            view.translatesAutoresizingMaskIntoConstraints = false; content.addSubview(view)
            view.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 20).isActive = true
            view.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -20).isActive = true
        }
        NSLayoutConstraint.activate([explanation.topAnchor.constraint(equalTo: content.topAnchor, constant: 20), scroll.topAnchor.constraint(equalTo: explanation.bottomAnchor, constant: 16), scroll.bottomAnchor.constraint(equalTo: buttons.topAnchor, constant: -14), buttons.bottomAnchor.constraint(equalTo: status.topAnchor, constant: -10), status.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -16)])
        let file = directory.appendingPathComponent("context.md")
        if FileManager.default.fileExists(atPath: file.path) {
            do { text.string = try readContext(file) } catch { text.string = ""; canSave = false; status.stringValue = "อ่านไฟล์เดิมไม่ได้ — ระงับการเขียนทับไฟล์" }
        } else { text.string = contextTemplate }
        lastSaved = text.string
        window.center()
    }
    func show() { window.makeKeyAndOrderFront(nil) }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        guard text.string != lastSaved else { return true }
        let alert = NSAlert(); alert.messageText = "ยังมีข้อความที่ไม่ได้บันทึก"
        alert.informativeText = "กลับไปบันทึก หรือปิดหน้าต่างโดยเก็บข้อความไว้ในแอปจนกว่าจะออกจากแอป"
        alert.addButton(withTitle: "กลับไปแก้ไข"); alert.addButton(withTitle: "ปิดหน้าต่าง")
        return alert.runModal() == .alertSecondButtonReturn
    }
    @objc func save() {
        guard canSave else { status.stringValue = "ไฟล์เดิมอ่านไม่ได้ — กรุณาตรวจไฟล์เดิมก่อน ไม่ได้เขียนทับ"; return }
        do { try saveContext(text.string, to: directory); lastSaved = text.string; status.stringValue = "บันทึก context.md แบบส่วนตัวแล้ว · ไม่ได้ส่งออกจากเครื่อง" }
        catch { status.stringValue = "บันทึกไม่ได้ — ไฟล์เดิมยังไม่ถูกแทนที่" }
    }
    @objc func loadFile() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.plainText, UTType(filenameExtension: "md") ?? .plainText]; panel.allowsMultipleSelection = false; panel.canChooseDirectories = false
        panel.beginSheetModal(for: window) { [weak self] result in
            guard result == .OK, let url = panel.url, let self else { return }
            do {
                let contents = try readContext(url)
                if self.text.string != self.lastSaved {
                    let alert = NSAlert(); alert.messageText = "แทนข้อความที่ยังไม่บันทึก?"
                    alert.addButton(withTitle: "ยกเลิก"); alert.addButton(withTitle: "เปิดข้อความใหม่")
                    guard alert.runModal() == .alertSecondButtonReturn else { return }
                }
                self.text.string = contents; self.status.stringValue = "เปิดสำเนาข้อความแล้ว — บันทึกในแอปจะไม่เขียนทับไฟล์ต้นทาง"
            } catch { self.status.stringValue = "เปิดไม่ได้ — รองรับไฟล์ข้อความ UTF-8 ไม่เกิน 2 MB" }
        }
    }
    @objc func copyContext() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text.string, forType: .string)
        status.stringValue = "คัดลอกแล้ว · วางด้วยตนเองใน Codex หรือ Claude · ไม่ได้ส่งอัตโนมัติ"
    }
    @objc func revealFile() {
        let file = directory.appendingPathComponent("context.md")
        guard FileManager.default.fileExists(atPath: file.path) else { status.stringValue = "บันทึกข้อความก่อนแสดงไฟล์"; return }
        NSWorkspace.shared.activateFileViewerSelecting([file])
    }
}

func label(_ text: String, size: CGFloat = 13, color: NSColor = .labelColor, bold: Bool = false) -> NSTextField {
    let field = NSTextField(wrappingLabelWithString: text)
    field.font = bold ? .boldSystemFont(ofSize: size) : .systemFont(ofSize: size)
    field.textColor = color
    return field
}

enum Palette {
    static func color(_ light: UInt32, _ dark: UInt32) -> NSColor {
        NSColor(name: nil) { appearance in
            let value = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
            return NSColor(srgbRed: CGFloat((value >> 16) & 255) / 255, green: CGFloat((value >> 8) & 255) / 255, blue: CGFloat(value & 255) / 255, alpha: 1)
        }
    }
    static let canvas = color(0xF4F7FA, 0x17232E)
    static let surface = color(0xFFFFFF, 0x21313E)
    static let ink = color(0x172B3A, 0xEFF6FA)
    static let slate = color(0x526777, 0xB7C7D2)
    static let teal = color(0x087F8C, 0x67D6DD)
    static let ribbon = color(0xE6F4F4, 0x193F47)
}
final class Surface: NSView {
    var tint: NSColor = Palette.surface
    override func draw(_ dirtyRect: NSRect) {
        tint.setFill(); NSBezierPath(roundedRect: bounds, xRadius: 12, yRadius: 12).fill()
    }
}
func resetSummary(_ date: Date?, now: Date = Date()) -> String {
    guard let date else { return "ยังไม่ทราบเวลารีเซ็ต" }
    let minutes = Int(ceil(date.timeIntervalSince(now) / 60))
    if minutes <= 0 { return "ถึงเวลารีเซ็ต · รอข้อมูลใหม่" }
    if minutes < 60 { return "รีเซ็ตใน \(minutes) นาที" }
    if minutes < 1440 { return "รีเซ็ตใน \(minutes / 60) ชม. \(minutes % 60) นาที" }
    return "รีเซ็ตใน \(minutes / 1440) วัน \((minutes % 1440) / 60) ชม."
}
final class RecommendationStrip: NSView {
    let title = label("ยังแนะนำบัญชีไม่ได้", size: 17, bold: true)
    let reason = label("รีเฟรชเพื่อดูโควตาล่าสุด", size: 13, color: Palette.slate)
    let button = NSButton(title: "รอข้อมูล", target: nil, action: nil)
    init(target: AnyObject, action: Selector) {
        super.init(frame: .zero)
        let surface = Surface(); surface.tint = Palette.ribbon
        surface.translatesAutoresizingMaskIntoConstraints = false; addSubview(surface)
        title.textColor = Palette.ink
        let top = NSStackView(views: [title, NSView(), button]); top.spacing = 8
        button.target = target; button.action = action; button.bezelStyle = .rounded; button.bezelColor = Palette.teal; button.isEnabled = false
        let stack = NSStackView(views: [top, reason]); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 6
        stack.translatesAutoresizingMaskIntoConstraints = false; addSubview(stack)
        NSLayoutConstraint.activate([surface.leadingAnchor.constraint(equalTo: leadingAnchor), surface.trailingAnchor.constraint(equalTo: trailingAnchor), surface.topAnchor.constraint(equalTo: topAnchor), surface.bottomAnchor.constraint(equalTo: bottomAnchor), stack.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12), stack.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12), stack.topAnchor.constraint(equalTo: topAnchor, constant: 10), stack.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -10), top.widthAnchor.constraint(equalTo: stack.widthAnchor), reason.widthAnchor.constraint(equalTo: stack.widthAnchor)])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
}
final class AccountRow: NSView {
    let primaryText = label("รอบหลัก —", size: 14, bold: true)
    let weeklyText = label("สัปดาห์ —", size: 14, bold: true)
    let primaryTime = label("", size: 11, color: Palette.slate)
    let weeklyTime = label("", size: 11, color: Palette.slate)
    let primaryBar = NSProgressIndicator()
    let weeklyBar = NSProgressIndicator()
    var primaryMetric: NSStackView!
    let resetText = label("", size: 11, color: Palette.slate)
    let stateText = label("", size: 11, color: Palette.teal)
    let switchButton: NSButton
    let resetButton = NSButton(title: "ใช้สิทธิ์รีเซ็ตฟรี", target: nil, action: nil)
    let detailsButton = NSButton(title: "รายละเอียด", target: nil, action: nil)
    var details = ""
    var identityDetails = ""
    let provider: String
    init(account: Account, number: Int, target: AnyObject, action: Selector) {
        provider = account.provider
        switchButton = NSButton(title: "ใช้บัญชีนี้", target: target, action: action)
        super.init(frame: .zero)
        identityDetails = "\(account.label)\n\(account.email ?? "ยังไม่เชื่อมตัวตนโควตา")\n"
        switchButton.identifier = NSUserInterfaceItemIdentifier(account.id); switchButton.bezelStyle = .rounded; switchButton.controlSize = .small
        switchButton.setAccessibilityLabel("สลับไป \(provider) บัญชี \(number)")
        detailsButton.bezelStyle = .inline; detailsButton.controlSize = .small; detailsButton.target = self; detailsButton.action = #selector(showDetails)
        resetButton.identifier = NSUserInterfaceItemIdentifier(account.id); resetButton.bezelStyle = .rounded; resetButton.controlSize = .small; resetButton.isEnabled = false
        resetButton.toolTip = "ยังไม่มีช่องทางรีเซ็ตที่ยืนยันได้สำหรับแอปนี้"
        let email = NSTextField(labelWithString: account.email ?? "ยังไม่เชื่อมอีเมล")
        email.font = .systemFont(ofSize: 11); email.textColor = Palette.slate; email.lineBreakMode = .byTruncatingMiddle
        email.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        email.toolTip = account.email
        let identity = NSStackView(views: [label("บัญชี \(number)", size: 15, color: Palette.ink, bold: true), email]); identity.orientation = .vertical; identity.alignment = .leading; identity.spacing = 2
        let title = NSStackView(views: [identity, stateText, NSView(), detailsButton, switchButton]); title.spacing = 6
        func metric(_ text: NSTextField, _ bar: NSProgressIndicator, _ time: NSTextField) -> NSStackView {
            bar.style = .bar; bar.isIndeterminate = false; bar.minValue = 0; bar.maxValue = 100; bar.controlSize = .small
            text.font = .monospacedDigitSystemFont(ofSize: 14, weight: .semibold)
            let stack = NSStackView(views: [text, bar, time]); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 4
            for view in [text, bar, time] { view.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true }
            return stack
        }
        primaryMetric = metric(primaryText, primaryBar, primaryTime)
        let metrics = NSStackView(views: [primaryMetric, metric(weeklyText, weeklyBar, weeklyTime)])
        metrics.detachesHiddenViews = true
        metrics.distribution = .fillEqually; metrics.alignment = .top; metrics.spacing = 18
        let bottom = NSStackView(views: [resetText, NSView(), resetButton]); bottom.spacing = 6
        resetButton.isHidden = provider != "codex"
        let stack = NSStackView(views: [title, metrics, bottom]); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 6
        stack.translatesAutoresizingMaskIntoConstraints = false; addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 8), stack.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -8), stack.topAnchor.constraint(equalTo: topAnchor, constant: 9), stack.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -9)])
        for view in [title, metrics, bottom] { view.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true }
        render(QuotaViewData(error: "กำลังอ่านโควตา…"))
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    func render(_ value: QuotaViewData) {
        primaryMetric.isHidden = value.primary == nil
        func metric(_ quota: WindowQuota?, _ title: String, _ text: NSTextField, _ bar: NSProgressIndicator, _ time: NSTextField) {
            let amount = percentRemaining(quota?.used)
            text.stringValue = "\(title) \(amount.map { String(format: "%.0f%%", $0) } ?? "—")"
            text.textColor = amount.map { $0 < 20 ? .systemOrange : Palette.ink } ?? Palette.slate
            bar.doubleValue = amount ?? 0; bar.isHidden = amount == nil
            bar.setAccessibilityLabel("\(title)คงเหลือ \(amount.map { String(Int($0)) } ?? "ไม่ทราบ") เปอร์เซ็นต์")
            time.stringValue = resetSummary(quota?.reset) + (quota?.reset.map { "\n" + shortDate($0) } ?? "")
            if let reset = quota?.reset { time.toolTip = localDate(ISO8601DateFormatter().string(from: reset)) }
        }
        metric(value.primary, "รอบหลัก", primaryText, primaryBar, primaryTime)
        metric(value.weekly, "สัปดาห์", weeklyText, weeklyBar, weeklyTime)
        if provider == "codex" {
            let count = value.resetCount.map(String.init) ?? value.resets
            resetText.stringValue = "รีเซ็ตฟรี \(count) ครั้ง" + (value.resetExpiry.map { " · หมด \(shortDate($0))" } ?? " · ไม่ทราบวันหมดอายุ")
        } else { resetText.stringValue = "ยอดคงเหลือ \(value.balance)" }
        details = identityDetails + (value.error ?? value.details)
        if value.primary == nil { details += "\nรอบสั้น: ผู้ให้บริการไม่ส่งข้อมูล · ใช้ข้อมูลรายสัปดาห์" }
        stateText.stringValue = value.error == nil ? "" : "รอข้อมูล"
        detailsButton.toolTip = details
    }
    func rank(_ recommendation: Recommendation, selected: Bool) {
        stateText.stringValue = recommendation.score == nil ? "รอข้อมูลใหม่" : selected ? "แนะนำ" : ""
        details += "\n\n" + (recommendation.score == nil ? recommendation.reason : "ข้อมูลโควตายังอยู่ในช่วงที่ใช้แนะนำได้") + "\nคำแนะนำใช้กลยุทธ์ที่เลือกด้านบน ไม่ใช่จำนวนโทเคนหรือการเทียบราคา"
        toolTip = details
    }
    @objc func showDetails() {
        let alert = NSAlert(); alert.messageText = "รายละเอียดโควตา"; alert.informativeText = details; alert.addButton(withTitle: "ปิด")
        if let window { alert.beginSheetModal(for: window) }
    }
}
func shortDate(_ date: Date) -> String {
    let formatter = DateFormatter(); formatter.locale = Locale(identifier: "th_TH"); formatter.timeZone = TimeZone(identifier: "Asia/Bangkok"); formatter.dateFormat = "d MMM HH:mm"
    return formatter.string(from: date)
}

final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    var window: NSWindow!
    var rows: [String: AccountRow] = [:]
    var accounts: [Account] = []
    var dependencies = Dependencies(codexApp: false, claudeApp: false)
    var columns: [NSStackView] = []
    var addButtons: [NSButton] = []
    var quotaValues: [String: QuotaViewData] = [:]
    var resetValues: [String: (ResetAvailability, Date)] = [:]
    let status = label("กำลังค้นหาบัญชี…", size: 12, color: .secondaryLabelColor)
    let dependencyNotice = label("", size: 12, color: .secondaryLabelColor)
    let refreshButton = NSButton(title: "รีเฟรช", target: nil, action: nil)
    let connectButton = NSButton(title: "เชื่อมยอดและเซสชัน", target: nil, action: nil)
    let state = SwitchState()
    var refreshing = false
    var contextEditor: ContextEditor?
    var recommendationTimer: Timer?
    var strips: [String: RecommendationStrip] = [:]
    var displayNumbers: [String: Int] = [:]
    var alertHistories: [String: AlertHistory] = [:]
    var lastRefresh: Date?
    var refreshGeneration = 0
    var nativeAllowed = false
    let notificationToggle = NSButton(checkboxWithTitle: "แจ้งเตือนบัญชีที่ควรใช้", target: nil, action: nil)
    let notificationNotice = label("", size: 12, color: Palette.slate)
    let notice = label("", size: 13, color: Palette.teal)
    let defaults = UserDefaults.standard
    let strategySelector = NSPopUpButton(frame: .zero, pullsDown: false)
    let resetHoursSelector = NSPopUpButton(frame: .zero, pullsDown: false)
    var strategy: AccountStrategy { AccountStrategy(rawValue: defaults.string(forKey: "accountStrategy") ?? "rate") ?? .rate }
    var avoidResetHours: Int { let value = defaults.integer(forKey: "avoidResetHours"); return [1, 6, 24, 48].contains(value) ? value : 48 }
    var notificationsEnabled: Bool { notificationToggle.state == .on }
    // Synthetic review never calls helpers, changes account state or sends native notifications.
    var fixtureMode: String? {
        guard let index = CommandLine.arguments.firstIndex(of: "--ui-fixture"), CommandLine.arguments.count > index + 1 else { return nil }
        return CommandLine.arguments[index + 1]
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1120, height: 800), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "AI Accounts · Beta"
        window.minSize = NSSize(width: 1080, height: 650)
        window.backgroundColor = Palette.canvas
        window.titlebarAppearsTransparent = true
        window.isReleasedWhenClosed = false
        let icon = NSImageView()
        if let url = Bundle.main.url(forResource: "AppIcon", withExtension: "png") { icon.image = NSImage(contentsOf: url) }
        icon.imageScaling = .scaleProportionallyUpOrDown
        icon.widthAnchor.constraint(equalToConstant: 48).isActive = true
        icon.heightAnchor.constraint(equalToConstant: 48).isActive = true
        let heading = NSStackView(views: [label("AI Accounts", size: 24, color: Palette.ink, bold: true), label("เลือกบัญชีให้เหมาะกับโควตาที่เหลือ", size: 13, color: Palette.slate)])
        heading.orientation = .vertical; heading.alignment = .leading; heading.spacing = 4
        refreshButton.target = self; refreshButton.action = #selector(refresh)
        refreshButton.bezelStyle = .rounded; refreshButton.bezelColor = .systemTeal
        connectButton.target = self; connectButton.action = #selector(connect)
        connectButton.bezelStyle = .rounded
        let context = NSButton(title: "บริบทกลาง", target: self, action: #selector(openContext))
        context.bezelStyle = .rounded
        let header = NSStackView(views: [icon, heading, NSView(), refreshButton]); header.spacing = 12
        let downloads = NSStackView()
        for (name, url) in [("ดาวน์โหลด Codex", "https://chatgpt.com/codex/"), ("ดาวน์โหลด Claude", "https://claude.com/download")] {
            let button = NSButton(title: name, target: self, action: #selector(download(_:)))
            button.identifier = NSUserInterfaceItemIdentifier(url); button.bezelStyle = .inline
            downloads.addArrangedSubview(button)
        }
        downloads.addArrangedSubview(NSView())
        downloads.addArrangedSubview(context); downloads.addArrangedSubview(connectButton)
        downloads.addArrangedSubview(dependencyNotice)
        notificationToggle.target = self; notificationToggle.action = #selector(toggleNotifications)
        notificationToggle.state = defaults.bool(forKey: "alertsEnabled") ? .on : .off
        if let data = defaults.data(forKey: "alertHistory"), let history = try? JSONDecoder().decode([String: AlertHistory].self, from: data) { alertHistories = history }
        let test = NSButton(title: "ทดสอบ", target: self, action: #selector(testNotification)); test.bezelStyle = .inline
        let settings = NSButton(title: "ตั้งค่าการแจ้งเตือน", target: self, action: #selector(notificationSettings)); settings.bezelStyle = .inline
        strategySelector.addItems(withTitles: AccountStrategy.allCases.map(\.title)); strategySelector.selectItem(at: AccountStrategy.allCases.firstIndex(of: strategy)!)
        strategySelector.target = self; strategySelector.action = #selector(changeStrategy)
        strategySelector.setAccessibilityLabel("กลยุทธ์เลือกบัญชี")
        strategySelector.toolTip = "ตามลำดับ: ใช้บัญชีแรกที่พร้อม · กระจายโควตา: เลือกบัญชีที่เหลือมาก · ตามรอบรีเซ็ต: เน้นบัญชีพร้อมและโควตาต่อเวลา"
        resetHoursSelector.addItems(withTitles: ["เว้นรีเซ็ต 1 ชม.", "เว้นรีเซ็ต 6 ชม.", "เว้นรีเซ็ต 24 ชม.", "เว้นรีเซ็ต 2 วัน"])
        resetHoursSelector.selectItem(at: [1, 6, 24, 48].firstIndex(of: avoidResetHours)!)
        resetHoursSelector.target = self; resetHoursSelector.action = #selector(changeStrategy)
        resetHoursSelector.setAccessibilityLabel("หลีกเลี่ยงใช้สิทธิ์เมื่อใกล้รีเซ็ตตามรอบ")
        let guidance = NSStackView(views: [notificationToggle, test, settings, NSView(), strategySelector, resetHoursSelector]); guidance.spacing = 10
        let providerColumns = NSStackView(); providerColumns.orientation = .horizontal; providerColumns.alignment = .top; providerColumns.distribution = .fillEqually; providerColumns.spacing = 16
        for provider in ["codex", "claude"] {
            let column = NSStackView(); column.orientation = .vertical; column.alignment = .leading; column.spacing = 0
            columns.append(column)
            let surface = Surface(); surface.translatesAutoresizingMaskIntoConstraints = false
            column.translatesAutoresizingMaskIntoConstraints = false; surface.addSubview(column); providerColumns.addArrangedSubview(surface)
            NSLayoutConstraint.activate([column.leadingAnchor.constraint(equalTo: surface.leadingAnchor, constant: 12), column.trailingAnchor.constraint(equalTo: surface.trailingAnchor, constant: -12), column.topAnchor.constraint(equalTo: surface.topAnchor, constant: 12), column.bottomAnchor.constraint(equalTo: surface.bottomAnchor, constant: -6)])
            let add = NSButton(title: "เพิ่มบัญชี", target: self, action: #selector(addAccount(_:)))
            add.identifier = NSUserInterfaceItemIdentifier(provider); add.bezelStyle = .rounded; addButtons.append(add)
            let title = NSStackView(views: [label(provider == "codex" ? "Codex" : "Claude", size: 18, color: Palette.ink, bold: true), NSView(), add])
            column.addArrangedSubview(title); title.widthAnchor.constraint(equalTo: column.widthAnchor).isActive = true
            column.setCustomSpacing(10, after: title)
            let strip = RecommendationStrip(target: self, action: #selector(switchAccount(_:))); strips[provider] = strip
            column.addArrangedSubview(strip); strip.widthAnchor.constraint(equalTo: column.widthAnchor).isActive = true
            column.setCustomSpacing(6, after: strip)
        }
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.drawsBackground = false; scroll.autohidesScrollers = true
        let document = FlippedView(); document.translatesAutoresizingMaskIntoConstraints = false
        providerColumns.translatesAutoresizingMaskIntoConstraints = false; document.addSubview(providerColumns); scroll.documentView = document
        NSLayoutConstraint.activate([document.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor), providerColumns.leadingAnchor.constraint(equalTo: document.leadingAnchor), providerColumns.trailingAnchor.constraint(equalTo: document.trailingAnchor, constant: -4), providerColumns.topAnchor.constraint(equalTo: document.topAnchor, constant: 8), providerColumns.bottomAnchor.constraint(equalTo: document.bottomAnchor)])
        let footer = NSStackView(views: [notificationNotice, notice]); footer.orientation = .vertical; footer.alignment = .leading; footer.spacing = 6
        notificationNotice.widthAnchor.constraint(equalTo: footer.widthAnchor).isActive = true
        notice.widthAnchor.constraint(equalTo: footer.widthAnchor).isActive = true
        let content = window.contentView!
        for view in [header, downloads, guidance, scroll, footer, status] { view.translatesAutoresizingMaskIntoConstraints = false; content.addSubview(view) }
        for view in [header, downloads, guidance, scroll, footer, status] {
            view.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 25).isActive = true
            view.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -25).isActive = true
        }
        NSLayoutConstraint.activate([
            header.topAnchor.constraint(equalTo: content.topAnchor, constant: 8), header.heightAnchor.constraint(equalToConstant: 48),
            guidance.topAnchor.constraint(equalTo: header.bottomAnchor, constant: 7),
            scroll.topAnchor.constraint(equalTo: guidance.bottomAnchor, constant: 6), scroll.bottomAnchor.constraint(equalTo: downloads.topAnchor, constant: -8),
            downloads.bottomAnchor.constraint(equalTo: footer.topAnchor, constant: -10),
            footer.bottomAnchor.constraint(equalTo: status.topAnchor, constant: -8), status.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -14)
        ])
        let menu = NSMenu(), item = NSMenuItem(), appMenu = NSMenu()
        appMenu.addItem(withTitle: "ออกจาก AI Accounts", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = appMenu; menu.addItem(item)
        let editItem = NSMenuItem(), editMenu = NSMenu(title: "แก้ไข")
        editMenu.addItem(withTitle: "ตัด", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "คัดลอก", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "วาง", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "เลือกทั้งหมด", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu; menu.addItem(editItem); NSApp.mainMenu = menu
        window.center(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        notificationNotice.stringValue = notificationHint(enabled: notificationsEnabled, nativeAllowed: nativeAllowed)
        if Bundle.main.bundleIdentifier != nil && fixtureMode == nil {
            UNUserNotificationCenter.current().delegate = self
            UNUserNotificationCenter.current().getNotificationSettings { [weak self] settings in DispatchQueue.main.async {
                self?.nativeAllowed = settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional
                self?.updateNotificationHint()
            } }
        }
        recommendationTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in self?.tick() }
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(wake), name: NSWorkspace.didWakeNotification, object: nil)
        refresh()
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { !state.busy }
    func applicationWillTerminate(_ notification: Notification) {
        recommendationTimer?.invalidate(); refreshGeneration += 1
        NSWorkspace.shared.notificationCenter.removeObserver(self)
    }
    func applicationDidBecomeActive(_ notification: Notification) { if window != nil { tick() } }
    @objc func wake() { tick() }
    func tick() {
        updateRecommendations()
        if fixtureMode == nil && !refreshing && !state.busy { for provider in ["codex", "claude"] { evaluateAlerts(provider: provider) } }
        if refreshDue(last: lastRefresh, now: Date(), busy: state.busy || refreshing) { refresh() }
    }
    func updateNotificationHint() { notificationNotice.stringValue = notificationHint(enabled: notificationsEnabled, nativeAllowed: nativeAllowed) }
    @objc func changeStrategy() {
        guard fixtureMode == nil else { return }
        defaults.set(AccountStrategy.allCases[strategySelector.indexOfSelectedItem].rawValue, forKey: "accountStrategy")
        defaults.set([1, 6, 24, 48][resetHoursSelector.indexOfSelectedItem], forKey: "avoidResetHours")
        updateRecommendations()
        for provider in ["codex", "claude"] { evaluateAlerts(provider: provider) }
    }
    @objc func toggleNotifications() {
        if fixtureMode == nil { defaults.set(notificationsEnabled, forKey: "alertsEnabled") }
        updateNotificationHint()
        guard notificationsEnabled else { notice.stringValue = "ปิดการแจ้งเตือนแล้ว"; return }
        guard Bundle.main.bundleIdentifier != nil && fixtureMode == nil else { return }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { [weak self] allowed, _ in
            DispatchQueue.main.async { self?.nativeAllowed = allowed; self?.updateNotificationHint() }
        }
    }
    @objc func notificationSettings() {
        let alert = NSAlert(); alert.messageText = "การแจ้งเตือน"
        alert.informativeText = "แจ้งเมื่อใช้โควตาถึง 50% ต่อบัญชีและรอบรีเซ็ต เมื่อบัญชีที่แนะนำเปลี่ยน หรือมีโควตาเหลือก่อนรีเซ็ตภายใน 60 นาที\n\nรวมเหตุการณ์ใช้ถึง 50% ที่พบพร้อมกัน และแจ้งครั้งเดียวต่อรอบ ส่วนคำแนะนำเว้นอย่างน้อย 30 นาทีต่อบริการ และใช้เฉพาะข้อมูลอายุไม่เกิน 15 นาที\n\nแอปต้องเปิดอยู่ ไม่สลับบัญชีให้อัตโนมัติ หาก macOS ไม่อนุญาต ยังเห็นข้อความเตือนในแอปได้\n\nสิทธิ์แจ้งเตือน macOS เปลี่ยนได้ที่ System Settings › Notifications › AI Accounts"
        alert.addButton(withTitle: "ปิด"); alert.beginSheetModal(for: window)
    }
    func showNotice(_ message: String, test: Bool = false) {
        notice.stringValue = message
        guard notificationsEnabled, nativeAllowed, Bundle.main.bundleIdentifier != nil, fixtureMode == nil else { return }
        let content = UNMutableNotificationContent(); content.title = test ? "ทดสอบ AI Accounts" : "AI Accounts"; content.body = message; content.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)) { [weak self] error in
            if error != nil { DispatchQueue.main.async { self?.nativeAllowed = false; self?.updateNotificationHint() } }
        }
    }
    @objc func testNotification() {
        guard notificationsEnabled else { notice.stringValue = "เปิดแจ้งเตือนก่อนทดสอบ"; return }
        showNotice("การแจ้งเตือนพร้อมในแอป · บัญชีและโควตาจะแสดงที่นี่", test: true)
    }
    func evaluateAlerts(provider: String) {
        let now = Date()
        let snapshots = accounts.filter { $0.provider == provider }.compactMap { account in quotaValues[account.id].flatMap { alertSnapshot(id: account.id, value: $0, now: now) } }
        let winner = strategyWinner(accounts, quota: quotaValues, numbers: displayNumbers, provider: provider, strategy: strategy, now: now)
        var history = alertHistories[provider] ?? AlertHistory()
        let previousWinner = history.winner
        let thresholds = accounts.filter { $0.provider == provider }.flatMap { account -> [UsageThreshold] in
            guard let windows = freshWindows(quotaValues[account.id], now: now) else { return [] }
            return windows.enumerated().map { UsageThreshold(id: account.id, window: $0.offset == 0 ? "สัปดาห์" : "รอบหลัก", used: $0.element.used!, reset: $0.element.reset!) }
        }
        let pending = thresholdEvents(thresholds, enabled: notificationsEnabled, now: now, history: &history)
        if !pending.isEmpty {
            let usage = pending.map { "บัญชี \(displayNumbers[$0.id] ?? 0) ใช้\($0.window) \(Int($0.used))%" }.joined(separator: " · ")
            let recommendation = winner.flatMap { displayNumbers[$0] }.map { " · แนะนำบัญชี \($0)" } ?? ""
            showNotice("\(provider == "codex" ? "Codex" : "Claude") \(usage)\(recommendation)")
            if let winner { history.winner = winner }
        } else if let id = alertEvent(enabled: notificationsEnabled, winner: winner, snapshots: snapshots, now: now, history: &history), let snapshot = snapshots.first(where: { $0.id == id }), let number = displayNumbers[id] {
            let reason = previousWinner != nil && previousWinner != winner && id == winner ? "แนะนำ" : "ใกล้รีเซ็ต"
            showNotice("\(provider == "codex" ? "Codex" : "Claude") \(reason)บัญชี \(number) · เหลือ \(Int(snapshot.remaining))% · \(resetSummary(snapshot.reset, now: now))")
        }
        alertHistories[provider] = history
        if let data = try? JSONEncoder().encode(alertHistories) { defaults.set(data, forKey: "alertHistory") }
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) { completionHandler([.banner, .sound]) }
    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
        DispatchQueue.main.async { self.window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }
        completionHandler()
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if !state.busy {
            if let editor = contextEditor, editor.text.string != editor.lastSaved {
                let alert = NSAlert(); alert.messageText = "บริบทกลางยังไม่ได้บันทึก"
                alert.addButton(withTitle: "กลับไปบันทึก"); alert.addButton(withTitle: "ออกโดยไม่บันทึก")
                if alert.runModal() != .alertSecondButtonReturn { editor.show(); return .terminateCancel }
            }
            return .terminateNow
        }
        let alert = NSAlert(); alert.messageText = "คำสั่งยังทำงานอยู่"
        alert.informativeText = "กรุณาจบหรือยกเลิกการเข้าสู่ระบบในหน้าต่างผู้ให้บริการก่อน แอปจะไม่ตัดคำสั่งที่อาจกำลังบันทึกบัญชี"
        alert.addButton(withTitle: "กลับไปทำต่อ"); alert.runModal()
        return .terminateCancel
    }
    func updateControls() {
        let busy = state.busy || refreshing || fixtureMode != nil
        refreshButton.isEnabled = !busy; connectButton.isEnabled = !busy
        for (id, row) in rows {
            let provider = accounts.first { $0.id == id }?.provider
            row.switchButton.isEnabled = !busy && (provider == "codex" ? dependencies.codexApp : dependencies.claudeApp)
            if let (value, fetched) = resetValues[id] {
                let avoid = avoidResetReason(quotaValues[id], hours: avoidResetHours, now: Date())
                row.resetButton.isEnabled = !busy && canReset(value, fetched: fetched, now: Date()) && avoid == nil
                row.resetButton.title = value.uncertain == true ? "ตรวจคำขอเดิม" : "ใช้สิทธิ์รีเซ็ตฟรี"
                if value.uncertain != true, avoid?.hasPrefix("เก็บสิทธิ์") == true { row.resetButton.title = "รอรีเซ็ตตามรอบ" }
                row.resetButton.toolTip = avoid ?? resetReasonThai(value.reason)
                if let count = value.availableCount { row.resetText.stringValue = "รีเซ็ตฟรี \(count) ครั้ง" + (value.expiresAt.map { " · หมด \(shortDate(Date(timeIntervalSince1970: $0)))" } ?? " · ไม่ทราบวันหมดอายุ") }
            } else { row.resetButton.isEnabled = false; row.resetButton.toolTip = "กำลังตรวจสิทธิ์รีเซ็ตจากผู้ให้บริการ" }
        }
        for button in addButtons { button.isEnabled = !busy && (button.identifier?.rawValue == "codex" ? dependencies.codexApp : dependencies.claudeApp) }
        for (provider, strip) in strips { strip.button.isEnabled = !busy && strip.button.identifier != nil && (provider == "codex" ? dependencies.codexApp : dependencies.claudeApp) }
    }
    func rebuildRows() {
        displayNumbers = accountNumbers(accounts, saved: fixtureMode == nil ? defaults.dictionary(forKey: "accountNumbers") as? [String: Int] ?? [:] : [:])
        if fixtureMode == nil { defaults.set(displayNumbers, forKey: "accountNumbers") }
        rows.removeAll()
        for column in columns { for view in column.arrangedSubviews.dropFirst(2) { column.removeArrangedSubview(view); view.removeFromSuperview() } }
        for (index, provider) in ["codex", "claude"].enumerated() {
            let matching = accounts.filter { $0.provider == provider }.sorted { (displayNumbers[$0.id] ?? 0) < (displayNumbers[$1.id] ?? 0) }
            if matching.isEmpty {
                let empty = label("ยังไม่มีบัญชี\nเพิ่มบัญชี หรือกดเชื่อมยอดและเซสชันเพื่อเตรียมบัญชีเดิม\nเปิดแท็บ Code ในแอปผู้ให้บริการอย่างน้อยหนึ่งครั้งก่อนเชื่อมเซสชัน", color: .secondaryLabelColor)
                columns[index].addArrangedSubview(empty); empty.widthAnchor.constraint(equalTo: columns[index].widthAnchor).isActive = true
            }
            for account in matching {
                let row = AccountRow(account: account, number: displayNumbers[account.id]!, target: self, action: #selector(switchAccount(_:)))
                row.resetButton.target = self; row.resetButton.action = #selector(resetAccount(_:))
                rows[account.id] = row; columns[index].addArrangedSubview(row)
                row.widthAnchor.constraint(equalTo: columns[index].widthAnchor).isActive = true
                let divider = NSBox(); divider.boxType = .separator
                columns[index].addArrangedSubview(divider); divider.widthAnchor.constraint(equalTo: columns[index].widthAnchor).isActive = true
            }
        }
        dependencyNotice.stringValue = "Codex: \(dependencies.codexApp ? "พร้อม" : "ยังไม่ติดตั้ง") · Claude: \(dependencies.claudeApp ? "พร้อม" : "ยังไม่ติดตั้ง")"
        updateControls()
    }
    func updateRecommendations() {
        let now = Date()
        var values: [String: Recommendation] = [:]
        for account in accounts {
            if let value = quotaValues[account.id], value.error == nil {
                values[account.id] = recommend(weekly: value.weekly, primary: value.primary, updated: value.updatedDate, now: now)
            } else { values[account.id] = Recommendation(score: nil, hours: nil, reason: "ยังไม่มีข้อมูลที่ใช้แนะนำได้") }
        }
        for provider in ["codex", "claude"] {
            let winner = strategyWinner(accounts, quota: quotaValues, numbers: displayNumbers, provider: provider, strategy: strategy, now: now)
            if let strip = strips[provider] {
                if let winner, let number = displayNumbers[winner], let value = quotaValues[winner], alertSnapshot(id: winner, value: value, now: now) != nil {
                    strip.title.stringValue = "แนะนำบัญชี \(number)"
                    let base = value.primary.map { "รอบหลัก \(remaining($0.used)) · สัปดาห์ \(remaining(value.weekly?.used))" } ?? "ใช้ข้อมูลรายสัปดาห์ · เหลือ \(remaining(value.weekly?.used))"
                    let comparison: String
                    switch strategy {
                    case .sequential: comparison = "บัญชีแรกตามลำดับที่ยังมีโควตา"
                    case .balance: comparison = "มีโควตาในรอบที่เหลือน้อยสุดมากที่สุด"
                    case .rate: comparison = "เน้นบัญชีพร้อมใช้ แล้วเทียบโควตาต่อเวลาถึงรีเซ็ต"
                    }
                    strip.reason.stringValue = base + "\n" + comparison
                    strip.button.title = "ใช้บัญชี \(number)"; strip.button.identifier = NSUserInterfaceItemIdentifier(winner)
                    strip.toolTip = "เลือกตามกลยุทธ์ที่ตั้งไว้ ใช้เฉพาะข้อมูลใหม่ภายใน 15 นาที เป็นคำแนะนำโดยประมาณ ไม่ใช่จำนวนโทเคนหรือการเทียบราคา"
                } else {
                    strip.title.stringValue = "ยังแนะนำบัญชีไม่ได้"
                    strip.reason.stringValue = accounts.contains { $0.provider == provider } ? "ต้องมีข้อมูลโควตาล่าสุด · ลองรีเฟรช" : "เพิ่มบัญชีเพื่อเริ่มดูโควตา"
                    strip.button.title = "รอข้อมูล"; strip.button.identifier = nil
                }
            }
            for account in accounts where account.provider == provider {
                // Render again so timer updates do not append duplicate detail text.
                if let value = quotaValues[account.id] { rows[account.id]?.render(value) }
                rows[account.id]?.rank(values[account.id]!, selected: winner == account.id)
            }
        }
        updateControls()
    }
    @objc func refresh() {
        guard !state.busy, !refreshing else { return }
        if let mode = fixtureMode { renderFixture(mode); return }
        refreshing = true; refreshGeneration += 1; let generation = refreshGeneration; updateControls()
        status.stringValue = "กำลังค้นหาบัญชีและอ่านโควตา…"
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let (data, error) = runHelper(["list"], timeout: 10)
            guard let data, let list = parseAccounts(data) else {
                DispatchQueue.main.async {
                    guard let self, self.refreshGeneration == generation else { return }
                    self.refreshing = false
                    self.lastRefresh = Date()
                    self.quotaValues = self.quotaValues.mapValues { value in var copy = value; copy.error = "รีเฟรชไม่สำเร็จ · ค่าจากครั้งก่อน"; return copy }
                    self.updateRecommendations()
                    self.status.stringValue = error ?? "รูปแบบบัญชีไม่ถูกต้อง — ไม่ได้เปลี่ยนบัญชีใด"
                    self.updateControls()
                }; return
            }
            DispatchQueue.main.async {
                guard let self, self.refreshGeneration == generation else { return }
                self.accounts = list.accounts; self.dependencies = list.dependencies; self.rebuildRows()
                self.updateRecommendations()
            }
            for provider in ["codex", "claude"] where list.accounts.contains(where: { $0.provider == provider }) {
                let (usage, error) = runHelper(["usage", provider], timeout: 30)
                DispatchQueue.main.async {
                    guard let self, self.refreshGeneration == generation else { return }
                    for account in list.accounts where account.provider == provider {
                        let value = usage.map { quotaData($0, account: account) } ?? QuotaViewData(error: error ?? "อ่านโควตาไม่ได้")
                        if value.error != nil, var old = self.quotaValues[account.id] { old.error = value.error; self.quotaValues[account.id] = old }
                        else { self.quotaValues[account.id] = value }
                    }
                    self.updateRecommendations()
                    self.evaluateAlerts(provider: provider)
                }
            }
            for account in list.accounts where account.provider == "codex" {
                let (data, _) = runHelper(["reset-status", "codex", account.key], timeout: 45)
                let value = data.flatMap { try? JSONDecoder().decode(ResetAvailability.self, from: $0) }
                DispatchQueue.main.async {
                    guard let self, self.refreshGeneration == generation else { return }
                    self.resetValues[account.id] = value.map { ($0, Date()) }
                    self.updateControls()
                }
            }
            DispatchQueue.main.async {
                guard let self, self.refreshGeneration == generation else { return }
                self.refreshing = false; self.updateControls()
                self.lastRefresh = Date()
                let formatter = DateFormatter(); formatter.dateFormat = "HH:mm"; formatter.timeZone = TimeZone(identifier: "Asia/Bangkok")
                self.status.stringValue = "อัปเดต \(formatter.string(from: Date())) · \(list.accounts.count) บัญชี · รีเฟรชทุก 5 นาทีขณะเปิดแอป · เวลาไทย"
            }
        }
    }
    func renderFixture(_ mode: String) {
        let now = Date()
        accounts = ["codex", "claude"].flatMap { provider in
            (1...(mode == "many" ? 14 : 3)).map { n in
                let key = n <= 3 ? (provider == "codex" ? ["main", "account2", "account3"][n - 1] : ["a", "b", "c"][n - 1]) : "extra\(n)"
                return Account(id: "\(provider):\(key)", provider: provider, key: key, label: "Example \(n)", email: nil, usageAccount: nil)
            }
        }
        dependencies = Dependencies(codexApp: true, claudeApp: true)
        // Avoid writing fixture IDs to the user's stable-number preferences.
        displayNumbers = accountNumbers(accounts, saved: [:])
        rebuildRows()
        for account in accounts {
            let number = displayNumbers[account.id] ?? 1
            let used = [62.0, 21.0, 88.0][(number - 1) % 3]
            let reset = now.addingTimeInterval(Double(number == 2 ? 7200 : 86400 * number))
            quotaValues[account.id] = mode == "no-data" ? QuotaViewData(error: "ข้อมูลตัวอย่าง: ไม่พบโควตา") : QuotaViewData(percent: 100 - used, balance: "0 Credits", resetTime: localDate(ISO8601DateFormatter().string(from: reset)), updated: "ตัวอย่าง", details: "ข้อมูลสังเคราะห์สำหรับตรวจหน้าจอ ไม่มีการเชื่อมต่อหรือสลับบัญชีจริง", weekly: WindowQuota(used: used, reset: reset), primary: WindowQuota(used: number == 1 ? 99 : 40, reset: now.addingTimeInterval(3600)), updatedDate: mode == "stale" ? now.addingTimeInterval(-901) : now, resetCount: 2, resetExpiry: now.addingTimeInterval(86400))
        }
        if mode == "denied" { notificationToggle.state = .on; nativeAllowed = false; notice.stringValue = "Codex แนะนำบัญชี 2 · เหลือ 79% · รีเซ็ตใน 2 ชม. (ตัวอย่าง)" }
        updateNotificationHint(); updateRecommendations(); lastRefresh = now
        status.stringValue = "ตัวอย่าง \(mode) · ไม่เชื่อมต่อและไม่สลับบัญชีจริง"
    }
    func mutation(_ arguments: [String], timeout: TimeInterval, alreadyBusy: Bool = false, prefix: String = "") {
        guard fixtureMode == nil else { return }
        guard alreadyBusy || (!state.busy && !refreshing) else { return }
        state.busy = true; updateControls()
        status.stringValue = "กำลังดำเนินการ… กรุณาทำขั้นตอนในหน้าต่างผู้ให้บริการหากปรากฏ"
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let (data, error) = runHelper(arguments, timeout: timeout, mutating: true) {
                DispatchQueue.main.async { self?.status.stringValue = "เกินเวลารอ แต่ยังไม่ตัดคำสั่ง — จบหรือยกเลิกการเข้าสู่ระบบในหน้าต่างผู้ให้บริการ สถานะบัญชียังไม่ยืนยัน" }
            }
            DispatchQueue.main.async {
                guard let self else { return }
                self.state.finish(); self.updateControls()
                let failure = error ?? mutationError(data)
                let message = prefix + (failure ?? data.flatMap(safeMessage) ?? "คำสั่งเสร็จแล้ว — ยังไม่ยืนยันบัญชีในแอป")
                self.status.stringValue = message
                let alert = NSAlert(); alert.messageText = failure == nil ? "ผลการดำเนินการ" : "ดำเนินการไม่สำเร็จ"
                alert.informativeText = message; alert.addButton(withTitle: "ปิด")
                alert.beginSheetModal(for: self.window) { _ in self.refresh() }
            }
        }
    }
    @objc func resetAccount(_ sender: NSButton) {
        guard fixtureMode == nil, !state.busy, !refreshing, let id = sender.identifier?.rawValue, let account = accounts.first(where: { $0.id == id && $0.provider == "codex" }) else { return }
        refreshing = true; updateControls(); status.stringValue = "กำลังตรวจสิทธิ์และตัวตนก่อนรีเซ็ต…"
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let (data, error) = runHelper(["reset-status", "codex", account.key], timeout: 45)
            let value = data.flatMap { try? JSONDecoder().decode(ResetAvailability.self, from: $0) }
            DispatchQueue.main.async {
                guard let self else { return }
                self.refreshing = false
                self.resetValues[id] = value.map { ($0, Date()) }; self.updateControls()
                guard let value, canReset(value, fetched: Date(), now: Date()) else {
                    self.status.stringValue = resetReasonThai(value?.reason ?? error); return
                }
                if let reason = avoidResetReason(self.quotaValues[id], hours: self.avoidResetHours, now: Date()) { self.status.stringValue = reason; return }
                let alert = NSAlert(); alert.alertStyle = .warning
                alert.messageText = value.uncertain == true ? "ตรวจคำขอรีเซ็ตเดิม?" : "ใช้สิทธิ์รีเซ็ตฟรี 1 ครั้ง?"
                alert.informativeText = "Codex บัญชี \(self.displayNumbers[id] ?? 0)\n\(value.accountEmail ?? value.accountId ?? "ไม่ทราบตัวตน")\nเหลือ \(value.availableCount ?? 0) สิทธิ์" + (value.expiresAt.map { " · หมด \(shortDate(Date(timeIntervalSince1970: $0)))" } ?? "") + "\n\nรีเซ็ตขีดจำกัดการใช้งานของบัญชีนี้ตามสิทธิ์ที่ผู้ให้บริการกำหนด ไม่สลับบัญชี ไม่ซื้อเครดิต" + (value.uncertain == true ? "\nส่งคำขอเดิมด้วยรหัสเดิมเพื่อยืนยันผล ไม่สร้างคำขอใหม่" : "\nผู้ให้บริการจะตรวจสิทธิ์และโควตาอีกครั้งก่อนใช้")
                alert.addButton(withTitle: "ยกเลิก").keyEquivalent = "\r"
                alert.addButton(withTitle: value.uncertain == true ? "ตรวจคำขอเดิม" : "ยืนยันใช้ 1 สิทธิ์").keyEquivalent = ""
                guard alert.runModal() == .alertSecondButtonReturn else { self.status.stringValue = "ยกเลิกแล้ว ไม่ได้ใช้สิทธิ์รีเซ็ต"; return }
                if let reason = avoidResetReason(self.quotaValues[id], hours: self.avoidResetHours, now: Date()) { self.status.stringValue = reason; return }
                self.mutation(["reset", "codex", account.key, "--confirmed"], timeout: 60)
            }
        }
    }
    @objc func switchAccount(_ sender: NSButton) {
        guard fixtureMode == nil else { return }
        guard !state.busy, !refreshing, let id = sender.identifier?.rawValue, let account = accounts.first(where: { $0.id == id }) else { return }
        let alert = NSAlert(); alert.alertStyle = .warning
        alert.messageText = "สลับไป \(account.provider == "codex" ? "Codex" : "Claude") บัญชี \(displayNumbers[account.id] ?? 0)?"
        alert.informativeText = "\(account.provider == "codex" ? "Codex" : "Claude") ที่กำลังทำงานอาจถูกปิด กรุณาบันทึกงานก่อน ประวัติในเครื่องใช้ร่วมกันภายในบริการตามการตั้งค่า"
        alert.addButton(withTitle: "ยกเลิก").keyEquivalent = "\r"
        alert.addButton(withTitle: "สลับบัญชี").keyEquivalent = ""
        guard alert.runModal() == .alertSecondButtonReturn else { status.stringValue = "ยกเลิกแล้ว — ไม่ได้สลับบัญชี"; return }
        _ = state.start(account, confirmed: true) { action in mutation(action.arguments, timeout: 60, alreadyBusy: true) }
    }
    @objc func addAccount(_ sender: NSButton) {
        guard fixtureMode == nil else { return }
        guard !state.busy, !refreshing, let provider = sender.identifier?.rawValue else { return }
        let alert = NSAlert(); alert.messageText = "เพิ่มบัญชี \(provider == "codex" ? "Codex" : "Claude")"
        let next = (displayNumbers.filter { $0.key.hasPrefix(provider + ":") }.map(\.value).max() ?? 0) + 1
        let name = "บัญชี \(next)"
        alert.informativeText = "เข้าสู่ระบบบัญชีใหม่ แอปจะแสดงอีเมลให้อัตโนมัติ การเข้าสู่ระบบอาจปิดแอปเดิม กรุณาบันทึกงานก่อน"
        alert.addButton(withTitle: "ยกเลิก").keyEquivalent = "\r"
        alert.addButton(withTitle: "เริ่มเข้าสู่ระบบ").keyEquivalent = ""
        guard alert.runModal() == .alertSecondButtonReturn else { return }
        mutation(["add", provider, name], timeout: 300)
    }
    @objc func connect() {
        guard fixtureMode == nil else { return }
        guard !state.busy, !refreshing else { return }
        let alert = NSAlert(); alert.messageText = "เชื่อมยอดและเซสชัน"
        alert.informativeText = "นำเข้าข้อมูลโควตาจากบัญชีที่เข้าสู่ระบบไว้ อาจมีคำถามจาก Keychain\nเปิดแท็บ Code ใน Codex/Claude อย่างน้อยหนึ่งครั้งก่อนเชื่อมเซสชัน\nไม่รวมประวัติแชตข้ามผู้ให้บริการ"
        alert.addButton(withTitle: "ยกเลิก").keyEquivalent = "\r"
        alert.addButton(withTitle: "ดำเนินการ").keyEquivalent = ""
        guard alert.runModal() == .alertSecondButtonReturn else { return }
        state.busy = true; updateControls(); status.stringValue = "กำลังเตรียมเซสชัน…"
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let (data, error) = runHelper(["setup"], timeout: 120, mutating: true) {
                DispatchQueue.main.async { self?.status.stringValue = "การเตรียมเซสชันยังทำงานอยู่ — ไม่ได้ตัดคำสั่ง" }
            }
            DispatchQueue.main.async {
                guard let self else { return }
                let setupFailure = error ?? mutationError(data)
                let prefix = setupFailure.map { "เซสชันยังเชื่อมไม่ครบ: \($0)\n\nผลการเชื่อมโควตา: " } ?? ""
                self.mutation(["connect"], timeout: 120, alreadyBusy: true, prefix: prefix)
            }
        }
    }
    @objc func download(_ sender: NSButton) {
        guard let raw = sender.identifier?.rawValue, ["https://chatgpt.com/codex/", "https://claude.com/download"].contains(raw), let url = URL(string: raw) else { return }
        NSWorkspace.shared.open(url)
    }
    @objc func openContext() {
        if contextEditor == nil { contextEditor = ContextEditor() }
        contextEditor?.show()
    }
}
final class FlippedView: NSView { override var isFlipped: Bool { true } }

let app = NSApplication.shared
if CommandLine.arguments.contains("--layout-test") {
    let testWindow = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 480, height: 250), styleMask: [.titled], backing: .buffered, defer: false)
    let account = Account(id: "codex:main", provider: "codex", key: "main", label: "test", email: nil, usageAccount: nil)
    let row = AccountRow(account: account, number: 1, target: NSObject(), action: NSSelectorFromString("unused"))
    row.translatesAutoresizingMaskIntoConstraints = false
    let content = testWindow.contentView!; content.addSubview(row)
    NSLayoutConstraint.activate([row.leadingAnchor.constraint(equalTo: content.leadingAnchor), row.trailingAnchor.constraint(equalTo: content.trailingAnchor), row.topAnchor.constraint(equalTo: content.topAnchor)])
    let now = Date()
    for primary in [WindowQuota(used: 40, reset: now.addingTimeInterval(3600)), nil, WindowQuota(used: 20, reset: now.addingTimeInterval(3600)), nil] {
        row.render(QuotaViewData(weekly: WindowQuota(used: 30, reset: now.addingTimeInterval(7200)), primary: primary, updatedDate: now))
        content.layoutSubtreeIfNeeded()
        for bar in primary == nil ? [row.weeklyBar] : [row.primaryBar, row.weeklyBar] {
            let frame = row.convert(bar.bounds, from: bar)
            assert(frame.minX >= 0 && frame.maxX <= row.bounds.width + 0.5, "quota progress must stay inside account card: \(frame), row \(row.bounds)")
        }
    }
    print("PASS: progress frame containment with primary present/absent transitions")
    exit(0)
}
let delegate = AppDelegate()
app.setActivationPolicy(.regular)
app.delegate = delegate
app.run()
