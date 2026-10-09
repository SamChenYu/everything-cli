import AppKit
import Foundation

// Watches the system clipboard and shows a notification banner whenever its
// changeCount ticks up — i.e. whenever a copy actually lands. changeCount
// increments on every successful write, even re-copying identical text, so
// silence after cmd+C means the keystroke was dropped.

let pb = NSPasteboard.general
var last = pb.changeCount

// Escape a string for embedding inside an AppleScript double-quoted literal.
func escapeForAppleScript(_ s: String) -> String {
    var out = s.replacingOccurrences(of: "\\", with: "\\\\")
    out = out.replacingOccurrences(of: "\"", with: "\\\"")
    return out
}

func preview(_ raw: String?) -> String {
    guard let raw = raw else { return "Copied (non-text)" }
    // Collapse whitespace/newlines to a single line.
    let oneLine = raw
        .replacingOccurrences(of: "\n", with: " ")
        .replacingOccurrences(of: "\r", with: " ")
        .replacingOccurrences(of: "\t", with: " ")
        .trimmingCharacters(in: .whitespaces)
    if oneLine.isEmpty { return "Copied (non-text)" }
    let maxLen = 60
    if oneLine.count > maxLen {
        return String(oneLine.prefix(maxLen)) + "…"
    }
    return oneLine
}

func notify(_ body: String) {
    let safe = escapeForAppleScript(body)
    let script = "display notification \"\(safe)\" with title \"Copied ✓\""
    let task = Process()
    task.launchPath = "/usr/bin/osascript"
    task.arguments = ["-e", script]
    do {
        try task.run()
    } catch {
        FileHandle.standardError.write("osascript failed: \(error)\n".data(using: .utf8)!)
    }
}

while true {
    let current = pb.changeCount
    if current != last {
        last = current
        notify(preview(pb.string(forType: .string)))
    }
    usleep(200_000) // 200ms
}
