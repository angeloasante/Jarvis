//
//  OnboardingState.swift
//  Friday
//
//  Tracks onboarding progress + connected services.
//  Source of truth for "has the user set up X?" questions.
//

import Foundation
import Combine
import EventKit
import Contacts
import AppKit

@MainActor
final class OnboardingState: ObservableObject {
    static let shared = OnboardingState()

    // MARK: - Completion

    @Published var hasCompletedOnboarding: Bool {
        didSet { defaults.set(hasCompletedOnboarding, forKey: Keys.completed) }
    }

    // MARK: - LLM

    @Published var llmProvider: LLMProvider {
        didSet { defaults.set(llmProvider.rawValue, forKey: Keys.llmProvider) }
    }
    @Published var llmApiKey: String {
        didSet { saveSecret(llmApiKey, key: Keys.llmApiKey) }
    }

    // MARK: - Gmail

    @Published var gmailConnected: Bool {
        didSet { defaults.set(gmailConnected, forKey: Keys.gmailConnected) }
    }
    @Published var gmailEmail: String {
        didSet { defaults.set(gmailEmail, forKey: Keys.gmailEmail) }
    }
    @Published var gmailName: String {
        didSet { defaults.set(gmailName, forKey: Keys.gmailName) }
    }

    // MARK: - WhatsApp

    @Published var whatsappConnected: Bool {
        didSet { defaults.set(whatsappConnected, forKey: Keys.whatsappConnected) }
    }

    // MARK: - Twilio / SMS

    @Published var twilioConnected: Bool {
        didSet { defaults.set(twilioConnected, forKey: Keys.twilioConnected) }
    }
    @Published var twilioNumber: String {
        didSet { defaults.set(twilioNumber, forKey: Keys.twilioNumber) }
    }
    @Published var twilioSid: String {
        didSet { saveSecret(twilioSid, key: Keys.twilioSid) }
    }
    @Published var twilioAuthToken: String {
        didSet { saveSecret(twilioAuthToken, key: Keys.twilioAuthToken) }
    }

    // MARK: - TV (LG WebOS)

    @Published var tvPaired: Bool {
        didSet { defaults.set(tvPaired, forKey: Keys.tvPaired) }
    }
    @Published var tvHost: String {
        didSet { defaults.set(tvHost, forKey: Keys.tvHost) }
    }

    // MARK: - X (Twitter)

    @Published var xBearerToken: String {
        didSet { saveSecret(xBearerToken, key: Keys.xBearerToken) }
    }

    // MARK: - Tavily

    @Published var tavilyApiKey: String {
        didSet { saveSecret(tavilyApiKey, key: Keys.tavilyApiKey) }
    }

    // MARK: - Allowed apps (for open_application safety gate)

    @Published var allowedApps: [String] {
        didSet { defaults.set(allowedApps, forKey: Keys.allowedApps) }
    }

    /// The default list shipped with FRIDAY — mirrors friday/tools/mac_tools.py SAFE_APPS.
    static let defaultAllowedApps: [String] = [
        "Safari", "Google Chrome", "Firefox", "Arc",
        "Finder", "Notes", "Calendar", "Mail", "Reminders", "Messages",
        "Music", "Apple Music", "TV", "Podcasts", "Spotify",
        "FaceTime", "Photos", "QuickTime Player", "Preview", "TextEdit",
        "Calculator", "Terminal", "iTerm", "Xcode",
        "Cursor", "Visual Studio Code",
        "Activity Monitor", "System Settings",
        "Slack", "Discord", "Zoom", "Notion", "Figma",
        "WhatsApp", "Telegram", "Signal",
    ]

    // MARK: - System permissions (iMessage, Calendar, Contacts)

    /// True if the Messages database is readable (requires Full Disk Access).
    var iMessageAccessGranted: Bool {
        let path = NSString(string: "~/Library/Messages/chat.db").expandingTildeInPath
        return FileManager.default.isReadableFile(atPath: path)
    }

