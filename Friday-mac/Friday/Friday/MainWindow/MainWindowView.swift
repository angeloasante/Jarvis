//
//  MainWindowView.swift
//  Friday
//
//  Chat-first layout. Sidebar has two modes:
//   - .chats    → FRIDAY header, "+ New chat", list of chats, profile + settings gear
//   - .settings → Back-to-chats, Home / Integrations / Allowed Apps / Accounts
//  Tapping the gear swaps the sidebar into settings mode. Back arrow returns.
//

import SwiftUI

struct MainWindowView: View {
    @EnvironmentObject var state: OnboardingState
    @StateObject private var store = ChatStore.shared

    enum SidebarMode { case chats, settings }
    enum SettingsTab: String, CaseIterable, Identifiable {
        case home = "Home"
        case integrations = "Integrations"
        case allowedApps = "Allowed Apps"
        case accounts = "Accounts"
        var id: String { rawValue }
        var icon: String {
            switch self {
            case .home: "house.fill"
            case .integrations: "link"
            case .allowedApps: "app.badge.checkmark"
            case .accounts: "person.circle.fill"
            }
        }
    }

    @State private var sidebarMode: SidebarMode = .chats
    @State private var settingsTab: SettingsTab = .home

    var body: some View {
        Group {
            if !state.hasCompletedOnboarding {
                OnboardingView()
            } else {
                NavigationSplitView {
                    sidebar
                } detail: {
                    detail
                }
                .navigationSplitViewStyle(.balanced)
                .environmentObject(store)
                .toolbar(removing: .sidebarToggle)
                .toolbarBackground(.hidden, for: .windowToolbar)
            }
        }
    }

    // MARK: - Sidebar

    @ViewBuilder
    private var sidebar: some View {
        switch sidebarMode {
        case .chats: chatsSidebar
        case .settings: settingsSidebar
        }
    }

