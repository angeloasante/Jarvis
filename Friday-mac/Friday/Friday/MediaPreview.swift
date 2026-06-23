//
//  MediaPreview.swift
//  Friday
//
//  Detects file paths in FRIDAY responses and renders previews
//  (images, videos, PDFs, audio). Click to open in default app.
//

import SwiftUI
import AppKit
import AVKit
import QuickLookThumbnailing

// MARK: - Media preview

struct MediaPreview: View {
    let path: String
    @State private var hovering = false
    @State private var thumbnail: NSImage?

    private var fileURL: URL {
        URL(fileURLWithPath: path)
    }

    private var mediaKind: MediaKind {
        let ext = fileURL.pathExtension.lowercased()
        if ["png", "jpg", "jpeg", "gif", "webp", "heic", "bmp", "tiff"].contains(ext) {
            return .image
        }
        if ["mp4", "mov", "m4v"].contains(ext) {
            return .video
        }
        if ["mp3", "m4a", "wav"].contains(ext) {
            return .audio
        }
        if ext == "pdf" {
            return .pdf
        }
        return .document
    }

    var body: some View {
        Button(action: { openFile() }) {
            previewContent
                .scaleEffect(hovering ? 1.01 : 1.0)
                .animation(.easeInOut(duration: 0.12), value: hovering)
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .onAppear(perform: loadThumbnail)
    }

    @ViewBuilder
    private var previewContent: some View {
        switch mediaKind {
        case .image:
            imageThumbnail
        case .pdf, .video, .audio, .document:
            fileCard
        }
    }

    // MARK: Image preview

    private var imageThumbnail: some View {
        ZStack(alignment: .topTrailing) {
            Group {
                if let thumbnail = thumbnail {
                    Image(nsImage: thumbnail)
                        .resizable()
                        .scaledToFill()
                } else if let direct = NSImage(contentsOfFile: path) {
                    Image(nsImage: direct)
                        .resizable()
                        .scaledToFill()
                } else {
                    fileCard  // Fallback if image can't load
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 160)
            .clipped()
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(Color.white.opacity(0.1), lineWidth: 0.5)
            )

            // Hover overlay with "open" icon
            if hovering {
                Image(systemName: "arrow.up.forward.app.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(.white)
                    .padding(6)
                    .background(Circle().fill(.black.opacity(0.5)))
                    .padding(8)
                    .transition(.scale.combined(with: .opacity))
            }
        }
    }

    // MARK: Generic file card (for PDFs, videos, audio, etc.)

    private var fileCard: some View {
        HStack(spacing: 10) {
            ZStack {
                RoundedRectangle(cornerRadius: 6)
                    .fill(tintColor.opacity(0.2))
                    .frame(width: 40, height: 40)
                Image(systemName: iconName)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(tintColor)
            }

            VStack(alignment: .leading, spacing: 1) {
                Text(fileURL.lastPathComponent)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                Text(fileSizeString())
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 4)

            Image(systemName: "arrow.up.forward")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(.secondary)
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color.white.opacity(hovering ? 0.1 : 0.06))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
        )
    }

    private var iconName: String {
        switch mediaKind {
        case .image: return "photo"
        case .video: return "video"
        case .audio: return "waveform"
        case .pdf: return "doc.richtext"
        case .document: return "doc"
        }
    }

    private var tintColor: Color {
        switch mediaKind {
        case .image: return .blue
        case .video: return .purple
        case .audio: return .pink
        case .pdf: return .red
        case .document: return .gray
        }
    }

    // MARK: Actions

    private func openFile() {
        NSWorkspace.shared.open(fileURL)
    }

    private func loadThumbnail() {
        guard mediaKind == .video || mediaKind == .pdf else { return }
        let size = CGSize(width: 320, height: 160)
        let scale = NSScreen.main?.backingScaleFactor ?? 2.0
        let request = QLThumbnailGenerator.Request(
            fileAt: fileURL,
            size: size,
            scale: scale,
            representationTypes: .thumbnail
        )
        QLThumbnailGenerator.shared.generateBestRepresentation(for: request) { rep, _ in
            DispatchQueue.main.async {
                self.thumbnail = rep?.nsImage
            }
        }
    }

    private func fileSizeString() -> String {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path),
              let size = attrs[.size] as? NSNumber else {
            return fileURL.pathExtension.uppercased()
        }
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        return "\(formatter.string(fromByteCount: size.int64Value)) · \(fileURL.pathExtension.uppercased())"
    }
}

enum MediaKind {
    case image, video, audio, pdf, document
}

#Preview {
    VStack(spacing: 12) {
        MediaPreview(path: "/Users/travismoore/Downloads/friday_screenshots/screenshot_20260412_055345.png")
        MediaPreview(path: "/Users/travismoore/Documents/sample.pdf")
    }
    .frame(width: 340)
    .padding()
    .background(Color.black)
}
