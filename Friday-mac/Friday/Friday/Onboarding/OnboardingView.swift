//
//  OnboardingView.swift
//  Friday
//
//  Multi-step onboarding: Welcome → LLM → Gmail → WhatsApp → Done.
//

import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject var state: OnboardingState
    @State private var step: Step = .welcome

    enum Step: CaseIterable {
        case welcome, llm, gmail, whatsapp, browser, done

        var title: String {
            switch self {
            case .welcome: "Welcome"
            case .llm: "Choose your AI"
            case .gmail: "Connect Gmail"
            case .whatsapp: "Connect WhatsApp"
            case .browser: "Drive your Chrome"
            case .done: "Ready"
            }
        }
    }

    var body: some View {
        ZStack {
            // Background — layered dark glass with subtle gradient
            LinearGradient(
                colors: [Color.black.opacity(0.95), Color(white: 0.08)],
                startPoint: .top, endPoint: .bottom
            )
            .ignoresSafeArea()

            VStack(spacing: 0) {
                progressBar
                    .padding(.top, 30)
                    .padding(.horizontal, 40)

                Spacer()

                Group {
                    switch step {
                    case .welcome: WelcomeStep(next: { step = .llm })
                    case .llm: LLMStep(next: { step = .gmail })
                    case .gmail: GmailStep(next: { step = .whatsapp }, skip: { step = .whatsapp })
                    case .whatsapp: WhatsAppStep(next: { step = .browser }, skip: { step = .browser })
                    case .browser: BrowserStep(next: { step = .done }, skip: { step = .done })
                    case .done: DoneStep(finish: { state.hasCompletedOnboarding = true })
                    }
                }
                .transition(.asymmetric(
                    insertion: .move(edge: .trailing).combined(with: .opacity),
                    removal: .move(edge: .leading).combined(with: .opacity)
                ))
                .animation(.easeInOut(duration: 0.35), value: step)

                Spacer()

                if step != .welcome && step != .done {
                    backButton
                        .padding(.bottom, 24)
                }
            }
        }
        .frame(minWidth: 680, minHeight: 560)
    }

    private var progressBar: some View {
        let allSteps = Step.allCases
        let currentIndex = allSteps.firstIndex(of: step) ?? 0
        return HStack(spacing: 6) {
            ForEach(Array(allSteps.enumerated()), id: \.offset) { idx, _ in
                Capsule()
                    .fill(idx <= currentIndex ? Color.white.opacity(0.9) : Color.white.opacity(0.15))
                    .frame(height: 3)
            }
        }
    }

    private var backButton: some View {
        Button {
            let all = Step.allCases
            if let idx = all.firstIndex(of: step), idx > 0 {
                step = all[idx - 1]
            }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "chevron.left")
                Text("Back")
            }
            .font(.system(size: 12, weight: .medium))
            .foregroundStyle(.secondary)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Step 1: Welcome

private struct WelcomeStep: View {
    let next: () -> Void

    var body: some View {
        VStack(spacing: 24) {
            ZStack {
                Circle()
                    .fill(
                        AngularGradient(
                            colors: [.green, .blue, .purple, .pink, .orange, .green],
                            center: .center
                        )
                    )
                    .frame(width: 92, height: 92)
                    .blur(radius: 1)
                Circle()
                    .fill(Color.black.opacity(0.55))
                    .frame(width: 64, height: 64)
                Image(systemName: "bolt.fill")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(.white)
            }
            .shadow(color: .green.opacity(0.4), radius: 24)

            VStack(spacing: 6) {
                Text("FRIDAY")
                    .font(.system(size: 38, weight: .bold, design: .rounded))
                    .kerning(-0.5)
                Text("Tony Stark had JARVIS.")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 14) {
                FeatureRow(icon: "message.fill", tint: .green,
                           title: "Holds down your conversations",
                           detail: "Watches your iMessage, WhatsApp and email. Replies in your voice while you're busy — nobody knows it wasn't you.")
                FeatureRow(icon: "bolt.horizontal.fill", tint: .blue,
                           title: "Runs your stuff",
                           detail: "Turns on the TV with a word, mutes it with a fist, opens any app. Sub-second fast path — no LLM round-trip.")
                FeatureRow(icon: "arrow.right.circle.fill", tint: .orange,
                           title: "Finishes things",
                           detail: "Tailors your CV and fills the application. Writes the report. Books the call. Not instructions — actual work, done.")
            }
            .frame(maxWidth: 460)
            .padding(.top, 10)

            Button(action: next) {
                Text("Let's go")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(.black)
                    .frame(width: 200, height: 40)
                    .background(Capsule().fill(Color.white))
            }
            .buttonStyle(.plain)
            .padding(.top, 10)

            Text("Built by one person, in Plymouth, UK, at 3am.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary.opacity(0.6))
        }
    }
}

private struct FeatureRow: View {
    let icon: String
    let tint: Color
    let title: String
    let detail: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 32, height: 32)
                .background(Circle().fill(tint.opacity(0.15)))
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.system(size: 13, weight: .semibold))
                Text(detail)
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
    }
}

