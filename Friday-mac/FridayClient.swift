//
//  FridayClient.swift
//  Friday
//
//  Bridges the SwiftUI app to FridayCore (Python).
//
//  Current: shells out to `uv run friday --oneshot "command"` or similar.
//  Future: local WebSocket/HTTP to an embedded FridayCore process.
//

import Foundation

@MainActor
final class FridayClient {
    static let shared = FridayClient()

    private var fridayRepoPath: String {
        // Default to the JARVIS repo. Override in Settings.
        UserDefaults.standard.string(forKey: "fridayRepoPath")
            ?? "/Users/\(NSUserName())/Desktop/JARVIS"
    }

    // MARK: - Send a command to FRIDAY

    func send(_ input: String) async -> String {
        // For now: run `uv run friday` with the command piped via stdin.
        // Eventually this becomes a WebSocket/HTTP call to a running FridayCore process.
        await Task.detached(priority: .userInitiated) {
            self.runShellCommand(input)
        }.value
    }

    // MARK: - Shell bridge (temporary — replace with WebSocket client)

    private nonisolated func runShellCommand(_ input: String) -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.currentDirectoryURL = URL(fileURLWithPath: fridayRepoPathStatic)
        process.arguments = ["-lc", "echo \(shellEscape(input)) | uv run python -m friday.core.oneshot_runner 2>&1"]

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe

        do {
            try process.run()
            process.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            return String(data: data, encoding: .utf8) ?? "(no output)"
        } catch {
            return "Error: \(error.localizedDescription)"
        }
    }

    private nonisolated var fridayRepoPathStatic: String {
        UserDefaults.standard.string(forKey: "fridayRepoPath")
            ?? "/Users/\(NSUserName())/Desktop/JARVIS"
    }

    private nonisolated func shellEscape(_ s: String) -> String {
        "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}