    private var chatsSidebar: some View {
        VStack(spacing: 0) {
            // Plain-text brand header
            HStack {
                Text("FRIDAY")
                    .font(.system(size: 13, weight: .bold, design: .rounded))
                    .tracking(1.2)
                    .foregroundStyle(.secondary)
                Spacer()
            }
            .padding(.horizontal, 14)
            .padding(.top, 40)  // clear the window's floating traffic lights
            .padding(.bottom, 10)

            // New chat
            Button {
                store.newChat()
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "square.and.pencil")
                        .font(.system(size: 12, weight: .semibold))
                    Text("New chat")
                        .font(.system(size: 13, weight: .medium, design: .rounded))
                    Spacer()
                    Text("⌘N")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color.white.opacity(0.05))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.1), lineWidth: 0.5))
                )
            }
            .buttonStyle(.plain)
            .keyboardShortcut("n", modifiers: .command)
            .padding(.horizontal, 10)
            .padding(.bottom, 4)

            // Settings row (right under New chat)
            Button {
                withAnimation(.easeInOut(duration: 0.18)) {
                    sidebarMode = .settings
                }
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "gearshape.fill")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .frame(width: 16)
                    Text("Settings")
                        .font(.system(size: 12, weight: .medium, design: .rounded))
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 7)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 10)
            .padding(.bottom, 8)

            // Chats list
            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(store.chats) { chat in
                        ChatRow(
                            chat: chat,
                            isActive: chat.id == store.activeChatID,
                            onOpen: { store.activeChatID = chat.id },
                            onDelete: { store.deleteChat(id: chat.id) }
                        )
                    }
                }
                .padding(.horizontal, 8)
            }
            .scrollIndicators(.hidden)

            Spacer(minLength: 0)

            Divider().opacity(0.12)

            // Profile footer — uses real signed-in info from onboarding
            profileFooter
        }
        .frame(minWidth: 220)
    }

    // MARK: - Profile footer (signed-in user)

    private var isSignedIn: Bool { state.gmailConnected || !state.gmailEmail.isEmpty }

    private var signedInName: String {
        if !state.gmailName.isEmpty { return state.gmailName }
        if !state.gmailEmail.isEmpty {
            // Pretty-print the local-part of the email as a fallback.
            return String(state.gmailEmail.split(separator: "@").first ?? "")
                .replacingOccurrences(of: ".", with: " ")
                .capitalized
        }
        return ""
    }

    @ViewBuilder
    private var profileFooter: some View {
        if isSignedIn {
            HStack(spacing: 10) {
                ZStack {
                    Circle().fill(Color.white.opacity(0.08)).frame(width: 28, height: 28)
                    Image(systemName: "person.fill")
                        .font(.system(size: 13))
                        .foregroundStyle(.secondary)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(signedInName)
                        .font(.system(size: 12, weight: .semibold))
                        .lineLimit(1)
                    Text(state.gmailEmail)
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                Spacer()
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
        } else {
            // Not signed in — tappable CTA that jumps into the sign-in flow.
            Button {
                withAnimation(.easeInOut(duration: 0.18)) {
                    sidebarMode = .settings
                    settingsTab = .accounts
                }
                // If onboarding wasn't completed, flip the flag back so the
                // dedicated onboarding flow reopens.
                if state.gmailEmail.isEmpty && !state.gmailConnected {
                    // Trigger Gmail OAuth directly from here.
                    Task {
                        if let profile = await GmailAuth.connect() {
                            await MainActor.run {
                                state.gmailEmail = profile.email
                                state.gmailName = profile.name
                                state.gmailConnected = true
                            }
                        }
                    }
                }
            } label: {
                HStack(spacing: 10) {
                    ZStack {
                        Circle().fill(Color.white.opacity(0.1)).frame(width: 28, height: 28)
                        Image(systemName: "person.crop.circle.badge.plus")
                            .font(.system(size: 14))
                            .foregroundStyle(.white.opacity(0.8))
                    }
                    VStack(alignment: .leading, spacing: 1) {
                        Text("Sign in")
                            .font(.system(size: 12, weight: .semibold, design: .rounded))
                        Text("Connect Gmail to personalise FRIDAY")
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .background(Color.white.opacity(0.04))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
    }

    private var settingsSidebar: some View {
        VStack(spacing: 0) {
            // Plain-text brand header (matches chats mode)
            HStack {
                Text("FRIDAY")
                    .font(.system(size: 13, weight: .bold, design: .rounded))
                    .tracking(1.2)
                    .foregroundStyle(.secondary)
                Spacer()
            }
            .padding(.horizontal, 14)
            .padding(.top, 40)  // clear the window's floating traffic lights
            .padding(.bottom, 10)

            // Back to chats
            Button {
                withAnimation(.easeInOut(duration: 0.18)) {
                    sidebarMode = .chats
                }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 11, weight: .semibold))
                    Text("Back to chats")
                        .font(.system(size: 12, weight: .medium, design: .rounded))
                    Spacer()
                }
                .foregroundStyle(.secondary)
                .padding(.horizontal, 12)
                .padding(.vertical, 7)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 10)
            .padding(.bottom, 8)

            Divider().opacity(0.12)

            // Settings sections
            VStack(spacing: 2) {
                ForEach(SettingsTab.allCases) { tab in
                    SettingsNavRow(
                        title: tab.rawValue,
                        icon: tab.icon,
                        isActive: settingsTab == tab
                    ) {
                        settingsTab = tab
                    }
                }
            }
            .padding(.horizontal, 8)
            .padding(.top, 8)

            Spacer()
        }
        .frame(minWidth: 220)
    }

    // MARK: - Detail

    @ViewBuilder
    private var detail: some View {
        switch sidebarMode {
        case .chats:
            if let id = store.activeChatID {
                ChatView(chatID: id)
                    .environmentObject(store)
                    .id(id)  // rebuild when switching chats
            } else {
                Color(red: 0.06, green: 0.06, blue: 0.08)
            }
        case .settings:
            switch settingsTab {
            case .home: HomeView()
            case .integrations: IntegrationsView()
            case .allowedApps: AllowedAppsPane()
            case .accounts: AccountsPane()
            }
        }
    }
}

// MARK: - Chat row

private struct ChatRow: View {
    let chat: Chat
    let isActive: Bool
    let onOpen: () -> Void
    let onDelete: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: onOpen) {
            HStack(spacing: 8) {
                Image(systemName: "bubble.left")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                Text(chat.title)
                    .font(.system(size: 12))
                    .foregroundStyle(isActive ? .primary : .secondary)
                    .lineLimit(1)
                Spacer()
                if hovering {
                    Button(action: onDelete) {
                        Image(systemName: "xmark")
                            .font(.system(size: 9))
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(isActive ? Color.white.opacity(0.08) : (hovering ? Color.white.opacity(0.04) : .clear))
            )
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
    }
}

// MARK: - Settings nav row

private struct SettingsNavRow: View {
    let title: String
    let icon: String
    let isActive: Bool
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: icon)
                    .font(.system(size: 12))
                    .foregroundStyle(isActive ? .primary : .secondary)
                    .frame(width: 16)
                Text(title)
                    .font(.system(size: 12, weight: .medium, design: .rounded))
                    .foregroundStyle(isActive ? .primary : .secondary)
                Spacer()
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(isActive ? Color.white.opacity(0.08) : (hovering ? Color.white.opacity(0.04) : .clear))
            )
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
    }
}