    /// EventKit calendar authorization.
    var calendarAccessGranted: Bool {
        if #available(macOS 14.0, *) {
            return EKEventStore.authorizationStatus(for: .event) == .fullAccess
        } else {
            return EKEventStore.authorizationStatus(for: .event) == .authorized
        }
    }

    /// Contacts authorization.
    var contactsAccessGranted: Bool {
        CNContactStore.authorizationStatus(for: .contacts) == .authorized
    }

    // MARK: - Convenience flags

    var xConnected: Bool { !xBearerToken.isEmpty }
    var tavilyConnected: Bool { !tavilyApiKey.isEmpty }

    // MARK: - Init

    private let defaults = UserDefaults.standard

    private init() {
        self.hasCompletedOnboarding = defaults.bool(forKey: Keys.completed)
        self.llmProvider = LLMProvider(rawValue: defaults.string(forKey: Keys.llmProvider) ?? "") ?? .openrouter
        self.llmApiKey = loadSecret(key: Keys.llmApiKey) ?? ""
        self.gmailConnected = defaults.bool(forKey: Keys.gmailConnected)
        self.gmailEmail = defaults.string(forKey: Keys.gmailEmail) ?? ""
        self.gmailName = defaults.string(forKey: Keys.gmailName) ?? ""
        self.whatsappConnected = defaults.bool(forKey: Keys.whatsappConnected)
        self.twilioConnected = defaults.bool(forKey: Keys.twilioConnected)
        self.twilioNumber = defaults.string(forKey: Keys.twilioNumber) ?? ""
        self.twilioSid = loadSecret(key: Keys.twilioSid) ?? ""
        self.twilioAuthToken = loadSecret(key: Keys.twilioAuthToken) ?? ""
        self.tvPaired = defaults.bool(forKey: Keys.tvPaired)
        self.tvHost = defaults.string(forKey: Keys.tvHost) ?? ""
        self.xBearerToken = loadSecret(key: Keys.xBearerToken) ?? ""
        self.tavilyApiKey = loadSecret(key: Keys.tavilyApiKey) ?? ""
        self.allowedApps = (defaults.array(forKey: Keys.allowedApps) as? [String])
            ?? OnboardingState.defaultAllowedApps
    }

    // MARK: - Reset (for dev/testing)

    func resetOnboarding() {
        let keys: [String] = [
            Keys.completed, Keys.llmProvider, Keys.gmailConnected, Keys.gmailEmail, Keys.gmailName,
            Keys.whatsappConnected, Keys.twilioConnected, Keys.twilioNumber,
            Keys.tvPaired, Keys.tvHost,
        ]
        for key in keys { defaults.removeObject(forKey: key) }
        for secret in [Keys.llmApiKey, Keys.twilioSid, Keys.twilioAuthToken,
                        Keys.xBearerToken, Keys.tavilyApiKey] {
            deleteSecret(key: secret)
        }
        objectWillChange.send()
    }

    // MARK: - Permission prompts

    /// Request calendar access. Opens System Settings if already denied.
    func requestCalendarAccess() async -> Bool {
        let store = EKEventStore()
        do {
            if #available(macOS 14.0, *) {
                return try await store.requestFullAccessToEvents()
            } else {
                return try await store.requestAccess(to: .event)
            }
        } catch {
            return false
        }
    }

    /// Request contacts access.
    func requestContactsAccess() async -> Bool {
        let store = CNContactStore()
        return await withCheckedContinuation { cont in
            store.requestAccess(for: .contacts) { granted, _ in
                cont.resume(returning: granted)
            }
        }
    }

    /// Open Full Disk Access pane so the user can grant Messages DB read access.
    func openFullDiskAccessSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles") {
            NSWorkspace.shared.open(url)
        }
    }

    // MARK: - Env export for Python subprocesses

    /// Builds an environment dict to pass to Python subprocesses so FRIDAY's
    /// Python layer sees the BYOK credentials entered in the GUI.
    func subprocessEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        if !llmApiKey.isEmpty { env[llmProvider.keyName] = llmApiKey }
        if !twilioSid.isEmpty { env["TWILIO_ACCOUNT_SID"] = twilioSid }
        if !twilioAuthToken.isEmpty { env["TWILIO_AUTH_TOKEN"] = twilioAuthToken }
        if !twilioNumber.isEmpty { env["TWILIO_PHONE_NUMBER"] = twilioNumber }
        if !xBearerToken.isEmpty { env["X_BEARER_TOKEN"] = xBearerToken }
        if !tavilyApiKey.isEmpty { env["TAVILY_API_KEY"] = tavilyApiKey }
        if tvPaired, !tvHost.isEmpty { env["LG_TV_HOST"] = tvHost }
        // Comma-separated list of allowed apps — read by friday/tools/mac_tools.py
        env["FRIDAY_ALLOWED_APPS"] = allowedApps.joined(separator: ",")
        return env
    }

    // MARK: - Storage keys

    private enum Keys {
        static let completed = "onboarding.completed"
        static let llmProvider = "onboarding.llm.provider"
        static let llmApiKey = "onboarding.llm.apikey"
        static let gmailConnected = "onboarding.gmail.connected"
        static let gmailEmail = "onboarding.gmail.email"
        static let gmailName = "onboarding.gmail.name"
        static let whatsappConnected = "onboarding.whatsapp.connected"
        static let twilioConnected = "onboarding.twilio.connected"
        static let twilioNumber = "onboarding.twilio.number"
        static let twilioSid = "onboarding.twilio.sid"
        static let twilioAuthToken = "onboarding.twilio.authtoken"
        static let tvPaired = "onboarding.tv.paired"
        static let tvHost = "onboarding.tv.host"
        static let xBearerToken = "onboarding.x.bearer"
        static let tavilyApiKey = "onboarding.tavily.key"
        static let allowedApps = "settings.allowed_apps"
    }
}

