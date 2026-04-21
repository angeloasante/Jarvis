//
//  SettingsView.swift
//  Friday
//

import SwiftUI

struct SettingsView: View {
    @AppStorage("fridayRepoPath") private var fridayRepoPath: String =
        "/Users/\(NSUserName())/Desktop/JARVIS"

    var body: some View {
        TabView {
            // General tab
            Form {
                Section("FRIDAY Installation") {
                    HStack {
                        TextField("Repo path", text: $fridayRepoPath)
                        Button("Choose…") {
                            chooseFolder()
                        }
                    }
                    Text("Path to your cloned JARVIS repo. FRIDAY runs via `uv run` from here.")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }
            .padding(20)
            .frame(width: 500, height: 200)
            .tabItem {
                Label("General", systemImage: "gear")
            }

            // Profile tab — writes to ~/.friday/user.json
            ProfileSettingsView()
                .tabItem {
                    Label("Profile", systemImage: "person.crop.circle")
                }

            // Accounts tab (placeholder)
            Form {
                Section("Connected Accounts") {
                    HStack {
                        Image(systemName: "envelope.fill")
                        Text("Google (Gmail + Calendar)")
                        Spacer()
                        Button("Connect") {}
                    }
                    HStack {
                        Image(systemName: "message.fill")
                        Text("WhatsApp")
                        Spacer()
                        Button("Connect") {}
                    }
                    HStack {
                        Image(systemName: "phone.fill")
                        Text("Twilio (SMS)")
                        Spacer()
                        Button("Connect") {}
                    }
                }
            }
            .padding(20)
            .frame(width: 500, height: 300)
            .tabItem {
                Label("Accounts", systemImage: "person.circle")
            }
        }
    }

    private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            fridayRepoPath = url.path
        }
    }
}


// MARK: - Profile tab

/// Personalises FRIDAY's prompts. Values are read by Python at
/// `~/.friday/user.json` — see `friday/core/user_config.py`.
struct ProfileSettingsView: View {
    @StateObject private var model = UserProfile()
    @State private var savedAt: Date? = nil

    var body: some View {
        Form {
            Section("Identity") {
                TextField("Name", text: $model.name)
                    .help("How FRIDAY addresses you in prompts.")
                TextField("Bio (one line)", text: $model.bio)
                    .help("e.g. 'ML engineer, Lagos' — injected into FRIDAY's personality.")
                TextField("Location", text: $model.location)
                TextField("Country code (ISO, 2 letters)", text: $model.countryCode)
                    .help("Used for web-search region bias. e.g. GB, US, NG.")
            }

            Section("Contact") {
                TextField("Email", text: $model.email)
                TextField("Phone (E.164, e.g. +447555834656)", text: $model.phone)
                TextField("GitHub username", text: $model.github)
                TextField("Website", text: $model.website)
            }

            Section("Voice") {
                TextField("Tone note", text: $model.tone)
                    .help("Free-form. e.g. 'direct, dry humour'.")
            }

            Section("Advanced (JSON)") {
                Text("Slang vocabulary, contact aliases, and briefing watchlist live in the raw file. Click Open to edit.")
                    .font(.caption)
                    .foregroundColor(.secondary)
                HStack {
                    Button("Open ~/.friday/user.json") { model.revealInFinder() }
                    Button("Reload") { model.load() }
                }
            }

            HStack {
                Button("Save") { model.save(); savedAt = Date() }
                    .keyboardShortcut("s", modifiers: .command)
                    .buttonStyle(.borderedProminent)
                if let savedAt {
                    Text("Saved at \(savedAt.formatted(date: .omitted, time: .standard))")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                Spacer()
            }
        }
        .padding(20)
        .frame(width: 520, height: 480)
        .onAppear { model.load() }
    }
}


// MARK: - Backing model (reads / writes ~/.friday/user.json)

@MainActor
final class UserProfile: ObservableObject {
    @Published var name = ""
    @Published var bio = ""
    @Published var location = ""
    @Published var countryCode = "US"
    @Published var email = ""
    @Published var phone = ""
    @Published var github = ""
    @Published var website = ""
    @Published var tone = ""

    /// Advanced fields round-trip verbatim so hand-edits in the JSON survive.
    private var slang: [String: String] = [:]
    private var contactAliases: [String: String] = [:]
    private var briefingWatchlist: [[String: String]] = []

    private var fileURL: URL {
        // ~/Friday/user.json — visible in Finder, matches the Python loader
        // at friday/core/user_config.py.
        let home = FileManager.default.homeDirectoryForCurrentUser
        return home.appendingPathComponent("Friday/user.json")
    }

    func load() {
        let url = fileURL
        guard let data = try? Data(contentsOf: url),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        name         = json["name"]         as? String ?? ""
        bio          = json["bio"]          as? String ?? ""
        location     = json["location"]     as? String ?? ""
        countryCode  = json["country_code"] as? String ?? "US"
        email        = json["email"]        as? String ?? ""
        phone        = json["phone"]        as? String ?? ""
        github       = json["github"]       as? String ?? ""
        website      = json["website"]      as? String ?? ""
        tone         = json["tone"]         as? String ?? ""

        slang              = json["slang"]              as? [String: String]    ?? [:]
        contactAliases     = json["contact_aliases"]    as? [String: String]    ?? [:]
        briefingWatchlist  = json["briefing_watchlist"] as? [[String: String]]  ?? []
    }

    func save() {
        let url = fileURL
        let dir = url.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        let payload: [String: Any] = [
            "name": name,
            "bio": bio,
            "location": location,
            "country_code": countryCode,
            "email": email,
            "phone": phone,
            "github": github,
            "website": website,
            "tone": tone,
            "slang": slang,
            "contact_aliases": contactAliases,
            "briefing_watchlist": briefingWatchlist,
        ]
        guard let data = try? JSONSerialization.data(
            withJSONObject: payload,
            options: [.prettyPrinted, .sortedKeys]
        ) else { return }

        try? data.write(to: url, options: .atomic)
        // Restrict to user — holds phone/email.
        try? FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: url.path
        )
    }

    func revealInFinder() {
        if !FileManager.default.fileExists(atPath: fileURL.path) {
            save()  // create it so Finder has something to reveal
        }
        NSWorkspace.shared.activateFileViewerSelecting([fileURL])
    }
}


#Preview {
    SettingsView()
}
