import Security
import SwiftUI
import WebKit

private let packagedEngine = Bundle.main.resourceURL?
    .appendingPathComponent("engine/clearview-engine")
private let keychainService = packagedEngine.map { FileManager.default.isExecutableFile(atPath: $0.path) } == true
    ? "io.github.w1k5.clearview" : "com.local.substack-pull"

private enum ShellError: Error {
    case failed(String)
}

private struct LocalEngine {
    let root: URL

    init() throws {
        if let engine = packagedEngine, FileManager.default.isExecutableFile(atPath: engine.path) {
            root = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support/Clearview", isDirectory: true)
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            return
        }
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

    private func process(_ command: String, module: String, arguments: [String]) -> Process {
        let task = Process()
        if let engine = packagedEngine, FileManager.default.isExecutableFile(atPath: engine.path) {
            task.executableURL = engine
            task.arguments = [command] + arguments
        } else {
            task.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            task.arguments = ["python3", "-m", module] + arguments
        }
        task.currentDirectoryURL = root
        return task
    }

    func command(_ action: String, publication: String? = nil, session: String? = nil, installedVersion: String? = nil) throws -> [String: Any] {
        let task = process("connection", module: "substack_local.desktop.connection",
                           arguments: [action] + (publication.map { ["--publication", $0] } ?? [])
                           + (installedVersion.map { ["--installed-version", $0] } ?? []))
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
        let task = process("dashboard", module: "substack_local.dashboard.server", arguments: ["--port", "0"])
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

private func readSession(account: String) throws -> String {
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: keychainService,
        kSecAttrAccount as String: account,
        kSecReturnData as String: true,
        kSecMatchLimit as String: kSecMatchLimitOne,
    ]
    var item: CFTypeRef?
    guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
          let data = item as? Data, let session = String(data: data, encoding: .utf8) else {
        throw ShellError.failed("Reconnect Substack to choose a publication.")
    }
    return session
}

@MainActor
private final class AppModel: ObservableObject {
    enum Screen { case loading, welcome, signIn, choosePublication, dashboard }

    @Published var screen: Screen = .loading
    @Published var publication = ""
    @Published var message: String?
    @Published var busy = false
    @Published var dashboardURL: URL?
    @Published var choices: [[String: String]] = []
    @Published var showManualPublication = false
    private var selectionSession: String?
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
        signInGeneration += 1
        pendingSessions.removeAll()
        attemptedSessions.removeAll()
        selectionSession = nil
        choices = []
        showManualPublication = false
        busy = false
        message = nil
        activeWebView = nil
        screen = .signIn
    }

    func changePublication() {
        guard screen == .dashboard else { return }
        signInGeneration += 1
        let generation = signInGeneration
        let account = publication
        choices = []
        showManualPublication = false
        selectionSession = nil
        activeWebView = nil
        busy = true
        message = "Finding your publications…"
        screen = .choosePublication
        Task.detached {
            do {
                let token = try readSession(account: account)
                let discovery = try LocalEngine().command("discover", session: token)
                await MainActor.run {
                    guard self.signInGeneration == generation else { return }
                    self.presentPublications(discovery, session: token)
                }
            } catch {
                await MainActor.run {
                    guard self.signInGeneration == generation else { return }
                    self.busy = false
                    self.message = "Could not load publications. Reconnect Substack and try again."
                }
            }
        }
    }

    private func presentPublications(_ discovery: [String: Any], session: String) {
        busy = false
        selectionSession = session
        choices = discovery["publications"] as? [[String: String]] ?? []
        showManualPublication = choices.isEmpty
        message = choices.isEmpty ? "Enter your publication address." : nil
        activeWebView = nil
        screen = .choosePublication
    }

    func cancelSignIn() {
        signInGeneration += 1
        pendingSessions.removeAll()
        attemptedSessions.removeAll()
        selectionSession = nil
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

    func choosePublication(_ address: String) {
        guard !busy, let session = selectionSession else { return }
        connect(session, address: address)
    }

    private func tryNextSession() {
        guard screen == .signIn, !busy, choices.isEmpty, !pendingSessions.isEmpty else { return }
        busy = true
        message = "Finding your publications…"
        let session = pendingSessions.removeFirst()
        let generation = signInGeneration
        Task.detached {
            let result = try? LocalEngine().command("discover", session: session)
            await MainActor.run {
                guard self.signInGeneration == generation else { return }
                guard let result else {
                    self.busy = false
                    self.selectionSession = session
                    self.showManualPublication = true
                    self.message = "Couldn’t find a publication automatically."
                    self.tryNextSession()
                    return
                }
                self.presentPublications(result, session: session)
                if let selected = result["selected"] as? String {
                    self.connect(session, address: selected)
                }
            }
        }
    }

    private func connect(_ session: String, address: String) {
        busy = true
        message = "Checking publication access…"
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
                    (self.screen == .signIn || self.screen == .choosePublication) && self.signInGeneration == generation
                }
                guard stillSigningIn else { return }
                try saveSession(session, account: account)
                _ = try engine.command("configure", publication: canonical)
                await MainActor.run {
                    guard self.signInGeneration == generation else { return }
                    self.busy = false
                    self.message = nil
                    self.selectionSession = nil
                    self.pendingSessions.removeAll()
                    self.attemptedSessions.removeAll()
                    self.publication = account
                    self.startDashboard()
                }
            } catch {
                let detail: String
                if case ShellError.failed(let reason) = error {
                    detail = reason
                } else {
                    detail = "Clearview could not start its connection helper."
                }
                await MainActor.run {
                    guard self.signInGeneration == generation else { return }
                    self.busy = false
                    self.message = detail
                    self.showManualPublication = true
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
                    document.documentElement.classList.add('mac-desktop', 'desktop-menu');
                } else {
                    document.addEventListener('DOMContentLoaded', () => {
                        document.documentElement.classList.add('mac-desktop', 'desktop-menu');
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
    @State private var selectedPublication = ""
    @State private var manualAddress = ""
    // Match the dashboard's sidebar, brand mark, and page background.
    private let forest = Color(red: 18.0 / 255, green: 53.0 / 255, blue: 46.0 / 255)
    private let lime = Color(red: 217.0 / 255, green: 237.0 / 255, blue: 171.0 / 255)
    private let canvas = Color(red: 248.0 / 255, green: 250.0 / 255, blue: 247.0 / 255)

    private var brandMark: some View {
        Image(systemName: "arrow.up.right")
            .font(.system(size: 17, weight: .bold))
            .foregroundStyle(forest)
            .frame(width: 37, height: 37)
            .background(lime, in: RoundedRectangle(cornerRadius: 11))
            .accessibilityHidden(true)
    }

    var body: some View {
        VStack(spacing: 0) {
            switch model.screen {
            case .loading:
                ProgressView(model.message ?? "Opening Clearview…")
                    .tint(forest)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(canvas)
            case .welcome:
                VStack(alignment: .leading, spacing: 18) {
                    brandMark
                    Text("Clearview").font(.largeTitle).bold()
                    Text("Connect your Substack publication to see its posts, Notes, and analytics.")
                        .foregroundStyle(.secondary)
                    Text("Your connection is saved in macOS Keychain for this dashboard and its MCP tools.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Button("Sign in to Substack") { model.beginSignIn() }
                        .buttonStyle(.borderedProminent)
                        .tint(forest)
                    if let message = model.message { Text(message).foregroundStyle(.secondary) }
                }
                .frame(maxWidth: 340, alignment: .leading)
                .padding(32)
                .background(.white, in: RoundedRectangle(cornerRadius: 13))
                .overlay(RoundedRectangle(cornerRadius: 13).strokeBorder(forest.opacity(0.12)))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(canvas)
            case .signIn, .choosePublication:
                VStack(spacing: 0) {
                    HStack(spacing: 12) {
                        brandMark
                        VStack(alignment: .leading, spacing: 3) {
                            Text("Clearview").font(.headline)
                            Text(model.screen == .signIn ? "Sign in to Substack" : "Choose publication").font(.caption).foregroundStyle(lime)
                        }
                        Spacer()
                        Button("Back") { model.cancelSignIn() }
                            .buttonStyle(.bordered)
                            .tint(.white)
                    }
                    .foregroundStyle(.white)
                    .padding(.horizontal, 20)
                    .padding(.top, 34)
                    .padding(.bottom, 12)
                    .background(forest)
                    VStack(spacing: 8) {
                        Text("Your Substack session stays in macOS Keychain.")
                            .font(.caption).foregroundStyle(.secondary)
                        if let message = model.message {
                            HStack(spacing: 8) {
                                if model.busy { ProgressView().controlSize(.small) }
                                Text(message).font(.callout)
                            }
                        }
                        if model.screen == .choosePublication && !model.choices.isEmpty {
                            HStack {
                                Picker("Publication", selection: $selectedPublication) {
                                    Text("Choose a publication").tag("")
                                    ForEach(model.choices, id: \.self) { choice in
                                        if let address = choice["address"] {
                                            Text(choice["name"] ?? address).tag(address)
                                        }
                                    }
                                }.pickerStyle(.menu)
                                Button("Open publication") { model.choosePublication(selectedPublication) }
                                    .buttonStyle(.borderedProminent)
                                    .disabled(selectedPublication.isEmpty)
                            }
                            .disabled(model.busy)
                            .onAppear { selectedPublication = "" }
                            Button("Enter publication address") { model.showManualPublication = true }
                                .disabled(model.busy)
                        }
                        if model.showManualPublication {
                            HStack {
                                TextField("name.substack.com", text: $manualAddress)
                                    .textFieldStyle(.roundedBorder)
                                    .autocorrectionDisabled()
                                    .frame(maxWidth: 270)
                                Button("Connect") { model.choosePublication(manualAddress) }
                                    .disabled(model.busy || manualAddress.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                            }
                        }
                    }
                    .padding(12)
                    .frame(maxWidth: .infinity)
                    .background(canvas)
                    .tint(forest)
                    if model.screen == .signIn {
                        SignInWebView(onSession: model.receivedSession,
                                      onCreate: { model.activeWebView = $0 })
                    } else {
                        Spacer(minLength: 0)
                    }
                }
            case .dashboard:
                if let url = model.dashboardURL {
                    DashboardWebView(url: url, onCreate: { model.activeWebView = $0 })
                }
            }
        }
        .frame(minWidth: 920, minHeight: 620)
        .ignoresSafeArea(edges: .top)
        .preferredColorScheme(.light)
        .onChange(of: model.screen) { screen in
            if screen == .signIn { manualAddress = "" }
        }
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
    let updates = NSMenu(title: "Software Updates")
    let updatesItem = NSMenuItem(title: "Software Updates", action: nil, keyEquivalent: "")
    updatesItem.submenu = updates
    appMenu.addItem(updatesItem)
    add("Automatically Check for Updates", to: updates,
        action: #selector(ClearviewDelegate.toggleAutomaticUpdates(_:)), target: delegate)
    add("Check for Updates…", to: updates,
        action: #selector(ClearviewDelegate.checkUpdates(_:)), target: delegate)
    appMenu.addItem(.separator())
    let aiConnections = NSMenu(title: "AI Connections")
    let aiItem = NSMenuItem(title: "AI Connections", action: nil, keyEquivalent: "")
    aiItem.submenu = aiConnections
    appMenu.addItem(aiItem)
    add("Install Claude Extension…", to: aiConnections, action: #selector(ClearviewDelegate.connectClaude(_:)), target: delegate)
    add("Connect to Codex…", to: aiConnections, action: #selector(ClearviewDelegate.connectCodex(_:)), target: delegate)
    aiConnections.addItem(.separator())
    add("Copy Test Prompt", to: aiConnections, action: #selector(ClearviewDelegate.copyTestPrompt(_:)), target: delegate)
    appMenu.addItem(.separator())
    add("Change Publication…", to: appMenu, action: #selector(ClearviewDelegate.changePublication(_:)), target: delegate)
    add("Reconnect Substack…", to: appMenu,
        action: #selector(ClearviewDelegate.reconnectSubstack(_:)), key: "r",
        modifiers: [.command, .shift], target: delegate)
    appMenu.addItem(.separator())
    add("Open data folder", to: appMenu, action: #selector(ClearviewDelegate.openDataFolder(_:)), target: delegate)
    add("Export writing backups", to: appMenu, action: #selector(ClearviewDelegate.exportBackups(_:)), target: delegate)
    add("Clear temporary cache", to: appMenu, action: #selector(ClearviewDelegate.clearCache(_:)), target: delegate)
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

    private var checkingUpdates = false
    private let automaticUpdatesKey = "automaticUpdateChecks"

    @MainActor func applicationDidFinishLaunching(_ notification: Notification) {
        if UserDefaults.standard.bool(forKey: automaticUpdatesKey) {
            checkForUpdates(automatic: true)
        }
    }

    @MainActor @objc func toggleAutomaticUpdates(_ sender: Any?) {
        let enabled = !UserDefaults.standard.bool(forKey: automaticUpdatesKey)
        UserDefaults.standard.set(enabled, forKey: automaticUpdatesKey)
        if enabled { checkForUpdates(automatic: true) }
    }

    @MainActor @objc func checkUpdates(_ sender: Any?) { checkForUpdates(automatic: false) }

    @MainActor private func checkForUpdates(automatic: Bool) {
        guard !checkingUpdates, packagedEngine != nil,
              let version = Bundle.main.object(forInfoDictionaryKey: "ClearviewReleaseVersion") as? String else { return }
        checkingUpdates = true
        Task.detached {
            let result = try? LocalEngine().command(automatic ? "check-update-automatic" : "check-update",
                                                    installedVersion: version)
            await MainActor.run {
                self.checkingUpdates = false
                if automatic && !UserDefaults.standard.bool(forKey: self.automaticUpdatesKey) { return }
                let alert = NSAlert()
                if let update = result?["update"] as? [String: String],
                   let version = update["version"], let url = update["url"].flatMap(URL.init(string:)) {
                    alert.messageText = "Clearview \(version) is available"
                    alert.informativeText = "Download the disk image, then replace Clearview in Applications."
                    alert.addButton(withTitle: "Download Update")
                    alert.addButton(withTitle: "Later")
                    if alert.runModal() == .alertFirstButtonReturn { NSWorkspace.shared.open(url) }
                } else if !automatic {
                    alert.messageText = result == nil ? "Could not check for updates" : "Clearview is up to date"
                    alert.runModal()
                }
            }
        }
    }

    @MainActor @objc func connectClaude(_ sender: Any?) { runAIConnection("setup-claude") }
    @MainActor @objc func connectCodex(_ sender: Any?) { runAIConnection("setup-codex") }
    @MainActor @objc func copyTestPrompt(_ sender: Any?) { runAIConnection("test-prompt") }

    @MainActor private func runAIConnection(_ action: String) {
        do {
            let result = try LocalEngine().command(action)
            if let prompt = result["prompt"] as? String {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(prompt, forType: .string)
                return
            }
            if let path = result["path"] as? String {
                let file = URL(fileURLWithPath: path)
                if !NSWorkspace.shared.open(file) {
                    NSWorkspace.shared.activateFileViewerSelecting([file])
                }
                showAIMessage("Finish installing in Claude Desktop. If the extension didn’t open, use Claude’s Install Extension command to select Clearview.mcpb.")
            } else if let message = result["message"] as? String {
                showAIMessage(message)
            }
        } catch ShellError.failed(let detail) {
            showAIMessage(detail)
        } catch {
            showAIMessage("Could not set up the connection.")
        }
    }

    @MainActor private func showAIMessage(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "AI Connections"
        alert.informativeText = message
        alert.runModal()
    }
    @MainActor @objc func changePublication(_ sender: Any?) { model.changePublication() }
    @MainActor @objc func reconnectSubstack(_ sender: Any?) { model.beginSignIn() }
    @MainActor @objc func openDataFolder(_ sender: Any?) { runDataAction("open") }
    @MainActor @objc func exportBackups(_ sender: Any?) { runDataAction("export") }
    @MainActor @objc func clearCache(_ sender: Any?) { runDataAction("clear-cache") }
    @MainActor private func runDataAction(_ action: String) {
        guard model.screen == .dashboard, let view = model.activeWebView else { return }
        view.evaluateJavaScript("document.querySelector('[data-local-action=\"\(action)\"]')?.click()", completionHandler: nil)
    }
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
        case #selector(toggleAutomaticUpdates(_:)):
            item.state = UserDefaults.standard.bool(forKey: automaticUpdatesKey) ? .on : .off
            return Bundle.main.object(forInfoDictionaryKey: "ClearviewReleaseVersion") != nil
        case #selector(checkUpdates(_:)):
            return !checkingUpdates && Bundle.main.object(forInfoDictionaryKey: "ClearviewReleaseVersion") != nil
        case #selector(connectClaude(_:)), #selector(connectCodex(_:)):
            return model.screen == .dashboard && packagedEngine != nil
        case #selector(changePublication(_:)):
            return model.screen == .dashboard
        case #selector(openDataFolder(_:)), #selector(exportBackups(_:)), #selector(clearCache(_:)):
            return model.screen == .dashboard && model.activeWebView != nil
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