// MARK: - LLM providers

enum LLMProvider: String, CaseIterable, Identifiable {
    case openrouter = "openrouter"
    case groq = "groq"
    case googleai = "googleai"
    case local = "local"

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .openrouter: return "OpenRouter"
        case .groq: return "Groq"
        case .googleai: return "Google AI"
        case .local: return "Local (Ollama)"
        }
    }

    var description: String {
        switch self {
        case .openrouter: return "Gemma 4 31B, Claude, GPT-5, and more. ~$0.14/M. Recommended."
        case .groq: return "Qwen3-32B, sub-second latency. ~$0.29/M."
        case .googleai: return "Gemma 4 31B on Google's servers. Free tier."
        case .local: return "Runs on your Mac via Ollama. No cloud, no API cost."
        }
    }

    var keyName: String {
        switch self {
        case .openrouter: return "OPENROUTER_API_KEY"
        case .groq: return "GROQ_API_KEY"
        case .googleai: return "GOOGLE_API_KEY"
        case .local: return ""
        }
    }

    var keyURL: URL? {
        switch self {
        case .openrouter: return URL(string: "https://openrouter.ai/settings/keys")
        case .groq: return URL(string: "https://console.groq.com/keys")
        case .googleai: return URL(string: "https://aistudio.google.com/apikey")
        case .local: return URL(string: "https://ollama.com/download")
        }
    }

    var needsKey: Bool { self != .local }
}

// MARK: - Secure storage (Keychain)

private let kKeychainService = "com.travis.Friday"

private func saveSecret(_ value: String, key: String) {
    if value.isEmpty {
        deleteSecret(key: key)
        return
    }
    guard let data = value.data(using: .utf8) else { return }
    let q: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: kKeychainService,
        kSecAttrAccount as String: key,
    ]
    SecItemDelete(q as CFDictionary)
    var attrs = q
    attrs[kSecValueData as String] = data
    SecItemAdd(attrs as CFDictionary, nil)
}

private func loadSecret(key: String) -> String? {
    let q: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: kKeychainService,
        kSecAttrAccount as String: key,
        kSecReturnData as String: true,
        kSecMatchLimit as String: kSecMatchLimitOne,
    ]
    var result: AnyObject?
    SecItemCopyMatching(q as CFDictionary, &result)
    guard let data = result as? Data else { return nil }
    return String(data: data, encoding: .utf8)
}

private func deleteSecret(key: String) {
    let q: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: kKeychainService,
        kSecAttrAccount as String: key,
    ]
    SecItemDelete(q as CFDictionary)
}
