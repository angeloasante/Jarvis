//
//  Commands.swift
//  Friday
//
//  Slash-style commands and natural-language command interception.
//  Handles UI-state commands locally in the app instead of sending to FridayCore.
//

import SwiftUI
import AppKit

// MARK: - Command definition

struct FridayCommand: Identifiable, Hashable {
    let id: String                 // slash form, e.g. "/voice"
    let title: String              // "Toggle voice"
    let subtitle: String           // "Turn voice pipeline on/off"
    let icon: String               // SF symbol
    let category: Category
    /// Natural-language phrases that should trigger this command.
    /// Lowercased, matched with `contains` after some light normalisation.
    let naturalLanguage: [String]

    enum Category: String, CaseIterable {
        case general = "General"
        case voice = "Voice"
        case gestures = "Gestures"
        case background = "Background"
    }
}

// MARK: - Command registry

enum Commands {
    static let all: [FridayCommand] = [
        // General
        FridayCommand(
            id: "/clear", title: "Clear conversation",
            subtitle: "Reset the chat history",
            icon: "eraser", category: .general,
            naturalLanguage: ["clear conversation", "clear chat", "reset chat",
                              "new conversation", "start over", "clear"]
        ),
        FridayCommand(
            id: "/memory", title: "Show memories",
            subtitle: "Recent stored memories",
            icon: "brain", category: .general,
            naturalLanguage: ["show memories", "show my memories",
                              "recent memories", "what do you remember"]
        ),
        FridayCommand(
            id: "/help", title: "Commands help",
            subtitle: "List all available commands",
            icon: "questionmark.circle", category: .general,
            naturalLanguage: ["help", "show commands", "list commands",
                              "what can you do", "what commands are there"]
        ),
        FridayCommand(
            id: "/quit", title: "Quit FRIDAY",
            subtitle: "Close the app",
            icon: "power", category: .general,
            naturalLanguage: ["quit friday", "close friday", "exit friday",
                              "shut down friday"]
        ),

        // Voice
        FridayCommand(
            id: "/voice", title: "Toggle voice",
            subtitle: "Turn voice pipeline on/off",
            icon: "mic", category: .voice,
            naturalLanguage: ["toggle voice", "voice toggle"]
        ),
        FridayCommand(
            id: "/voice-on", title: "Turn voice on",
            subtitle: "Enable the voice pipeline",
            icon: "mic.fill", category: .voice,
            naturalLanguage: ["turn on voice", "enable voice", "voice on",
                              "start voice", "activate voice"]
        ),
        FridayCommand(
            id: "/voice-off", title: "Turn voice off",
            subtitle: "Disable the voice pipeline",
            icon: "mic.slash", category: .voice,
            naturalLanguage: ["turn off voice", "disable voice", "voice off",
                              "stop voice", "deactivate voice", "mute voice"]
        ),
        FridayCommand(
            id: "/listening-on", title: "Resume listening",
            subtitle: "Resume ambient mic listening",
            icon: "ear", category: .voice,
            naturalLanguage: ["start listening", "resume listening",
                              "begin listening", "listen again"]
        ),
        FridayCommand(
            id: "/listening-off", title: "Pause listening",
            subtitle: "Pause ambient mic listening",
            icon: "ear.badge.waveform", category: .voice,
            naturalLanguage: ["stop listening", "pause listening",
                              "mute mic", "stop listening to me"]
        ),

        // Gestures
        FridayCommand(
            id: "/gestures-on", title: "Enable gestures",
            subtitle: "Start camera + gesture detection",
            icon: "hand.raised.fill", category: .gestures,
            naturalLanguage: ["turn on gestures", "enable gestures",
                              "gestures on", "start gestures",
                              "activate gestures", "gesture control on"]
        ),
        FridayCommand(
            id: "/gestures-off", title: "Disable gestures",
            subtitle: "Stop camera + gesture detection",
            icon: "hand.raised.slash", category: .gestures,
            naturalLanguage: ["turn off gestures", "disable gestures",
                              "gestures off", "stop gestures",
                              "gesture control off"]
        ),
        FridayCommand(
            id: "/gestures", title: "Toggle gestures",
            subtitle: "Toggle gesture detection",
            icon: "hand.wave", category: .gestures,
            naturalLanguage: ["toggle gestures"]
        ),

        // Background
        FridayCommand(
            id: "/clearwatches", title: "Clear watches",
            subtitle: "Kill all active watch tasks",
            icon: "eye.slash", category: .background,
            naturalLanguage: ["clear watches", "stop all watches",
                              "kill watches", "cancel all watches",
                              "stop watching"]
        ),
    ]

