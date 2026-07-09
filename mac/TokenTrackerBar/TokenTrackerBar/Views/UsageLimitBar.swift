import SwiftUI

/// Usage-limit progress bar drawn in a single `Canvas`, mirroring CodexBar's
/// `UsageProgressBar` line logic.
///
/// Why a single Canvas: it paints track, fill, warning markers and the pace tip
/// in one pass with plain Core Graphics — no SwiftUI `.blendMode` /
/// `.compositingGroup` modifiers, which trigger the macOS 26 Metal shader crash
/// (CodexBar issue #805). All compositing stays inside the Canvas.
///
/// The pace tip is CodexBar's "notch" style: a small punched-out gap at the pace
/// position with a colored center stripe (green = on/under pace, red = ahead of
/// pace). Punching first means the stripe sits over cleared pixels, so it stays
/// visible even when its color matches the fill underneath. Warning markers are
/// thin rounded ticks at configured threshold percentages.
struct UsageLimitBar: View, Animatable {
    /// Filled portion, 0...100, already adjusted for used/remaining mode.
    var percent: Double

    /// Interpolates `percent` so fill changes animate when the caller attaches
    /// `.animation(_:value:)` — Canvas alone doesn't tween its inputs.
    var animatableData: Double {
        get { percent }
        set { percent = newValue }
    }
    /// Fill color (the unified green→amber→red threshold color).
    let fillColor: Color
    /// Pace position, 0...100 in the same display space as `percent`; `nil` hides the tip.
    let pacePercent: Double?
    /// True when ahead of pace (deficit) → red stripe; false → green.
    let paceOver: Bool

    var height: CGFloat = 6
    @Environment(\.displayScale) private var displayScale

    var body: some View {
        Canvas { context, size in
            let scale = max(displayScale, 1)
            let align: (CGFloat) -> CGFloat = { ($0 * scale).rounded() / scale }
            let radius = size.height / 2
            let cornerSize = CGSize(width: radius, height: radius)
            let rect = CGRect(origin: .zero, size: size)
            context.clip(to: Path(rect))

            // Track.
            context.fill(Path { $0.addRoundedRect(in: rect, cornerSize: cornerSize) },
                         with: .color(Color.limitTrack))

            // Fill.
            let clamped = min(100, max(0, percent))
            let fillWidth = size.width * clamped / 100
            if fillWidth > 0 {
                let fillRect = CGRect(x: 0, y: 0, width: max(size.height, min(fillWidth, size.width)), height: size.height)
                context.fill(Path { $0.addRoundedRect(in: fillRect, cornerSize: cornerSize) },
                             with: .color(fillColor))
            }

            // Pace tip: punch a small gap, then draw a colored center stripe in it.
            if let pacePercent {
                let x = align(size.width * min(100, max(0, pacePercent)) / 100)
                let punchWidth = align(6)
                let stripeWidth = align(2)
                let extend = size.height

                let gap = CGRect(x: x - punchWidth / 2, y: -extend, width: punchWidth, height: size.height + extend * 2)
                context.blendMode = .destinationOut
                context.fill(Path(gap), with: .color(.white))
                context.blendMode = .normal

                let stripe = CGRect(x: x - stripeWidth / 2, y: 0, width: stripeWidth, height: size.height)
                context.fill(Path(stripe), with: .color(paceOver ? Self.deficitColor : Self.onPaceColor))
            }
        }
        .frame(height: height)
        .accessibilityHidden(true)
    }

    private static let onPaceColor = Color(.sRGB, red: 0.20, green: 0.72, blue: 0.40, opacity: 1.0)
    private static let deficitColor = Color(.sRGB, red: 0.90, green: 0.30, blue: 0.30, opacity: 1.0)
}
