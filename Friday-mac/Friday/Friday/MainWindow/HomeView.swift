//
//  HomeView.swift
//  Friday
//
//  Dashboard — quick status + entry points.
//

import SwiftUI

struct HomeView: View {
    @EnvironmentObject var state: OnboardingState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                header

                sectionGrid

                quickActions

                Spacer(minLength: 40)
            }
            .padding(30)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(red: 0.06, green: 0.06, blue: 0.08))
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(greeting())
                .font(.system(size: 28, weight: .bold, design: .rounded))
            Text("Ready when you are.")
                .font(.system(size: 14))
                .foregroundStyle(.secondary)
        }
    }

    private var sectionGrid: some View {
        let cols = [GridItem(.flexible(), spacing: 14), GridItem(.flexible(), spacing: 14)]
        return LazyVGrid(columns: cols, spacing: 14) {
            StatusCard(
                icon: "envelope.fill", tint: .red,
                title: "Gmail",
                value: state.gmailConnected ? (state.gmailEmail.isEmpty ? "Connected" : state.gmailEmail) : "Not connected",
                connected: state.gmailConnected
            )
            StatusCard(
                icon: "message.fill", tint: .green,
                title: "WhatsApp",
                value: state.whatsappConnected ? "Connected" : "Not connected",
                connected: state.whatsappConnected
            )
            StatusCard(
                icon: "sparkles", tint: .orange,
                title: "AI Provider",
                value: state.llmProvider.displayName,
                connected: !state.llmApiKey.isEmpty || state.llmProvider == .local
            )
            StatusCard(
                icon: "phone.fill", tint: .blue,
                title: "SMS (Twilio)",
                value: state.twilioConnected ? state.twilioNumber : "Not connected",
                connected: state.twilioConnected
            )
        }
    }

    private var quickActions: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Quick actions")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.secondary)
            HStack(spacing: 10) {
                QuickActionButton(icon: "envelope.badge", title: "Check emails")
                QuickActionButton(icon: "calendar", title: "Today's calendar")
                QuickActionButton(icon: "tv", title: "TV status")
                QuickActionButton(icon: "sparkles", title: "Briefing")
            }
        }
    }

    private func greeting() -> String {
        let hour = Calendar.current.component(.hour, from: Date())
        switch hour {
        case 5..<12: return "Morning, Travis."
        case 12..<17: return "Afternoon, Travis."
        case 17..<22: return "Evening, Travis."
        default: return "Late night, Travis."
        }
    }
}

// MARK: - Components

struct StatusCard: View {
    let icon: String
    let tint: Color
    let title: String
    let value: String
    let connected: Bool

    var body: some View {
        HStack(spacing: 12) {
            ZStack {
                Circle().fill(tint.opacity(0.15)).frame(width: 40, height: 40)
                Image(systemName: icon)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(tint)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.system(size: 13, weight: .medium))
                    .lineLimit(1)
            }
            Spacer()
            Circle()
                .fill(connected ? Color.green : Color.white.opacity(0.2))
                .frame(width: 8, height: 8)
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color.white.opacity(0.04))
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
                )
        )
    }
}

struct QuickActionButton: View {
    let icon: String
    let title: String
    @State private var hovering = false

    var body: some View {
        Button {
            // TODO: route through FridayClient
        } label: {
            VStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.system(size: 16))
                Text(title)
                    .font(.system(size: 11, weight: .medium))
            }
            .foregroundStyle(.primary)
            .frame(width: 110, height: 80)
            .background(
                RoundedRectangle(cornerRadius: 10)
                    .fill(Color.white.opacity(hovering ? 0.1 : 0.05))
                    .overlay(
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
                    )
            )
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .animation(.easeInOut(duration: 0.12), value: hovering)
    }
}
