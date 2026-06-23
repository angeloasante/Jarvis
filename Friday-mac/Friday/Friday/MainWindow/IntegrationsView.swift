//
//  IntegrationsView.swift
//  Friday
//
//  Grid of integrations with search, category filters, and a side-docked
//  configuration sheet. Status is derived from real app state — no hardcoded
//  "connected" labels.
//

import SwiftUI
import AppKit

// MARK: - Integration model

struct Integration: Identifiable, Hashable {
    enum Category: String, CaseIterable {
        case all = "All"
        case comms = "Comms"
        case home = "Home"
        case ai = "AI"
        case web = "Web"

        static let tabs: [Category] = [.all, .comms, .home, .ai, .web]
    }

    enum Status {
        case connected
        case available
        case setupRequired
    }

    let id: String
    let name: String
    let description: String
    let category: Category
    let status: Status
    let actionLabel: String
    /// Fires when the user clicks the inline action button. Nil ⇒ let the card
    /// open the configuration sheet instead.
    let quickAction: (() -> Void)?

    static func == (lhs: Integration, rhs: Integration) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

// MARK: - Main view

struct IntegrationsView: View {
    @EnvironmentObject var state: OnboardingState
    @State private var search: String = ""
    @State private var activeCategory: Integration.Category = .all
    @State private var sortBy: SortOption = .popularity
    @State private var isGmailConnecting = false
    @State private var selected: Integration?

    enum SortOption: String, CaseIterable {
        case popularity = "Popularity"
        case name = "A–Z"
        case status = "Connected first"
    }

    var body: some View {
        HStack(spacing: 0) {
            mainColumn

            if let sel = selected {
                IntegrationSheet(integration: sel) {
                    withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
                        selected = nil
                    }
                }
                .transition(.move(edge: .trailing).combined(with: .opacity))
            }
        }
        .background(Color(red: 0.06, green: 0.06, blue: 0.08))
    }

