import AppKit

let size: CGFloat = 1024
let image = NSImage(size: NSSize(width: size, height: size))
image.lockFocus()
NSGraphicsContext.current?.imageInterpolation = .high

let tile = NSBezierPath(roundedRect: NSRect(x: 72, y: 72, width: 880, height: 880),
                        xRadius: 210, yRadius: 210)
NSColor(srgbRed: 0.85, green: 0.93, blue: 0.67, alpha: 1).setFill()
tile.fill()

let arrow = NSBezierPath()
arrow.lineWidth = 76
arrow.lineCapStyle = .round
arrow.lineJoinStyle = .round
arrow.move(to: NSPoint(x: 323, y: 331))
arrow.line(to: NSPoint(x: 699, y: 707))
arrow.move(to: NSPoint(x: 489, y: 707))
arrow.line(to: NSPoint(x: 699, y: 707))
arrow.line(to: NSPoint(x: 699, y: 497))
NSColor(srgbRed: 0.07, green: 0.21, blue: 0.18, alpha: 1).setStroke()
arrow.stroke()

image.unlockFocus()
guard let tiff = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let png = bitmap.representation(using: .png, properties: [:]) else {
    fatalError("Could not render Clearview icon")
}
try png.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
