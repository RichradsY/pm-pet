import AppKit
import WebKit
import Foundation
import Darwin

// PM Pet deliberately uses only its explicitly supplied runtime directory.
// Codex sessions and account data are interpreted by the separate local bridge.
struct LaunchOptions {
    let runtime: URL
    let bridge: String?
    let python: String

    init() throws {
        var values: [String: String] = [:]
        var args = Array(CommandLine.arguments.dropFirst())
        while !args.isEmpty {
            let key = args.removeFirst()
            guard ["--runtime", "--bridge", "--python"].contains(key), !args.isEmpty else {
                throw NSError(domain: "PMPet", code: 1, userInfo: [NSLocalizedDescriptionKey: "Usage: PMPet --runtime /absolute/path [--bridge /absolute/server.py --python /absolute/python]"])
            }
            values[key] = args.removeFirst()
        }
        guard let path = values["--runtime"], path.hasPrefix("/"), path != "/" else {
            throw NSError(domain: "PMPet", code: 2, userInfo: [NSLocalizedDescriptionKey: "An absolute, dedicated --runtime directory is required."])
        }
        runtime = URL(fileURLWithPath: path, isDirectory: true).standardizedFileURL.resolvingSymlinksInPath()
        bridge = values["--bridge"]
        python = values["--python"] ?? "/usr/bin/python3"
    }
}

final class PetPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

// WebKit reports CSS geometry from the viewport's top-left corner. Keeping the
// native host flipped makes the material islands use those same point units.
final class PetSurfaceHost: NSView {
    var didResize: (() -> Void)?
    override var isFlipped: Bool { true }
    override var isOpaque: Bool { false }

    override func setFrameSize(_ newSize: NSSize) {
        super.setFrameSize(newSize)
        didResize?()
    }
}

final class PetGlassIsland: NSView {
    private let material = NSVisualEffectView()
    private let solidFallback = NSView()

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        layer?.masksToBounds = true
        material.material = .popover
        material.blendingMode = .behindWindow
        material.state = .active
        material.isEmphasized = false
        material.wantsLayer = true
        material.layer?.masksToBounds = true
        material.frame = bounds
        material.autoresizingMask = [.width, .height]
        solidFallback.frame = bounds
        solidFallback.autoresizingMask = [.width, .height]
        solidFallback.wantsLayer = true
        addSubview(material)
        addSubview(solidFallback)
        updateAccessibility()
    }

    required init?(coder: NSCoder) { nil }

    override func hitTest(_ point: NSPoint) -> NSView? { nil }

    func setRadius(_ radius: CGFloat) {
        let clippedRadius = max(0, min(radius, min(bounds.width, bounds.height) / 2))
        layer?.cornerRadius = clippedRadius
        material.layer?.cornerRadius = clippedRadius
    }

    func updateAccessibility() {
        let reduceTransparency = NSWorkspace.shared.accessibilityDisplayShouldReduceTransparency
        material.isHidden = reduceTransparency
        solidFallback.isHidden = !reduceTransparency
        effectiveAppearance.performAsCurrentDrawingAppearance {
            solidFallback.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        }
    }

    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance()
        updateAccessibility()
    }
}

