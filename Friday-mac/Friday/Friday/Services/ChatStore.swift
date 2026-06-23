//
//  ChatStore.swift
//  Friday
//
//  In-session chat list + persistence. Each Chat holds its turns; the store
//  manages which one is active and saves/loads to a JSON file under
//  ~/Library/Application Support/Friday/chats.json.
//

import Foundation
import Combine
import SwiftUI

struct Chat: Identifiable, Codable, Hashable {
    var id: UUID = UUID()
    var title: String
    var turns: [ChatTurn]
    var createdAt: Date
    var lastActiveAt: Date

    init(id: UUID = UUID(), title: String = "New chat", turns: [ChatTurn] = []) {
        self.id = id
        self.title = title
        self.turns = turns
        let now = Date()
        self.createdAt = now
        self.lastActiveAt = now
    }

    /// Pull a readable title from the first user turn — cap at ~40 chars.
    mutating func retitleFromFirstTurn() {
        guard let first = turns.first(where: { $0.role == .user }) else { return }
        let t = first.text.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty { return }
        title = t.count <= 40 ? t : String(t.prefix(40)) + "…"
    }
}

@MainActor
final class ChatStore: ObservableObject {
    static let shared = ChatStore()

    @Published private(set) var chats: [Chat] = []
    @Published var activeChatID: UUID? = nil

    private let fileURL: URL

    private init() {
        let base = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Friday", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        self.fileURL = base.appendingPathComponent("chats.json")
        load()
        if chats.isEmpty {
            let first = Chat(title: "New chat")
            chats = [first]
            activeChatID = first.id
            save()
        } else {
            activeChatID = chats.sorted(by: { $0.lastActiveAt > $1.lastActiveAt }).first?.id
        }
    }

    // MARK: - Active chat

    var activeChat: Chat? {
        guard let id = activeChatID else { return nil }
        return chats.first { $0.id == id }
    }

    func binding(for id: UUID) -> Binding<Chat>? {
        guard let idx = chats.firstIndex(where: { $0.id == id }) else { return nil }
        return Binding(
            get: { self.chats[idx] },
            set: { newValue in
                self.chats[idx] = newValue
                self.save()
            }
        )
    }

    // MARK: - Mutations

    func newChat() {
        let chat = Chat(title: "New chat")
        chats.insert(chat, at: 0)
        activeChatID = chat.id
        save()
    }

    func deleteChat(id: UUID) {
        chats.removeAll { $0.id == id }
        if activeChatID == id {
            activeChatID = chats.first?.id
            if chats.isEmpty { newChat() }
        }
        save()
    }

    func renameChat(id: UUID, to title: String) {
        guard let idx = chats.firstIndex(where: { $0.id == id }) else { return }
        chats[idx].title = title
        save()
    }

    /// Append a turn to the chat with `id` and bump lastActiveAt.
    func appendTurn(_ turn: ChatTurn, to id: UUID) {
        guard let idx = chats.firstIndex(where: { $0.id == id }) else { return }
        chats[idx].turns.append(turn)
        chats[idx].lastActiveAt = Date()
        if chats[idx].title == "New chat" {
            chats[idx].retitleFromFirstTurn()
        }
        save()
    }

    /// Wipe all turns from a chat (keeps the chat, just empties it).
    func clearChat(_ id: UUID) {
        guard let idx = chats.firstIndex(where: { $0.id == id }) else { return }
        chats[idx].turns = []
        chats[idx].title = "New chat"
        save()
    }

    /// Append text to the last turn (used for streaming chunks).
    func appendChunkToLastTurn(_ text: String, in chatID: UUID) {
        guard let cIdx = chats.firstIndex(where: { $0.id == chatID }),
              let lastIdx = chats[cIdx].turns.indices.last else { return }
        chats[cIdx].turns[lastIdx].text += text
        chats[cIdx].lastActiveAt = Date()
        // Don't save() per chunk — that's a write storm. We save once at the end.
    }

    /// Add a media path to the last turn (used for streaming media events).
    func appendMediaToLastTurn(_ path: String, in chatID: UUID) {
        guard let cIdx = chats.firstIndex(where: { $0.id == chatID }),
              let lastIdx = chats[cIdx].turns.indices.last else { return }
        if !chats[cIdx].turns[lastIdx].media.contains(path) {
            chats[cIdx].turns[lastIdx].media.append(path)
        }
    }

    /// Persist now — call after a streaming response completes.
    func flush() { save() }

    // MARK: - Persistence

    private func save() {
        do {
            let data = try JSONEncoder().encode(chats)
            try data.write(to: fileURL, options: .atomic)
        } catch {
            NSLog("ChatStore save failed: \(error)")
        }
    }

    private func load() {
        guard let data = try? Data(contentsOf: fileURL),
              let decoded = try? JSONDecoder().decode([Chat].self, from: data) else {
            chats = []
            return
        }
        chats = decoded.sorted { $0.lastActiveAt > $1.lastActiveAt }
    }
}
