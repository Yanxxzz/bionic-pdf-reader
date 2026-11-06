// Approve only the two observed automation prompts on an ephemeral CI host.
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
let deadline=Date().addingTimeInterval(75)
while Date()<deadline{
    for app in NSWorkspace.shared.runningApplications{
        let bundle=app.bundleIdentifier ?? ""
        guard bundle=="com.apple.UserNotificationCenter" || bundle=="com.apple.CoreServicesUIAgent" else{continue}
        let root=AXUIElementCreateApplication(app.processIdentifier)
        let windows=attribute(root,kAXWindowsAttribute as String) as? [AXUIElement] ?? []
        for window in windows{
            let nodes=descendants(window)
            let text=nodes.flatMap{node in [kAXTitleAttribute,kAXValueAttribute,kAXDescriptionAttribute].compactMap{attribute(node,$0 as String) as? String}}.joined(separator:" ")
            guard text.contains("hosted-compute-agent"),text.contains("control"),text.contains("Safari") || text.contains("System Events") else{continue}
            if let allow=nodes.first(where:{(attribute($0,kAXRoleAttribute as String) as? String)=="AXButton" && (attribute($0,kAXTitleAttribute as String) as? String)=="Allow"}){
                let result=AXUIElementPerformAction(allow,kAXPressAction as CFString)
                print("Observed and approved CI automation permission: \(text) / \(result.rawValue)")
                fflush(stdout)
            }
        }
    }
    Thread.sleep(forTimeInterval:0.25)
}
