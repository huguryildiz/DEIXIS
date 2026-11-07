// UI helper for scripts/desktop/desktop_acceptance.py (P10 M2): looks at and presses parts of a running DEIXIS.app by pid,
// through the window list and the Accessibility API (the terminal that runs the acceptance needs Accessibility access).
// Not part of the app. Compiled by the acceptance script with `swiftc`.
//
//   desktop_ui windows PID            JSON list of the process's windows: id, on screen, layer, bounds
//   desktop_ui press PID LABEL        press the first element whose description or title is LABEL (web content too)
//   desktop_ui press-part PID TEXT    press the first button, link or menu item whose label or help contains TEXT
//   desktop_ui front PID              the frontmost app's bundle id (com.apple.loginwindow: the screen is locked)
//   desktop_ui texts PID              JSON list of the texts of the window's web content (titles, descriptions, values)
//   desktop_ui close PID              press the close button of the app's first window
//   desktop_ui menu PID               open the menu-bar item's menu, print its item titles as JSON, close it again
//   desktop_ui menu-press PID TITLE   open the menu-bar item's menu and press the item with that title
//   desktop_ui activate PID           bring the app to the front (for a full-size window screenshot)
//   desktop_ui tray-count PID         how many menu-bar items the app has
//   desktop_ui terminate PID          ask the app to quit (as Cmd+Q does), never launching anything

import AppKit
import ApplicationServices
import Foundation

func attr(_ element: AXUIElement, _ name: String) -> AnyObject? {
    var value: AnyObject?
    return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success ? value : nil
}

func children(_ element: AXUIElement) -> [AXUIElement] {
    return (attr(element, kAXChildrenAttribute) as? [AXUIElement]) ?? []
}

func label(_ element: AXUIElement) -> [String] {
    return [kAXDescriptionAttribute, kAXTitleAttribute, kAXValueDescriptionAttribute]
        .compactMap { attr(element, $0) as? String }
}

/// The web content of the app's windows (AXWebArea), each element once: the tree can point back at itself.
func webAreas(_ app: AXUIElement) -> [AXUIElement] {
    var found: [AXUIElement] = []
    for window in (attr(app, kAXWindowsAttribute) as? [AXUIElement]) ?? [] {
        if let area = find(window, { (attr($0, kAXRoleAttribute) as? String) == "AXWebArea" }) { found.append(area) }
    }
    return found
}

func walk(_ root: AXUIElement, _ visit: (AXUIElement) -> Bool) {
    var seen = Set<UInt>()
    var todo = [root]
    while let element = todo.popLast() {
        if !seen.insert(UInt(CFHash(element))).inserted || seen.count > 20000 { continue }
        if visit(element) { return }
        todo.append(contentsOf: children(element).reversed())
    }
}

func texts(_ root: AXUIElement, into found: inout [String]) {
    walk(root) { element in
        for name in [kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute] {
            if let text = attr(element, name) as? String, !text.isEmpty { found.append(text) }
        }
        return false
    }
}

let pressable: Set<String> = [kAXButtonRole, "AXLink", kAXMenuItemRole, kAXRadioButtonRole, kAXPopUpButtonRole,
                              kAXMenuButtonRole, kAXCheckBoxRole]

func find(_ root: AXUIElement, depth: Int = 0, _ match: (AXUIElement) -> Bool) -> AXUIElement? {
    if match(root) { return root }
    if depth > 60 { return nil }
    for child in children(root) {
        if let found = find(child, depth: depth + 1, match) { return found }
    }
    return nil
}

func emit(_ object: Any) {
    let data = try! JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
}

func statusItem(_ app: AXUIElement) -> AXUIElement? {
    guard let bar = attr(app, "AXExtrasMenuBar") else { return nil }
    return children(bar as! AXUIElement).first
}

func openMenu(_ app: AXUIElement) -> AXUIElement? {
    guard let item = statusItem(app) else { return nil }
    AXUIElementPerformAction(item, kAXPressAction as CFString)
    for _ in 0..<30 {
        if let menu = children(item).first(where: { (attr($0, kAXRoleAttribute) as? String) == kAXMenuRole }) {
            return menu
        }
        usleep(100_000)
    }
    return nil
}

