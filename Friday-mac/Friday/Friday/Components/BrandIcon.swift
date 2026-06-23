//
//  BrandIcon.swift
//  Friday
//
//  Real brand logos fetched from simpleicons.org CDN, cached locally.
//  For native Apple apps (iMessage, Calendar, Contacts) we use SF Symbols
//  since simpleicons has no brand mark for those.
//

import SwiftUI

enum Brand: String {
    case gmail, google, whatsapp, imessage, sms, twilio, calendar, contacts
    case tv, lgtv, x, twitter, tavily, openrouter, groq, ollama
    case openai, anthropic, googleai, fridayBrand = "friday"
}

struct BrandIcon: View {
    let brand: Brand
    var size: CGFloat = 40

    var body: some View {
        switch brand {
        case .gmail:
            AsyncBrandLogo(slug: "gmail", bg: .white, size: size) {
                letterMark("M", tint: .white, bg: .red)
            }
        case .google, .googleai:
            AsyncBrandLogo(slug: "google", bg: .white, size: size) {
                multiTile(colors: [.red, .yellow, .green, .blue])
            }
        case .whatsapp:
            AsyncBrandLogo(slug: "whatsapp", bg: .white, size: size) {
                shapeMark(system: "message.fill", tint: .white,
                          bg: Color(red: 0.15, green: 0.71, blue: 0.39))
            }
        case .imessage:
            shapeMark(system: "bubble.left.fill", tint: .white,
                      bg: LinearGradient(colors: [Color(red: 0.11, green: 0.74, blue: 0.95),
                                                   Color(red: 0.22, green: 0.52, blue: 1.0)],
                                          startPoint: .top, endPoint: .bottom))
        case .sms, .twilio:
            AsyncBrandLogo(slug: "twilio", bg: .white, size: size) {
                letterMark("T", tint: .white, bg: Color(red: 0.94, green: 0.09, blue: 0.15))
            }
        case .calendar:
            calendarTile()
        case .contacts:
            shapeMark(system: "person.crop.circle.fill", tint: .white, bg: Color.brown)
        case .tv, .lgtv:
            AsyncBrandLogo(slug: "lg", bg: .white, size: size) {
                shapeMark(system: "tv.fill", tint: .white,
                          bg: LinearGradient(colors: [Color(red: 0.82, green: 0.18, blue: 0.45), .purple],
                                              startPoint: .topLeading, endPoint: .bottomTrailing))
            }
        case .x, .twitter:
            AsyncBrandLogo(slug: "x", color: "FFFFFF", bg: .black, size: size) {
                shapeMark(system: "xmark", tint: .white, bg: Color.black, weight: .black)
            }
        case .tavily:
            letterMark("T", tint: .white, bg: Color(red: 0.23, green: 0.66, blue: 0.65))
        case .openrouter:
            AsyncBrandLogo(slug: "openrouter", bg: .white, size: size) {
                letterMark("OR", tint: .white, bg: Color(red: 0.42, green: 0.28, blue: 0.93))
            }
        case .groq:
            AsyncBrandLogo(slug: "groq", bg: .white, size: size) {
                letterMark("G", tint: .white, bg: Color(red: 1.0, green: 0.35, blue: 0.2))
            }
        case .ollama:
            AsyncBrandLogo(slug: "ollama", color: "FFFFFF", bg: .black, size: size) {
                shapeMark(system: "cpu", tint: .white,
                          bg: LinearGradient(colors: [Color(red: 0.9, green: 0.36, blue: 0.55),
                                                      Color(red: 0.63, green: 0.29, blue: 0.82)],
                                              startPoint: .topLeading, endPoint: .bottomTrailing))
            }
        case .openai:
            AsyncBrandLogo(slug: "openai", bg: .white, size: size) {
                letterMark("O", tint: .white, bg: Color(red: 0.06, green: 0.65, blue: 0.52))
            }
        case .anthropic:
            AsyncBrandLogo(slug: "anthropic", bg: .white, size: size) {
                letterMark("A", tint: .white, bg: Color(red: 0.82, green: 0.40, blue: 0.20))
            }
        case .fridayBrand:
            fridayMark()
        }
    }

    // MARK: - Stylised fallback primitives

    private func letterMark(_ text: String, tint: Color, bg: Color) -> some View {
        let corner = size * 0.22
        return ZStack {
            RoundedRectangle(cornerRadius: corner, style: .continuous).fill(bg)
            Text(text)
                .font(.system(size: size * (text.count == 1 ? 0.52 : 0.38),
                              weight: .bold, design: .rounded))
                .foregroundStyle(tint)
                .kerning(-0.5)
        }
        .frame(width: size, height: size)
    }

    private func shapeMark(system: String, tint: Color, bg: some ShapeStyle,
                            weight: Font.Weight = .semibold) -> some View {
        let corner = size * 0.22
        return ZStack {
            RoundedRectangle(cornerRadius: corner, style: .continuous).fill(bg)
            Image(systemName: system)
                .font(.system(size: size * 0.44, weight: weight))
                .foregroundStyle(tint)
        }
        .frame(width: size, height: size)
    }

    private func multiTile(colors: [Color]) -> some View {
        let corner = size * 0.22
        return ZStack {
            RoundedRectangle(cornerRadius: corner, style: .continuous).fill(Color.white)
            let cell = size * 0.3
            VStack(spacing: 2) {
                HStack(spacing: 2) {
                    Circle().fill(colors[0]).frame(width: cell, height: cell)
                    Circle().fill(colors[1]).frame(width: cell, height: cell)
                }
                HStack(spacing: 2) {
                    Circle().fill(colors[2]).frame(width: cell, height: cell)
                    Circle().fill(colors[3]).frame(width: cell, height: cell)
                }
            }
        }
        .frame(width: size, height: size)
    }

    private func calendarTile() -> some View {
        let corner = size * 0.22
        return ZStack(alignment: .top) {
            RoundedRectangle(cornerRadius: corner, style: .continuous).fill(Color.white)
            UnevenRoundedRectangle(topLeadingRadius: corner, topTrailingRadius: corner)
                .fill(Color.red)
                .frame(height: size * 0.3)
            Text("\(Calendar.current.component(.day, from: Date()))")
                .font(.system(size: size * 0.4, weight: .bold, design: .rounded))
                .foregroundStyle(.black)
                .offset(y: size * 0.32)
        }
        .frame(width: size, height: size)
    }

    private func fridayMark() -> some View {
        ZStack {
            Circle()
                .fill(AngularGradient(
                    colors: [.green, .blue, .purple, .pink, .orange, .green],
                    center: .center
                ))
            Circle().fill(Color.black.opacity(0.55)).frame(width: size * 0.55, height: size * 0.55)
            Image(systemName: "bolt.fill")
                .font(.system(size: size * 0.34, weight: .bold))
                .foregroundStyle(.white)
        }
        .frame(width: size, height: size)
    }
}

// MARK: - Integration id → Brand resolver (shared)

func brandForIntegration(_ id: String) -> Brand {
    switch id {
    case "gmail": return .gmail
    case "whatsapp": return .whatsapp
    case "imessage": return .imessage
    case "sms": return .twilio
    case "calendar": return .calendar
    case "contacts": return .contacts
    case "tv": return .lgtv
    case "x": return .x
    case "tavily": return .tavily
    case "openrouter": return .openrouter
    case "groq": return .groq
    case "ollama": return .ollama
    default: return .fridayBrand
    }
}
