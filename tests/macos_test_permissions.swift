// Handle only observed test-host prompts. Loopback reading needs no LAN access.
// Do not alter TCC databases or grant access to user folders or other apps.
import AppKit
import ApplicationServices
import Foundation

func attribute(_ element:AXUIElement,_ key:String)->Any?{
    var value:CFTypeRef?
    guard AXUIElementCopyAttributeValue(element,key as CFString,&value) == .success else{return nil}
    return value
}
func descendants(_ element:AXUIElement,_ depth:Int=0)->[AXUIElement]{
    if depth>9{return [element]}
    let children=attribute(element,kAXChildrenAttribute as String) as? [AXUIElement] ?? []
    return [element]+children.flatMap{descendants($0,depth+1)}
}
guard AXIsProcessTrusted() else {print("CI process is not trusted for accessibility");exit(2)}
if CommandLine.arguments.count == 5 && CommandLine.arguments[1] == "click" {
    let apps=NSWorkspace.shared.runningApplications.filter{$0.bundleIdentifier == "com.apple.Safari"}
    guard apps.count == 1,
          let x=Double(CommandLine.arguments[2]),let y=Double(CommandLine.arguments[3]),
          let viewportHeight=Double(CommandLine.arguments[4]) else{exit(3)}
    let root=AXUIElementCreateApplication(apps[0].processIdentifier)
    guard let focused=attribute(root,kAXFocusedWindowAttribute as String) else{exit(4)}
    let window=focused as! AXUIElement
    guard let origin=attribute(window,kAXPositionAttribute as String),
          let extent=attribute(window,kAXSizeAttribute as String) else{exit(5)}
    var position=CGPoint.zero,size=CGSize.zero
    guard AXValueGetValue(origin as! AXValue,.cgPoint,&position),
          AXValueGetValue(extent as! AXValue,.cgSize,&size),
          x>0,x<size.width,y>0,y<viewportHeight else{exit(6)}
    // The page reports its real hit-target rectangle; AX supplies current chrome geometry.
    let point=CGPoint(x:position.x+x,y:position.y+size.height-viewportHeight+y)
    CGEvent(mouseEventSource:nil,mouseType:.leftMouseDown,mouseCursorPosition:point,mouseButton:.left)?.post(tap:.cghidEventTap)
    Thread.sleep(forTimeInterval:0.05)
    CGEvent(mouseEventSource:nil,mouseType:.leftMouseUp,mouseCursorPosition:point,mouseButton:.left)?.post(tap:.cghidEventTap)
    print("Native Safari click at \(point.x), \(point.y)")
    exit(0)
}
let deadline=Date().addingTimeInterval(75)
while Date()<deadline{
    for app in NSWorkspace.shared.runningApplications{
        let root=AXUIElementCreateApplication(app.processIdentifier)
        let windows=attribute(root,kAXWindowsAttribute as String) as? [AXUIElement] ?? []
        for window in windows{
            let nodes=descendants(window)
            let text=nodes.flatMap{node in [kAXTitleAttribute,kAXValueAttribute,kAXDescriptionAttribute].compactMap{attribute(node,$0 as String) as? String}}.joined(separator:" ")
            let automation=text.contains("hosted-compute-agent") && text.contains("control") && (text.contains("Safari") || text.contains("System Events"))
            let localNetwork=text.contains("Python") && text.contains("find devices") && text.contains("local networks")
            guard automation || localNetwork else{continue}
            let title=automation ? "Allow" : "Don’t Allow"
            if let button=nodes.first(where:{(attribute($0,kAXRoleAttribute as String) as? String)=="AXButton" && (attribute($0,kAXTitleAttribute as String) as? String)==title}){
                let result=AXUIElementPerformAction(button,kAXPressAction as CFString)
                print("Observed CI dialog, selected \(title): \(text) / \(result.rawValue)")
                fflush(stdout)
            }
        }
    }
    Thread.sleep(forTimeInterval:0.25)
}