// MARK: - Allowed Apps pane (split out from the old Settings tab)

struct AllowedAppsPane: View {
    @EnvironmentObject var state: OnboardingState
    @State private var newAppName: String = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Allowed Apps")
                        .font(.system(size: 22, weight: .bold, design: .rounded))
                        .kerning(-0.3)
                    Text("When you say \"open X\", FRIDAY only launches apps on this list. Add anything you keep on your Mac; remove what you don't want triggered by voice or chat.")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: 640, alignment: .leading)
                }

                HStack(spacing: 8) {
                    TextField("App name (e.g. Obsidian, Raycast, Linear)", text: $newAppName)
                        .textFieldStyle(.roundedBorder)
                        .frame(maxWidth: 420)
                    Button("Add") { addApp() }
                        .disabled(newAppName.trimmingCharacters(in: .whitespaces).isEmpty)
                    Button("Reset to defaults") {
                        state.allowedApps = OnboardingState.defaultAllowedApps
                    }
                }

                LazyVGrid(columns: [GridItem(.adaptive(minimum: 200), spacing: 8)], alignment: .leading, spacing: 8) {
                    ForEach(state.allowedApps.sorted(), id: \.self) { app in
                        HStack(spacing: 8) {
                            Image(systemName: "app.fill").foregroundStyle(.secondary)
                            Text(app).font(.system(size: 12))
                            Spacer()
                            Button {
                                state.allowedApps.removeAll { $0 == app }
                            } label: {
                                Image(systemName: "xmark.circle.fill")
                                    .foregroundStyle(.secondary)
                            }
                            .buttonStyle(.plain)
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 7)
                        .background(
                            RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.04))
                                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.08), lineWidth: 0.5))
                        )
                    }
                }

                Text("\(state.allowedApps.count) app\(state.allowedApps.count == 1 ? "" : "s") allowed")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(30)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(red: 0.06, green: 0.06, blue: 0.08))
    }

    private func addApp() {
        let name = newAppName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        if !state.allowedApps.contains(where: { $0.caseInsensitiveCompare(name) == .orderedSame }) {
            state.allowedApps.append(name)
        }
        newAppName = ""
    }
}

// MARK: - Accounts pane

struct AccountsPane: View {
    @EnvironmentObject var state: OnboardingState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Accounts")
                        .font(.system(size: 22, weight: .bold, design: .rounded))
                        .kerning(-0.3)
                    Text("Connected services. Manage each from the Integrations page.")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }

                VStack(spacing: 10) {
                    accountRow(icon: "envelope.fill", tint: .red, name: "Gmail",
                               connected: state.gmailConnected, detail: state.gmailEmail)
                    accountRow(icon: "message.fill", tint: .green, name: "WhatsApp",
                               connected: state.whatsappConnected, detail: "Local Baileys bridge")
                    accountRow(icon: "phone.fill", tint: .blue, name: "SMS (Twilio)",
                               connected: state.twilioConnected, detail: state.twilioNumber)
                    accountRow(icon: "sparkles", tint: .orange, name: "AI Provider",
                               connected: !state.llmApiKey.isEmpty || state.llmProvider == .local,
                               detail: state.llmProvider.displayName)
                }
            }
            .padding(30)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(red: 0.06, green: 0.06, blue: 0.08))
    }

    private func accountRow(icon: String, tint: Color, name: String,
                             connected: Bool, detail: String) -> some View {
        HStack(spacing: 12) {
            ZStack {
                Circle().fill(tint.opacity(0.15)).frame(width: 34, height: 34)
                Image(systemName: icon).foregroundStyle(tint)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(name).font(.system(size: 13, weight: .semibold, design: .rounded))
                Text(detail.isEmpty ? (connected ? "Connected" : "Not connected") : detail)
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            Circle().fill(connected ? Color.green : Color.white.opacity(0.2)).frame(width: 8, height: 8)
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(0.04))
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.white.opacity(0.08), lineWidth: 0.5))
        )
    }
}
