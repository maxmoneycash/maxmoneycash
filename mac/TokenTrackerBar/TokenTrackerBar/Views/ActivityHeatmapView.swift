import SwiftUI

struct ActivityHeatmapView: View {
    let heatmap: HeatmapResponse?

    private let cellSize: CGFloat = 11
    private let spacing: CGFloat = 3

    /// The grid cell the pointer is over, if any. AppKit tooltips (`.help` /
    /// `NSView.toolTip`) don't surface inside this NSPopover-hosted SwiftUI, so —
    /// like UsageLimitsView — we drive our own hint with `.onHover`, shown inline
    /// in the section header instead of a floating tooltip.
    @State private var hovered: HoveredCellKey?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: Strings.activityTitle) {
                if let h = heatmap {
                    headerTrailing(h)
                }
            }

            if let h = heatmap, !h.weeks.isEmpty {
                // Use native SwiftUI views instead of Canvas for reliable rendering
                ScrollViewReader { proxy in
                    ScrollView(.horizontal, showsIndicators: false) {
                        let labels = monthLabels(h)
                        VStack(alignment: .leading, spacing: spacing) {
                            // Month anchors above the grid — a year of cells is
                            // unreadable without a time axis.
                            HStack(alignment: .top, spacing: spacing) {
                                ForEach(Array(labels.enumerated()), id: \.offset) { _, label in
                                    Text(label ?? "")
                                        .font(.system(size: 9))
                                        .foregroundStyle(.tertiary)
                                        .fixedSize()
                                        .frame(width: cellSize, height: 10, alignment: .leading)
                                }
                            }
                            HStack(alignment: .top, spacing: spacing) {
                                ForEach(Array(h.weeks.enumerated()), id: \.offset) { idx, week in
                                    VStack(spacing: spacing) {
                                        ForEach(0..<7, id: \.self) { dayIdx in
                                            cellView(week: week, weekIdx: idx, dayIdx: dayIdx)
                                        }
                                    }
                                    .id(idx)
                                }
                            }
                        }
                    }
                    .onAppear {
                        proxy.scrollTo(h.weeks.count - 1, anchor: .trailing)
                    }
                }

                // Legend
                HStack(spacing: 4) {
                    Spacer()
                    Text(Strings.heatmapLegendLess)
                        .font(.system(size: 9))
                        .foregroundStyle(.tertiary)
                    ForEach(0..<5, id: \.self) { level in
                        RoundedRectangle(cornerRadius: 1.5)
                            .fill(colorForLevel(level))
                            .frame(width: 8, height: 8)
                    }
                    Text(Strings.heatmapLegendMore)
                        .font(.system(size: 9))
                        .foregroundStyle(.tertiary)
                }
            } else {
                RoundedRectangle(cornerRadius: 6)
                    .fill(Color.gray.opacity(0.06))
                    .frame(height: 7 * (cellSize + spacing) - spacing)
            }
        }
        .animation(.easeOut(duration: 0.12), value: hovered)
    }

    // MARK: - Cell

    @ViewBuilder
    private func cellView(week: [HeatmapCell?], weekIdx: Int, dayIdx: Int) -> some View {
        let cell = dayIdx < week.count ? week[dayIdx] : nil
        let level = cell?.level ?? 0
        let key = HoveredCellKey(week: weekIdx, day: dayIdx)
        let isHovered = cell != nil && hovered == key
        RoundedRectangle(cornerRadius: 2)
            .fill(colorForLevel(min(max(level, 0), 4)))
            .frame(width: cellSize, height: cellSize)
            .overlay(
                RoundedRectangle(cornerRadius: 2)
                    .strokeBorder(Color.primary.opacity(isHovered ? 0.55 : 0), lineWidth: 1)
            )
            .onHover { inside in
                // Only meaningful cells (real days) carry a tooltip; grid padding is skipped.
                guard cell != nil else { return }
                if inside {
                    hovered = key
                } else if hovered == key {
                    hovered = nil
                }
            }
    }

    // MARK: - Header trailing

    /// Shows the hovered day's date + token count while hovering, otherwise the
    /// resting "N active days" summary — no layout shift, so the grid stays put.
    @ViewBuilder
    private func headerTrailing(_ h: HeatmapResponse) -> some View {
        if let cell = hoveredCell(in: h) {
            Text(hoverSummary(cell))
                .font(.caption2)
                .foregroundStyle(.secondary)
                .modifier(FontWeightModifier(weight: .medium))
        } else {
            Text(Strings.activeDays(h.activeDays))
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
    }

    private func hoveredCell(in h: HeatmapResponse) -> HeatmapCell? {
        guard let key = hovered,
              key.week >= 0, key.week < h.weeks.count,
              key.day >= 0, key.day < h.weeks[key.week].count
        else { return nil }
        return h.weeks[key.week][key.day]
    }

    private func hoverSummary(_ cell: HeatmapCell) -> String {
        "\(Self.formattedDay(cell.day)) · \(TokenFormatter.formatCompact(cell.totalTokens)) \(Strings.tokensUnit)"
    }

    // MARK: - Month labels

    /// One slot per week column; a localized month name where the month first
    /// changes, nil elsewhere. Labels overflow their 11pt slot to the right —
    /// months are ≥4 columns apart so they never collide.
    private func monthLabels(_ h: HeatmapResponse) -> [String?] {
        var labels: [String?] = []
        var lastMonth: Substring?
        for week in h.weeks {
            guard let day = week.compactMap({ $0?.day }).first, day.count >= 7 else {
                labels.append(nil)
                continue
            }
            let month = day.prefix(7) // "yyyy-MM"
            if month != lastMonth {
                labels.append(Self.formattedMonth(day))
                lastMonth = month
            } else {
                labels.append(nil)
            }
        }
        return labels
    }

    /// Localizes a `yyyy-MM-dd` day into a short standalone month label
    /// (e.g. "Jun" / "6月").
    private static func formattedMonth(_ iso: String) -> String? {
        guard let date = isoDayParser.date(from: iso) else { return nil }
        let out = DateFormatter()
        out.locale = Locale(identifier: NativeLocalization.currentResolvedLocale)
        out.timeZone = TimeZone(identifier: "UTC")
        out.setLocalizedDateFormatFromTemplate("MMM")
        return out.string(from: date)
    }

    // MARK: - Helpers

    private func colorForLevel(_ level: Int) -> Color {
        let clamped = min(max(level, 0), Color.heatmapLevels.count - 1)
        return Color.heatmapLevels[clamped]
    }

    /// Parses the `yyyy-MM-dd` day string in UTC (heatmap days are bucketed in UTC).
    private static let isoDayParser: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = TimeZone(identifier: "UTC")
        return f
    }()

    /// Localizes a `yyyy-MM-dd` heatmap day into a short month/day label
    /// (e.g. "Jun 14" / "6月14日"). Falls back to the raw string if unparsable.
    private static func formattedDay(_ iso: String) -> String {
        guard let date = isoDayParser.date(from: iso) else { return iso }
        let out = DateFormatter()
        out.locale = Locale(identifier: NativeLocalization.currentResolvedLocale)
        out.timeZone = TimeZone(identifier: "UTC")
        out.setLocalizedDateFormatFromTemplate("MMMd")
        return out.string(from: date)
    }
}

private struct HoveredCellKey: Equatable {
    let week: Int
    let day: Int
}
