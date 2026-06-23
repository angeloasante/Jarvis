//
//  ChatView.swift
//  Friday
//
//  Full-window chat. Same conversation logic as the menu bar popover,
//  laid out to fill the window properly.
//

import SwiftUI

struct ChatView: View {
    @EnvironmentObject var store: ChatStore
    let chatID: UUID

    @State private var commandText: String = ""
    @State private var isProcessing: Bool = false
    @State private var selectedModel: String = "Gemma 4"
    @FocusState private var inputFocused: Bool

    private var turns: [ChatTurn] {
        store.chats.first(where: { $0.id == chatID })?.turns ?? []
    }

    private func append(_ turn: ChatTurn) {
        store.appendTurn(turn, to: chatID)
    }

    private func clearTurns() {
        store.clearChat(chatID)
    }

    var body: some View {
        VStack(spacing: 0) {
            topBar
            Divider().opacity(0.1)

            if turns.isEmpty {
                emptyState
            } else {
                chatScroll
            }

            Divider().opacity(0.1)
            inputBar
        }
        .background(Color(red: 0.06, green: 0.06, blue: 0.08))
        .onAppear { inputFocused = true }
    }

    // MARK: - Top bar (model selector + actions)

    private var topBar: some View {
        HStack(spacing: 10) {
            // Model selector pill
            Menu {
                Button("Gemma 4 31B (OpenRouter)") { selectedModel = "Gemma 4" }
                Button("Qwen3-32B (Groq)") { selectedModel = "Qwen3" }
                Button("Local (Ollama)") { selectedModel = "Local" }
            } label: {
                HStack(spacing: 4) {
                    Circle()
                        .fill(AngularGradient(colors: [.green, .blue, .purple, .pink, .green], center: .center))
                        .frame(width: 10, height: 10)
                    Text(selectedModel)
                        .font(.system(size: 12, weight: .medium))
                    Image(systemName: "chevron.down")
                        .font(.system(size: 9, weight: .semibold))
                }
                .foregroundStyle(.primary)
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(
                    Capsule()
                        .fill(Color.white.opacity(0.06))
                        .overlay(Capsule().stroke(Color.white.opacity(0.1), lineWidth: 0.5))
                )
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()

            Spacer()

            HStack(spacing: 6) {
                IconCircle(icon: "plus") { store.newChat() }
                IconCircle(icon: "square.and.arrow.up") { /* export */ }
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
    }

    // MARK: - Empty state

    private var emptyState: some View {
        VStack(spacing: 18) {
            Spacer()
            ZStack {
                Circle()
                    .fill(AngularGradient(
                        colors: [.green, .blue, .purple, .pink, .orange, .green],
                        center: .center
                    ))
                    .frame(width: 72, height: 72)
                    .blur(radius: 2)
                Circle().fill(Color.black.opacity(0.6)).frame(width: 48, height: 48)
                Image(systemName: "bolt.fill")
                    .font(.system(size: 20, weight: .bold))
                    .foregroundStyle(.white)
            }
            .shadow(color: .green.opacity(0.3), radius: 20)

            VStack(spacing: 4) {
                Text("What's on your mind?")
                    .font(.system(size: 22, weight: .bold, design: .rounded))
                Text("Ask anything. Or try one of these:")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }

            suggestions
                .padding(.top, 10)
                .frame(maxWidth: 540)

            Spacer()
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var suggestions: some View {
        let items: [(String, String)] = [
            ("envelope.fill", "Check my emails"),
            ("tv.fill", "Turn on the TV"),
            ("calendar", "What's on my calendar today?"),
            ("doc.text.magnifyingglass", "Write a short report on AR glasses and save to my desktop"),
        ]
        return LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
            ForEach(items, id: \.1) { icon, text in
                Button { send(text) } label: {
                    HStack(spacing: 10) {
                        Image(systemName: icon)
                            .font(.system(size: 13))
                            .foregroundStyle(.secondary)
                            .frame(width: 16)
                        Text(text)
                            .font(.system(size: 12))
                            .foregroundStyle(.primary)
                            .multilineTextAlignment(.leading)
                            .lineLimit(2)
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(
                        RoundedRectangle(cornerRadius: 10)
                            .fill(Color.white.opacity(0.04))
                            .overlay(
                                RoundedRectangle(cornerRadius: 10)
                                    .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
                            )
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: - Chat scroll

    private var chatScroll: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    ForEach(turns) { turn in
                        turnView(turn).id(turn.id)
                    }
                    if isProcessing {
                        processingRow.id("processing")
                    }
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 18)
                .frame(maxWidth: 820, alignment: .leading)
                .frame(maxWidth: .infinity)  // center within wider window
            }
            .scrollIndicators(.hidden)
            .onChange(of: turns.count) { _, _ in
                withAnimation(.easeOut(duration: 0.25)) {
                    if let last = turns.last { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
            .onChange(of: isProcessing) { _, p in
                if p { withAnimation { proxy.scrollTo("processing", anchor: .bottom) } }
            }
        }
    }

    @ViewBuilder
    private func turnView(_ turn: ChatTurn) -> some View {
        switch turn.role {
        case .user:
            HStack {
                Spacer(minLength: 60)
                Text(turn.text)
                    .font(.system(size: 14))
                    .foregroundStyle(.primary)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(Capsule().fill(Color.white.opacity(0.1)))
                    .textSelection(.enabled)
            }
        case .assistant:
            HStack(alignment: .top, spacing: 12) {
                avatar
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
                            .font(.system(size: 14))
                            .foregroundStyle(.primary)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    ForEach(turn.media, id: \.self) { path in
                        MediaPreview(path: path)
                    }
                }
                Spacer(minLength: 0)
            }
        }
    }

    private var avatar: some View {
        ZStack {
            Circle()
                .fill(AngularGradient(
                    colors: [.green, .blue, .purple, .pink, .orange, .green],
                    center: .center
                ))
                .frame(width: 26, height: 26)
            Circle().fill(Color.black.opacity(0.5)).frame(width: 13, height: 13)
        }
    }

    private var processingRow: some View {
        HStack(alignment: .top, spacing: 12) {
            avatar
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
            .padding(.top, 10)
            Spacer()
        }
    }

    // MARK: - Input bar

    private var inputBar: some View {
        VStack(spacing: 0) {
            HStack(alignment: .bottom, spacing: 10) {
                Image(systemName: "command")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(.secondary)
                    .padding(.bottom, 9)

                TextField(turns.isEmpty ? "Ask FRIDAY anything…" : "Reply…", text: $commandText, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.system(size: 14))
                    .focused($inputFocused)
                    .lineLimit(1...6)
                    .onSubmit { send() }

                Button(action: { send() }) {
                    ZStack {
                        Circle()
                            .fill(commandText.isEmpty ? Color.white.opacity(0.2) : Color.white)
                            .frame(width: 32, height: 32)
                        Image(systemName: "arrow.up")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(commandText.isEmpty ? Color.white.opacity(0.4) : Color.black)
                    }
                }
                .buttonStyle(.plain)
                .disabled(commandText.isEmpty || isProcessing)
                .animation(.easeInOut(duration: 0.15), value: commandText.isEmpty)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(Color.white.opacity(0.04))
                    .overlay(
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .stroke(Color.white.opacity(0.1), lineWidth: 0.5)
                    )
            )
            .padding(.horizontal, 24)
            .padding(.vertical, 14)
            .frame(maxWidth: 860)
            .frame(maxWidth: .infinity)
        }
    }

    // MARK: - Logic

    private func send(_ override: String? = nil) {
        let input = override ?? commandText
        guard !input.isEmpty, !isProcessing else { return }
        if override == nil { commandText = "" }

        if let cmd = Commands.match(input) {
            runCommand(cmd, userInput: input)
            return
        }

        append(ChatTurn(role: .user, text: input))
        streamReply(for: input)
    }

    /// Push the user's input through FridayClient's streaming pipeline. Adds
    /// an empty assistant turn and grows it as chunks arrive.
    private func streamReply(for input: String) {
        // Empty placeholder turn that we'll grow chunk-by-chunk.
        append(ChatTurn(role: .assistant, text: ""))
        isProcessing = true
        let id = chatID

        Task {
            await FridayClient.shared.sendStreaming(input) { event in
                switch event {
                case .chunk(let text):
                    store.appendChunkToLastTurn(text, in: id)
                case .media(let path):
                    store.appendMediaToLastTurn(path, in: id)
                case .status:
                    break  // could surface a progress chip later
                case .error(let msg):
                    store.appendChunkToLastTurn("\n\n_Error: \(msg)_", in: id)
                case .done:
                    isProcessing = false
                    store.flush()
                }
            }
            isProcessing = false
            store.flush()
        }
    }

    private func runCommand(_ cmd: FridayCommand, userInput: String) {
        append(ChatTurn(role: .user, text: userInput))
        let context = CommandContext(clearConversation: { clearTurns() })
        let result = CommandExecutor.execute(cmd, context: context)
        switch result {
        case .handled(let text):
            if cmd.id == "/clear" { clearTurns() }
            withAnimation(.easeOut(duration: 0.2)) {
                append(ChatTurn(role: .assistant, text: text))
            }
        case .passthrough:
            streamReply(for: cmd.id)
        }
    }

    private func relativeTime(_ date: Date) -> String {
        let i = Int(Date().timeIntervalSince(date))
        if i < 5 { return "now" }
        if i < 60 { return "\(i)s" }
        if i < 3600 { return "\(i / 60)m" }
        return "\(i / 3600)h"
    }
}
