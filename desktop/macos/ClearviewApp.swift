import Security
import SwiftUI
import WebKit

private let keychainService = "com.local.substack-pull"

private enum ShellError: Error {
    case failed(String)
}

private struct LocalEngine {
    let root: URL

    init() throws {
        let path = ProcessInfo.processInfo.environment["CLEARVIEW_ROOT"]
            ?? Bundle.main.bundleURL
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent().path
        guard FileManager.default.fileExists(atPath: path + "/substack_local/dashboard/server.py") else {
            throw ShellError.failed("Could not find the Clearview project.")
        }
        root = URL(fileURLWithPath: path, isDirectory: true)
    }

    func command(_ action: String, publication: String? = nil, session: String? = nil) throws -> [String: Any] {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        task.arguments = ["python3", "-m", "substack_local.desktop.connection", action]
            + (publication.map { ["--publication", $0] } ?? [])
        task.currentDirectoryURL = root
        let output = Pipe()
        task.standardOutput = output
        task.standardError = Pipe()
        let input = Pipe()
        task.standardInput = input
        try task.run()
        if let session, let data = session.data(using: .utf8) {
            input.fileHandleForWriting.write(data)
        }
        try? input.fileHandleForWriting.close()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        task.waitUntilExit()
        guard let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw ShellError.failed("The local connection check did not respond.")
        }
        if task.terminationStatus != 0 {
            throw ShellError.failed(value["error"] as? String ?? "Could not connect to Substack.")
        }
        return value
    }

    func launchDashboard() throws -> (Process, URL) {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        task.arguments = ["python3", "-m", "substack_local.dashboard.server", "--port", "0"]
        task.currentDirectoryURL = root
        let output = Pipe()
        task.standardOutput = output
        task.standardError = Pipe()
        try task.run()
        var bytes = Data()
        while bytes.count < 256 {
            let next = output.fileHandleForReading.readData(ofLength: 1)
            if next.isEmpty || next == Data([10]) { break }
            bytes.append(next)
        }
        let line = String(data: bytes, encoding: .utf8) ?? ""
        guard line.hasPrefix("Substack analytics: "),
              let url = URL(string: String(line.dropFirst("Substack analytics: ".count))),
              url.host == "127.0.0.1" else {
            if task.isRunning { task.terminate() }
            throw ShellError.failed("The dashboard could not start. Reconnect and try again.")
        }
        return (task, url)
    }
}

private func saveSession(_ value: String, account: String) throws {
    guard let data = value.data(using: .utf8), !data.isEmpty else {
        throw ShellError.failed("Substack did not provide a sign-in session.")
    }
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: keychainService,
        kSecAttrAccount as String: account,
    ]
    var item = query
    item[kSecValueData as String] = data
    item[kSecAttrLabel as String] = "Substack Pull (\(account))"
    let status = SecItemAdd(item as CFDictionary, nil)
    let result = status == errSecDuplicateItem
        ? SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        : status
    guard result == errSecSuccess else {
        throw ShellError.failed("Could not save the connection in macOS Keychain (\(result)).")
    }
}

@MainActor
private final class AppModel: ObservableObject {
    enum Screen { case loading, welcome, signIn, dashboard }

    @Published var screen: Screen = .loading
    @Published var publication = ""
    @Published var message: String?
    @Published var busy = false
    @Published var dashboardURL: URL?
    weak var activeWebView: WKWebView?
    private var dashboardProcess: Process?
    private var pendingSessions: [String] = []
    private var attemptedSessions: Set<String> = []
    private var signInGeneration = 0

    func load() {
        Task.detached {
            do {
                let current = try LocalEngine().command("current")
                let publication = current["publication"] as? String ?? ""
                let connected = current["connected"] as? Bool ?? false
                await MainActor.run {
                    self.publication = publication.replacingOccurrences(of: "https://", with: "")
                    if connected { self.startDashboard() }
                    else { self.screen = .welcome }
                }
            } catch {
                await MainActor.run {
                    self.message = "Could not read the saved connection."
                    self.screen = .welcome
                }
            }
        }
    }

