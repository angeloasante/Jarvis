//
//  FridayClient.swift
//  Friday
//
//  Bridges the SwiftUI app to FridayCore (Python) via a streaming subprocess.
//  Python emits NDJSON events (one per line) which we read off stdout as they
//  arrive — chat updates token-by-token instead of waiting for the whole reply.
//

import Foundation

// Single event from Python's NDJSON stream.
enum FridayEvent {
    case chunk(String)
    case media(String)
    case status(String)
    case error(String)
    case done

    static func parse(_ line: String) -> FridayEvent? {
        guard let data = line.data(using: .utf8),
              let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let event = dict["event"] as? String else { return nil }
        switch event {
        case "chunk":  return .chunk(dict["text"] as? String ?? "")
        case "media":  return .media(dict["path"] as? String ?? "")
        case "status": return .status(dict["text"] as? String ?? "")
        case "error":  return .error(dict["text"] as? String ?? "unknown")
        case "done":   return .done
        default:       return nil
        }
    }
}

// Final aggregated result (back-compat for callers that don't want streaming).
struct FridayResponse {
    let text: String
    let media: [String]
}

@MainActor
final class FridayClient {
    static let shared = FridayClient()

    private var fridayRepoPath: String {
        UserDefaults.standard.string(forKey: "fridayRepoPath")
            ?? "/Users/\(NSUserName())/Desktop/JARVIS"
    }

    // MARK: - Streaming send

    /// Stream a command to FRIDAY. `onEvent` is called on the MainActor as
    /// each NDJSON event arrives. Returns when the `done` event fires (or the
    /// process exits, whichever comes first).
    func sendStreaming(_ input: String, onEvent: @escaping (FridayEvent) -> Void) async {
        let userEnv = OnboardingState.shared.subprocessEnvironment()
        let repoPath = fridayRepoPath
        await Task.detached(priority: .userInitiated) {
            self.runStreaming(input, userEnv: userEnv, repoPath: repoPath, onEvent: onEvent)
        }.value
    }

    /// Aggregating helper — collects all chunks into a single FridayResponse.
    func send(_ input: String) async -> FridayResponse {
        var text = ""
        var media: [String] = []
        await sendStreaming(input) { event in
            switch event {
            case .chunk(let s): text += s
            case .media(let p): if !media.contains(p) { media.append(p) }
            default: break
            }
        }
        return FridayResponse(text: text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                ? "(no response)"
                                : text,
                              media: media)
    }

    // MARK: - Subprocess + line-by-line stdout reader

    private nonisolated func runStreaming(
        _ input: String,
        userEnv: [String: String],
        repoPath: String,
        onEvent: @escaping (FridayEvent) -> Void
    ) {
        let process = Process()

        let bundledPython = Bundle.main.resourceURL?
            .appendingPathComponent("python/bin/python3")
            .path ?? ""

        var env = ProcessInfo.processInfo.environment
        for (k, v) in userEnv { env[k] = v }
        env["FRIDAY_ENV_FILE"] = (env["HOME"] ?? NSHomeDirectory()) + "/.friday/.env"
        env["PYTHONUNBUFFERED"] = "1"  // ensure Python flushes stdout immediately

        if FileManager.default.isExecutableFile(atPath: bundledPython) {
            process.executableURL = URL(fileURLWithPath: bundledPython)
            process.arguments = ["-u", "-m", "friday.core.oneshot_runner", input]
            process.environment = env
        } else {
            process.executableURL = URL(fileURLWithPath: "/bin/zsh")
            process.currentDirectoryURL = URL(fileURLWithPath: repoPath)
            process.arguments = [
                "-lc",
                "uv run python -u -m friday.core.oneshot_runner \(shellEscape(input))"
            ]
            process.environment = env
        }

        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        do {
            try process.run()
        } catch {
            DispatchQueue.main.async {
                onEvent(.error("subprocess failed to start: \(error.localizedDescription)"))
                onEvent(.done)
            }
            return
        }

        // Read stdout line-by-line. As each NDJSON line arrives, parse it and
        // dispatch the event onto the main actor.
        let handle = stdoutPipe.fileHandleForReading
        var buffer = Data()
        var sawDone = false

        while true {
            let chunk = handle.availableData
            if chunk.isEmpty { break }  // EOF
            buffer.append(chunk)

            while let nlIdx = buffer.firstIndex(of: 0x0A) {
                let lineData = buffer.subdata(in: 0..<nlIdx)
                buffer.removeSubrange(0...nlIdx)
                guard let line = String(data: lineData, encoding: .utf8),
                      !line.trimmingCharacters(in: .whitespaces).isEmpty else { continue }

                if let event = FridayEvent.parse(line) {
                    if case .done = event { sawDone = true }
                    DispatchQueue.main.async { onEvent(event) }
                }
            }
        }

        process.waitUntilExit()
        if !sawDone {
            DispatchQueue.main.async { onEvent(.done) }
        }
    }

    private nonisolated func shellEscape(_ s: String) -> String {
        "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}
