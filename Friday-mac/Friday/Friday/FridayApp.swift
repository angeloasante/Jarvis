//
//  FridayApp.swift
//  Friday
//
//  Menu bar entry point for FRIDAY macOS app.
//  Uses NSStatusItem + NSPopover for stable popover behaviour
//  (SwiftUI's MenuBarExtra dismisses on focus loss — no good for text input).
//

import SwiftUI
import AppKit

@main
struct FridayApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var onboarding = OnboardingState.shared

    var body: some Scene {
        // Main app window — sidebar + content.
        // Opens on first launch for onboarding, then stays available.
        WindowGroup("FRIDAY", id: "main") {
            MainWindowView()
                .environmentObject(onboarding)
                .frame(minWidth: 780, minHeight: 560)
        }
        .defaultSize(width: 960, height: 620)
        .windowResizability(.contentMinSize)
        .windowStyle(.hiddenTitleBar)  // chat-app look: no titlebar, traffic lights float
        .commands {
            CommandGroup(replacing: .newItem) { }  // hide File > New Window
            CommandGroup(replacing: .toolbar) { }  // hide View > Toggle Toolbar
        }

        // Native preferences window (Cmd+,)
        Settings {
            SettingsView()
                .environmentObject(onboarding)
        }
    }
}

// MARK: - App Delegate

class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var popover: NSPopover!
    private var eventMonitor: EventMonitor?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // .regular: dock icon + main window + menu bar item, all three.
        // Users who prefer menu-bar-only can hide dock icon from Settings later.
        NSApp.setActivationPolicy(.regular)

        // Create status bar item
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)

        if let button = statusItem.button {
            // Green bolt. NSImage with tint.
            let config = NSImage.SymbolConfiguration(pointSize: 14, weight: .semibold)
            if let image = NSImage(systemSymbolName: "bolt.fill", accessibilityDescription: "FRIDAY")?
                .withSymbolConfiguration(config) {
                image.isTemplate = false  // We want green, not theme tint
                button.image = image.tinted(with: NSColor.systemGreen)
            }
            button.target = self
            button.action = #selector(togglePopover(_:))
        }

        // Popover containing the SwiftUI content.
        // NSHostingController with .preferredContentSize auto-resizes
        // when the SwiftUI view's intrinsic size changes (e.g. response area appears).
        popover = NSPopover()
        popover.behavior = .transient  // Close on click outside, NOT on text input
        popover.animates = true
        let hosting = NSHostingController(rootView: MenuBarContent())
        hosting.sizingOptions = [.preferredContentSize]
        popover.contentViewController = hosting

        // Close popover when user clicks outside the app window
        eventMonitor = EventMonitor(mask: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            if let popover = self?.popover, popover.isShown {
                self?.closePopover()
            }
        }
    }

    @objc func togglePopover(_ sender: Any?) {
        guard let button = statusItem.button else { return }

        if popover.isShown {
            closePopover()
        } else {
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            // Bring app to foreground so text field can receive keystrokes
            NSApp.activate(ignoringOtherApps: true)
            eventMonitor?.start()
        }
    }

    private func closePopover() {
        popover.performClose(nil)
        eventMonitor?.stop()
    }
}

// MARK: - Global event monitor (detects clicks outside popover)

final class EventMonitor {
    private var monitor: Any?
    private let mask: NSEvent.EventTypeMask
    private let handler: (NSEvent?) -> Void

    init(mask: NSEvent.EventTypeMask, handler: @escaping (NSEvent?) -> Void) {
        self.mask = mask
        self.handler = handler
    }

    deinit { stop() }

    func start() {
        monitor = NSEvent.addGlobalMonitorForEvents(matching: mask, handler: handler)
    }

    func stop() {
        if let monitor = monitor {
            NSEvent.removeMonitor(monitor)
            self.monitor = nil
        }
    }
}

// MARK: - NSImage tint helper

extension NSImage {
    func tinted(with color: NSColor) -> NSImage {
        let image = self.copy() as! NSImage
        image.lockFocus()
        color.set()
        let rect = NSRect(origin: .zero, size: image.size)
        rect.fill(using: .sourceAtop)
        image.unlockFocus()
        image.isTemplate = false
        return image
    }
}
