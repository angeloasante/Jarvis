//
//  FridayApp.swift
//  Friday
//
//  Menu bar entry point for FRIDAY macOS app.
//

import SwiftUI

@main
struct FridayApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        // MenuBarExtra is the modern SwiftUI way to do menu bar apps (macOS 13+)
        MenuBarExtra {
            MenuBarContent()
        } label: {
            // Menu bar icon — replace "bolt.circle.fill" with custom FRIDAY icon later
            Image(systemName: "bolt.circle.fill")
                .foregroundColor(.green)
        }
        .menuBarExtraStyle(.window)  // .window for custom UI, .menu for standard dropdown

        // Settings window (opens via gear icon in menu)
        Settings {
            SettingsView()
        }
    }
}

// MARK: - App Delegate (for lifecycle + hotkey registration later)

class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Hide dock icon — this is a menu bar-only app
        NSApp.setActivationPolicy(.accessory)
    }
}