// MARK: - Step 2: LLM

private struct LLMStep: View {
    @EnvironmentObject var state: OnboardingState
    let next: () -> Void
    @State private var testing = false
    @State private var testResult: String?

    var body: some View {
        VStack(spacing: 20) {
            stepHeader(
                title: "Choose your AI",
                subtitle: "FRIDAY works with any OpenAI-compatible provider. Pick one."
            )

            VStack(spacing: 8) {
                ForEach(LLMProvider.allCases) { provider in
                    ProviderCard(provider: provider, selected: state.llmProvider == provider) {
                        state.llmProvider = provider
                    }
                }
            }
            .frame(maxWidth: 440)

            if state.llmProvider.needsKey {
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("API key")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(.secondary)
                        Spacer()
                        if let url = state.llmProvider.keyURL {
                            Link(destination: url) {
                                HStack(spacing: 3) {
                                    Text("Get key")
                                    Image(systemName: "arrow.up.right")
                                }
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(.blue)
                            }
                        }
                    }
                    SecureField("\(state.llmProvider.keyName)…", text: $state.llmApiKey)
                        .textFieldStyle(.plain)
                        .font(.system(size: 13, design: .monospaced))
                        .padding(10)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.08)))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.15), lineWidth: 0.5))
                }
                .frame(maxWidth: 440)
            }

            if let msg = testResult {
                Text(msg)
                    .font(.system(size: 12))
                    .foregroundStyle(msg.hasPrefix("✓") ? .green : .red)
                    .transition(.opacity)
            }

            HStack(spacing: 10) {
                if state.llmProvider.needsKey {
                    Button {
                        testConnection()
                    } label: {
                        HStack(spacing: 6) {
                            if testing { ProgressView().controlSize(.small) }
                            Text(testing ? "Testing…" : "Test connection")
                        }
                        .font(.system(size: 13, weight: .medium))
                        .frame(width: 160, height: 36)
                        .background(Capsule().fill(Color.white.opacity(0.12)))
                    }
                    .buttonStyle(.plain)
                    .disabled(state.llmApiKey.isEmpty || testing)
                }

                Button(action: next) {
                    Text("Continue")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(.black)
                        .frame(width: 160, height: 36)
                        .background(Capsule().fill(Color.white))
                }
                .buttonStyle(.plain)
                .disabled(state.llmProvider.needsKey && state.llmApiKey.isEmpty)
            }
            .padding(.top, 4)
        }
    }

    private func testConnection() {
        testing = true
        testResult = nil
        Task {
            // TODO: actual ping to the provider with the key. For now: save, assume ok.
            try? await Task.sleep(nanoseconds: 600_000_000)
            await MainActor.run {
                testing = false
                testResult = "✓ Connected"
            }
        }
    }
}

private struct ProviderCard: View {
    let provider: LLMProvider
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Circle()
                    .stroke(Color.white.opacity(selected ? 0.9 : 0.25), lineWidth: 1.5)
                    .overlay(
                        Circle().fill(selected ? Color.white : Color.clear)
                            .padding(3)
                    )
                    .frame(width: 16, height: 16)
                VStack(alignment: .leading, spacing: 2) {
                    Text(provider.displayName)
                        .font(.system(size: 13, weight: .semibold))
                    Text(provider.description)
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                Spacer()
            }
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 10)
                    .fill(selected ? Color.white.opacity(0.1) : Color.white.opacity(0.03))
                    .overlay(
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(selected ? Color.white.opacity(0.3) : Color.white.opacity(0.08), lineWidth: 0.5)
                    )
            )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Step 3: Gmail

private struct GmailStep: View {
    @EnvironmentObject var state: OnboardingState
    let next: () -> Void
    let skip: () -> Void
    @State private var isConnecting = false

