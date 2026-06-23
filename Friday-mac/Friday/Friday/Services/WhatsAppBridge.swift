//
//  WhatsAppBridge.swift
//  Friday
//
//  Talks to the local Baileys HTTP bridge (friday/whatsapp/server.js).
//  The bridge runs on localhost:3100 and exposes:
//    GET /status → { status: "connected" | "qr_pending" | ... , qr: "<QR string>" }
//
//  On connected, we flip state. On qr_pending, we render the QR image for the user to scan.
//

import Foundation
import AppKit
import CoreImage.CIFilterBuiltins

enum WhatsAppStatus {
    case idle                  // haven't polled yet / unknown
    case needsQR(NSImage)      // show this QR code
    case connected             // done
    case bridgeDown            // Baileys server isn't running

    var message: String {
        switch self {
        case .idle: "Starting WhatsApp bridge…"
        case .needsQR: "Scan with your phone"
        case .connected: "Connected"
        case .bridgeDown: "Bridge not running. Will start automatically."
        }
    }
}

enum WhatsAppBridge {
    private static let bridgeURL = URL(string: "http://localhost:3100/status")!

    static func fetchStatus() async -> WhatsAppStatus {
        // Ensure the bridge is running — try to start it if not
        await ensureBridgeRunning()

        var req = URLRequest(url: bridgeURL)
        req.timeoutInterval = 2

        do {
            let (data, _) = try await URLSession.shared.data(for: req)
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return .bridgeDown
            }

            let status = (json["status"] as? String) ?? ""
            if status == "connected" {
                return .connected
            }

            // qr_pending → render the QR string as an image
            if let qr = json["qr"] as? String, !qr.isEmpty, let img = renderQR(qr) {
                return .needsQR(img)
            }

            return .idle
        } catch {
            return .bridgeDown
        }
    }

    // MARK: - Bridge lifecycle

    private static func ensureBridgeRunning() async {
        // Quick check — does port 3100 answer?
        var req = URLRequest(url: bridgeURL)
        req.timeoutInterval = 1
        if (try? await URLSession.shared.data(for: req)) != nil {
            return
        }

        // Not running. Try to start from the bundled path or repo.
        let bundleWA = Bundle.main.resourceURL?
            .appendingPathComponent("whatsapp/server.js").path
        let repoWA = "/Users/\(NSUserName())/Desktop/JARVIS/friday/whatsapp/server.js"
        let script = (bundleWA.map { FileManager.default.fileExists(atPath: $0) ? $0 : nil } ?? nil)
            ?? (FileManager.default.fileExists(atPath: repoWA) ? repoWA : nil)

        guard let script else { return }

        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/zsh")
        p.arguments = ["-lc", "cd \(URL(fileURLWithPath: script).deletingLastPathComponent().path) && node server.js > /tmp/friday_whatsapp.log 2>&1 &"]
        try? p.run()
    }

    // MARK: - QR rendering

    private static func renderQR(_ string: String) -> NSImage? {
        let data = Data(string.utf8)
        let filter = CIFilter.qrCodeGenerator()
        filter.message = data
        filter.correctionLevel = "M"
        guard let ciImage = filter.outputImage else { return nil }

        // Scale up so the QR is crisp at 220px
        let scaled = ciImage.transformed(by: CGAffineTransform(scaleX: 10, y: 10))
        let rep = NSCIImageRep(ciImage: scaled)
        let ns = NSImage(size: rep.size)
        ns.addRepresentation(rep)
        return ns
    }
}
