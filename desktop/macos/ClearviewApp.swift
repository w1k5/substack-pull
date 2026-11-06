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
        screen = .signIn
    }

    func cancelSignIn() {
        signInGeneration += 1
        pendingSessions.removeAll()
        busy = false
        message = nil
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

    func makeCoordinator() -> Coordinator { Coordinator(onSession: onSession) }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        context.coordinator.store = config.websiteDataStore.httpCookieStore
        config.websiteDataStore.httpCookieStore.add(context.coordinator)
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
                    SignInWebView(onSession: model.receivedSession)
                }
                .padding(.top, 30)
            case .dashboard:
                if let url = model.dashboardURL {
                    DashboardWebView(url: url)
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
    let mainMenu = NSMenu()
    let appItem = NSMenuItem()
    let appMenu = NSMenu(title: "Clearview")
    let reconnect = NSMenuItem(title: "Reconnect Substack…", action: #selector(ClearviewDelegate.reconnectSubstack(_:)), keyEquivalent: "R")
    reconnect.target = delegate
    appMenu.addItem(reconnect)
    appMenu.addItem(.separator())
    appMenu.addItem(withTitle: "Quit Clearview", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
    appItem.submenu = appMenu
    mainMenu.addItem(appItem)

    let editItem = NSMenuItem()
    let editMenu = NSMenu(title: "Edit")
    editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
    editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
    editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
    editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
    editItem.submenu = editMenu
    mainMenu.addItem(editItem)
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

private final class ClearviewDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let model: AppModel

    init(model: AppModel) { self.model = model }

    @MainActor @objc func reconnectSubstack(_ sender: Any?) { model.beginSignIn() }
    func windowWillClose(_ notification: Notification) { NSApplication.shared.terminate(nil) }
    func applicationWillTerminate(_ notification: Notification) { model.stop() }
}