    /// Try to match user input to a command. Returns the command or nil.
    /// Matches slash form first, then natural language (case-insensitive).
    static func match(_ input: String) -> FridayCommand? {
        let normalised = input.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalised.isEmpty else { return nil }

        // Exact slash match
        if let cmd = all.first(where: { $0.id == normalised }) {
            return cmd
        }

        // Natural language — match the most specific phrase that appears in the input
        var best: (FridayCommand, Int)? = nil  // (command, phrase length)
        for cmd in all {
            for phrase in cmd.naturalLanguage {
                if normalised == phrase || normalised.contains(phrase) {
                    let len = phrase.count
                    if best == nil || len > best!.1 {
                        best = (cmd, len)
                    }
                }
            }
        }
        return best?.0
    }

    static func grouped() -> [(FridayCommand.Category, [FridayCommand])] {
        FridayCommand.Category.allCases.map { cat in
            (cat, all.filter { $0.category == cat })
        }
    }
}

// MARK: - Command execution

enum CommandResult {
    case handled(String)   // Show this text in chat as the assistant response
    case passthrough       // Command not local — send to FRIDAY normally
}

enum CommandExecutor {
    static func execute(_ command: FridayCommand, context: CommandContext) -> CommandResult {
        switch command.id {
        case "/quit":
            NSApplication.shared.terminate(nil)
            return .handled("Shutting down.")

        case "/clear":
            context.clearConversation()
            return .handled("Cleared.")

        case "/help":
            return .handled(helpText())

        // Voice, gestures, memory, watches — these need Python backend or
        // future Swift pipeline integration. For now, note it's not wired yet
        // but the command is recognised (progress over silence).
        case "/voice", "/voice-on", "/voice-off",
             "/listening-on", "/listening-off":
            return .handled("Voice pipeline lives in the CLI for now. This'll move into the app soon. Use `uv run friday --voice` in the terminal meanwhile.")

        case "/gestures", "/gestures-on", "/gestures-off":
            return .handled("Gesture control runs in the CLI for now. Same roadmap as voice — it's coming to the app.")

        case "/memory":
            return .passthrough  // Let FRIDAY's memory_agent handle it

        case "/clearwatches":
            return .passthrough  // FRIDAY handles watch state

        default:
            return .passthrough
        }
    }

    private static func helpText() -> String {
        var out = "Commands I recognise:\n\n"
        for (cat, cmds) in Commands.grouped() {
            out += "**\(cat.rawValue)**\n"
            for c in cmds {
                out += "  \(c.id) — \(c.subtitle)\n"
            }
            out += "\n"
        }
        out += "You can also say them naturally — e.g. \"clear the chat\" or \"turn on gestures\"."
        return out
    }
}

// MARK: - Context injected into commands

struct CommandContext {
    let clearConversation: () -> Void
}

// MARK: - Command popover UI (shown when ⌘ icon is tapped)

struct CommandPopover: View {
    let onSelect: (FridayCommand) -> Void
    @State private var search: String = ""
    @FocusState private var searchFocused: Bool

    private var filtered: [(FridayCommand.Category, [FridayCommand])] {
        let q = search.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        if q.isEmpty { return Commands.grouped() }
        return Commands.grouped().compactMap { cat, cmds in
            let matches = cmds.filter { c in
                c.id.contains(q) || c.title.lowercased().contains(q)
                    || c.subtitle.lowercased().contains(q)
                    || c.naturalLanguage.contains(where: { $0.contains(q) })
            }
            return matches.isEmpty ? nil : (cat, matches)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 6) {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.secondary)
                TextField("Search commands…", text: $search)
                    .textFieldStyle(.plain)
                    .font(.system(size: 12))
                    .focused($searchFocused)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .background(Color.black.opacity(0.25))

            Divider().opacity(0.15)

            ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(filtered, id: \.0) { cat, cmds in
                        Text(cat.rawValue.uppercased())
                            .font(.system(size: 9, weight: .bold))
                            .foregroundStyle(.secondary.opacity(0.8))
                            .padding(.horizontal, 10)
                            .padding(.top, 6)

                        ForEach(cmds) { cmd in
                            CommandRow(cmd: cmd) { onSelect(cmd) }
                        }
                    }
                }
                .padding(.vertical, 4)
            }
            .scrollIndicators(.hidden)
            .frame(maxHeight: 360)
        }
        .frame(width: 300)
        .onAppear { searchFocused = true }
    }
}

private struct CommandRow: View {
    let cmd: FridayCommand
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: cmd.icon)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.primary)
                    .frame(width: 18)
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 6) {
                        Text(cmd.title)
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(.primary)
                        Text(cmd.id)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.secondary.opacity(0.7))
                    }
                    Text(cmd.subtitle)
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(hovering ? Color.white.opacity(0.1) : Color.clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
    }
}
