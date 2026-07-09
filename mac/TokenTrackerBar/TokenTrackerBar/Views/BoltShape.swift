import SwiftUI

/// Lightning bolt shape drawn from the SVG path data.
/// Renders at any size, works as MenuBar icon, header icon, etc.
struct BoltShape: Shape {
    func path(in rect: CGRect) -> Path {
        let svgW: CGFloat = 24
        let svgH: CGFloat = 24
        let scale = min(rect.width / svgW, rect.height / svgH)
        let dx = rect.minX + (rect.width - svgW * scale) / 2
        let dy = rect.minY + (rect.height - svgH * scale) / 2

        func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
            CGPoint(x: dx + x * scale, y: dy + y * scale)
        }

        var p = Path()
        // M3.08378 15.25
        p.move(to: pt(3.08378, 15.25))
        // C1.42044 15.25 0.483971 13.3378 1.5038 12.0237
        p.addCurve(to: pt(1.5038, 12.0237),
                   control1: pt(1.42044, 15.25),
                   control2: pt(0.483971, 13.3378))
        // L10.2099 0.806317
        p.addLine(to: pt(10.2099, 0.806317))
        // C10.794 0.053716 11.9999 0.466765 11.9999 1.41944
        p.addCurve(to: pt(11.9999, 1.41944),
                   control1: pt(10.794, 0.053716),
                   control2: pt(11.9999, 0.466765))
        // V8.74999
        p.addLine(to: pt(11.9999, 8.74999))
        // H20.9159
        p.addLine(to: pt(20.9159, 8.74999))
        // C22.5793 8.74999 23.5157 10.6622 22.4959 11.9762
        p.addCurve(to: pt(22.4959, 11.9762),
                   control1: pt(22.5793, 8.74999),
                   control2: pt(23.5157, 10.6622))
        // L13.7898 23.1937
        p.addLine(to: pt(13.7898, 23.1937))
        // C13.2057 23.9463 11.9999 23.5332 11.9999 22.5805
        p.addCurve(to: pt(11.9999, 22.5805),
                   control1: pt(13.2057, 23.9463),
                   control2: pt(11.9999, 23.5332))
        // V15.25
        p.addLine(to: pt(11.9999, 15.25))
        // H3.08378
        p.addLine(to: pt(3.08378, 15.25))
        p.closeSubpath()
        return p
    }
}

/// Convenience view for the bolt icon at a specific size and color.
struct BoltIcon: View {
    var size: CGFloat = 16
    var color: Color = .primary

    var body: some View {
        BoltShape()
            .fill(color)
            .frame(width: size, height: size)
    }
}
