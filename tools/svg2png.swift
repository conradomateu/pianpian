// Render an SVG to a square PNG with what macOS already has (no Inkscape, no rsvg).
//   swiftc -O svg2png.swift -o svg2png && ./svg2png in.svg out.png 1024
import AppKit

let a = CommandLine.arguments
guard a.count == 4, let size = Int(a[3]), let img = NSImage(contentsOf: URL(fileURLWithPath: a[1])) else {
    FileHandle.standardError.write("usage: svg2png in.svg out.png size\n".data(using: .utf8)!)
    exit(1)
}
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8, samplesPerPixel: 4,
                           hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
img.draw(in: NSRect(x: 0, y: 0, width: size, height: size))
NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: a[2]))
