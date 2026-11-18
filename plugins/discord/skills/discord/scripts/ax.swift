// Drives the Discord desktop app through the macOS Accessibility API: reads which server and
// channel are open, lists the servers and the open server's channels, and opens a channel or a
// server — all without bringing Discord to the front. Scrolling is not here: Discord ignores
// synthetic key and wheel events while it is in the background, so `discord.py sync` scrolls with
// System Events while Discord is frontmost.
//
// Usage: ax state | ax open-channel <channel_id> | ax open-server <name> | ax focus-messages
// Output: one JSON object on stdout. Exit 1 with a message on stderr when Discord or its window is
// missing, 2 when the target is not found.
import AppKit
import ApplicationServices

func fail(_ message: String, _ code: Int32 = 1) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(code)
}

func attr(_ e: AXUIElement, _ a: String) -> AnyObject? {
    var v: AnyObject?
    return AXUIElementCopyAttributeValue(e, a as CFString, &v) == .success ? v : nil
}
func str(_ e: AXUIElement, _ a: String) -> String { (attr(e, a) as? String) ?? "" }
func role(_ e: AXUIElement) -> String { str(e, "AXRole") }
func label(_ e: AXUIElement) -> String {
    [str(e, "AXTitle"), str(e, "AXDescription"), str(e, "AXValue")].first { !$0.isEmpty } ?? ""
}
func children(_ e: AXUIElement) -> [AXUIElement] { (attr(e, "AXChildren") as? [AXUIElement]) ?? [] }
func actions(_ e: AXUIElement) -> [String] {
    var names: CFArray?
    AXUIElementCopyActionNames(e, &names)
    return (names as? [String]) ?? []
}
func walk(_ e: AXUIElement, _ visit: (AXUIElement) -> Bool) {
    if !visit(e) { return }
    for c in children(e) { walk(c, visit) }
}
func find(_ e: AXUIElement, _ pred: (AXUIElement) -> Bool) -> AXUIElement? {
    var hit: AXUIElement?
    walk(e) { el in
        if hit != nil { return false }
        if pred(el) { hit = el; return false }
        return true
    }
    return hit
}

guard AXIsProcessTrusted() else {
    fail("No Accessibility permission: System Settings → Privacy & Security → Accessibility → allow the app running this shell (terminal, Paseo, Claude).")
}
let bundleIds = ["com.hnc.Discord", "com.hnc.DiscordPTB", "com.hnc.DiscordCanary"]
guard let app = bundleIds.lazy.compactMap({ NSRunningApplication.runningApplications(withBundleIdentifier: $0).first }).first else {
    fail("Discord is not running.")
}
let appEl = AXUIElementCreateApplication(app.processIdentifier)
// Electron builds its accessibility tree only for assistive tech; this flag asks for it. The tree
// fills in asynchronously, so the first read after enabling it may come back thin.
AXUIElementSetAttributeValue(appEl, "AXManualAccessibility" as CFString, kCFBooleanTrue)

func mainWindow() -> AXUIElement {
    // AXWindows comes back empty for Discord; AXMainWindow works.
    for _ in 0..<10 {
        if let w = attr(appEl, "AXMainWindow") {
            let win = w as! AXUIElement
            if find(win, { role($0) == "AXWebArea" }) != nil { return win }
        }
        Thread.sleep(forTimeInterval: 0.3)
    }
    fail("Discord has no open window (it is in the tray). Ask the user to open it.")
}

