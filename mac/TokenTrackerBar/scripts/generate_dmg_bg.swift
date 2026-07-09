#!/usr/bin/env swift

import AppKit
import CoreGraphics
import Foundation

// ==========================================================
// DMG Background — TokenTracker
// Inspired by Sketch/Linear DMG: clean, refined, professional
//
// Coordinate system:
//   Finder: 660x400, Y=0 at TOP
//   CG:     1320x800 @2x, Y=0 at BOTTOM
//   Convert: cg_y = (400 - finder_y) * 2
//
//   App icon:     Finder(170, 180) → CG(340, 440)
//   Apps folder:  Finder(490, 180) → CG(980, 440)
// ==========================================================

let W: CGFloat = 1320
let H: CGFloat = 800

// Icon centers in CG coords (moved up for vertical centering)
let appCX: CGFloat = 340
let appsCX: CGFloat = 980
let iconCY: CGFloat = 440

let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: Int(W), pixelsHigh: Int(H),
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
    isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!

NSGraphicsContext.saveGraphicsState()
let ctx = NSGraphicsContext(bitmapImageRep: rep)!
NSGraphicsContext.current = ctx
let cg = ctx.cgContext
let cs = CGColorSpaceCreateDeviceRGB()

// ── 1. Background — clean gradient with subtle cool tones ──
let c1 = NSColor(red: 0.965, green: 0.968, blue: 0.975, alpha: 1).cgColor  // top: cool white
let c2 = NSColor(red: 0.925, green: 0.928, blue: 0.938, alpha: 1).cgColor  // bottom: soft cool gray
let bg = CGGradient(colorsSpace: cs, colors: [c1, c2] as CFArray, locations: [0, 1])!
cg.drawLinearGradient(bg, start: CGPoint(x: 0, y: H), end: .zero, options: [])

// ── 2. Subtle top highlight — soft glow from top center ──
func radialGlow(_ cx: CGFloat, _ cy: CGFloat, _ r: CGFloat, _ color: NSColor) {
    let g = CGGradient(colorsSpace: cs,
        colors: [color.cgColor,
                 color.withAlphaComponent(0).cgColor] as CFArray, locations: [0, 1])!
    cg.saveGState()
    cg.drawRadialGradient(g, startCenter: CGPoint(x: cx, y: cy), startRadius: 0,
                          endCenter: CGPoint(x: cx, y: cy), endRadius: r, options: [])
    cg.restoreGState()
}

// Large soft glow from top center for depth
radialGlow(W / 2, H + 100, 700, NSColor(white: 1.0, alpha: 0.45))

// ── 3. Soft light pools behind icon positions ──
radialGlow(appCX, iconCY, 200, NSColor(white: 1.0, alpha: 0.5))
radialGlow(appsCX, iconCY, 200, NSColor(white: 1.0, alpha: 0.5))

// ── 3b. Very subtle inner shadow / vignette at edges ──
cg.saveGState()
let vignetteG = CGGradient(colorsSpace: cs,
    colors: [NSColor(white: 0.0, alpha: 0.0).cgColor,
             NSColor(white: 0.0, alpha: 0.04).cgColor] as CFArray, locations: [0.6, 1.0])!
cg.drawRadialGradient(vignetteG,
    startCenter: CGPoint(x: W / 2, y: H / 2), startRadius: 0,
    endCenter: CGPoint(x: W / 2, y: H / 2), endRadius: max(W, H) * 0.7,
    options: .drawsAfterEndLocation)
cg.restoreGState()

// ── 4. THE ARROW — elegant dashed arc with arrowhead ──
// Curved path from app to Applications, slightly arching upward
let arrowColor = NSColor(red: 0.30, green: 0.35, blue: 0.45, alpha: 0.50)

cg.saveGState()
cg.setStrokeColor(arrowColor.cgColor)
cg.setLineWidth(4.0)
cg.setLineCap(.round)
cg.setLineDash(phase: 0, lengths: [12, 8])

// Bezier curve arching slightly above center
let startX = appCX + 150
let endX = appsCX - 150
let controlY = iconCY + 80  // arch upward (CG coords, + is up)

let arrowPath = CGMutablePath()
arrowPath.move(to: CGPoint(x: startX, y: iconCY))
arrowPath.addQuadCurve(to: CGPoint(x: endX, y: iconCY),
                       control: CGPoint(x: (startX + endX) / 2, y: controlY))
cg.addPath(arrowPath)
cg.strokePath()

// Solid arrowhead at the end (no dash)
cg.setLineDash(phase: 0, lengths: [])
cg.setFillColor(arrowColor.cgColor)
cg.setLineWidth(3.5)

// Calculate tangent direction at end of curve for proper arrowhead angle
let t: CGFloat = 0.95
let tangentX = 2 * (1 - t) * ((startX + endX) / 2 - startX) + 2 * t * (endX - (startX + endX) / 2)
let tangentY = 2 * (1 - t) * (controlY - iconCY) + 2 * t * (iconCY - controlY)
let angle = atan2(tangentY, tangentX)

let headLen: CGFloat = 28
let headWidth: CGFloat = 12
let tipX = endX
let tipY = iconCY

let head = CGMutablePath()
head.move(to: CGPoint(x: tipX, y: tipY))
head.addLine(to: CGPoint(x: tipX - headLen * cos(angle) + headWidth * sin(angle),
                         y: tipY - headLen * sin(angle) - headWidth * cos(angle)))
head.addLine(to: CGPoint(x: tipX - headLen * cos(angle) - headWidth * sin(angle),
                         y: tipY - headLen * sin(angle) + headWidth * cos(angle)))
head.closeSubpath()
cg.addPath(head)
cg.fillPath()
cg.restoreGState()

// ── 5. Bottom section — thin separator + text ──
let paraStyle = NSMutableParagraphStyle()
paraStyle.alignment = .center

// Thin separator line
let sepY: CGFloat = 150
cg.setFillColor(NSColor(white: 0.0, alpha: 0.06).cgColor)
cg.fill(CGRect(x: W / 2 - 180, y: sepY, width: 360, height: 1))

// Instruction text
("Drag to Applications to install" as NSString).draw(
    in: NSRect(x: 0, y: 80, width: W, height: 44),
    withAttributes: [
        .font: NSFont.systemFont(ofSize: 22, weight: .regular),
        .foregroundColor: NSColor(red: 0.30, green: 0.30, blue: 0.34, alpha: 0.65),
        .paragraphStyle: paraStyle,
        .kern: 0.3 as NSNumber
    ])

// Brand wordmark
("TOKENTRACKER" as NSString).draw(
    in: NSRect(x: 0, y: 40, width: W, height: 24),
    withAttributes: [
        .font: NSFont.systemFont(ofSize: 13, weight: .medium),
        .foregroundColor: NSColor(white: 0.45, alpha: 0.35),
        .paragraphStyle: paraStyle,
        .kern: 3.0 as NSNumber
    ])

NSGraphicsContext.restoreGraphicsState()

// Set 144 DPI for retina
rep.size = NSSize(width: Int(W) / 2, height: Int(H) / 2)

// Save
let out = URL(fileURLWithPath: CommandLine.arguments[0])
    .deletingLastPathComponent().appendingPathComponent("dmg-background.png")
guard let png = rep.representation(using: .png, properties: [:]) else { exit(1) }
try! png.write(to: out)
print("Done: \(out.path)")
