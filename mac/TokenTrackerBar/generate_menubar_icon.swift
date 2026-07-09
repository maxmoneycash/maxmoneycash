#!/usr/bin/env swift
import AppKit
import CoreGraphics

func createBoltPath(in rect: CGRect) -> NSBezierPath {
    let path = NSBezierPath()
    let svgSize: CGFloat = 24
    let padding: CGFloat = rect.width * 0.10
    let drawRect = rect.insetBy(dx: padding, dy: padding)
    let scale = min(drawRect.width / svgSize, drawRect.height / svgSize)
    let ox = drawRect.minX + (drawRect.width - svgSize * scale) / 2
    let oy = drawRect.minY + (drawRect.height - svgSize * scale) / 2

    func p(_ x: CGFloat, _ y: CGFloat) -> NSPoint {
        NSPoint(x: ox + x * scale, y: oy + (svgSize - y) * scale)
    }

    path.move(to: p(3.08378, 15.25))
    path.curve(to: p(1.5038, 12.0237),
               controlPoint1: p(1.42044, 15.25),
               controlPoint2: p(0.483971, 13.3378))
    path.line(to: p(10.2099, 0.806317))
    path.curve(to: p(11.9999, 1.41944),
               controlPoint1: p(10.794, 0.053716),
               controlPoint2: p(11.9999, 0.466765))
    path.line(to: p(11.9999, 8.74999))
    path.line(to: p(20.9159, 8.74999))
    path.curve(to: p(22.4959, 11.9762),
               controlPoint1: p(22.5793, 8.74999),
               controlPoint2: p(23.5157, 10.6622))
    path.line(to: p(13.7898, 23.1937))
    path.curve(to: p(11.9999, 22.5805),
               controlPoint1: p(13.2057, 23.9463),
               controlPoint2: p(11.9999, 23.5332))
    path.line(to: p(11.9999, 15.25))
    path.line(to: p(3.08378, 15.25))
    path.close()

    return path
}

func generateMenuBarIcon(size: Int) -> NSImage {
    let image = NSImage(size: NSSize(width: size, height: size))
    image.lockFocus()

    // Transparent background - no fill
    let rect = NSRect(x: 0, y: 0, width: size, height: size)

    // Black bolt (template image: macOS uses black shape on transparent bg)
    NSColor.black.setFill()
    createBoltPath(in: rect).fill()

    image.unlockFocus()
    return image
}

func savePNG(_ image: NSImage, to path: String) {
    guard let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let png = bitmap.representation(using: .png, properties: [:]) else {
        print("Failed: \(path)")
        return
    }
    try! png.write(to: URL(fileURLWithPath: path))
    print("Created: \(path)")
}

let outputDir = CommandLine.arguments.count > 1
    ? CommandLine.arguments[1]
    : "TokenTrackerBar/TokenTrackerBar/Assets.xcassets/MenuBarIcon.imageset"

try? FileManager.default.createDirectory(atPath: outputDir, withIntermediateDirectories: true)

savePNG(generateMenuBarIcon(size: 18), to: "\(outputDir)/menubar_18.png")
savePNG(generateMenuBarIcon(size: 36), to: "\(outputDir)/menubar_36.png")
print("Done!")
