#!/usr/bin/env swift
import Foundation

let canvasSize: Double = 1024
let safeAreaRatio: Double = 824.0 / 1024.0
let boltPaddingRatio: Double = 0.15

struct Point {
    let x: Double
    let y: Double
}

enum Segment {
    case move(Point)
    case line(Point)
    case curve(Point, Point, Point)
    case close
}

func format(_ value: Double) -> String {
    let rounded = (value * 1000).rounded() / 1000
    if rounded == rounded.rounded() {
        return String(Int(rounded))
    }
    return String(format: "%.3f", rounded)
}

func svgPath(_ segments: [Segment]) -> String {
    segments.map { segment in
        switch segment {
        case .move(let point):
            return "M\(format(point.x)) \(format(point.y))"
        case .line(let point):
            return "L\(format(point.x)) \(format(point.y))"
        case .curve(let control1, let control2, let point):
            return "C\(format(control1.x)) \(format(control1.y)) \(format(control2.x)) \(format(control2.y)) \(format(point.x)) \(format(point.y))"
        case .close:
            return "Z"
        }
    }
    .joined(separator: " ")
}

func transformedPoint(_ x: Double, _ y: Double) -> Point {
	let drawSize = canvasSize * safeAreaRatio
	let safeAreaOrigin = (canvasSize - drawSize) / 2.0
	let paddedDrawSize = drawSize * (1.0 - (boltPaddingRatio * 2.0))
	let drawOrigin = safeAreaOrigin + (drawSize - paddedDrawSize) / 2.0
	let scale = paddedDrawSize / 24.0

	// Preserve the original SVG orientation instead of mirroring it again.
	return Point(
		x: drawOrigin + x * scale,
		y: drawOrigin + y * scale
	)
}

let boltSegments: [Segment] = [
    .move(transformedPoint(3.08378, 15.25)),
    .curve(
        transformedPoint(1.42044, 15.25),
        transformedPoint(0.483971, 13.3378),
        transformedPoint(1.5038, 12.0237)
    ),
    .line(transformedPoint(10.2099, 0.806317)),
    .curve(
        transformedPoint(10.794, 0.053716),
        transformedPoint(11.9999, 0.466765),
        transformedPoint(11.9999, 1.41944)
    ),
    .line(transformedPoint(11.9999, 8.74999)),
    .line(transformedPoint(20.9159, 8.74999)),
    .curve(
        transformedPoint(22.5793, 8.74999),
        transformedPoint(23.5157, 10.6622),
        transformedPoint(22.4959, 11.9762)
    ),
    .line(transformedPoint(13.7898, 23.1937)),
    .curve(
        transformedPoint(13.2057, 23.9463),
        transformedPoint(11.9999, 23.5332),
        transformedPoint(11.9999, 22.5805)
    ),
    .line(transformedPoint(11.9999, 15.25)),
    .line(transformedPoint(3.08378, 15.25)),
    .close
]

let outputDir = CommandLine.arguments.count > 1
    ? URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
    : URL(fileURLWithPath: "TokenTrackerBar/icon_composer", isDirectory: true)

try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)

let backgroundSVG = """
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <rect width="1024" height="1024" fill="#000000"/>
</svg>
"""

let boltSVG = """
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <path fill="#FFFFFF" d="\(svgPath(boltSegments))"/>
</svg>
"""

let readme = """
# Icon Composer Source

These files are the source layers for TokenTrackerBar's macOS 26 app icon workflow.

Files:
- `01-background.svg`: full-bleed square background. Do not add a rounded-rectangle mask here.
- `02-bolt.svg`: foreground glyph positioned inside Apple's safe area.

Recommended import flow:
1. Open `Icon Composer.app` from Xcode beta.
2. Create a new icon document.
3. Drag `01-background.svg` and `02-bolt.svg` into the canvas in that order.
4. Preview the macOS variant and tune material/specular settings as needed.
5. Save the result as `TokenTrackerBar/TokenTrackerBar/AppIcon.icon`.
6. Keep the target app icon name set to `AppIcon` and rebuild TokenTrackerBar.

Apple guidance:
- Keep exported source art flat and unmasked.
- Let Icon Composer or the system apply the rounded-rectangle crop and edge treatment.
"""

try backgroundSVG.write(to: outputDir.appendingPathComponent("01-background.svg"), atomically: true, encoding: .utf8)
try boltSVG.write(to: outputDir.appendingPathComponent("02-bolt.svg"), atomically: true, encoding: .utf8)

if outputDir.lastPathComponent != "Assets" {
	try readme.write(to: outputDir.appendingPathComponent("README.md"), atomically: true, encoding: .utf8)
}

print("Created: \(outputDir.path)/01-background.svg")
print("Created: \(outputDir.path)/02-bolt.svg")
if outputDir.lastPathComponent != "Assets" {
	print("Created: \(outputDir.path)/README.md")
}