    func beginSignIn() {
        let address = publication.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !address.isEmpty else {
            message = "Enter your publication address first."
            return
        }
        publication = address
        signInGeneration += 1
        pendingSessions.removeAll()
        attemptedSessions.removeAll()
        message = nil
        activeWebView = nil
        screen = .signIn
    }

    func cancelSignIn() {
        signInGeneration += 1
        pendingSessions.removeAll()
        busy = false
        message = nil
        activeWebView = nil
        screen = dashboardProcess?.isRunning == true && dashboardURL != nil ? .dashboard : .welcome
    }

    func receivedSession(_ value: String) {
        guard screen == .signIn, !attemptedSessions.contains(value) else { return }
        attemptedSessions.insert(value)
        pendingSessions.append(value)
        tryNextSession()
    }

    private func tryNextSession() {
        guard screen == .signIn, !busy, !pendingSessions.isEmpty else { return }
        busy = true
        message = "Checking publication access…"
        let session = pendingSessions.removeFirst()
        let address = publication
        let generation = signInGeneration
        Task.detached {
            do {
                let engine = try LocalEngine()
                let verified = try engine.command("verify", publication: address, session: session)
                guard let account = verified["account"] as? String,
                      let canonical = verified["publication"] as? String else {
                    throw ShellError.failed("Substack did not confirm publication access.")
                }
                let stillSigningIn = await MainActor.run {
                    self.screen == .signIn && self.signInGeneration == generation
                }
                guard stillSigningIn else { return }
                try saveSession(session, account: account)
                _ = try engine.command("configure", publication: canonical)
                await MainActor.run {
                    guard self.signInGeneration == generation else { return }
                    self.busy = false
                    self.message = nil
                    self.publication = account
                    self.startDashboard()
                }
            } catch {
                await MainActor.run {
                    guard self.signInGeneration == generation else { return }
                    self.busy = false
                    self.message = "Could not connect. Check the publication address, then finish signing in."
                    self.tryNextSession()
                }
            }
        }
    }

    func startDashboard() {
        busy = true
        message = "Opening your dashboard…"
        screen = .loading
        activeWebView = nil
        if dashboardProcess?.isRunning == true { dashboardProcess?.terminate() }
        dashboardProcess = nil
        Task.detached {
            do {
                let (process, url) = try LocalEngine().launchDashboard()
                await MainActor.run {
                    self.dashboardProcess = process
                    self.dashboardURL = url
                    self.busy = false
                    self.message = nil
                    self.screen = .dashboard
                }
            } catch {
                await MainActor.run {
                    self.busy = false
                    self.message = "Could not open the dashboard. Connect Substack again."
                    self.screen = .welcome
                }
            }
        }
    }

    func stop() {
        if dashboardProcess?.isRunning == true { dashboardProcess?.terminate() }
        dashboardProcess = nil
    }
}

private struct SignInWebView: NSViewRepresentable {
    let onSession: (String) -> Void
    let onCreate: (WKWebView) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onSession: onSession) }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        context.coordinator.store = config.websiteDataStore.httpCookieStore
        config.websiteDataStore.httpCookieStore.add(context.coordinator)
        onCreate(view)
        view.load(URLRequest(url: URL(string: "https://substack.com/sign-in")!))
        return view
    }

    func updateNSView(_ view: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKHTTPCookieStoreObserver {
        let onSession: (String) -> Void
        weak var store: WKHTTPCookieStore?
        private var seen = Set<String>()

        init(onSession: @escaping (String) -> Void) { self.onSession = onSession }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url, let host = url.host?.lowercased() else {
                decisionHandler(.allow)
                return
            }
            if url.scheme == "https" && (host == "substack.com" || host.hasSuffix(".substack.com")) {
                decisionHandler(.allow)
            } else {
                if url.scheme == "https" && action.navigationType == .linkActivated {
                    NSWorkspace.shared.open(url)
                }
                decisionHandler(.cancel)
            }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { checkCookies() }
        func cookiesDidChange(in cookieStore: WKHTTPCookieStore) { checkCookies() }

        private func checkCookies() {
            store?.getAllCookies { cookies in
                for cookie in cookies where ["substack.sid", "connect.sid"].contains(cookie.name) {
                    let domain = cookie.domain.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "."))
                    guard domain == "substack.com", !cookie.value.isEmpty,
                          !self.seen.contains(cookie.value) else { continue }
                    self.seen.insert(cookie.value)
                    DispatchQueue.main.async { self.onSession(cookie.value) }
                }
            }
        }
    }
}

