//
//  MenuBarContent.swift
//  Friday
//
//  Chat-style menu bar card, inspired by Claude's Mac app.
//  Dark glass, pill bubbles, circular white send button.
//

import SwiftUI

// A single turn in the conversation
struct ChatTurn: Identifiable, Codable, Hashable {
    var id: UUID = UUID()
    var role: Role
    var text: String
    var media: [String]  // File paths for media previews (images, PDFs, etc.)
    var timestamp: Date

    enum Role: String, Codable { case user, assistant }

    init(role: Role, text: String, media: [String] = [], timestamp: Date = Date()) {
        self.role = role
        self.text = text
        self.media = media
        self.timestamp = timestamp
    }
}

struct MenuBarContent: View {
    @State private var commandText: String = ""
    @State private var turns: [ChatTurn] = []
    @State private var isProcessing: Bool = false
    @State private var selectedModel: String = "Gemma 4"
    @State private var showCommandPopover: Bool = false
    @FocusState private var inputFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            topBar
            Divider().opacity(0.15)

            if turns.isEmpty {
                emptyState
            } else {
                chatArea
            }

            Divider().opacity(0.15)
            inputBar
        }
        .frame(width: 380)
        .frame(minHeight: 220)
        .background(
            // Glass layer — NSPopover provides vibrancy, this adds depth
            LinearGradient(
                colors: [
                    Color.black.opacity(0.35),
                    Color.black.opacity(0.25)
                ],
                startPoint: .top,
                endPoint: .bottom
            )
        )
        .onAppear { inputFocused = true }
    }

    // MARK: - Top bar (model selector + window controls)

    private var topBar: some View {
        HStack {
            // Model selector pill
            Menu {
                Button("Gemma 4 31B (Google AI)") { selectedModel = "Gemma 4" }
                Button("Qwen3-32B (Groq)") { selectedModel = "Qwen3" }
                Button("Ollama (local)") { selectedModel = "Local" }
            } label: {
                HStack(spacing: 4) {
                    Text(selectedModel)
                        .font(.system(size: 12, weight: .medium))
                    Image(systemName: "chevron.down")
                        .font(.system(size: 9, weight: .semibold))
                }
                .foregroundStyle(.primary)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(
                    Capsule()
                        .fill(Color.white.opacity(0.08))
                        .overlay(Capsule().stroke(Color.white.opacity(0.12), lineWidth: 0.5))
                )
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()

            Spacer()

            // Window controls
            HStack(spacing: 6) {
                IconCircle(icon: "square") {
                    // Clear conversation
                    turns = []
                }
                IconCircle(icon: "arrow.up.left.and.arrow.down.right") {
                    // Future: expand to full window
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }

    // MARK: - Empty state (before first message)

    private var emptyState: some View {
        VStack(spacing: 8) {
            ZStack {
                Circle()
                    .fill(
                        AngularGradient(
                            colors: [.green, .blue, .purple, .pink, .orange, .green],
                            center: .center
                        )
                    )
                    .frame(width: 36, height: 36)
                    .blur(radius: 2)
                Circle()
                    .fill(Color.black.opacity(0.6))
                    .frame(width: 24, height: 24)
            }
            .shadow(color: .green.opacity(0.4), radius: 12)

            Text("FRIDAY")
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundStyle(.primary)

            Text("Ask anything.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 32)
    }

    // MARK: - Chat area

    private var chatArea: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(turns) { turn in
                        turnView(turn)
                            .id(turn.id)
                    }
                    if isProcessing {
                        processingIndicator
                            .id("processing")
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
            }
            .scrollIndicators(.hidden)
            .frame(maxHeight: 360)
            .onChange(of: turns.count) { _, _ in
                withAnimation(.easeOut(duration: 0.25)) {
                    if let last = turns.last {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
            .onChange(of: isProcessing) { _, processing in
                if processing {
                    withAnimation { proxy.scrollTo("processing", anchor: .bottom) }
                }
            }
        }
    }

    @ViewBuilder
    private func turnView(_ turn: ChatTurn) -> some View {
        switch turn.role {
        case .user:
            HStack {
                Spacer(minLength: 40)
                Text(turn.text)
                    .font(.system(size: 13))
                    .foregroundStyle(.primary)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(
                        Capsule()
                            .fill(Color.white.opacity(0.1))
                    )
            }
        case .assistant:
            HStack(alignment: .top, spacing: 10) {
                assistantAvatar
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 6) {
                        Text("FRIDAY")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(.secondary)
                        Text(relativeTime(turn.timestamp))
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary.opacity(0.7))
                    }

                    if !turn.text.isEmpty {
                        Text(turn.text)
                            .font(.system(size: 13))
                            .foregroundStyle(.primary)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    // Render media previews — paths come directly from
                    // FRIDAY's tool results, not regex-parsed from text.
                    ForEach(turn.media, id: \.self) { path in
                        MediaPreview(path: path)
                    }
                }
                Spacer(minLength: 0)
            }
        }
    }

    private var assistantAvatar: some View {
        ZStack {
            Circle()
                .fill(
                    AngularGradient(
                        colors: [.green, .blue, .purple, .pink, .orange, .green],
                        center: .center
                    )
                )
                .frame(width: 20, height: 20)
                .blur(radius: 0.5)
            Circle()
                .fill(Color.black.opacity(0.5))
                .frame(width: 10, height: 10)
        }
    }

    private var processingIndicator: some View {
        HStack(alignment: .top, spacing: 10) {
            assistantAvatar
            HStack(spacing: 4) {
                ForEach(0..<3) { i in
                    Circle()
                        .fill(Color.white.opacity(0.6))
                        .frame(width: 5, height: 5)
                        .scaleEffect(isProcessing ? 1 : 0.5)
                        .animation(
                            .easeInOut(duration: 0.6)
                                .repeatForever()
                                .delay(Double(i) * 0.15),
                            value: isProcessing
                        )
                }
            }
            .padding(.top, 8)
            Spacer()
        }
    }

    // MARK: - Input bar

    private var inputBar: some View {
        HStack(spacing: 10) {
            // ⌘ button — click to open the command palette
            Button {
                showCommandPopover.toggle()
            } label: {
                Image(systemName: "command")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(showCommandPopover ? .primary : .secondary)
            }
            .buttonStyle(.plain)
            .popover(isPresented: $showCommandPopover, arrowEdge: .top) {
                CommandPopover { cmd in
                    showCommandPopover = false
                    runCommand(cmd)
                }
            }

            TextField(turns.isEmpty ? "Ask FRIDAY anything…" : "Reply…", text: $commandText)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .focused($inputFocused)
                .onSubmit { send() }

            Button(action: send) {
                ZStack {
                    Circle()
                        .fill(commandText.isEmpty ? Color.white.opacity(0.2) : Color.white)
                        .frame(width: 28, height: 28)
                    Image(systemName: "arrow.up")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(commandText.isEmpty ? Color.white.opacity(0.4) : Color.black)
                }
            }
            .buttonStyle(.plain)
            .disabled(commandText.isEmpty || isProcessing)
            .animation(.easeInOut(duration: 0.15), value: commandText.isEmpty)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }

    // MARK: - Logic

    private func send() {
        guard !commandText.isEmpty, !isProcessing else { return }
        let input = commandText
        commandText = ""

        // Try to match a command (slash or natural language) first
        if let cmd = Commands.match(input) {
            runCommand(cmd, userInput: input)
            return
        }

        turns.append(ChatTurn(role: .user, text: input))
        isProcessing = true

        Task {
            let response = await FridayClient.shared.send(input)
            await MainActor.run {
                isProcessing = false
                withAnimation(.easeOut(duration: 0.25)) {
                    turns.append(ChatTurn(
                        role: .assistant,
                        text: response.text,
                        media: response.media
                    ))
                }
            }
        }
    }

    /// Execute a command, either from the palette or from matched NL input.
    private func runCommand(_ cmd: FridayCommand, userInput: String? = nil) {
        let shown = userInput ?? cmd.id
        turns.append(ChatTurn(role: .user, text: shown))

        let context = CommandContext(
            clearConversation: { turns = [] }
        )
        let result = CommandExecutor.execute(cmd, context: context)

        switch result {
        case .handled(let text):
            // Clear runs first, then show feedback — so the "Cleared." appears as the first new turn
            if cmd.id == "/clear" { turns = [] }
            withAnimation(.easeOut(duration: 0.2)) {
                turns.append(ChatTurn(role: .assistant, text: text))
            }
        case .passthrough:
            // Let FRIDAY handle it (memory, clearwatches, etc.)
            isProcessing = true
            Task {
                let response = await FridayClient.shared.send(cmd.id)
                await MainActor.run {
                    isProcessing = false
                    withAnimation(.easeOut(duration: 0.25)) {
                        turns.append(ChatTurn(
                            role: .assistant,
                            text: response.text,
                            media: response.media
                        ))
                    }
                }
            }
        }
    }

    private func relativeTime(_ date: Date) -> String {
        let interval = Int(Date().timeIntervalSince(date))
        if interval < 5 { return "now" }
        if interval < 60 { return "\(interval)s" }
        if interval < 3600 { return "\(interval / 60)m" }
        return "\(interval / 3600)h"
    }
}

// MARK: - Circular icon button (for top bar controls)

struct IconCircle: View {
    let icon: String
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(.primary)
                .frame(width: 22, height: 22)
                .background(
                    Circle()
                        .fill(hovering ? Color.white.opacity(0.18) : Color.white.opacity(0.08))
                )
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .animation(.easeInOut(duration: 0.12), value: hovering)
    }
}

#Preview {
    MenuBarContent()
        .frame(width: 380)
        .background(Color.black)
}
