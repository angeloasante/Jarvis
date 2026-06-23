//
//  IntegrationSheet.swift
//  Friday
//
//  Side-docked configuration panel. All form fields persist to
//  OnboardingState (Keychain + UserDefaults). The header toggle reflects
//  real connection state and can flip it.
//

import SwiftUI
import AppKit

struct IntegrationSheet: View {
    @EnvironmentObject var state: OnboardingState
    let integration: Integration
    let onDismiss: () -> Void

    // Local buffers for fields that get committed on Save (so typing doesn't
    // constantly write to Keychain mid-keystroke).
    @State private var twilioSidDraft: String = ""
    @State private var twilioAuthTokenDraft: String = ""
    @State private var twilioNumberDraft: String = ""
    @State private var xBearerDraft: String = ""
    @State private var tavilyKeyDraft: String = ""
    @State private var llmKeyDraft: String = ""
    @State private var tvHostDraft: String = ""
    @State private var lastSavedAt: Date?

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().opacity(0.12)

            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    bodyContent(for: integration.id)
                    recentActivity
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
        .frame(width: 360)
        .frame(maxHeight: .infinity)
        .background(Color(red: 0.08, green: 0.08, blue: 0.10))
        .overlay(alignment: .leading) {
            Divider().opacity(0.12)
        }
        .onAppear { loadDrafts() }
        .onChange(of: integration.id) { _, _ in loadDrafts() }
    }

    // MARK: - Header

    private var header: some View {
        HStack(spacing: 12) {
            BrandIcon(brand: brandForIntegration(integration.id), size: 34)
            VStack(alignment: .leading, spacing: 1) {
                Text("\(integration.name) Configuration")
                    .font(.system(size: 13, weight: .semibold, design: .rounded))
                    .kerning(-0.2)
                Text(integration.description)
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            Toggle("", isOn: activeBinding)
                .toggleStyle(.switch)
                .controlSize(.small)
                .labelsHidden()
            Button { onDismiss() } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 22, height: 22)
                    .background(Circle().fill(Color.white.opacity(0.06)))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }

    // MARK: - Toggle binding — real connection state

    private var activeBinding: Binding<Bool> {
        Binding(
            get: { isActive },
            set: { newValue in setActive(newValue) }
        )
    }

    private var isActive: Bool {
        switch integration.id {
        case "gmail": return state.gmailConnected
        case "whatsapp": return state.whatsappConnected
        case "sms": return state.twilioConnected
        case "tv": return state.tvPaired
        case "x": return state.xConnected
        case "tavily": return state.tavilyConnected
        case "openrouter": return state.llmProvider == .openrouter && !state.llmApiKey.isEmpty
        case "groq": return state.llmProvider == .groq && !state.llmApiKey.isEmpty
        case "ollama": return state.llmProvider == .local
        case "imessage": return state.iMessageAccessGranted
        case "calendar": return state.calendarAccessGranted
        case "contacts": return state.contactsAccessGranted
        default: return false
        }
    }

    private func setActive(_ value: Bool) {
        switch integration.id {
        case "gmail":
            if !value { state.gmailConnected = false; state.gmailEmail = "" }
        case "whatsapp":
            if !value { state.whatsappConnected = false }
        case "sms":
            state.twilioConnected = value && !state.twilioSid.isEmpty && !state.twilioAuthToken.isEmpty
        case "tv":
            if !value { state.tvPaired = false }
        case "x":
            if !value { state.xBearerToken = "" }
        case "tavily":
            if !value { state.tavilyApiKey = "" }
        case "openrouter":
            if value { state.llmProvider = .openrouter }
        case "groq":
            if value { state.llmProvider = .groq }
        case "ollama":
            if value { state.llmProvider = .local }
        default: break
        }
    }

    // MARK: - Per-integration body

    @ViewBuilder
    private func bodyContent(for id: String) -> some View {
        switch id {
        case "gmail": gmailBody
        case "whatsapp": whatsappBody
        case "sms": twilioBody
        case "openrouter": llmBody(provider: .openrouter)
        case "groq": llmBody(provider: .groq)
        case "ollama": llmBody(provider: .local)
        case "tv": tvBody
        case "x": xBody
        case "tavily": tavilyBody
        case "imessage": iMessageBody
        case "calendar": calendarBody
        case "contacts": contactsBody
        default: genericBody
        }
    }

    // MARK: - Gmail

    private var gmailBody: some View {
        VStack(alignment: .leading, spacing: 20) {
            sectionHeading("Account")
            if state.gmailConnected {
                infoRow("Signed in as", state.gmailEmail.isEmpty ? "Connected" : state.gmailEmail)
                actionButton("Disconnect Gmail", tint: .red) {
                    state.gmailConnected = false
                    state.gmailEmail = ""
                }
            } else {
                actionButton("Sign in with Google", filled: true) {
                    Task {
                        if let profile = await GmailAuth.connect() {
                            state.gmailEmail = profile.email
                            state.gmailName = profile.name
                            state.gmailConnected = true
                        }
                    }
                }
            }

            sectionHeading("Scopes")
            scopeRow("Read inbox and threads", checked: true)
            scopeRow("Search emails with Gmail query syntax", checked: true)
            scopeRow("Draft and send emails (requires confirm)", checked: true)
            scopeRow("Label and archive", checked: true)
        }
    }

    // MARK: - WhatsApp

    private var whatsappBody: some View {
        VStack(alignment: .leading, spacing: 20) {
            sectionHeading("Connection")
            infoRow("Bridge", "localhost:3100 (Baileys)")
            infoRow("Status", state.whatsappConnected ? "Connected" : "Not linked")

            if !state.whatsappConnected {
                Text("Open the WhatsApp step in Onboarding to scan the QR, or restart the bridge.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            } else {
                actionButton("Logout device", tint: .red) {
                    state.whatsappConnected = false
                }
            }

            sectionHeading("Permissions")
            scopeRow("Read chats and messages", checked: true)
            scopeRow("Send messages", checked: true)
            scopeRow("Search across conversations", checked: true)
        }
    }

    // MARK: - Twilio / SMS

    private var twilioBody: some View {
        VStack(alignment: .leading, spacing: 20) {
            sectionHeading("Twilio credentials")
            fieldLabel("Account SID")
            textField($twilioSidDraft, placeholder: "ACxxxxxxxxxxxxxxxxxxxxx", mono: true)
            fieldLabel("Auth Token")
            secureField($twilioAuthTokenDraft, placeholder: "••••••••••••••••")
            fieldLabel("Phone number")
            textField($twilioNumberDraft, placeholder: "+447367000489", mono: true)

            saveRow(
                enabled: !twilioSidDraft.isEmpty && !twilioAuthTokenDraft.isEmpty,
                title: state.twilioConnected ? "Update credentials" : "Save"
            ) {
                state.twilioSid = twilioSidDraft
                state.twilioAuthToken = twilioAuthTokenDraft
                state.twilioNumber = twilioNumberDraft
                state.twilioConnected = !twilioSidDraft.isEmpty && !twilioAuthTokenDraft.isEmpty
                markSaved()
            }

            sectionHeading("Webhook")
            Text("FRIDAY auto-configures a public URL via ngrok and points your Twilio number's inbound webhook at it.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - LLM providers

    private func llmBody(provider: LLMProvider) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            sectionHeading("Provider")
            infoRow("Name", provider.displayName)
            infoRow("Default model", defaultModel(for: provider))

            if provider.needsKey {
                sectionHeading("API key")
                fieldLabel(provider.keyName)
                secureField($llmKeyDraft, placeholder: "sk-…")
                if let url = provider.keyURL {
                    Link("Get a key →", destination: url)
                        .font(.system(size: 11))
                        .foregroundStyle(.blue)
                }

                saveRow(
                    enabled: !llmKeyDraft.isEmpty,
                    title: isCurrentLLM(provider) ? "Update key" : "Save & activate"
                ) {
                    state.llmProvider = provider
                    state.llmApiKey = llmKeyDraft
                    markSaved()
                }
            } else {
                Text("Ollama runs locally — make sure `ollama serve` is running on your Mac.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)

                actionButton(
                    state.llmProvider == provider ? "Active" : "Switch to \(provider.displayName)",
                    filled: state.llmProvider != provider
                ) {
                    state.llmProvider = provider
                }
            }

            sectionHeading("What this powers")
            scopeRow("Intent classification", checked: true)
            scopeRow("Tool dispatch", checked: true)
            scopeRow("Agent reasoning (research, comms, etc.)", checked: true)
        }
    }

    private func isCurrentLLM(_ provider: LLMProvider) -> Bool {
        state.llmProvider == provider && !state.llmApiKey.isEmpty
    }

    private func defaultModel(for provider: LLMProvider) -> String {
        switch provider {
        case .openrouter: return "google/gemma-4-31b-it"
        case .groq: return "qwen/qwen3-32b"
        case .googleai: return "gemma-4-31b-it"
        case .local: return "qwen3.5:9b"
        }
    }

    // MARK: - TV

    private var tvBody: some View {
        VStack(alignment: .leading, spacing: 20) {
            sectionHeading("LG WebOS pairing")
            fieldLabel("TV IP address (optional — autodiscovered if empty)")
            textField($tvHostDraft, placeholder: "192.168.1.42", mono: true)

            saveRow(enabled: true, title: state.tvPaired ? "Re-pair TV" : "Pair TV") {
                state.tvHost = tvHostDraft
                state.tvPaired = true
                markSaved()
            }

            if state.tvPaired {
                actionButton("Unpair", tint: .red) {
                    state.tvPaired = false
                    state.tvHost = ""
                    tvHostDraft = ""
                }
            }

            Text("Pairing uses LG's WebOS handshake. The client key is stored in the Keychain; the first pair prompts on your TV.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - X

    private var xBody: some View {
        VStack(alignment: .leading, spacing: 20) {
            sectionHeading("X API credentials")
            fieldLabel("Bearer token")
            secureField($xBearerDraft, placeholder: "AAAAAAAAAAA…")

            saveRow(enabled: !xBearerDraft.isEmpty, title: state.xConnected ? "Update token" : "Save") {
                state.xBearerToken = xBearerDraft
                markSaved()
            }

            if state.xConnected {
                actionButton("Disconnect", tint: .red) {
                    state.xBearerToken = ""
                    xBearerDraft = ""
                }
            }

            Link("Get a bearer token →", destination: URL(string: "https://developer.x.com/en/portal/dashboard")!)
                .font(.system(size: 11))
                .foregroundStyle(.blue)
        }
    }

    // MARK: - Tavily

    private var tavilyBody: some View {
        VStack(alignment: .leading, spacing: 20) {
            sectionHeading("Tavily API")
            fieldLabel("API key")
            secureField($tavilyKeyDraft, placeholder: "tvly-…")

            saveRow(enabled: !tavilyKeyDraft.isEmpty, title: state.tavilyConnected ? "Update key" : "Save") {
                state.tavilyApiKey = tavilyKeyDraft
                markSaved()
            }

            if state.tavilyConnected {
                actionButton("Disconnect", tint: .red) {
                    state.tavilyApiKey = ""
                    tavilyKeyDraft = ""
                }
            }

            Link("Get a key →", destination: URL(string: "https://tavily.com/")!)
                .font(.system(size: 11))
                .foregroundStyle(.blue)
        }
    }

    // MARK: - iMessage / Calendar / Contacts

    private var iMessageBody: some View {
        VStack(alignment: .leading, spacing: 20) {
            sectionHeading("Full Disk Access")
            if state.iMessageAccessGranted {
                infoRow("Access", "Granted")
                Text("FRIDAY can read ~/Library/Messages/chat.db.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            } else {
                Text("Reading iMessage requires Full Disk Access. Grant it in System Settings → Privacy & Security.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                actionButton("Open System Settings", filled: true) {
                    state.openFullDiskAccessSettings()
                }
            }
        }
    }

    private var calendarBody: some View {
        VStack(alignment: .leading, spacing: 20) {
            sectionHeading("Calendar access")
            infoRow("Status", state.calendarAccessGranted ? "Granted" : "Not granted")

            if !state.calendarAccessGranted {
                actionButton("Request access", filled: true) {
                    Task { _ = await state.requestCalendarAccess() }
                }
            }
            actionButton("Open Calendar") {
                NSWorkspace.shared.open(URL(string: "calshow:")!)
            }
        }
    }

    private var contactsBody: some View {
        VStack(alignment: .leading, spacing: 20) {
            sectionHeading("Contacts access")
            infoRow("Status", state.contactsAccessGranted ? "Granted" : "Not granted")

            if !state.contactsAccessGranted {
                actionButton("Request access", filled: true) {
                    Task { _ = await state.requestContactsAccess() }
                }
            }
            actionButton("Open Contacts") {
                NSWorkspace.shared.open(URL(fileURLWithPath: "/System/Applications/Contacts.app"))
            }
        }
    }

    // MARK: - Generic fallback

    private var genericBody: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(integration.description)
                .font(.system(size: 12))
            if let quick = integration.quickAction {
                actionButton(integration.actionLabel, filled: true, action: quick)
            }
        }
    }

    // MARK: - Recent activity placeholder

    private var recentActivity: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionHeading("Recent activity")
            HStack(spacing: 10) {
                Image(systemName: "clock")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                Text("Nothing yet. Activity shows here once FRIDAY uses this integration.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                Spacer()
            }
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color.white.opacity(0.03))
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.08), lineWidth: 0.5))
            )
        }
    }

    // MARK: - Drafts ↔ state

    private func loadDrafts() {
        twilioSidDraft = state.twilioSid
        twilioAuthTokenDraft = state.twilioAuthToken
        twilioNumberDraft = state.twilioNumber
        xBearerDraft = state.xBearerToken
        tavilyKeyDraft = state.tavilyApiKey
        tvHostDraft = state.tvHost
        // LLM key: only prefill if the current provider matches this sheet
        if let p = providerForSheet, state.llmProvider == p {
            llmKeyDraft = state.llmApiKey
        } else {
            llmKeyDraft = ""
        }
    }

    private var providerForSheet: LLMProvider? {
        switch integration.id {
        case "openrouter": return .openrouter
        case "groq": return .groq
        case "ollama": return .local
        default: return nil
        }
    }

    private func markSaved() {
        lastSavedAt = Date()
    }

    // MARK: - UI helpers

    private func saveRow(enabled: Bool, title: String, action: @escaping () -> Void) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            actionButton(title, filled: enabled, enabled: enabled, action: action)
            if let t = lastSavedAt {
                Text("Saved \(relativeSavedTime(t)) — keys stored in Keychain.")
                    .font(.system(size: 10))
                    .foregroundStyle(.green.opacity(0.8))
            }
        }
    }

    private func relativeSavedTime(_ t: Date) -> String {
        let s = Int(Date().timeIntervalSince(t))
        if s < 3 { return "just now" }
        if s < 60 { return "\(s)s ago" }
        if s < 3600 { return "\(s / 60)m ago" }
        return "\(s / 3600)h ago"
    }

    private func sectionHeading(_ text: String) -> some View {
        Text(text.uppercased())
            .font(.system(size: 10, weight: .semibold, design: .rounded))
            .foregroundStyle(.secondary.opacity(0.9))
            .tracking(0.6)
    }

    private func fieldLabel(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(.secondary)
    }

    private func infoRow(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(.primary)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .padding(.vertical, 4)
    }

    private func scopeRow(_ text: String, checked: Bool) -> some View {
        HStack(spacing: 8) {
            Image(systemName: checked ? "checkmark.square.fill" : "square")
                .font(.system(size: 12))
                .foregroundStyle(checked ? .green : .secondary)
            Text(text)
                .font(.system(size: 12))
                .foregroundStyle(.primary)
            Spacer()
        }
    }

    private func textField(_ value: Binding<String>, placeholder: String, mono: Bool = false) -> some View {
        TextField(placeholder, text: value)
            .textFieldStyle(.plain)
            .font(.system(size: 12, design: mono ? .monospaced : .default))
            .padding(8)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(Color.white.opacity(0.05))
                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.white.opacity(0.1), lineWidth: 0.5))
            )
    }

    private func secureField(_ value: Binding<String>, placeholder: String) -> some View {
        SecureField(placeholder, text: value)
            .textFieldStyle(.plain)
            .font(.system(size: 12, design: .monospaced))
            .padding(8)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(Color.white.opacity(0.05))
                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.white.opacity(0.1), lineWidth: 0.5))
            )
    }

    private func actionButton(_ title: String,
                               filled: Bool = false,
                               enabled: Bool = true,
                               tint: Color = .white,
                               action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 12, weight: .semibold, design: .rounded))
                .foregroundStyle(filled ? AnyShapeStyle(.black) : AnyShapeStyle(tint))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 9)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(filled ? tint : Color.white.opacity(0.06))
                        .overlay(
                            RoundedRectangle(cornerRadius: 8).stroke(
                                filled ? Color.clear : tint.opacity(0.25),
                                lineWidth: 0.5
                            )
                        )
                )
                .opacity(enabled ? 1 : 0.4)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}