private struct DashboardWebView: NSViewRepresentable {
    let url: URL
    let onCreate: (WKWebView) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(dashboardURL: url) }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.addUserScript(WKUserScript(
            source: """
                if (document.documentElement) {
                    document.documentElement.classList.add('mac-desktop');
                } else {
                    document.addEventListener('DOMContentLoaded', () => {
                        document.documentElement.classList.add('mac-desktop');
                    }, { once: true });
                }
                """,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        ))
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        view.uiDelegate = context.coordinator
        onCreate(view)
        view.load(URLRequest(url: url))
        return view
    }
    func updateNSView(_ view: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        let dashboardURL: URL

        init(dashboardURL: URL) { self.dashboardURL = dashboardURL }

        private func isDashboard(_ url: URL) -> Bool {
            url.scheme == dashboardURL.scheme && url.host == dashboardURL.host
                && url.port == dashboardURL.port
        }

        private func openExternally(_ url: URL) {
            guard url.scheme == "https" || url.scheme == "http" else { return }
            NSWorkspace.shared.open(url)
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let destination = action.request.url else {
                decisionHandler(.cancel)
                return
            }
            if isDashboard(destination) || action.targetFrame == nil {
                decisionHandler(.allow)
                return
            }
            if action.navigationType == .linkActivated { openExternally(destination) }
            decisionHandler(.cancel)
        }

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            guard let destination = action.request.url else { return nil }
            if isDashboard(destination) {
                webView.load(action.request)
            } else if action.navigationType == .linkActivated {
                openExternally(destination)
            }
            return nil
        }
    }
}

private struct ContentView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            switch model.screen {
            case .loading:
                ProgressView(model.message ?? "Opening Clearview…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            case .welcome:
                VStack(alignment: .leading, spacing: 18) {
                    Text("Clearview").font(.largeTitle).bold()
                    Text("Connect your Substack publication to see its posts, Notes, and analytics.")
                        .foregroundStyle(.secondary)
                    Text("Your connection is saved in macOS Keychain for this dashboard and its MCP tools.")
                        .font(.footnote).foregroundStyle(.secondary)
                    TextField("name.substack.com", text: $model.publication)
                        .textFieldStyle(.roundedBorder)
                        .autocorrectionDisabled()
                        .frame(maxWidth: 420)
                    Button("Connect Substack") { model.beginSignIn() }
                        .buttonStyle(.borderedProminent)
                    if let message = model.message { Text(message).foregroundStyle(.secondary) }
                }
                .padding(44)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
            case .signIn:
                VStack(spacing: 0) {
                    HStack {
                        Text("Sign in to Substack").font(.headline)
                        Spacer()
                        if model.busy { ProgressView().controlSize(.small) }
                        Button("Back") { model.cancelSignIn() }
                    }
                    .padding(14)
                    Text("This is Substack's sign-in page. Clearview saves the resulting session in macOS Keychain.")
                        .font(.caption).foregroundStyle(.secondary).padding(.bottom, 8)
                    if let message = model.message {
                        Text(message).font(.caption).foregroundStyle(.secondary).padding(.bottom, 8)
                    }
                    SignInWebView(onSession: model.receivedSession,
                                  onCreate: { model.activeWebView = $0 })
                }
                .padding(.top, 30)
            case .dashboard:
                if let url = model.dashboardURL {
                    DashboardWebView(url: url, onCreate: { model.activeWebView = $0 })
                }
            }
        }
        .frame(minWidth: 920, minHeight: 620)
        .ignoresSafeArea(edges: .top)
        .task { model.load() }
    }
}

