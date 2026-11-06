// Validate Apple's actual PDFKit renderer/text extractor, used by macOS readers.
import AppKit
import PDFKit
import Foundation

func render(_ page: PDFPage) -> Data {
    let rect=page.bounds(for:.mediaBox)
    let bitmap=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:Int(ceil(rect.width*1.5)),pixelsHigh:Int(ceil(rect.height*1.5)),bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    let context=NSGraphicsContext(bitmapImageRep:bitmap)!.cgContext
    context.setFillColor(NSColor.white.cgColor);context.fill(CGRect(x:0,y:0,width:CGFloat(bitmap.pixelsWide),height:CGFloat(bitmap.pixelsHigh)))
    context.scaleBy(x:1.5,y:1.5);page.draw(with:.mediaBox,to:context)
    return Data(bytes:bitmap.bitmapData!,count:bitmap.bytesPerRow*bitmap.pixelsHigh)
}
let args=CommandLine.arguments
guard args.count==4,let source=PDFDocument(url:URL(fileURLWithPath:args[1])),let off=PDFDocument(url:URL(fileURLWithPath:args[2])),let active=PDFDocument(url:URL(fileURLWithPath:args[3])) else {fatalError("Expected source, switchable and static PDFs")}
precondition(source.pageCount==13&&off.pageCount==13&&active.pageCount==13)
for i in 0..<source.pageCount {
    let a=source.page(at:i)!,b=off.page(at:i)!,c=active.page(at:i)!
    precondition(a.string==b.string&&a.string==c.string,"PDFKit text changed on page \(i+1)")
    let original=render(a)
    precondition(original==render(b),"PDFKit default layer changed original pixels on page \(i+1)")
    precondition(original != render(c),"PDFKit static emphasis missing on page \(i+1)")
}
print("Apple PDFKit: all 13 language samples, original text, default pixels and static emphasis passed")