    private var mainColumn: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                searchAndFilters
                grid
            }
            .padding(.horizontal, 30)
            .padding(.vertical, 28)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Integrations & Webhooks")
                .font(.system(size: 24, weight: .bold, design: .rounded))
                .kerning(-0.4)
            Text("Connect FRIDAY to the services you already use.")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
        }
    }

    // MARK: Search + filters row

    private var searchAndFilters: some View {
        VStack(spacing: 12) {
            HStack(spacing: 10) {
                searchField
                    .frame(maxWidth: 320)
                Spacer()
                sortMenu
            }

            HStack(spacing: 8) {
                ForEach(Integration.Category.tabs, id: \.self) { cat in
                    CategoryTab(title: cat.rawValue, active: activeCategory == cat) {
                        activeCategory = cat
                    }
                }
                Spacer()
            }
        }
    }

    private var searchField: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(.secondary)
            TextField("Search integrations…", text: $search)
                .textFieldStyle(.plain)
                .font(.system(size: 12))
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.white.opacity(0.04))
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
                )
        )
    }

    private var sortMenu: some View {
        Menu {
            ForEach(SortOption.allCases, id: \.self) { opt in
                Button(opt.rawValue) { sortBy = opt }
            }
        } label: {
            HStack(spacing: 5) {
                Image(systemName: "arrow.up.arrow.down")
                    .font(.system(size: 10))
                Text("Sort by: \(sortBy.rawValue)")
                    .font(.system(size: 11))
            }
            .foregroundStyle(.secondary)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(Capsule().fill(Color.white.opacity(0.04)))
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
    }

    // MARK: Grid

    private var grid: some View {
        let columns = [GridItem(.adaptive(minimum: 220, maximum: 300), spacing: 12)]
        return LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
            ForEach(filtered()) { integration in
                IntegrationCard(
                    integration: integration,
                    isSelected: selected?.id == integration.id
                ) {
                    withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
                        selected = selected?.id == integration.id ? nil : integration
                    }
                }
            }
        }
    }

    // MARK: Data — statuses bound to real state

    private func allIntegrations() -> [Integration] {
        [
            Integration(
                id: "gmail", name: "Gmail",
                description: "Read, search, draft, and send emails.",
                category: .comms,
                status: state.gmailConnected ? .connected : .available,
                actionLabel: state.gmailConnected ? "Connected" : (isGmailConnecting ? "Connecting…" : "Connect"),
                quickAction: state.gmailConnected ? nil as (() -> Void)? : gmailAction
            ),
            Integration(
                id: "whatsapp", name: "WhatsApp",
                description: "Read and send via local Baileys bridge.",
                category: .comms,
                status: state.whatsappConnected ? .connected : .available,
                actionLabel: state.whatsappConnected ? "Connected" : "Connect",
                quickAction: nil
            ),
            Integration(
                id: "imessage", name: "iMessage",
                description: "Read and send texts. Needs Full Disk Access.",
                category: .comms,
                status: state.iMessageAccessGranted ? .connected : .setupRequired,
                actionLabel: state.iMessageAccessGranted ? "Access OK" : "Grant access",
                quickAction: state.iMessageAccessGranted ? nil as (() -> Void)? : { state.openFullDiskAccessSettings() }
            ),
            Integration(
                id: "sms", name: "SMS (Twilio)",
                description: "Text FRIDAY from any phone on any network.",
                category: .comms,
                status: state.twilioConnected ? .connected : .available,
                actionLabel: state.twilioConnected ? "Connected" : "Set up",
                quickAction: nil
            ),
            Integration(
                id: "calendar", name: "Calendar",
                description: "Native macOS Calendar — iCloud + Google synced.",
                category: .comms,
                status: state.calendarAccessGranted ? .connected : .setupRequired,
                actionLabel: state.calendarAccessGranted ? "Open Calendar" : "Grant access",
                quickAction: {
                    if state.calendarAccessGranted {
                        NSWorkspace.shared.open(URL(string: "calshow:")!)
                    } else {
                        Task { _ = await state.requestCalendarAccess() }
                    }
                }
            ),
            Integration(
                id: "contacts", name: "Contacts",
                description: "Fuzzy search + nickname resolution.",
                category: .comms,
                status: state.contactsAccessGranted ? .connected : .setupRequired,
                actionLabel: state.contactsAccessGranted ? "Open Contacts" : "Grant access",
                quickAction: {
                    if state.contactsAccessGranted {
                        NSWorkspace.shared.open(URL(fileURLWithPath: "/System/Applications/Contacts.app"))
                    } else {
                        Task { _ = await state.requestContactsAccess() }
                    }
                }
            ),
            Integration(
                id: "tv", name: "LG TV",
                description: "Control your TV over LAN (WebOS).",
                category: .home,
                status: state.tvPaired ? .connected : .available,
                actionLabel: state.tvPaired ? "Paired" : "Pair TV",
                quickAction: nil
            ),
            Integration(
                id: "x", name: "X (Twitter)",
                description: "Post, search, mentions, like, retweet.",
                category: .web,
                status: state.xConnected ? .connected : .available,
                actionLabel: state.xConnected ? "Connected" : "Add bearer token",
                quickAction: nil
            ),
            Integration(
                id: "tavily", name: "Tavily Search",
                description: "Real-time web search for the research agent.",
                category: .web,
                status: state.tavilyConnected ? .connected : .available,
                actionLabel: state.tavilyConnected ? "Connected" : "Add API key",
                quickAction: nil
            ),
            Integration(
                id: "openrouter", name: "OpenRouter",
                description: "Gemma 4, Claude, GPT-5 and 200+ models.",
                category: .ai,
                status: isLLMActive(.openrouter) ? .connected : .available,
                actionLabel: isLLMActive(.openrouter) ? "Active" : "Configure",
                quickAction: nil
            ),
            Integration(
                id: "groq", name: "Groq",
                description: "Sub-second inference, Qwen3-32B.",
                category: .ai,
                status: isLLMActive(.groq) ? .connected : .available,
                actionLabel: isLLMActive(.groq) ? "Active" : "Configure",
                quickAction: nil
            ),
            Integration(
                id: "ollama", name: "Ollama",
                description: "Run models locally. No cloud, no cost.",
                category: .ai,
                status: state.llmProvider == .local ? .connected : .available,
                actionLabel: state.llmProvider == .local ? "Active" : "Switch",
                quickAction: nil
            ),
        ]
    }

    private func isLLMActive(_ provider: LLMProvider) -> Bool {
        state.llmProvider == provider && !state.llmApiKey.isEmpty
    }

    private func filtered() -> [Integration] {
        let q = search.lowercased().trimmingCharacters(in: .whitespaces)
        var list = allIntegrations().filter { i in
            (activeCategory == .all || i.category == activeCategory)
                && (q.isEmpty || i.name.lowercased().contains(q) || i.description.lowercased().contains(q))
        }
        switch sortBy {
        case .popularity: break
        case .name: list.sort { $0.name.lowercased() < $1.name.lowercased() }
        case .status: list.sort {
            ($0.status == .connected ? 0 : 1) < ($1.status == .connected ? 0 : 1)
        }
        }
        return list
    }

    // MARK: Gmail action

    private func gmailAction() {
        if state.gmailConnected {
            state.gmailConnected = false
            state.gmailEmail = ""
            state.gmailName = ""
            return
        }
        isGmailConnecting = true
        Task {
            let result = await GmailAuth.connect()
            await MainActor.run {
                isGmailConnecting = false
                if let profile = result {
                    state.gmailEmail = profile.email
                    state.gmailName = profile.name
                    state.gmailConnected = true
                }
            }
        }
    }
}

