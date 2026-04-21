//
//  MenuBarContent.swift
//  Friday
//
//  What appears when you click the menu bar icon.
//

import SwiftUI

struct MenuBarContent: View {
    @State private var commandText: String = ""
    @State private var status: String = "Ready."
    @State private var response: String = ""
    @State private var isProcessing: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack {
                Image(systemName: "bolt.circle.fill")
                    .foregroundColor(.green)
                Text("FRIDAY")
                    .font(.headline)
                Spacer()
                Circle()
                    .fill(isProcessing ? Color.orange : Color.green)
                    .frame(width: 8, height: 8)
            }
            .padding(12)
            .background(Color(NSColor.windowBackgroundColor))

            Divider()

            // Command input
            VStack(alignment: .leading, spacing: 8) {
                TextField("Ask FRIDAY…", text: $commandText)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit {
                        send()
                    }

                Text(status)
                    .font(.caption)
                    .foregroundColor(.secondary)

                if !response.isEmpty {
                    ScrollView {
                        Text(response)
                            .font(.system(.body, design: .monospaced))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 200)
                    .padding(8)
                    .background(Color(NSColor.textBackgroundColor))
                    .cornerRadius(6)
                }
            }
            .padding(12)

            Divider()

            // Footer actions
            HStack {
                Button("Settings…") {
                    NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
                }
                .buttonStyle(.plain)
                .font(.caption)

                Spacer()

                Button("Quit") {
                    NSApplication.shared.terminate(nil)
                }
                .buttonStyle(.plain)
                .font(.caption)
                .foregroundColor(.red)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
        .frame(width: 360)
    }

    // MARK: - Send command to FridayCore

    private func send() {
        guard !commandText.isEmpty else { return }
        let input = commandText
        commandText = ""
        status = "Processing…"
        response = ""
        isProcessing = true

        Task {
            let result = await FridayClient.shared.send(input)
            await MainActor.run {
                response = result
                status = "Ready."
                isProcessing = false
            }
        }
    }
}

#Preview {
    MenuBarContent()
}