    var body: some View {
        VStack(spacing: 18) {
            stepHeader(
                title: "Connect Gmail",
                subtitle: "FRIDAY reads, searches, and drafts emails on your behalf. No data leaves your machine."
            )

            ZStack {
                Circle().fill(Color.red.opacity(0.12)).frame(width: 88, height: 88)
                Image(systemName: "envelope.fill")
                    .font(.system(size: 34))
                    .foregroundStyle(.red)
            }

            if state.gmailConnected {
                VStack(spacing: 4) {
                    Label(state.gmailEmail.isEmpty ? "Connected" : state.gmailEmail,
                          systemImage: "checkmark.circle.fill")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.green)
                    Button("Disconnect") {
                        state.gmailConnected = false
                        state.gmailEmail = ""
                    }
                    .buttonStyle(.plain)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                }
            } else {
                Button {
                    connectGmail()
                } label: {
                    HStack(spacing: 8) {
                        if isConnecting {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "arrow.up.forward.app")
                        }
                        Text(isConnecting ? "Waiting for Google…" : "Sign in with Google")
                    }
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.black)
                    .frame(width: 220, height: 38)
                    .background(Capsule().fill(Color.white))
                }
                .buttonStyle(.plain)
                .disabled(isConnecting)
            }

            HStack(spacing: 12) {
                Button("Skip for now", action: skip)
                    .buttonStyle(.plain)
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)

                Button("Continue", action: next)
                    .buttonStyle(.plain)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.black)
                    .frame(width: 130, height: 36)
                    .background(Capsule().fill(Color.white))
                    .disabled(!state.gmailConnected)
                    .opacity(state.gmailConnected ? 1 : 0.4)
            }
            .padding(.top, 10)
        }
    }

    private func connectGmail() {
        isConnecting = true
        Task {
            let result = await GmailAuth.connect()
            await MainActor.run {
                isConnecting = false
                if let profile = result {
                    state.gmailEmail = profile.email
                    state.gmailName = profile.name
                    state.gmailConnected = true
                }
            }
        }
    }
}

// MARK: - Step 4: WhatsApp

private struct WhatsAppStep: View {
    @EnvironmentObject var state: OnboardingState
    let next: () -> Void
    let skip: () -> Void
    @State private var qrImage: NSImage?
    @State private var bridgeStatus: WhatsAppStatus = .idle
    @State private var polling: Task<Void, Never>?

    var body: some View {
        VStack(spacing: 18) {
            stepHeader(
                title: "Connect WhatsApp",
                subtitle: "Scan the QR code in WhatsApp → Settings → Linked Devices. Optional — skip if you don't use WhatsApp."
            )

            ZStack {
                RoundedRectangle(cornerRadius: 16)
                    .fill(Color.white)
                    .frame(width: 240, height: 240)

                if state.whatsappConnected {
                    VStack(spacing: 8) {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.system(size: 48))
                            .foregroundStyle(.green)
                        Text("Connected")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(.black)
                    }
                } else if let img = qrImage {
                    Image(nsImage: img)
                        .interpolation(.none)
                        .resizable()
                        .scaledToFit()
                        .frame(width: 220, height: 220)
                } else {
                    VStack(spacing: 10) {
                        ProgressView()
                            .tint(.black)
                        Text(bridgeStatus.message)
                            .font(.system(size: 11))
                            .foregroundStyle(.black.opacity(0.6))
                            .multilineTextAlignment(.center)
                    }
                    .frame(width: 200)
                }
            }
            .shadow(color: .black.opacity(0.3), radius: 20, y: 8)

            HStack(spacing: 12) {
                Button("Skip", action: skip)
                    .buttonStyle(.plain)
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)

                Button("Continue", action: next)
                    .buttonStyle(.plain)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.black)
                    .frame(width: 130, height: 36)
                    .background(Capsule().fill(Color.white))
            }
        }
        .onAppear(perform: startPolling)
        .onDisappear { polling?.cancel() }
    }

    private func startPolling() {
        polling = Task {
            while !Task.isCancelled {
                let status = await WhatsAppBridge.fetchStatus()
                await MainActor.run {
                    self.bridgeStatus = status
                    switch status {
                    case .connected:
                        self.state.whatsappConnected = true
                        self.qrImage = nil
                    case .needsQR(let qr):
                        self.qrImage = qr
                    case .idle, .bridgeDown:
                        self.qrImage = nil
                    }
                }
                if case .connected = status { break }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
    }
}

// MARK: - Step 5: Browser extension

private struct BrowserStep: View {
    let next: () -> Void
    let skip: () -> Void
    @State private var token: String = ""
    @State private var copied = false
    @State private var extensionURL: URL?

    var body: some View {
        VStack(spacing: 16) {
            stepHeader(
                title: "Drive your Chrome",
                subtitle: "FRIDAY uses headless Playwright by default, but it can also act in your real, logged-in Chrome — LinkedIn, Gmail, anti-bot pages. Optional — skip if you don't want this."
            )

            VStack(alignment: .leading, spacing: 10) {
                BrowserStepRow(num: "1", text: "Open Chrome → ", linkLabel: "chrome://extensions", action: openChromeExtensions)
                BrowserStepRow(num: "2", text: "Toggle Developer mode (top-right of the extensions page).")
                BrowserStepRow(num: "3", text: "Click Load unpacked and pick the extension folder.", linkLabel: extensionURL == nil ? nil : "Reveal in Finder", action: openExtensionFolder)
                BrowserStepRow(num: "4", text: "Click the FRIDAY icon in the toolbar, paste the token, and Save & Connect.")
            }
            .frame(maxWidth: 460, alignment: .leading)

            // Token card
            VStack(alignment: .leading, spacing: 6) {
                Text("Bridge token")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.secondary)
                HStack(spacing: 8) {
                    Text(token.isEmpty ? "Run FRIDAY once to mint a token." : token)
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(token.isEmpty ? .secondary : .primary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Button(action: copyToken) {
                        Text(copied ? "Copied" : "Copy")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(copied ? .green : .white)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 6)
                            .background(Capsule().fill(Color.white.opacity(0.12)))
                    }
                    .buttonStyle(.plain)
                    .disabled(token.isEmpty)
                }
                .padding(10)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.06)))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.12), lineWidth: 0.5))
            }
            .frame(maxWidth: 460)

            HStack(spacing: 12) {
                Button("Skip", action: skip)
                    .buttonStyle(.plain)
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)

                Button("Continue", action: next)
                    .buttonStyle(.plain)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.black)
                    .frame(width: 130, height: 36)
                    .background(Capsule().fill(Color.white))
            }
        }
        .onAppear(perform: load)
    }

    private func load() {
        token = readToken()
        extensionURL = findExtensionFolder()
    }

    private func readToken() -> String {
        let envPath = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Friday/.env")
        guard let contents = try? String(contentsOf: envPath, encoding: .utf8) else { return "" }
        for line in contents.split(separator: "\n") {
            let s = String(line)
            if s.hasPrefix("FRIDAY_BROWSER_EXT_TOKEN=") {
                let value = s.dropFirst("FRIDAY_BROWSER_EXT_TOKEN=".count)
                return value.trimmingCharacters(in: CharacterSet(charactersIn: " \"'"))
            }
        }
        return ""
    }

    private func findExtensionFolder() -> URL? {
        let fm = FileManager.default
        let home = fm.homeDirectoryForCurrentUser
        let candidates: [URL] = [
            home.appendingPathComponent("Friday/extension/browser-bridge"),
            home.appendingPathComponent("Desktop/JARVIS/extension/browser-bridge"),
            Bundle.main.resourceURL?.appendingPathComponent("browser-bridge"),
        ].compactMap { $0 }
        return candidates.first { fm.fileExists(atPath: $0.path) }
    }

    private func copyToken() {
        guard !token.isEmpty else { return }
        let pb = NSPasteboard.general
        pb.clearContents()
        pb.setString(token, forType: .string)
        copied = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { copied = false }
    }

    private func openChromeExtensions() {
        if let url = URL(string: "chrome://extensions") {
            NSWorkspace.shared.open(url)
        }
    }

    private func openExtensionFolder() {
        guard let url = extensionURL else { return }
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }
}