let channelURL = try! NSRegularExpression(pattern: #"discord\.com/channels/(\d+|@me)/(\d+)"#)
func ids(_ url: String) -> (String, String)? {
    guard let m = channelURL.firstMatch(in: url, range: NSRange(url.startIndex..., in: url)) else { return nil }
    return (String(url[Range(m.range(at: 1), in: url)!]), String(url[Range(m.range(at: 2), in: url)!]))
}
func url(_ e: AXUIElement) -> String { (attr(e, "AXURL") as? URL)?.absoluteString ?? "" }

// A channel link's label is "[status, ]name (kind)[, more]", e.g. "nie przeczytano, social (kanał
// tekstowy)", "unread, social (text channel)" or "kurs2 (kanał tekstowy), Kanał prywatny
// (zablokowany)", in the UI language. Channel names have no spaces, so the first "word (…)" is it.
let linkLabel = try! NSRegularExpression(pattern: #"(?:^|, )([^,\s]+) \(([^)]+)\)"#)

func state(_ win: AXUIElement) -> [String: Any] {
    var out: [String: Any] = ["title": str(win, "AXTitle")]
    if let web = find(win, { role($0) == "AXWebArea" }), let (g, c) = ids(url(web)) {
        out["guild_id"] = g
        out["channel_id"] = c
    }
    var channels: [[String: Any]] = []
    var seen = Set<String>()
    var servers: [[String: Any]] = []
    walk(win) { el in
        let r = role(el)
        if r == "AXLink", let (g, c) = ids(url(el)), !seen.contains(c) {
            seen.insert(c)
            let text = label(el)
            var ch: [String: Any] = ["guild_id": g, "channel_id": c, "label": text]
            if let m = linkLabel.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) {
                ch["name"] = String(text[Range(m.range(at: 1), in: text)!])
                ch["kind"] = String(text[Range(m.range(at: 2), in: text)!])
                let before = String(text[..<Range(m.range, in: text)!.lowerBound])
                if !before.isEmpty { ch["status"] = before }
            }
            channels.append(ch)
            return false
        }
        // The server sidebar group ("Serwery" / "Servers"): each server is a subtree whose deepest
        // static text is its name and whose other text carries unread/mention status.
        if r == "AXGroup", ["Serwery", "Servers"].contains(label(el)) {
            walk(el) { item in
                if role(item) == "AXStaticText" {
                    let t = label(item)
                    if t.contains(", ") {
                        let parts = t.components(separatedBy: ", ")
                        servers.append(["name": parts.dropFirst().joined(separator: ", "), "status": parts[0]])
                    } else if !t.isEmpty, Int(t) == nil, !servers.contains(where: { ($0["name"] as? String) == t }) {
                        servers.append(["name": t])
                    }
                }
                return true
            }
            return false
        }
        return true
    }
    out["channels"] = channels
    out["servers"] = servers
    return out
}

func press(_ el: AXUIElement) -> Bool {
    var cur: AXUIElement? = el
    while let e = cur {
        if actions(e).contains("AXPress") { return AXUIElementPerformAction(e, "AXPress" as CFString) == .success }
        cur = attr(e, "AXParent").map { $0 as! AXUIElement }
    }
    return false
}

func emit(_ obj: Any) {
    let data = try! JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
}

let args = Array(CommandLine.arguments.dropFirst())
let win = mainWindow()
switch args.first {
case "state":
    emit(state(win))
case "open-channel":
    guard args.count == 2 else { fail("usage: ax open-channel <channel_id>", 2) }
    guard let link = find(win, { role($0) == "AXLink" && ids(url($0))?.1 == args[1] }) else {
        fail("Channel \(args[1]) is not in the open server's sidebar (another server, or a collapsed category).", 2)
    }
    _ = press(link)
    Thread.sleep(forTimeInterval: 1.0)
    emit(state(mainWindow()))
case "open-server":
    guard args.count >= 2 else { fail("usage: ax open-server <name>", 2) }
    let name = args.dropFirst().joined(separator: " ").lowercased()
    guard let group = find(win, { role($0) == "AXGroup" && ["Serwery", "Servers"].contains(label($0)) }),
          let text = find(group, { role($0) == "AXStaticText" && label($0).lowercased() == name })
            ?? find(group, { role($0) == "AXStaticText" && label($0).lowercased().contains(name) })
    else { fail("No server named \"\(name)\" in the sidebar (inside a collapsed folder?).", 2) }
    _ = press(text)
    Thread.sleep(forTimeInterval: 1.5)
    emit(state(mainWindow()))
case "focus-messages":
    // Page Up scrolls whatever has keyboard focus; after AXPress on a channel link that is the
    // sidebar. The message list is labelled "Wiadomości w <channel>" / "Messages in <channel>".
    guard let list = find(win, { el in role(el) == "AXList" && ["Wiadomości w ", "Messages in "].contains { label(el).hasPrefix($0) } }) else {
        fail("No message list in the open channel.", 2)
    }
    let ok = AXUIElementSetAttributeValue(list, "AXFocused" as CFString, kCFBooleanTrue) == .success
    emit(["focused": ok])
default:
    fail("usage: ax state | ax open-channel <channel_id> | ax open-server <name> | ax focus-messages", 2)
}