private final class FullWindowHostingView<Content: View>: NSHostingView<Content> {
    override var safeAreaInsets: NSEdgeInsets { NSEdgeInsets() }
    override var safeAreaRect: NSRect { bounds }
}

private func installMenus(delegate: ClearviewDelegate) {
    func menu(_ title: String, in bar: NSMenu) -> NSMenu {
        let item = NSMenuItem()
        let submenu = NSMenu(title: title)
        item.submenu = submenu
        bar.addItem(item)
        return submenu
    }

    @discardableResult
    func add(_ title: String, to menu: NSMenu, action: Selector, key: String = "",
             modifiers: NSEvent.ModifierFlags = [.command], target: AnyObject? = nil) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.keyEquivalentModifierMask = modifiers
        item.target = target
        menu.addItem(item)
        return item
    }

    let mainMenu = NSMenu()
    let appMenu = menu("Clearview", in: mainMenu)
    add("About Clearview", to: appMenu,
        action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)))
    appMenu.addItem(.separator())
    let services = NSMenu(title: "Services")
    let servicesItem = NSMenuItem(title: "Services", action: nil, keyEquivalent: "")
    servicesItem.submenu = services
    appMenu.addItem(servicesItem)
    NSApplication.shared.servicesMenu = services
    appMenu.addItem(.separator())
    add("Hide Clearview", to: appMenu, action: #selector(NSApplication.hide(_:)), key: "h")
    add("Hide Others", to: appMenu, action: #selector(NSApplication.hideOtherApplications(_:)),
        key: "h", modifiers: [.command, .option])
    add("Show All", to: appMenu, action: #selector(NSApplication.unhideAllApplications(_:)))
    appMenu.addItem(.separator())
    add("Reconnect Substack…", to: appMenu,
        action: #selector(ClearviewDelegate.reconnectSubstack(_:)), key: "r",
        modifiers: [.command, .shift], target: delegate)
    appMenu.addItem(.separator())
    add("Quit Clearview", to: appMenu, action: #selector(NSApplication.terminate(_:)), key: "q")

    let editMenu = menu("Edit", in: mainMenu)
    add("Undo", to: editMenu, action: Selector(("undo:")), key: "z")
    add("Redo", to: editMenu, action: Selector(("redo:")), key: "z",
        modifiers: [.command, .shift])
    editMenu.addItem(.separator())
    add("Cut", to: editMenu, action: #selector(NSText.cut(_:)), key: "x")
    add("Copy", to: editMenu, action: #selector(NSText.copy(_:)), key: "c")
    add("Paste", to: editMenu, action: #selector(NSText.paste(_:)), key: "v")
    add("Select All", to: editMenu, action: #selector(NSText.selectAll(_:)), key: "a")

    let viewMenu = menu("View", in: mainMenu)
    add("Reload", to: viewMenu, action: #selector(ClearviewDelegate.reloadPage(_:)),
        key: "r", target: delegate)
    viewMenu.addItem(.separator())
    add("Zoom In", to: viewMenu, action: #selector(ClearviewDelegate.zoomIn(_:)),
        key: "+", target: delegate)
    add("Zoom Out", to: viewMenu, action: #selector(ClearviewDelegate.zoomOut(_:)),
        key: "-", target: delegate)
    add("Actual Size", to: viewMenu, action: #selector(ClearviewDelegate.resetZoom(_:)),
        key: "0", target: delegate)
    viewMenu.addItem(.separator())
    add("Enter Full Screen", to: viewMenu,
        action: #selector(ClearviewDelegate.toggleFullScreen(_:)),
        key: "f", modifiers: [.command, .control], target: delegate)

    let windowMenu = menu("Window", in: mainMenu)
    add("Minimize", to: windowMenu, action: #selector(NSWindow.performMiniaturize(_:)), key: "m")
    add("Zoom", to: windowMenu, action: #selector(NSWindow.performZoom(_:)))
    windowMenu.addItem(.separator())
    add("Bring All to Front", to: windowMenu, action: #selector(NSApplication.arrangeInFront(_:)))
    NSApplication.shared.windowsMenu = windowMenu

    let helpMenu = menu("Help", in: mainMenu)
    add("Clearview Help", to: helpMenu, action: #selector(ClearviewDelegate.showHelp(_:)),
        target: delegate)
    NSApplication.shared.helpMenu = helpMenu
    NSApplication.shared.mainMenu = mainMenu
}

@main
struct ClearviewApp {
    @MainActor static func main() {
        let application = NSApplication.shared
        application.setActivationPolicy(.regular)
        if let iconURL = Bundle.main.url(forResource: "Clearview", withExtension: "icns"),
           let icon = NSImage(contentsOf: iconURL) {
            application.applicationIconImage = icon
        }
        let model = AppModel()
        let delegate = ClearviewDelegate(model: model)
        installMenus(delegate: delegate)
        application.delegate = delegate
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1120, height: 760),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "Clearview"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.center()
        window.delegate = delegate
        window.contentView = FullWindowHostingView(rootView: ContentView(model: model))
        window.makeKeyAndOrderFront(nil)
        application.activate(ignoringOtherApps: true)
        application.run()
    }
}

private final class ClearviewDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuItemValidation {
    let model: AppModel

    init(model: AppModel) { self.model = model }

    @MainActor @objc func reconnectSubstack(_ sender: Any?) { model.beginSignIn() }
    @MainActor @objc func reloadPage(_ sender: Any?) { model.activeWebView?.reload() }
    @MainActor @objc func zoomIn(_ sender: Any?) {
        guard let view = model.activeWebView else { return }
        view.pageZoom = min(2.0, view.pageZoom + 0.1)
    }
    @MainActor @objc func zoomOut(_ sender: Any?) {
        guard let view = model.activeWebView else { return }
        view.pageZoom = max(0.5, view.pageZoom - 0.1)
    }
    @MainActor @objc func resetZoom(_ sender: Any?) { model.activeWebView?.pageZoom = 1.0 }
    @MainActor @objc func toggleFullScreen(_ sender: Any?) {
        NSApplication.shared.keyWindow?.toggleFullScreen(sender)
    }
    @MainActor func validateMenuItem(_ item: NSMenuItem) -> Bool {
        switch item.action {
        case #selector(reloadPage(_:)), #selector(zoomIn(_:)),
             #selector(zoomOut(_:)), #selector(resetZoom(_:)):
            return model.activeWebView != nil
        case #selector(toggleFullScreen(_:)):
            item.title = NSApplication.shared.keyWindow?.styleMask.contains(.fullScreen) == true
                ? "Exit Full Screen" : "Enter Full Screen"
            return NSApplication.shared.keyWindow != nil
        default:
            return true
        }
    }
    @MainActor @objc func showHelp(_ sender: Any?) {
        let alert = NSAlert()
        alert.messageText = "Clearview Help"
        alert.informativeText = "Use the sidebar to explore your publication, posts, Notes, and Note planner. Choose an activity period at the top of the dashboard, or refresh for newer data. If your Substack connection expires, choose Clearview > Reconnect Substack."
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }
    func windowWillClose(_ notification: Notification) { NSApplication.shared.terminate(nil) }
    func applicationWillTerminate(_ notification: Notification) { model.stop() }
}