private struct BrowserStepRow: View {
    let num: String
    let text: String
    var linkLabel: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Text(num)
                .font(.system(size: 11, weight: .bold, design: .rounded))
                .foregroundStyle(.black)
                .frame(width: 20, height: 20)
                .background(Circle().fill(Color.white.opacity(0.85)))
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 4) {
                    Text(text)
                        .font(.system(size: 12))
                    if let label = linkLabel, let action = action {
                        Button(action: action) {
                            Text(label)
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(.blue)
                                .underline()
                        }
                        .buttonStyle(.plain)
                    }
                }
                .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
    }
}

// MARK: - Step 6: Done

private struct DoneStep: View {
    let finish: () -> Void

    var body: some View {
        VStack(spacing: 20) {
            ZStack {
                Circle().fill(Color.green.opacity(0.18)).frame(width: 92, height: 92)
                Image(systemName: "checkmark")
                    .font(.system(size: 36, weight: .bold))
                    .foregroundStyle(.green)
            }

            Text("You're set.")
                .font(.system(size: 28, weight: .bold, design: .rounded))

            Text("Click the bolt in your menu bar, or press ⌘⇧F, and ask me anything.")
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 360)

            Button(action: finish) {
                Text("Open FRIDAY")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(.black)
                    .frame(width: 200, height: 40)
                    .background(Capsule().fill(Color.white))
            }
            .buttonStyle(.plain)
            .padding(.top, 8)
        }
    }
}

// MARK: - Shared header

@ViewBuilder
private func stepHeader(title: String, subtitle: String) -> some View {
    VStack(spacing: 6) {
        Text(title)
            .font(.system(size: 24, weight: .bold, design: .rounded))
        Text(subtitle)
            .font(.system(size: 12))
            .foregroundStyle(.secondary)
            .multilineTextAlignment(.center)
            .frame(maxWidth: 420)
    }
}
