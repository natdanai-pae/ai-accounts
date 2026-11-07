import AppKit
import UniformTypeIdentifiers

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
    var result = week.0
    if let primary {
        guard let short = score(primary) else { return Recommendation(score: nil, hours: week.1, reason: "ไม่นำมาจัดอันดับ: รอบหลักหมด ขาดข้อมูล หรือเลยเวลารีเซ็ต") }
        result = min(result, short.0)
    }
    return Recommendation(score: result, hours: week.1, reason: String(format: "%.2f %%/ชม. · รีเซ็ตสัปดาห์ใน %.1f ชม.", result, week.1))
}
func recommendationWinner(_ accounts: [Account], values: [String: Recommendation], provider: String) -> String? {
    accounts.filter { $0.provider == provider && values[$0.id]?.score != nil }.sorted {
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
    assert(recommend(weekly: week, primary: nil, updated: now, now: now).score == 25)
    assert(recommend(weekly: week, primary: WindowQuota(used: 90, reset: now.addingTimeInterval(7200)), updated: now, now: now).score == 5)
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
                         updatedDate: dateValue(usage["updatedAt"] as? String))
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

final class AccountRow: NSView {
    let percentage = label("—", size: 29, bold: true)
    let weeklyCaption = label("เหลือในสัปดาห์", size: 12, color: .secondaryLabelColor)
    let balance = label("กำลังอ่านโควตา…")
    let times = label("", size: 11, color: .secondaryLabelColor)
    let ranking = label("ยังไม่มีคำแนะนำ", size: 11, color: .secondaryLabelColor)
    let progress = NSProgressIndicator()
    let switchButton: NSButton
    let detailsButton = NSButton(title: "รายละเอียด", target: nil, action: nil)
    var details = "กำลังอ่านโควตา…"
    var accent: NSColor = .systemTeal
    init(account: Account, target: AnyObject, action: Selector) {
        switchButton = NSButton(title: "ใช้บัญชีนี้", target: target, action: action)
        super.init(frame: .zero)
        let provider = account.provider == "codex" ? "Codex" : "Claude"
        switchButton.identifier = NSUserInterfaceItemIdentifier(account.id); switchButton.bezelStyle = .rounded
        switchButton.setAccessibilityLabel("สลับไป \(provider) \(account.label) \(account.email ?? "")")
        let identity = NSStackView(views: [label(account.label, size: 14, bold: true), label(account.email ?? "ยังไม่เชื่อมตัวตนโควตา", size: 12, color: .secondaryLabelColor)])
        identity.orientation = .vertical; identity.alignment = .leading; identity.spacing = 2
        let top = NSStackView(views: [identity, NSView(), switchButton]); top.distribution = .fill
        let metric = NSStackView(views: [percentage, weeklyCaption, NSView(), detailsButton])
        metric.alignment = .lastBaseline; metric.spacing = 8
        accent = account.provider == "codex" ? .systemTeal : .systemOrange
        percentage.setContentCompressionResistancePriority(.required, for: .horizontal)
        detailsButton.bezelStyle = .inline; detailsButton.controlSize = .small
        detailsButton.target = self; detailsButton.action = #selector(showDetails)
        detailsButton.setAccessibilityLabel("รายละเอียดโควตา \(provider) \(account.label)")
        progress.style = .bar; progress.isIndeterminate = false; progress.minValue = 0; progress.maxValue = 100
        progress.controlSize = .small
        let stack = NSStackView(views: [top, metric, progress, balance, times, ranking])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 7
        stack.translatesAutoresizingMaskIntoConstraints = false; addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: leadingAnchor), stack.trailingAnchor.constraint(equalTo: trailingAnchor), stack.topAnchor.constraint(equalTo: topAnchor, constant: 9), stack.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -9), top.widthAnchor.constraint(equalTo: stack.widthAnchor), metric.widthAnchor.constraint(equalTo: stack.widthAnchor), progress.widthAnchor.constraint(equalTo: stack.widthAnchor), balance.widthAnchor.constraint(equalTo: stack.widthAnchor), times.widthAnchor.constraint(equalTo: stack.widthAnchor), ranking.widthAnchor.constraint(equalTo: stack.widthAnchor)])
        render(QuotaViewData(error: "กำลังอ่านโควตา…"))
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    func render(_ value: QuotaViewData) {
        let low = value.percent.map { $0 <= 10 } ?? false
        percentage.textColor = low ? .systemRed : accent
        weeklyCaption.stringValue = low ? "เหลือน้อยในสัปดาห์" : "เหลือในสัปดาห์"
        percentage.stringValue = value.percent.map { String(format: "%.0f%%", $0) } ?? "—"
        percentage.setAccessibilityLabel(value.percent.map { "โควตาสัปดาห์เหลือ \(Int($0)) เปอร์เซ็นต์" } ?? "โควตาสัปดาห์ไม่ทราบ")
        progress.isHidden = value.percent == nil
        progress.doubleValue = value.percent ?? 0
        progress.setAccessibilityLabel("โควตาสัปดาห์ที่เหลือ")
        balance.stringValue = value.error ?? "ยอดคงเหลือ \(value.balance)  ·  สิทธิ์รีเซ็ต \(value.resets)"
        times.stringValue = value.error == nil ? "รีเซ็ต \(value.resetTime)  ·  อัปเดต \(value.updated)" : "เวลาแสดงตามประเทศไทย"
        details = value.error ?? value.details
        ranking.stringValue = "ยังไม่มีคำแนะนำ"
        toolTip = details; detailsButton.toolTip = details
    }
    func rank(_ recommendation: Recommendation, selected: Bool) {
        ranking.stringValue = (selected ? "แนะนำ · " : "") + recommendation.reason
        ranking.textColor = selected ? .systemTeal : .secondaryLabelColor
        ranking.font = selected ? .boldSystemFont(ofSize: 11) : .systemFont(ofSize: 11)
        details += "\n\n" + ranking.stringValue + "\nคำนวณจากเปอร์เซ็นต์ที่เหลือต่อชั่วโมงถึงรีเซ็ต ใช้รอบที่จำกัดกว่า ไม่ใช่จำนวนโทเคนหรือความคุ้มค่าของราคา เปรียบเทียบภายในบริการเท่านั้น ข้อมูลต้องไม่เกิน 15 นาที"
        toolTip = details
    }
    @objc func showDetails() {
        let alert = NSAlert(); alert.messageText = "รายละเอียดโควตา"
        alert.informativeText = details; alert.addButton(withTitle: "ปิด")
        if let window { alert.beginSheetModal(for: window) }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var rows: [String: AccountRow] = [:]
    var accounts: [Account] = []
    var dependencies = Dependencies(codexApp: false, claudeApp: false)
    var columns: [NSStackView] = []
    var addButtons: [NSButton] = []
    var quotaValues: [String: QuotaViewData] = [:]
    let status = label("กำลังค้นหาบัญชี…", size: 12, color: .secondaryLabelColor)
    let dependencyNotice = label("", size: 12, color: .secondaryLabelColor)
    let refreshButton = NSButton(title: "รีเฟรช", target: nil, action: nil)
    let connectButton = NSButton(title: "เชื่อมยอดและเซสชัน", target: nil, action: nil)
    let state = SwitchState()
    var refreshing = false
    var contextEditor: ContextEditor?
    var recommendationTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1120, height: 850), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "AI Accounts · Beta"
        window.minSize = NSSize(width: 1040, height: 650)
        window.isReleasedWhenClosed = false
        let icon = NSImageView()
        if let url = Bundle.main.url(forResource: "AppIcon", withExtension: "png") { icon.image = NSImage(contentsOf: url) }
        icon.imageScaling = .scaleProportionallyUpOrDown
        icon.widthAnchor.constraint(equalToConstant: 48).isActive = true
        icon.heightAnchor.constraint(equalToConstant: 48).isActive = true
        let heading = NSStackView(views: [label("AI Accounts", size: 25, bold: true), label("บัญชีของคุณ · โควตา · บริบทกลาง", color: .secondaryLabelColor)])
        heading.orientation = .vertical; heading.alignment = .leading; heading.spacing = 4
        refreshButton.target = self; refreshButton.action = #selector(refresh)
        refreshButton.bezelStyle = .rounded; refreshButton.bezelColor = .systemTeal
        connectButton.target = self; connectButton.action = #selector(connect)
        connectButton.bezelStyle = .rounded
        let context = NSButton(title: "บริบทกลาง", target: self, action: #selector(openContext))
        context.bezelStyle = .rounded
        let header = NSStackView(views: [icon, heading, NSView(), context, connectButton, refreshButton]); header.spacing = 12
        let downloads = NSStackView()
        for (name, url) in [("ดาวน์โหลด Codex", "https://chatgpt.com/codex/"), ("ดาวน์โหลด Claude", "https://claude.com/download")] {
            let button = NSButton(title: name, target: self, action: #selector(download(_:)))
            button.identifier = NSUserInterfaceItemIdentifier(url); button.bezelStyle = .inline
            downloads.addArrangedSubview(button)
        }
        downloads.addArrangedSubview(dependencyNotice)
        let guidance = label("แนะนำแยกบริการ: % ที่เหลือต่อชั่วโมงถึงรีเซ็ต โดยใช้รอบที่จำกัดกว่า · ไม่ใช่จำนวนโทเคนหรือการเทียบราคา · ข้อมูลใหม่ภายใน 15 นาที", size: 11, color: .secondaryLabelColor)
        let providerColumns = NSStackView(); providerColumns.orientation = .horizontal; providerColumns.alignment = .top; providerColumns.distribution = .fillEqually; providerColumns.spacing = 30
        for provider in ["codex", "claude"] {
            let column = NSStackView(); column.orientation = .vertical; column.alignment = .leading; column.spacing = 0
            columns.append(column); providerColumns.addArrangedSubview(column)
            let add = NSButton(title: "เพิ่มบัญชี", target: self, action: #selector(addAccount(_:)))
            add.identifier = NSUserInterfaceItemIdentifier(provider); add.bezelStyle = .rounded; addButtons.append(add)
            let title = NSStackView(views: [label(provider == "codex" ? "Codex" : "Claude", size: 20, bold: true), NSView(), add])
            column.addArrangedSubview(title); title.widthAnchor.constraint(equalTo: column.widthAnchor).isActive = true
        }
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.drawsBackground = false; scroll.autohidesScrollers = true
        let document = FlippedView(); document.translatesAutoresizingMaskIntoConstraints = false
        providerColumns.translatesAutoresizingMaskIntoConstraints = false; document.addSubview(providerColumns); scroll.documentView = document
        NSLayoutConstraint.activate([document.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor), providerColumns.leadingAnchor.constraint(equalTo: document.leadingAnchor), providerColumns.trailingAnchor.constraint(equalTo: document.trailingAnchor, constant: -4), providerColumns.topAnchor.constraint(equalTo: document.topAnchor, constant: 8), providerColumns.bottomAnchor.constraint(equalTo: document.bottomAnchor)])
        let footer = label("การสลับอาจปิดแอป · เซสชันใช้ร่วมกันภายในบริการตามการตั้งค่า · บริบทกลางคือข้อความส่งต่องาน ไม่ใช่ประวัติแชตร่วม\nสิทธิ์รีเซ็ตดูได้เท่านั้น · เวลาไทย · Beta ยังไม่ได้ notarize", size: 11, color: .secondaryLabelColor)
        let content = window.contentView!
        for view in [header, downloads, guidance, scroll, footer, status] { view.translatesAutoresizingMaskIntoConstraints = false; content.addSubview(view) }
        for view in [header, downloads, guidance, scroll, footer, status] {
            view.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 25).isActive = true
            view.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -25).isActive = true
        }
        NSLayoutConstraint.activate([
            header.topAnchor.constraint(equalTo: content.topAnchor, constant: 18), header.heightAnchor.constraint(equalToConstant: 56),
            downloads.topAnchor.constraint(equalTo: header.bottomAnchor, constant: 12),
            guidance.topAnchor.constraint(equalTo: downloads.bottomAnchor, constant: 10),
            scroll.topAnchor.constraint(equalTo: guidance.bottomAnchor, constant: 16), scroll.bottomAnchor.constraint(equalTo: footer.topAnchor, constant: -14),
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
        recommendationTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in self?.updateRecommendations() }
        refresh()
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { !state.busy }
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
        let busy = state.busy || refreshing
        refreshButton.isEnabled = !busy; connectButton.isEnabled = !busy
        for (id, row) in rows {
            let provider = accounts.first { $0.id == id }?.provider
            row.switchButton.isEnabled = !busy && (provider == "codex" ? dependencies.codexApp : dependencies.claudeApp)
        }
        for button in addButtons { button.isEnabled = !busy && (button.identifier?.rawValue == "codex" ? dependencies.codexApp : dependencies.claudeApp) }
    }
    func rebuildRows() {
        rows.removeAll()
        for column in columns { for view in column.arrangedSubviews.dropFirst() { column.removeArrangedSubview(view); view.removeFromSuperview() } }
        for (index, provider) in ["codex", "claude"].enumerated() {
            let matching = accounts.filter { $0.provider == provider }
            if matching.isEmpty {
                let empty = label("ยังไม่มีบัญชี\nเพิ่มบัญชี หรือกดเชื่อมยอดและเซสชันเพื่อเตรียมบัญชีเดิม\nเปิดแท็บ Code ในแอปผู้ให้บริการอย่างน้อยหนึ่งครั้งก่อนเชื่อมเซสชัน", color: .secondaryLabelColor)
                columns[index].addArrangedSubview(empty); empty.widthAnchor.constraint(equalTo: columns[index].widthAnchor).isActive = true
            }
            for account in matching {
                let row = AccountRow(account: account, target: self, action: #selector(switchAccount(_:)))
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
            let winner = recommendationWinner(accounts, values: values, provider: provider)
            for account in accounts where account.provider == provider {
                // Render again so timer updates do not append duplicate detail text.
                if let value = quotaValues[account.id] { rows[account.id]?.render(value) }
                rows[account.id]?.rank(values[account.id]!, selected: winner == account.id)
            }
        }
    }
    @objc func refresh() {
        guard !state.busy, !refreshing else { return }
        refreshing = true; quotaValues.removeAll(); updateControls()
        rows.values.forEach { $0.render(QuotaViewData(error: "กำลังอ่านโควตา…")) }
        status.stringValue = "กำลังค้นหาบัญชีและอ่านโควตา…"
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let (data, error) = runHelper(["list"], timeout: 10)
            guard let data, let list = parseAccounts(data) else {
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.refreshing = false
                    self.rows.values.forEach { $0.render(QuotaViewData(error: "อ่านรายชื่อบัญชีไม่ได้")) }
                    self.status.stringValue = error ?? "รูปแบบบัญชีไม่ถูกต้อง — ไม่ได้เปลี่ยนบัญชีใด"
                    self.updateControls()
                }; return
            }
            DispatchQueue.main.async {
                guard let self else { return }
                self.accounts = list.accounts; self.dependencies = list.dependencies; self.rebuildRows()
            }
            for provider in ["codex", "claude"] where list.accounts.contains(where: { $0.provider == provider }) {
                let (usage, error) = runHelper(["usage", provider], timeout: 30)
                DispatchQueue.main.async {
                    guard let self else { return }
                    for account in list.accounts where account.provider == provider {
                        self.quotaValues[account.id] = usage.map { quotaData($0, account: account) } ?? QuotaViewData(error: error ?? "อ่านโควตาไม่ได้")
                    }
                    self.updateRecommendations()
                }
            }
            DispatchQueue.main.async {
                guard let self else { return }
                self.refreshing = false; self.updateControls()
                self.status.stringValue = "อ่านข้อมูลเสร็จแล้ว · \(list.accounts.count) บัญชี · ดูเวลาและข้อจำกัดในแต่ละแถว"
            }
        }
    }
    func mutation(_ arguments: [String], timeout: TimeInterval, alreadyBusy: Bool = false, prefix: String = "") {
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
    @objc func switchAccount(_ sender: NSButton) {
        guard !state.busy, !refreshing, let id = sender.identifier?.rawValue, let account = accounts.first(where: { $0.id == id }) else { return }
        let alert = NSAlert(); alert.alertStyle = .warning
        alert.messageText = "สลับไป \(account.label)?"
        alert.informativeText = "\(account.provider == "codex" ? "Codex" : "Claude") ที่กำลังทำงานอาจถูกปิด กรุณาบันทึกงานก่อน ประวัติในเครื่องใช้ร่วมกันภายในบริการตามการตั้งค่า"
        alert.addButton(withTitle: "ยกเลิก").keyEquivalent = "\r"
        alert.addButton(withTitle: "สลับบัญชี").keyEquivalent = ""
        guard alert.runModal() == .alertSecondButtonReturn else { status.stringValue = "ยกเลิกแล้ว — ไม่ได้สลับบัญชี"; return }
        _ = state.start(account, confirmed: true) { action in mutation(action.arguments, timeout: 60, alreadyBusy: true) }
    }
    @objc func addAccount(_ sender: NSButton) {
        guard !state.busy, !refreshing, let provider = sender.identifier?.rawValue else { return }
        let alert = NSAlert(); alert.messageText = "เพิ่มบัญชี \(provider == "codex" ? "Codex" : "Claude")"
        alert.informativeText = "ตั้งชื่อที่แยกบัญชีได้ง่าย การเข้าสู่ระบบอย่างเป็นทางการอาจปิดแอปเดิม เมื่อเสร็จให้กดเชื่อมยอดและเซสชัน"
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 350, height: 26)); field.placeholderString = "ชื่อบัญชี"
        alert.accessoryView = field
        alert.addButton(withTitle: "ยกเลิก").keyEquivalent = "\r"
        alert.addButton(withTitle: "เริ่มเข้าสู่ระบบ").keyEquivalent = ""
        guard alert.runModal() == .alertSecondButtonReturn else { return }
        let name = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, name.count <= 120, name.rangeOfCharacter(from: .controlCharacters) == nil else { status.stringValue = "กรุณาระบุชื่อบัญชี 1–120 ตัวอักษร"; return }
        mutation(["add", provider, name], timeout: 300)
    }
    @objc func connect() {
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
let delegate = AppDelegate()
app.setActivationPolicy(.regular)
app.delegate = delegate
app.run()