final class PetSurface: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    let window: PetPanel
    let webView: WKWebView
    var receive: (([String: Any]) -> Void)?
    private var ready = false
    private var pending: [String: Any]?
    private(set) var appliedRevision = -1
    var didRender: (() -> Void)?
    private let host: PetSurfaceHost
    private var glassIslands: [String: PetGlassIsland] = [:]
    private var glassRegions: [[String: Any]] = []
    private var accessibilityObserver: NSObjectProtocol?

    init(kind: String, size: NSSize) {
        window = PetPanel(contentRect: NSRect(origin: .zero, size: size), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        webView = WKWebView(frame: NSRect(origin: .zero, size: size), configuration: config)
        host = PetSurfaceHost(frame: NSRect(origin: .zero, size: size))
        super.init()
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.level = .floating
        window.hidesOnDeactivate = false
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        window.isReleasedWhenClosed = false
        window.contentView = host
        host.addSubview(webView)
        host.didResize = { [weak self] in self?.layoutGlassRegions() }
        window.title = "PM Pet"
        webView.autoresizingMask = [.width, .height]
        webView.setValue(false, forKey: "drawsBackground")
        webView.navigationDelegate = self
        accessibilityObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            self?.glassIslands.values.forEach { $0.updateAccessibility() }
        }
        config.userContentController.add(self, name: "pet")
        config.userContentController.addUserScript(WKUserScript(source: "window.PET_SURFACE = '\(kind)';", injectionTime: .atDocumentStart, forMainFrameOnly: true))
        if let resource = Bundle.main.url(forResource: "pet", withExtension: "html") {
            webView.loadFileURL(resource, allowingReadAccessTo: resource.deletingLastPathComponent())
        }
    }

    func render(_ payload: [String: Any]) {
        pending = payload
        guard ready, let data = try? JSONSerialization.data(withJSONObject: payload), let json = String(data: data, encoding: .utf8) else { return }
        let revision = payload["_revision"] as? Int ?? 0
        webView.evaluateJavaScript("window.renderPet(\(json))") { [weak self] _, error in
            guard let self = self, error == nil else { return }
            self.appliedRevision = max(self.appliedRevision, revision)
            self.didRender?()
        }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, let body = message.body as? [String: Any] else { return }
        if body["action"] as? String == "glassRegions" {
            glassRegions = Array((body["regions"] as? [[String: Any]] ?? []).prefix(4))
            layoutGlassRegions()
            return
        }
        receive?(body)
    }

    private func layoutGlassRegions() {
        let bounds = host.bounds
        var visibleIDs = Set<String>()
        for region in glassRegions {
            guard let id = region["id"] as? String,
                  ["panel", "name", "quota", "attention"].contains(id),
                  !visibleIDs.contains(id),
                  let x = region["x"] as? Double,
                  let y = region["y"] as? Double,
                  let width = region["width"] as? Double,
                  let height = region["height"] as? Double,
                  x.isFinite, y.isFinite, width.isFinite, height.isFinite,
                  width > 0, height > 0 else { continue }
            let radius = region["radius"] as? Double ?? 12
            guard radius.isFinite else { continue }
            let left = max(0, min(bounds.width, CGFloat(x)))
            let top = max(0, min(bounds.height, CGFloat(y)))
            let right = max(0, min(bounds.width, CGFloat(x + width)))
            let bottom = max(0, min(bounds.height, CGFloat(y + height)))
            guard right > left, bottom > top else { continue }
            let island: PetGlassIsland
            if let existing = glassIslands[id] {
                island = existing
            } else {
                island = PetGlassIsland(frame: .zero)
                glassIslands[id] = island
                host.addSubview(island, positioned: .below, relativeTo: webView)
            }
            island.frame = NSRect(x: left, y: top, width: right - left, height: bottom - top)
            island.setRadius(CGFloat(radius))
            visibleIDs.insert(id)
        }
        for id in Array(glassIslands.keys) where !visibleIDs.contains(id) {
            glassIslands.removeValue(forKey: id)?.removeFromSuperview()
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        ready = true
        if let payload = pending { render(payload) }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        // The UI is bundled. Conversation links are validated and opened natively.
        let isBundled = navigationAction.request.url?.isFileURL == true
        decisionHandler(isBundled ? .allow : .cancel)
    }

    func close() {
        if let observer = accessibilityObserver {
            NSWorkspace.shared.notificationCenter.removeObserver(observer)
            accessibilityObserver = nil
        }
        host.didResize = nil
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "pet")
        window.close()
    }
}

final class PetWindowController {
    let id: String
    let owl = PetSurface(kind: "owl", size: NSSize(width: 208, height: 176))
    let panel = PetSurface(kind: "panel", size: NSSize(width: 320, height: 280))
    var pet: [String: Any] = [:]
    var panelVisible = false
    private var payload: [String: Any] = [:]
    private var dragOrigin: NSPoint?
    private var dragMouse: NSPoint?
    private var hasPosition = false
    private var appliedPosition: NSPoint?
    private var lastQuestionID: String?
    private var panelHeight: CGFloat = 280
    private let send: ([String: Any]) -> Void
    var didRender: (() -> Void)? {
        didSet {
            owl.didRender = didRender
            panel.didRender = didRender
        }
    }

