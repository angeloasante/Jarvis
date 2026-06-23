//
//  AsyncBrandLogo.swift
//  Friday
//
//  Fetches real brand logos from simpleicons.org's CDN, caches them on disk,
//  and falls back to a stylised mark while loading / on failure.
//
//  simpleicons.org returns single-colour SVGs — macOS 14+ decodes SVG natively
//  via NSImage, so we just hand the data to NSImage and display it.
//

import SwiftUI

struct AsyncBrandLogo<Fallback: View>: View {
    /// simpleicons.org slug (e.g. "gmail", "whatsapp", "groq")
    let slug: String
    /// Optional hex colour (no "#"). Defaults to the brand's official colour.
    var color: String?
    /// Background tile colour behind the logo.
    var bg: Color = .white
    /// Inner padding as a fraction of size (0.22 = 22%)
    var inset: CGFloat = 0.22
    let size: CGFloat
    let fallback: () -> Fallback

    @State private var image: NSImage?
    @State private var failed: Bool = false

    private var url: URL? {
        let base = "https://cdn.simpleicons.org/\(slug)"
        let full = color.map { "\(base)/\($0)" } ?? base
        return URL(string: full)
    }

    var body: some View {
        let corner = size * 0.22
        ZStack {
            RoundedRectangle(cornerRadius: corner, style: .continuous)
                .fill(bg)

            if let image {
                Image(nsImage: image)
                    .resizable()
                    .renderingMode(.original)
                    .scaledToFit()
                    .padding(size * inset)
            } else if failed {
                fallback()
            } else {
                ProgressView()
                    .controlSize(.small)
                    .opacity(0.4)
            }
        }
        .frame(width: size, height: size)
        .task(id: slug) {
            await load()
        }
    }

    private func load() async {
        guard image == nil, !failed, let url else { return }
        do {
            if let cached = LogoCache.shared.image(for: url) {
                self.image = cached
                return
            }
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  let img = NSImage(data: data) else {
                self.failed = true
                return
            }
            LogoCache.shared.store(image: img, for: url)
            self.image = img
        } catch {
            self.failed = true
        }
    }
}

// MARK: - Simple disk + memory cache

final class LogoCache {
    static let shared = LogoCache()

    private let cache = NSCache<NSURL, NSImage>()
    private let dir: URL

    private init() {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first!
        self.dir = base.appendingPathComponent("BrandLogos", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    func image(for url: URL) -> NSImage? {
        if let hit = cache.object(forKey: url as NSURL) { return hit }
        let disk = fileURL(for: url)
        if let data = try? Data(contentsOf: disk), let img = NSImage(data: data) {
            cache.setObject(img, forKey: url as NSURL)
            return img
        }
        return nil
    }

    func store(image: NSImage, for url: URL) {
        cache.setObject(image, forKey: url as NSURL)
        if let data = image.tiffRepresentation {
            try? data.write(to: fileURL(for: url))
        }
    }

    private func fileURL(for url: URL) -> URL {
        let name = url.absoluteString
            .replacingOccurrences(of: "[^A-Za-z0-9.-]", with: "_", options: .regularExpression)
        return dir.appendingPathComponent(name)
    }
}
