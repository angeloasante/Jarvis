//
//  SettingsView.swift
//  Friday
//

import SwiftUI

struct SettingsView: View {
    @AppStorage("fridayRepoPath") private var fridayRepoPath: String =
        "/Users/\(NSUserName())/Desktop/JARVIS"
    @EnvironmentObject var state: OnboardingState

    var body: some View {
        TabView {
            generalTab
                .tabItem { Label("General", systemImage: "gear") }

            allowedAppsTab
                .tabItem { Label("Allowed Apps", systemImage: "app.badge.checkmark") }

            accountsTab
                .tabItem { Label("Accounts", systemImage: "person.circle") }
        }
    }

    // MARK: - General

    private var generalTab: some View {
        Form {
            Section("FRIDAY Installation") {
                HStack {
                    TextField("Repo path", text: $fridayRepoPath)
                    Button("Choose…") { chooseFolder() }
                }
                Text("Path to your cloned JARVIS repo. FRIDAY runs via `uv run` from here in dev, or from the bundled Python in the app.")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .padding(20)
        .frame(width: 540, height: 200)
    }

    // MARK: - Allowed Apps

    @State private var newAppName: String = ""

    private var allowedAppsTab: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Apps FRIDAY is allowed to open")
                .font(.system(size: 14, weight: .semibold, design: .rounded))
            Text("When you say \"open X\", FRIDAY only launches apps on this list. Add what's on your Mac; remove anything you don't want opened via voice/chat.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)

            HStack(spacing: 8) {
                TextField("App name (e.g. 'Linear', 'Obsidian')", text: $newAppName)
                    .textFieldStyle(.roundedBorder)
                Button("Add") { addApp() }
                    .disabled(newAppName.trimmingCharacters(in: .whitespaces).isEmpty)
                Button("Reset to defaults") {
                    state.allowedApps = OnboardingState.defaultAllowedApps
                }
            }

            List {
                ForEach(state.allowedApps.sorted(), id: \.self) { app in
                    HStack {
                        Image(systemName: "app.fill")
                            .foregroundStyle(.secondary)
                        Text(app)
                        Spacer()
                        Button {
                            state.allowedApps.removeAll { $0 == app }
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .frame(minHeight: 280)

            Text("\(state.allowedApps.count) app\(state.allowedApps.count == 1 ? "" : "s") allowed")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(20)
        .frame(width: 540, height: 460)
    }

    private func addApp() {
        let name = newAppName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        if !state.allowedApps.contains(where: { $0.caseInsensitiveCompare(name) == .orderedSame }) {
            state.allowedApps.append(name)
        }
        newAppName = ""
    }

    // MARK: - Accounts

    private var accountsTab: some View {
        Form {
            Section("Connected Accounts") {
                HStack {
                    Image(systemName: "envelope.fill")
                    Text("Google (Gmail + Calendar)")
                    Spacer()
                    Text(state.gmailConnected ? "Connected" : "Not connected")
                        .foregroundStyle(state.gmailConnected ? .green : .secondary)
                        .font(.caption)
                }
                HStack {
                    Image(systemName: "message.fill")
                    Text("WhatsApp")
                    Spacer()
                    Text(state.whatsappConnected ? "Connected" : "Not connected")
                        .foregroundStyle(state.whatsappConnected ? .green : .secondary)
                        .font(.caption)
                }
                HStack {
                    Image(systemName: "phone.fill")
                    Text("Twilio (SMS)")
                    Spacer()
                    Text(state.twilioConnected ? "Connected" : "Not connected")
                        .foregroundStyle(state.twilioConnected ? .green : .secondary)
                        .font(.caption)
                }
            }
            Text("Manage connections from the main window → Integrations.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(20)
        .frame(width: 540, height: 260)
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

#Preview {
    SettingsView().environmentObject(OnboardingState.shared)
}