    init(id: String, index: Int, send: @escaping ([String: Any]) -> Void) {
        self.id = id
        self.send = send
        owl.receive = { [weak self] body in self?.handle(body) }
        panel.receive = { [weak self] body in self?.handle(body) }
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1200, height: 800)
        owl.window.setFrameOrigin(NSPoint(x: screen.maxX - 224 - CGFloat(index % 3) * 208, y: screen.minY + 30 + CGFloat(index / 3) * 192))
    }

    var title: String { (pet["title"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "Codex conversation" }
    var quotaVisible: Bool { pet["quotaVisible"] as? Bool ?? false }
    var sizePercent: Int { min(150, max(75, pet["size"] as? Int ?? 100)) }

    func update(pet: [String: Any], state: [String: Any]) {
        self.pet = pet
        let height = ceil(104 * CGFloat(sizePercent) / 100) + 38 + (quotaVisible ? 54 : 0)
        let width = max(180, ceil(132 * CGFloat(sizePercent) / 100) + 36)
        var frame = owl.window.frame
        frame.size = NSSize(width: width, height: height)
        if dragOrigin == nil, let position = pet["position"] as? [String: Any], let x = position["x"] as? Double, let y = position["y"] as? Double, x.isFinite, y.isFinite {
            let next = NSPoint(x: x, y: y)
            if !hasPosition || appliedPosition != next {
                frame.origin = next
                appliedPosition = next
            }
            hasPosition = true
        }
        owl.window.setFrame(clamped(frame), display: true)
        owl.window.title = "PM Pet · \(title)"
        panel.window.title = "PM Pet progress · \(title)"
        payload = ["pet": pet, "quota": state["quota"] ?? NSNull(), "capabilities": state["capabilities"] ?? [:], "panelVisible": panelVisible, "_revision": state["revision"] ?? 0]
        owl.render(payload)
        panel.render(payload)
        let question = pet["question"] as? [String: Any]
        let questionID = question?["id"] as? String ?? question?["text"] as? String
        if let questionID = questionID, questionID != lastQuestionID {
            showPanel(true)
        }
        lastQuestionID = questionID
        layoutPanel()
        owl.window.orderFrontRegardless()
    }

    func showPanel(_ visible: Bool, focus: Bool = false) {
        panelVisible = visible
        payload["panelVisible"] = visible
        owl.render(payload)
        layoutPanel()
        if visible {
            if focus { panel.window.makeKeyAndOrderFront(nil) }
            else { panel.window.orderFrontRegardless() }
        } else { panel.window.orderOut(nil) }
    }

    private func clamped(_ proposed: NSRect) -> NSRect {
        let screen = NSScreen.screens.first { $0.visibleFrame.intersects(proposed) } ?? NSScreen.main
        guard let bounds = screen?.visibleFrame else { return proposed }
        var frame = proposed
        frame.origin.x = min(max(frame.minX, bounds.minX), bounds.maxX - frame.width)
        frame.origin.y = min(max(frame.minY, bounds.minY), bounds.maxY - frame.height)
        return frame
    }

    private func layoutPanel() {
        let base = owl.window.frame
        var frame = NSRect(x: base.midX - 160, y: base.maxY + 6, width: 320, height: panelHeight)
        let screen = NSScreen.screens.first { $0.visibleFrame.intersects(base) } ?? NSScreen.main
        if let bounds = screen?.visibleFrame, frame.maxY > bounds.maxY { frame.origin.y = base.minY - frame.height - 6 }
        panel.window.setFrame(clamped(frame), display: true)
    }

    func preferences(_ fields: [String: Any]) {
        var command = fields
        command["action"] = "preferences"
        command["id"] = id
        send(command)
    }

    func openConversation() {
        let candidate = pet["conversationId"] as? String ?? id
        guard UUID(uuidString: candidate) != nil, let url = URL(string: "codex://threads/\(candidate)") else { NSSound.beep(); return }
        NSWorkspace.shared.open(url)
    }

    func disable() { send(["action": "disable", "id": id]) }

    func menu() -> NSMenu {
        let menu = NSMenu()
        let header = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        menu.addItem(actionItem(panelVisible ? "Hide progress" : "Show progress") { [weak self] in guard let self = self else { return }; self.showPanel(!self.panelVisible, focus: true) })
        menu.addItem(actionItem("Return to Codex") { [weak self] in self?.openConversation() })
        let usage = actionItem("Show account usage") { [weak self] in guard let self = self else { return }; self.preferences(["quotaVisible": !self.quotaVisible]) }
        usage.state = quotaVisible ? .on : .off
        menu.addItem(usage)
        let sizes = NSMenuItem(title: "Pet size", action: nil, keyEquivalent: "")
        sizes.submenu = NSMenu()
        for size in [75, 100, 125, 150] {
            let item = actionItem("\(size)%") { [weak self] in self?.preferences(["size": size]) }
            item.state = sizePercent == size ? .on : .off
            sizes.submenu?.addItem(item)
        }
        menu.addItem(sizes)
        menu.addItem(.separator())
        menu.addItem(actionItem("Disable this Pet") { [weak self] in self?.disable() })
        return menu
    }

    private func handle(_ body: [String: Any]) {
        guard let action = body["action"] as? String else { return }
        switch action {
        case "togglePanel": showPanel(!panelVisible, focus: true)
        case "hidePanel": showPanel(false)
        case "openConversation": openConversation()
        case "hideQuota": preferences(["quotaVisible": false])
        case "menu":
            let point = owl.webView.convert(owl.window.convertPoint(fromScreen: NSEvent.mouseLocation), from: nil)
            menu().popUp(positioning: nil, at: point, in: owl.webView)
        case "panelHeight":
            if let height = body["height"] as? Double, height.isFinite {
                panelHeight = CGFloat(min(420, max(120, height)))
                layoutPanel()
            }
        case "dragStart":
            dragOrigin = owl.window.frame.origin
            dragMouse = NSEvent.mouseLocation
        case "dragMove":
            if let origin = dragOrigin, let mouse = dragMouse {
                let current = NSEvent.mouseLocation
                var frame = owl.window.frame
                frame.origin = NSPoint(x: origin.x + current.x - mouse.x, y: origin.y + current.y - mouse.y)
                owl.window.setFrame(clamped(frame), display: true)
                layoutPanel()
            }
        case "dragEnd":
            if let start = dragOrigin, start != owl.window.frame.origin {
                let origin = owl.window.frame.origin
                appliedPosition = origin
                hasPosition = true
                preferences(["position": ["x": origin.x, "y": origin.y]])
            }
            dragOrigin = nil
            dragMouse = nil
        default: break
        }
    }

    func close() { owl.close(); panel.close() }
}

// NSMenuItem does not retain its target. The represented object owns each action.
final class MenuAction: NSObject {
    let callback: () -> Void
    init(_ callback: @escaping () -> Void) { self.callback = callback }
    @objc func invoke(_ sender: Any?) { callback() }
}
func actionItem(_ title: String, action: @escaping () -> Void) -> NSMenuItem {
    let target = MenuAction(action)
    let item = NSMenuItem(title: title, action: #selector(MenuAction.invoke(_:)), keyEquivalent: "")
    item.target = target
    item.representedObject = target
    return item
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private let options: LaunchOptions
    private var statusItem: NSStatusItem!
    private var controllers: [String: PetWindowController] = [:]
    private var orderedIDs: [String] = []
    private var timer: Timer?
    private var bridgeProcess: Process?
    private var lastModified: Date?
    private var lastSize: UInt64?
    private var lastData: Data?
    private var lockFD: Int32 = -1
    private var bridgeError: String?
    private var appliedRevision = -1
    private var terminating = false
    private var ownsRuntime = false
    private var terminationSignal: DispatchSourceSignal?
    private var lastHeartbeat = Date.distantPast
    private var quitRequestID: String?

    init(options: LaunchOptions) { self.options = options }

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            try FileManager.default.createDirectory(at: options.runtime, withIntermediateDirectories: true)
            lockFD = open(options.runtime.appendingPathComponent("native.lock").path, O_CREAT | O_RDWR, 0o600)
            guard lockFD >= 0, flock(lockFD, LOCK_EX | LOCK_NB) == 0 else {
                fputs("PM Pet is already running for this runtime.\n", stderr)
                NSApp.terminate(nil)
                return
            }
            ownsRuntime = true
            try FileManager.default.createDirectory(at: options.runtime.appendingPathComponent("inbox"), withIntermediateDirectories: true)
            try launchBridge()
        } catch { bridgeError = error.localizedDescription }
        // Install after spawning Python so the child retains a normal SIGTERM
        // disposition and its own cleanup handler can stop its watchers.
        signal(SIGTERM, SIG_IGN)
        let termination = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        termination.setEventHandler { NSApp.terminate(nil) }
        termination.resume()
        terminationSignal = termination
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = NSImage(systemSymbolName: "bird.fill", accessibilityDescription: "PM Pet") ?? NSImage(systemSymbolName: "sparkles", accessibilityDescription: "PM Pet")
        statusItem.button?.toolTip = "PM Pet · Codex companions"
        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu
        reloadState()
        publishNativeStatus()
        timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(timer!, forMode: .common)
    }

    private func launchBridge() throws {
        guard let script = options.bridge else { return }
        guard script.hasPrefix("/"), options.python.hasPrefix("/") else {
            throw NSError(domain: "PMPet", code: 3, userInfo: [NSLocalizedDescriptionKey: "Bridge and Python paths must be absolute."])
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: options.python)
        process.arguments = [script, "serve", "--runtime", options.runtime.path]
        process.currentDirectoryURL = options.runtime
        let log = options.runtime.appendingPathComponent("bridge.log")
        if !FileManager.default.fileExists(atPath: log.path) { FileManager.default.createFile(atPath: log.path, contents: nil) }
        let logHandle = try FileHandle(forWritingTo: log)
        try logHandle.seekToEnd()
        process.standardError = logHandle
        process.standardOutput = FileHandle.nullDevice
        process.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                if self?.timer != nil { self?.bridgeError = "Local bridge stopped (\(process.terminationStatus))." }
            }
        }
        try process.run()
        bridgeProcess = process
    }

    private func reloadState() {
        let url = options.runtime.appendingPathComponent("state.json")
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path) else { return }
        let modified = attributes[.modificationDate] as? Date
        let size = attributes[.size] as? UInt64
        guard modified != lastModified || size != lastSize else { return }
        guard let data = try? Data(contentsOf: url), data.count <= 4_194_304,
              let state = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let pets = state["pets"] as? [[String: Any]] else { return }
        lastModified = modified
        lastSize = size
        guard data != lastData else { return }
        lastData = data
        appliedRevision = state["revision"] as? Int ?? 0
        let enabled = Array(pets.filter { ($0["enabled"] as? Bool ?? false) && ($0["id"] as? String != nil) }.prefix(5))
        orderedIDs = enabled.compactMap { $0["id"] as? String }
        for id in Array(controllers.keys) where !orderedIDs.contains(id) {
            controllers.removeValue(forKey: id)?.close()
        }
        for (index, pet) in enabled.enumerated() {
            guard let id = pet["id"] as? String else { continue }
            if controllers[id] == nil {
                let themeSlot = ["sage", "sky", "lilac", "rose", "sand"].firstIndex(of: pet["theme"] as? String ?? "") ?? index
                controllers[id] = PetWindowController(id: id, index: themeSlot) { [weak self] command in self?.send(command) }
                controllers[id]?.didRender = { [weak self] in self?.publishNativeStatus() }
            }
            controllers[id]?.update(pet: pet, state: state)
        }
        publishNativeStatus()
    }

    private func tick() {
        let quitFile = options.runtime.appendingPathComponent("quit-request.json")
        if let attributes = try? FileManager.default.attributesOfItem(atPath: quitFile.path),
           let modified = attributes[.modificationDate] as? Date,
           abs(modified.timeIntervalSinceNow) < 30,
           let data = try? Data(contentsOf: quitFile), data.count < 4096,
           let request = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let requestID = request["requestId"] as? String, UUID(uuidString: requestID) != nil,
           let pid = request["pid"] as? Int, pid == Int(ProcessInfo.processInfo.processIdentifier) {
            quitRequestID = requestID
            NSApp.terminate(nil)
            return
        }
        reloadState()
        if Date().timeIntervalSince(lastHeartbeat) >= 1 { publishNativeStatus() }
    }

    private func publishNativeStatus() {
        guard ownsRuntime else { return }
        let rendered = controllers.values.allSatisfy { $0.owl.appliedRevision >= appliedRevision && $0.panel.appliedRevision >= appliedRevision }
        lastHeartbeat = Date()
        let timestamp = ISO8601DateFormatter().string(from: lastHeartbeat)
        var status: [String: Any] = [
            "pid": ProcessInfo.processInfo.processIdentifier,
            "runtime": options.runtime.path,
            "appliedRevision": appliedRevision,
            "enabledIds": terminating ? [] : orderedIDs.filter { id in
                guard let controller = controllers[id] else { return false }
                return controller.owl.appliedRevision >= appliedRevision && controller.panel.appliedRevision >= appliedRevision
            },
            "uiReady": !terminating && rendered,
            "running": !terminating,
            "updatedAt": timestamp,
            "heartbeatAt": timestamp
        ]
        if let requestID = quitRequestID { status["quitRequestId"] = requestID }
        if let data = try? JSONSerialization.data(withJSONObject: status, options: [.sortedKeys]) {
            try? data.write(to: options.runtime.appendingPathComponent("native-status.json"), options: [.atomic])
        }
    }

    private func send(_ command: [String: Any]) {
        let inbox = options.runtime.appendingPathComponent("inbox", isDirectory: true).resolvingSymlinksInPath()
        guard inbox.path.hasPrefix(options.runtime.path + "/") else { NSSound.beep(); return }
        var envelope = command
        let requestID = UUID().uuidString.lowercased()
        envelope["requestId"] = requestID
        do {
            let data = try JSONSerialization.data(withJSONObject: envelope, options: [.sortedKeys])
            try data.write(to: inbox.appendingPathComponent(requestID + ".json"), options: [.atomic])
        } catch {
            bridgeError = "Could not save Pet preference. \(error.localizedDescription)"
            NSSound.beep()
        }
    }

    func menuWillOpen(_ menu: NSMenu) {
        menu.removeAllItems()
        let header = NSMenuItem(title: "PM Pet · \(controllers.count) of 5 enabled", action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        if orderedIDs.isEmpty {
            let item = NSMenuItem(title: "Enable a Pet from its Codex conversation", action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }
        for id in orderedIDs {
            guard let controller = controllers[id] else { continue }
            let item = NSMenuItem(title: controller.title, action: nil, keyEquivalent: "")
            item.submenu = controller.menu()
            menu.addItem(item)
        }
        menu.addItem(.separator())
        let capability = NSMenuItem(title: "Observation only · build pause unavailable", action: nil, keyEquivalent: "")
        capability.isEnabled = false
        menu.addItem(capability)
        if let error = bridgeError {
            let item = NSMenuItem(title: error, action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }
        menu.addItem(actionItem("Open local bridge log") { [weak self] in
            guard let self = self else { return }
            NSWorkspace.shared.open(self.options.runtime.appendingPathComponent("bridge.log"))
        })
        menu.addItem(actionItem("Quit PM Pet") { NSApp.terminate(nil) })
    }

    func applicationWillTerminate(_ notification: Notification) {
        guard ownsRuntime else {
            if lockFD >= 0 { Darwin.close(lockFD) }
            return
        }
        terminating = true
        publishNativeStatus()
        timer?.invalidate()
        timer = nil
        controllers.values.forEach { $0.close() }
        if bridgeProcess?.isRunning == true { bridgeProcess?.terminate() }
        if lockFD >= 0 { flock(lockFD, LOCK_UN); Darwin.close(lockFD) }
    }
}

do {
    let options = try LaunchOptions()
    let app = NSApplication.shared
    let delegate = AppDelegate(options: options)
    app.delegate = delegate
    app.setActivationPolicy(.accessory)
    app.run()
} catch {
    fputs("PM Pet: \(error.localizedDescription)\n", stderr)
    exit(2)
}
