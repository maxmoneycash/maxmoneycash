import SwiftUI

extension Color {
    /// Primary accent used for emphasis throughout the app.
    static let brand = Color.accentColor

    /// Heatmap level colors using the brand accent, indexed 0-4.
    static let heatmapLevels: [Color] = [
        Color(.sRGB, red: 0.5, green: 0.5, blue: 0.5, opacity: 0.10),  // level 0 — empty
        Color.accentColor.opacity(0.25),                                  // level 1
        Color.accentColor.opacity(0.50),                                  // level 2
        Color.accentColor.opacity(0.75),                                  // level 3
        Color.accentColor,                                                // level 4
    ]

    /// Trend chart fill gradient.
    static let trendFill = Color.accentColor.opacity(0.15)

    /// Trend chart line color.
    static let trendLine = Color.accentColor

    /// Refined dot colors for model list, ordered by rank.
    private static let modelDotPalette: [Color] = [
        Color(.sRGB, red: 0.35, green: 0.55, blue: 0.95, opacity: 1.0),  // soft blue
        Color(.sRGB, red: 0.60, green: 0.45, blue: 0.90, opacity: 1.0),  // lavender
        Color(.sRGB, red: 0.30, green: 0.72, blue: 0.65, opacity: 1.0),  // teal
        Color(.sRGB, red: 0.90, green: 0.55, blue: 0.35, opacity: 1.0),  // warm amber
        Color(.sRGB, red: 0.70, green: 0.50, blue: 0.75, opacity: 1.0),  // muted plum
    ]

    /// Returns a dot color for model list by rank index.
    static func modelDot(index: Int) -> Color {
        modelDotPalette[index % modelDotPalette.count]
    }

    // MARK: - Usage Limit Bars

    /// Track background for usage limit progress bars.
    static let limitTrack = Color.gray.opacity(0.10)

    /// Usage limit bar color by fraction (0.0–1.0): green → amber → red as the
    /// window fills. Unified across providers (no per-provider brand tint).
    static func limitBar(fraction: Double) -> Color {
        if fraction >= 0.9 { return Color(.sRGB, red: 0.90, green: 0.30, blue: 0.30, opacity: 1.0) }
        if fraction >= 0.7 { return Color(.sRGB, red: 0.85, green: 0.65, blue: 0.20, opacity: 1.0) }
        return Color(.sRGB, red: 0.20, green: 0.72, blue: 0.40, opacity: 1.0)
    }

    /// Returns a brand color for the given AI source/provider name.
    static func sourceColor(_ source: String) -> Color {
        switch source.lowercased() {
        case "claude":    return .purple
        case "codex":     return .green
        case "gemini":    return .blue
        case "opencode":  return .orange
        case "openclaw":  return .pink
        case "cursor":    return .yellow
        case "everycode": return .cyan
        default:          return .gray
        }
    }
}
