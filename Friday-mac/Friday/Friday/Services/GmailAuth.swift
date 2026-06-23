//
//  GmailAuth.swift
//  Friday
//
//  Drives FRIDAY's Gmail OAuth flow via the bundled Python backend.
//  Python opens the browser, waits for Google consent, writes a token
//  to ~/.friday/google_token.json, and returns the authenticated email + name.
//

import Foundation

struct GmailProfile {
    let email: String
    let name: String
}

enum GmailAuth {
    /// Kicks off the OAuth flow. Returns {email, name}, or nil on failure.
    static func connect() async -> GmailProfile? {
        await Task.detached(priority: .userInitiated) {
            runPython()
        }.value
    }

    private nonisolated static func runPython() -> GmailProfile? {
        let process = Process()

        let bundledPython = Bundle.main.resourceURL?
            .appendingPathComponent("python/bin/python3")
            .path ?? ""

        if FileManager.default.isExecutableFile(atPath: bundledPython) {
            process.executableURL = URL(fileURLWithPath: bundledPython)
            process.arguments = ["-m", "friday.tools.google_auth"]
        } else {
            // Dev fallback
            let repoPath = UserDefaults.standard.string(forKey: "fridayRepoPath")
                ?? "/Users/\(NSUserName())/Desktop/JARVIS"
            process.executableURL = URL(fileURLWithPath: "/bin/zsh")
            process.currentDirectoryURL = URL(fileURLWithPath: repoPath)
            process.arguments = ["-lc", "uv run python -m friday.tools.google_auth"]
        }

        let outPipe = Pipe(); let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe

        do {
            try process.run()
            process.waitUntilExit()
            let outData = outPipe.fileHandleForReading.readDataToEndOfFile()
            let out = String(data: outData, encoding: .utf8) ?? ""
            // Expect a line like: "AUTHENTICATED: user@example.com|Full Name"
            for line in out.split(separator: "\n") {
                if line.hasPrefix("AUTHENTICATED:") {
                    let payload = String(line.dropFirst("AUTHENTICATED:".count))
                        .trimmingCharacters(in: .whitespaces)
                    let parts = payload.split(separator: "|", maxSplits: 1).map(String.init)
                    let email = parts.first ?? payload
                    let name = parts.count > 1 ? parts[1] : ""
                    return GmailProfile(email: email, name: name)
                }
            }
            return process.terminationStatus == 0 ? GmailProfile(email: "", name: "") : nil
        } catch {
            return nil
        }
    }
}