// MARK: - Category tab

private struct CategoryTab: View {
    let title: String
    let active: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 12, weight: .medium, design: .rounded))
                .foregroundStyle(active ? .primary : .secondary)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(
                    Capsule()
                        .fill(active ? Color.white.opacity(0.12) : Color.clear)
                        .overlay(
                            Capsule().stroke(
                                active ? Color.white.opacity(0.2) : Color.clear,
                                lineWidth: 0.5
                            )
                        )
                )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Integration card

private struct IntegrationCard: View {
    let integration: Integration
    let isSelected: Bool
    let onOpen: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: onOpen) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .top) {
                    BrandIcon(brand: brandForIntegration(integration.id), size: 32)
                    Spacer()
                    statusDot
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text(integration.name)
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .kerning(-0.2)
                    Text(integration.description)
                        .font(.system(size: 10.5))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .frame(height: 26, alignment: .top)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Divider().opacity(0.18)

                actionRow
            }
            .padding(12)
            .frame(height: 148)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(cardBackground)
        }
        .buttonStyle(.plain)
        .animation(.easeInOut(duration: 0.12), value: hovering)
        .animation(.easeInOut(duration: 0.15), value: isSelected)
        .onHover { hovering = $0 }
    }

    @ViewBuilder
    private var statusDot: some View {
        switch integration.status {
        case .connected:
            HStack(spacing: 4) {
                Circle().fill(Color.green).frame(width: 5, height: 5)
                Text("Connected")
                    .font(.system(size: 9.5, weight: .medium, design: .rounded))
                    .foregroundStyle(.green.opacity(0.9))
            }
        case .available:
            HStack(spacing: 4) {
                Circle().fill(Color.white.opacity(0.3)).frame(width: 5, height: 5)
                Text("Available")
                    .font(.system(size: 9.5, weight: .medium, design: .rounded))
                    .foregroundStyle(.secondary)
            }
        case .setupRequired:
            HStack(spacing: 4) {
                Circle().fill(Color.orange).frame(width: 5, height: 5)
                Text("Setup needed")
                    .font(.system(size: 9.5, weight: .medium, design: .rounded))
                    .foregroundStyle(.orange)
            }
        }
    }

    private var actionRow: some View {
        Button {
            if let quick = integration.quickAction {
                quick()
            } else {
                onOpen()
            }
        } label: {
            HStack {
                Text(integration.actionLabel)
                    .font(.system(size: 11, weight: .medium, design: .rounded))
                Spacer()
                Image(systemName: integration.status == .connected ? "checkmark" : "chevron.right")
                    .font(.system(size: 9, weight: .semibold))
            }
            .foregroundStyle(integration.status == .connected ? AnyShapeStyle(.secondary) : AnyShapeStyle(.primary))
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(Color.white.opacity(hovering ? 0.08 : 0.05))
            )
        }
        .buttonStyle(.plain)
    }

    private var cardBackground: some View {
        let fillTint = Color.white.opacity(isSelected ? 0.06 : (hovering ? 0.04 : 0.025))
        let strokeTint = Color.white.opacity(isSelected ? 0.22 : (hovering ? 0.15 : 0.08))
        return RoundedRectangle(cornerRadius: 12, style: .continuous)
            .fill(fillTint)
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(strokeTint, lineWidth: 0.5)
            )
            .shadow(color: .black.opacity(hovering ? 0.18 : 0), radius: 8, y: 4)
    }
}