let args = CommandLine.arguments
guard args.count >= 3, let pid = pid_t(args[2]) else {
    FileHandle.standardError.write("usage: desktop_ui windows|press|close|menu|menu-press|terminate PID [LABEL]\n".data(using: .utf8)!)
    exit(2)
}
let app = AXUIElementCreateApplication(pid)

switch args[1] {
case "windows":
    let list = (CGWindowListCopyWindowInfo([.optionAll], kCGNullWindowID) as? [[String: Any]]) ?? []
    emit(list.filter { ($0[kCGWindowOwnerPID as String] as? Int) == Int(pid) }.map { info -> [String: Any] in
        ["id": info[kCGWindowNumber as String] ?? 0, "onscreen": info[kCGWindowIsOnscreen as String] ?? false,
         "layer": info[kCGWindowLayer as String] ?? 0, "bounds": info[kCGWindowBounds as String] ?? [:],
         "name": info[kCGWindowName as String] ?? ""]
    })
case "press":
    let wanted = args.count > 3 ? args[3] : ""
    let windows = (attr(app, kAXWindowsAttribute) as? [AXUIElement]) ?? []
    for window in windows {
        if let element = find(window, { label($0).contains(wanted) }) {
            let result = AXUIElementPerformAction(element, kAXPressAction as CFString)
            emit(["pressed": result == .success, "label": wanted])
            exit(result == .success ? 0 : 1)
        }
    }
    emit(["pressed": false, "label": wanted, "windows": windows.count])
    exit(1)
case "press-part":
    let wanted = args.count > 3 ? args[3] : ""
    var hit: AXUIElement?
    for area in webAreas(app) where hit == nil {
        walk(area) { element in
            let names = label(element) + [kAXValueAttribute, kAXHelpAttribute].map { (attr(element, $0) as? String) ?? "" }
            if pressable.contains((attr(element, kAXRoleAttribute) as? String) ?? "") && names.contains(where: { $0.contains(wanted) }) {
                hit = element
                return true
            }
            return false
        }
    }
    guard let element = hit else { emit(["pressed": false, "label": wanted]); exit(1) }
    let result = AXUIElementPerformAction(element, kAXPressAction as CFString)
    emit(["pressed": result == .success, "label": wanted, "found": label(element)])
    exit(result == .success ? 0 : 1)
case "front":
    emit(["front": NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? ""])
case "texts":
    var found: [String] = []
    for area in webAreas(app) { texts(area, into: &found) }
    emit(found)
case "close":
    let windows = (attr(app, kAXWindowsAttribute) as? [AXUIElement]) ?? []
    guard let window = windows.first, let button = attr(window, kAXCloseButtonAttribute) else {
        emit(["closed": false, "windows": windows.count]); exit(1)
    }
    let result = AXUIElementPerformAction(button as! AXUIElement, kAXPressAction as CFString)
    emit(["closed": result == .success])
case "menu":
    guard let menu = openMenu(app) else { emit(["menu": NSNull()]); exit(1) }
    let titles = children(menu).compactMap { attr($0, kAXTitleAttribute) as? String }
    AXUIElementPerformAction(menu, kAXCancelAction as CFString)
    emit(["menu": titles])
case "menu-press":
    let wanted = args.count > 3 ? args[3] : ""
    guard let menu = openMenu(app) else { emit(["pressed": false]); exit(1) }
    guard let item = children(menu).first(where: { (attr($0, kAXTitleAttribute) as? String) == wanted }) else {
        AXUIElementPerformAction(menu, kAXCancelAction as CFString)
        emit(["pressed": false, "label": wanted]); exit(1)
    }
    let result = AXUIElementPerformAction(item, kAXPressAction as CFString)
    emit(["pressed": result == .success, "label": wanted])
case "activate":
    guard let running = NSRunningApplication(processIdentifier: pid) else { emit(["activated": false]); exit(1) }
    emit(["activated": running.activate()])
case "tray-count":
    let bar = attr(app, "AXExtrasMenuBar")
    emit(["items": bar == nil ? 0 : children(bar as! AXUIElement).count])
case "terminate":
    guard let running = NSRunningApplication(processIdentifier: pid) else { emit(["terminated": false]); exit(1) }
    emit(["terminated": running.terminate()])
default:
    exit(2)
}
