// Codeck para macOS: janela nativa (WebKit) para a tela do backend em Python, com contador no Dock e na
// barra de menus, notificações clicáveis e atualização automática (latest.json no site da ThomSoft).
//
// O app sobe o backend embutido (Resources/backend/server.py) e passa uma chave nova a cada execução: sem ela o
// backend não responde, então nenhum outro programa da máquina consegue ler a fila ou agir por você.
// Desenvolvimento: CODECK_ATTACH=1 + CODECK_PORT=<porta> conecta num backend já rodando (debug no VS Code).
import Cocoa
import ServiceManagement
import UserNotifications
import WebKit

let env = ProcessInfo.processInfo.environment
let attachMode = env["CODECK_ATTACH"] == "1"
// Autoteste do app de desktop (scripts/test-desktop.sh): roteiro JS rodando DENTRO desta janela, com teclas reais.
let selfTestScript = env["CODECK_SELFTEST"]
let selfTestOut = env["CODECK_SELFTEST_OUT"] ?? NSTemporaryDirectory()
let port = Int(env["CODECK_PORT"] ?? "") ?? 47821
let baseURL = URL(string: "http://127.0.0.1:\(port)/")!
let token = attachMode ? (env["CODECK_TOKEN"] ?? "") : UUID().uuidString + UUID().uuidString
let appVersion = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
let appBuild = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "0"
let updateURL = Bundle.main.object(forInfoDictionaryKey: "CodeckUpdateURL") as? String ?? ""
let supportDir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
    .appendingPathComponent("Codeck", isDirectory: true)

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate,
    WKScriptMessageHandler, UNUserNotificationCenterDelegate, NSMenuDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var projectWindows: [NSWindow] = []   // projetos abertos em janela própria (Projetos → "Abrir em janela")
    var statusItem: NSStatusItem!
    var loginMenuItem: NSMenuItem!
    var server: Process?
    var quitting = false
    var hideAfterFullScreen = false
    var loaded = false
    var lastSeq = -1
    var nativeNotifications = false
    var powerActivity: NSObjectProtocol?   // segura o Mac acordado e fora do App Nap (Configurações → Geral)

    func applicationDidFinishLaunching(_ notification: Notification) {
        if adoptLegacyInstall() { return }
        buildMainMenu()
        buildWindow()
        buildStatusItem()
        setupNotifications()
        setHold(true)   // até o backend dizer o modo: o padrão é continuar trabalhando
        observePower()
        ensureServer { [weak self] in self?.loadUI() }
        Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in self?.poll() }
        if !attachMode && selfTestScript == nil { enableLoginItemOnFirstRun() }
    }

    // MARK: nomes antigos (Commitdeck, PR Pilot)

    /// O app já se chamou Commitdeck e, antes, PR Pilot. A pasta de dados mais recente dos nomes antigos vira a nova
    /// (contas, regras, histórico) e, se a atualização automática deixou este app com o nome antigo
    /// ("Commitdeck.app" ou "PR Pilot.app" — o app antigo troca o próprio pacote), ele se renomeia para "Codeck.app"
    /// e reabre — devolve true quando vai reabrir. O identificador do pacote não mudou: Keychain, permissões de pasta,
    /// notificações e o armazenamento da tela continuam valendo.
    func adoptLegacyInstall() -> Bool {
        let fm = FileManager.default
        if env["CODECK_DATA"] == nil {
            for name in ["Commitdeck", "PR Pilot"] where !fm.fileExists(atPath: supportDir.path) {
                let legacy = supportDir.deletingLastPathComponent().appendingPathComponent(name, isDirectory: true)
                if fm.fileExists(atPath: legacy.path) { try? fm.moveItem(at: legacy, to: supportDir) }
            }
        }
        if attachMode || selfTestScript != nil { return false }
        let bundle = URL(fileURLWithPath: Bundle.main.bundlePath)
        guard ["Commitdeck.app", "PR Pilot.app"].contains(bundle.lastPathComponent) else { return false }
        let target = bundle.deletingLastPathComponent().appendingPathComponent("Codeck.app")
        guard !fm.fileExists(atPath: target.path), (try? fm.moveItem(at: bundle, to: target)) != nil else { return false }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        p.arguments = ["-n", target.path]
        try? p.run()
        NSApp.terminate(nil)
        return true
    }

    // MARK: backend

    func request(_ path: String, method: String = "GET") -> URLRequest {
        var req = URLRequest(url: URL(string: path, relativeTo: baseURL)!)
        req.httpMethod = method
        req.timeoutInterval = 3
        req.setValue(token, forHTTPHeaderField: "X-Codeck-Token")
        if method == "POST" { req.setValue("1", forHTTPHeaderField: "X-Codeck") }
        return req
    }

    func getJSON(_ path: String, _ done: @escaping ([String: Any]?, Int) -> Void) {
        URLSession.shared.dataTask(with: request(path)) { data, resp, _ in
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            let json = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            DispatchQueue.main.async { done(json, code) }
        }.resume()
    }

    func pythonPath() -> String? {
        ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"].first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    func ensureServer(_ ready: @escaping () -> Void) {
        getJSON("api/summary") { [weak self] _, code in
            guard let self else { return }
            if code == 200 { return ready() }
            if code == 401 || code == 403 {
                return self.showFatal("Outro Codeck já está usando a porta \(port). Feche-o (ou o ▶ do editor) e abra de novo.")
            }
            if attachMode { return self.waitForServer(attempts: 240, ready) } // espera o backend do debug subir
            self.startServer()
            self.waitForServer(attempts: 60, ready)
        }
    }

    func waitForServer(attempts: Int, _ ready: @escaping () -> Void) {
        getJSON("api/summary") { [weak self] _, code in
            if code == 200 { return ready() }
            guard attempts > 0 else {
                self?.showFatal("O backend do Codeck não respondeu. Log: ~/Library/Application Support/Codeck/codeck.log")
                return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self?.waitForServer(attempts: attempts - 1, ready) }
        }
    }

    func startServer() {
        guard let script = Bundle.main.path(forResource: "server", ofType: "py", inDirectory: "backend") else {
            return showFatal("O backend não está dentro do app.")
        }
        guard let python = pythonPath() else {
            return showFatal("Python 3 não encontrado. Instale as ferramentas da Apple com: xcode-select --install")
        }
        try? FileManager.default.createDirectory(at: supportDir, withIntermediateDirectories: true)
        let logURL = supportDir.appendingPathComponent("codeck.log")
        if !FileManager.default.fileExists(atPath: logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil) }
        let log = try? FileHandle(forWritingTo: logURL)
        log?.seekToEndOfFile()

        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = [script]
        var e = env
        e["CODECK_PORT"] = String(port)
        e["CODECK_TOKEN"] = token
        e["CODECK_PARENT_PID"] = String(ProcessInfo.processInfo.processIdentifier)
        e["CODECK_NATIVE_NOTIFY"] = "1"
        e["CODECK_VERSION"] = appVersion
        e["CODECK_BUILD"] = appBuild
        e["CODECK_PLATFORM"] = "macos"
        e["CODECK_UPDATE_URL"] = updateURL
        e["PYTHONDONTWRITEBYTECODE"] = "1"
        e["PYTHONUNBUFFERED"] = "1"
        p.environment = e
        p.currentDirectoryURL = supportDir
        p.standardOutput = log
        p.standardError = log
        p.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self, !self.quitting else { return }
                // caiu sozinho: sobe de novo
                DispatchQueue.main.asyncAfter(deadline: .now() + 3) { self.ensureServer { self.web.reload() } }
            }
        }
        do { try p.run(); server = p } catch { showFatal("Não consegui iniciar o backend: \(error.localizedDescription)") }
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        server?.terminate()
    }

    // MARK: janela

    func buildWindow() {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.mediaTypesRequiringUserActionForPlayback = []   // os sons dos avisos tocam sem esperar um clique
        if selfTestScript != nil {
            // ganchos de leitura para o autoteste (buffer do terminal, marcações do editor) — só neste modo
            config.userContentController.addUserScript(WKUserScript(source: "window.__CD_SELFTEST = true;", injectionTime: .atDocumentStart, forMainFrameOnly: true))
            // autoteste roda sem ninguém olhando: janela coberta/tela apagada não pode congelar os timers da página
            if #available(macOS 14.0, *) { config.preferences.inactiveSchedulingPolicy = .none }
            selfTestActivity = ProcessInfo.processInfo.beginActivity(options: [.userInitiated, .idleDisplaySleepDisabled], reason: "autoteste")
        }
        let js = "window.CODECK_TOKEN = \(jsString(token)); window.CODECK_PLATFORM = 'macos';"
        config.userContentController.addUserScript(WKUserScript(source: js, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        config.userContentController.add(self, name: "codeck")
        web = WKWebView(frame: .zero, configuration: config)
        web.uiDelegate = self
        web.navigationDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        web.loadHTMLString(Self.splash, baseURL: nil)

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1440, height: 900),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Codeck"
        window.minSize = NSSize(width: 760, height: 520)
        window.contentView = web
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.tabbingMode = .disallowed
        window.center()
        window.setFrameAutosaveName("CodeckMain")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func loadUI() {
        loaded = true
        web.load(URLRequest(url: baseURL))
        poll()
    }

    /// Um projeto numa janela só dele (ex.: outro monitor). Mesma chave, mesmo servidor; a tela entra no modo "solo".
    func openProjectWindow(hash: String, title: String) {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        let js = "window.CODECK_TOKEN = \(jsString(token)); window.CODECK_PLATFORM = 'macos';"
        config.userContentController.addUserScript(WKUserScript(source: js, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        config.userContentController.add(self, name: "codeck")
        let wv = WKWebView(frame: .zero, configuration: config)
        wv.uiDelegate = self
        wv.navigationDelegate = self
        wv.setValue(false, forKey: "drawsBackground")
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
                         styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        w.title = title
        w.minSize = NSSize(width: 760, height: 520)
        w.contentView = wv
        w.isReleasedWhenClosed = false
        w.tabbingMode = .disallowed
        w.appearance = window.appearance
        w.backgroundColor = window.backgroundColor
        w.setFrameAutosaveName("CodeckProject-\(title)")
        if !w.setFrameUsingName("CodeckProject-\(title)") { w.center() }
        var comps = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        comps.fragment = hash
        wv.load(URLRequest(url: comps.url!))
        w.makeKeyAndOrderFront(nil)
        projectWindows.removeAll { !$0.isVisible }
        projectWindows.append(w)
    }

    @objc func showWindow() {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        // Em tela cheia, esconder a janela deixa o espaço da tela cheia PRETO e travado (era preciso forçar o encerramento):
        // sai da tela cheia primeiro e esconde quando a animação termina (windowDidExitFullScreen).
        if sender.styleMask.contains(.fullScreen) {
            hideAfterFullScreen = true
            sender.toggleFullScreen(nil)
            return false
        }
        sender.orderOut(nil) // só esconde: o piloto continua agindo e avisando
        return false
    }

    func windowDidExitFullScreen(_ notification: Notification) {
        guard hideAfterFullScreen, let w = notification.object as? NSWindow else { return }
        hideAfterFullScreen = false
        w.orderOut(nil)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    @objc func reloadPage() {
        if loaded { web.reload() } else { ensureServer { [weak self] in self?.loadUI() } }
    }

    func openTarget(_ target: String) {
        showWindow()
        web.evaluateJavaScript("window.openTarget && window.openTarget(\(jsString(target)))")
    }

    // MARK: contador e notificações

    func buildStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            // a marca em "template" (o sistema pinta claro/escuro); sem o arquivo, um símbolo do sistema
            if let mark = Bundle.main.image(forResource: "MenuIcon") {
                mark.isTemplate = true
                mark.size = NSSize(width: 18, height: 18)
                mark.accessibilityDescription = "Codeck"
                button.image = mark
            } else {
                button.image = NSImage(systemSymbolName: "arrow.triangle.pull", accessibilityDescription: "Codeck")
            }
            button.imagePosition = .imageLeading
        }
        let menu = NSMenu()
        menu.addItem(withTitle: "Abrir Codeck", action: #selector(showWindow), keyEquivalent: "")
        menu.addItem(withTitle: "Ler o Azure agora", action: #selector(refreshNow), keyEquivalent: "")
        menu.addItem(withTitle: "Procurar atualização", action: #selector(checkUpdate), keyEquivalent: "")
        menu.addItem(.separator())
        loginMenuItem = menu.addItem(withTitle: "Abrir ao iniciar o Mac", action: #selector(toggleLoginItem), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "Sair do Codeck", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.delegate = self
        statusItem.menu = menu
    }

    func menuWillOpen(_ menu: NSMenu) {
        loginMenuItem.state = SMAppService.mainApp.status == .enabled ? .on : .off
    }

    func poll() {
        getJSON("api/summary") { [weak self] json, _ in
            guard let self else { return }
            let total = json?["total"] as? Int ?? 0
            NSApp.dockTile.badgeLabel = total > 0 ? String(total) : nil
            self.statusItem.button?.title = total > 0 ? " \(total)" : ""
            self.statusItem.button?.toolTip = json == nil ? "Codeck — backend fora do ar" : "Codeck — \(total) pendente(s)"
            guard let seq = json?["notifySeq"] as? Int else { return }
            if let power = json?["power"] as? [String: Any] { self.setHold(power["hold"] as? Bool ?? true) }
            if self.lastSeq < 0 { self.lastSeq = seq; return } // ao abrir, não repete o que já passou
            if seq > self.lastSeq { self.fetchNotifications() }
        }
    }

    // MARK: tela bloqueada, protetor de tela, suspensão — o modo vem do backend (/api/summary → power)

    /// "Continuar trabalhando": impede a suspensão por ociosidade e o App Nap (que atrasava os timers do app e do
    /// backend com a janela escondida pelo protetor de tela). O monitor pode apagar normalmente.
    func setHold(_ hold: Bool) {
        if hold, powerActivity == nil {
            powerActivity = ProcessInfo.processInfo.beginActivity(options: [.userInitiated, .idleSystemSleepDisabled],
                                                                  reason: "Codeck: agentes e automação trabalhando")
        } else if !hold, let a = powerActivity {
            ProcessInfo.processInfo.endActivity(a)
            powerActivity = nil
        }
    }

    func observePower() {
        let ws = NSWorkspace.shared.notificationCenter
        let local: [(Notification.Name, String)] = [(NSWorkspace.willSleepNotification, "sleep"), (NSWorkspace.didWakeNotification, "wake"),
                                                    (NSWorkspace.screensDidSleepNotification, "display-sleep"),
                                                    (NSWorkspace.screensDidWakeNotification, "display-wake")]
        for (name, event) in local {
            ws.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in self?.powerEvent(event) }
        }
        let dist: [(String, String)] = [("com.apple.screenIsLocked", "lock"), ("com.apple.screenIsUnlocked", "unlock"),
                                        ("com.apple.screensaver.didstart", "screensaver-start"), ("com.apple.screensaver.didstop", "screensaver-stop")]
        for (name, event) in dist {
            DistributedNotificationCenter.default().addObserver(forName: Notification.Name(name), object: nil, queue: .main) { [weak self] _ in
                self?.powerEvent(event)
            }
        }
    }

    /// `at`: quando aconteceu — o "sleep" sai ao dormir e às vezes só é entregue depois do "wake"; o backend descarta o
    /// atrasado. O "wake"/"unlock" tenta de novo se o backend não respondeu (a rede local volta junto, mas nem sempre na hora).
    func powerEvent(_ event: String, at: Double = Date().timeIntervalSince1970, attempt: Int = 0) {
        var req = request("api/power/event", method: "POST")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 10
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["event": event, "at": at])
        URLSession.shared.dataTask(with: req) { [weak self] _, resp, err in
            let ok = err == nil && (resp as? HTTPURLResponse)?.statusCode == 200
            let back = event == "wake" || event == "unlock"
            if !ok && back && attempt < 4 {
                DispatchQueue.main.asyncAfter(deadline: .now() + 3) { self?.powerEvent(event, at: at, attempt: attempt + 1) }
                return
            }
            if back { DispatchQueue.main.async { self?.poll() } }   // relê o contador já
        }.resume()
    }

    func fetchNotifications() {
        getJSON("api/notifications?after=\(lastSeq)") { [weak self] json, _ in
            guard let self, let items = json?["items"] as? [[String: Any]] else { return }
            for n in items { self.deliver(n) }
            self.lastSeq = json?["seq"] as? Int ?? self.lastSeq
        }
    }

    func setupNotifications() {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound, .badge]) { [weak self] granted, _ in
            DispatchQueue.main.async { self?.nativeNotifications = granted }
        }
    }

    func deliver(_ n: [String: Any]) {
        let title = n["title"] as? String ?? "Codeck", subtitle = n["subtitle"] as? String ?? "", body = n["message"] as? String ?? ""
        let target = n["target"] as? String ?? ""
        // o tipo do aviso pode estar só com som (a tela toca) — sem notificação do sistema
        if n["os"] as? Bool == false { return }
        if nativeNotifications {
            let content = UNMutableNotificationContent()
            content.title = title
            content.subtitle = subtitle
            content.body = body
            // som próprio do Codeck (tocado pela tela) ou mudo: a notificação sai sem o som do sistema
            let sound = n["sound"] as? String ?? "system"
            content.sound = sound == "system" ? .default : nil
            content.userInfo = ["target": target]
            UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
        } else {
            // sem permissão de notificação: aviso simples (não abre o item ao clicar)
            let q = { (s: String) in "\"" + s.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") + "\"" }
            NSAppleScript(source: "display notification \(q(body)) with title \(q(title)) subtitle \(q(subtitle))")?.executeAndReturnError(nil)
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        if let target = response.notification.request.content.userInfo["target"] as? String { openTarget(target) }
        completionHandler()
    }

    @objc func refreshNow() {
        URLSession.shared.dataTask(with: request("api/refresh", method: "POST")) { [weak self] _, _, _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 6) { self?.poll(); self?.web.reload() }
        }.resume()
    }

    @objc func checkUpdate() {
        showWindow()
        web.evaluateJavaScript("window.checkUpdate && window.checkUpdate(true)")
    }

    // MARK: atualização — o backend baixou e conferiu o SHA-256; aqui o .app é trocado

    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any] else { return }
        if body["type"] as? String == "pickFolder", let id = body["id"] as? String {
            return pickFolder(id: id, title: body["title"] as? String ?? "Escolha uma pasta")
        }
        if let t = body["type"] as? String, t.hasPrefix("selftest-") { return selfTestMessage(t, body) }
        if body["type"] as? String == "openWindow", let hash = body["hash"] as? String {
            return openProjectWindow(hash: hash, title: body["title"] as? String ?? "Codeck")
        }
        if body["type"] as? String == "power" { return poll() }   // mudou o modo em Configurações: aplica já
        if body["type"] as? String == "theme" {
            // a tela manda o tema RESOLVIDO; a barra de título e o fundo da janela acompanham
            let light = body["mode"] as? String == "light"
            window.appearance = NSAppearance(named: light ? .aqua : .darkAqua)
            window.backgroundColor = light ? NSColor(srgbRed: 0.961, green: 0.965, blue: 0.980, alpha: 1)
                                           : NSColor(srgbRed: 0.043, green: 0.051, blue: 0.071, alpha: 1)
            return
        }
        guard body["type"] as? String == "install", let path = body["path"] as? String else { return }
        do { try installUpdate(dmg: path) } catch { alert("Não consegui atualizar", error.localizedDescription) }
    }

    // MARK: seletor de pasta — devolve o caminho para a tela por window.__nativeResolve(id, path|null)

    func pickFolder(id: String, title: String) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.message = title
        panel.prompt = "Escolher"
        panel.beginSheetModal(for: window) { [weak self] resp in
            guard let self else { return }
            let path = resp == .OK ? panel.url?.path : nil
            self.web.evaluateJavaScript("window.__nativeResolve && window.__nativeResolve(\(self.jsString(id)), \(path.map(self.jsString) ?? "null"))")
        }
    }

    func installUpdate(dmg: String) throws {
        let updates = supportDir.appendingPathComponent("updates").path
        guard dmg.hasPrefix(updates + "/"), dmg.hasSuffix(".dmg"), FileManager.default.fileExists(atPath: dmg) else {
            throw NSError(domain: "Codeck", code: 1, userInfo: [NSLocalizedDescriptionKey: "Instalador fora da pasta de atualizações."])
        }
        let bundle = Bundle.main.bundlePath
        let parent = (bundle as NSString).deletingLastPathComponent
        let staged = "\(parent)/.codeck-update.app"
        let mount = NSTemporaryDirectory() + "codeck-mnt-\(UUID().uuidString)"
        try run("/usr/bin/hdiutil", ["attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", mount, dmg], "Não consegui abrir o .dmg baixado.")
        defer { _ = try? run("/usr/bin/hdiutil", ["detach", "-quiet", "-force", mount], "") }
        guard let app = try FileManager.default.contentsOfDirectory(atPath: mount).first(where: { $0.hasSuffix(".app") }) else {
            throw NSError(domain: "Codeck", code: 2, userInfo: [NSLocalizedDescriptionKey: "O .dmg não tem o aplicativo."])
        }
        _ = try? run("/bin/rm", ["-rf", staged], "")
        try run("/usr/bin/ditto", ["\(mount)/\(app)", staged], "Sem permissão para gravar em \(parent). Instale o .dmg à mão desta vez.")
        // Troca depois que este processo sair; se falhar, a versão antiga volta. Nunca fica sem app.
        let q = { (s: String) in "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'" }
        let pid = ProcessInfo.processInfo.processIdentifier
        let old = "\(bundle).old-\(pid)"
        let script = """
        #!/bin/sh
        for i in $(seq 1 120); do kill -0 \(pid) 2>/dev/null || break; sleep 0.5; done
        mv \(q(bundle)) \(q(old)) || exit 1
        if mv \(q(staged)) \(q(bundle)); then
          xattr -dr com.apple.quarantine \(q(bundle)) 2>/dev/null
          rm -rf \(q(old))
        else
          mv \(q(old)) \(q(bundle))
        fi
        open \(q(bundle))
        rm -f "$0"
        """
        let path = NSTemporaryDirectory() + "codeck-swap-\(pid).sh"
        try script.write(toFile: path, atomically: true, encoding: .utf8)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/sh")
        p.arguments = [path]
        try p.run()
        NSApp.terminate(nil)
    }

    @discardableResult
    func run(_ cmd: String, _ args: [String], _ message: String) throws -> Int32 {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: cmd)
        p.arguments = args
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        try p.run()
        p.waitUntilExit()
        if p.terminationStatus != 0 && !message.isEmpty {
            throw NSError(domain: "Codeck", code: Int(p.terminationStatus), userInfo: [NSLocalizedDescriptionKey: message])
        }
        return p.terminationStatus
    }

    // MARK: abrir no login

    func enableLoginItemOnFirstRun() {
        let key = "loginItemOffered"
        guard !UserDefaults.standard.bool(forKey: key) else { return }
        UserDefaults.standard.set(true, forKey: key)
        try? SMAppService.mainApp.register()
    }

    @objc func toggleLoginItem() {
        do {
            if SMAppService.mainApp.status == .enabled { try SMAppService.mainApp.unregister() } else { try SMAppService.mainApp.register() }
        } catch {
            alert("Não consegui alterar o item de login", error.localizedDescription)
        }
    }

    // MARK: diálogos do JavaScript (alert/confirm/prompt) e links externos

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert()
        a.messageText = message
        a.addButton(withTitle: "OK")
        a.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert()
        a.messageText = message
        a.addButton(withTitle: "Confirmar")
        a.addButton(withTitle: "Cancelar")
        a.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let a = NSAlert()
        a.messageText = prompt
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 320, height: 24))
        field.stringValue = defaultText ?? ""
        a.accessoryView = field
        a.addButton(withTitle: "Confirmar")
        a.addButton(withTitle: "Cancelar")
        a.window.initialFirstResponder = field
        a.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn ? field.stringValue : nil) }
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url { NSWorkspace.shared.open(url) } // target=_blank → navegador
        return nil
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = navigationAction.request.url, let host = url.host, host != "127.0.0.1", url.scheme?.hasPrefix("http") == true {
            NSWorkspace.shared.open(url)
            return decisionHandler(.cancel)
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // autoteste: o roteiro entra uma vez, quando a tela de verdade (não o splash) terminou de carregar
        guard webView === web, let path = selfTestScript, !selfTestStarted, webView.url?.host == "127.0.0.1",
              let code = try? String(contentsOfFile: path, encoding: .utf8) else { return }
        selfTestStarted = true
        let ctx = env["CODECK_SELFTEST_CTX"] ?? "{}"
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
            // o roteiro é assíncrono: devolve 0 para o WebKit (uma Promise não é um retorno aceito)
            webView.evaluateJavaScript("window.SELFTEST = \(ctx);\n" + code + "\n;0") { _, err in
                if let err { self.selfTestFinish("{\"fatal\": \(self.jsString(err.localizedDescription))}") }
            }
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in self?.reloadPage() }
    }

    // MARK: menus e utilidades

    func buildMainMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Sobre o Codeck", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(withTitle: "Procurar atualização…", action: #selector(checkUpdate), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Ocultar Codeck", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Sair do Codeck", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Editar")
        edit.addItem(withTitle: "Desfazer", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Refazer", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Recortar", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copiar", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Colar", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Selecionar tudo", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)

        let viewItem = NSMenuItem()
        let view = NSMenu(title: "Visualizar")
        view.addItem(withTitle: "Recarregar", action: #selector(reloadPage), keyEquivalent: "r")
        view.addItem(withTitle: "Ler o Azure agora", action: #selector(refreshNow), keyEquivalent: "R")
        viewItem.submenu = view
        main.addItem(viewItem)

        let winItem = NSMenuItem()
        let win = NSMenu(title: "Janela")
        win.addItem(withTitle: "Minimizar", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        // ⌘W fica para a tela (fecha a aba de terminal/arquivo); a janela fecha com ⇧⌘W
        win.addItem(withTitle: "Fechar janela", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "W")
        win.addItem(withTitle: "Mostrar Codeck", action: #selector(showWindow), keyEquivalent: "0")
        winItem.submenu = win
        main.addItem(winItem)
        NSApp.windowsMenu = win
        NSApp.mainMenu = main
    }

    func alert(_ title: String, _ text: String) {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = text
        a.runModal()
    }

    func showFatal(_ text: String) {
        let safe = text.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;").replacingOccurrences(of: ">", with: "&gt;")
        web?.loadHTMLString(Self.splash.replacingOccurrences(of: "Iniciando…", with: safe), baseURL: nil)
    }

    func jsString(_ s: String) -> String {
        let data = try? JSONSerialization.data(withJSONObject: [s])
        let arr = data.flatMap { String(data: $0, encoding: .utf8) } ?? "[\"\"]"
        return String(arr.dropFirst().dropLast())
    }

    /// A tela de abertura animada (brand/splash.html, copiada para Resources pelo build). Sem ela, um texto simples.
    static let splash: String = {
        if let url = Bundle.main.url(forResource: "splash", withExtension: "html"),
           let html = try? String(contentsOf: url, encoding: .utf8) { return html }
        return "<html><body style=\"margin:0;height:100vh;display:grid;place-items:center;font:15px -apple-system,sans-serif;background:#07080d;color:#b4bac6\">Iniciando…</body></html>"
    }()
}

// MARK: autoteste do desktop — teclas reais (NSEvent), screenshots da janela e estado nativo
var selfTestStarted = false
var selfTestActivity: NSObjectProtocol?

extension AppDelegate {
    func selfTestReply(_ id: Any?, _ value: String) {
        guard let id = id as? String else { return }
        web.evaluateJavaScript("window.__selftestResolve && window.__selftestResolve(\(jsString(id)), \(value))")
    }

    func selfTestMessage(_ type: String, _ body: [String: Any]) {
        guard selfTestScript != nil else { return }
        let id = body["id"]
        switch type {
        case "selftest-keys":
            // [{c: caracteres, k: keyCode, m: "cmd,shift,alt,ctrl"}]: enviados como eventos de teclado do sistema
            let target = (body["window"] as? Int).flatMap { $0 > 0 && $0 <= projectWindows.count ? projectWindows[$0 - 1] : nil } ?? window!
            // texto só entra numa janela em foco (janela-chave): garante isso antes de cada sequência
            if !target.isKeyWindow {
                NSApp.activate(ignoringOtherApps: true)
                target.makeKeyAndOrderFront(nil)
            }
            for k in (body["keys"] as? [[String: Any]]) ?? [] {
                var mods: NSEvent.ModifierFlags = []
                let m = (k["m"] as? String) ?? ""
                if m.contains("cmd") { mods.insert(.command) }
                if m.contains("shift") { mods.insert(.shift) }
                if m.contains("alt") { mods.insert(.option) }
                if m.contains("ctrl") { mods.insert(.control) }
                let chars = (k["c"] as? String) ?? ""
                let code = UInt16((k["k"] as? Int) ?? 0)
                // texto comum entra pelo NSTextInputClient da WKWebView (o mesmo caminho que o macOS usa para entregar o
                // que foi digitado) — não depende da janela estar em foco. Atalhos e teclas especiais seguem como eventos.
                let plain = mods.subtracting(.shift).isEmpty && chars.unicodeScalars.allSatisfy { $0.value >= 0x20 && $0.value < 0xF700 && $0.value != 0x7F }
                if plain, !chars.isEmpty, let wv = target.contentView as? WKWebView {
                    wv.insertText(chars)
                    continue
                }
                for type in [NSEvent.EventType.keyDown, .keyUp] {
                    if let ev = NSEvent.keyEvent(with: type, location: .zero, modifierFlags: mods, timestamp: ProcessInfo.processInfo.systemUptime,
                                                 windowNumber: target.windowNumber, context: nil, characters: chars,
                                                 charactersIgnoringModifiers: (k["i"] as? String) ?? chars.lowercased(), isARepeat: false, keyCode: code) {
                        target.sendEvent(ev)
                    }
                }
            }
            selfTestReply(id, "true")
        case "selftest-shot":
            let name = (body["name"] as? String) ?? "shot"
            let wv: WKWebView = (body["window"] as? Int).flatMap { $0 > 0 && $0 <= projectWindows.count ? projectWindows[$0 - 1].contentView as? WKWebView : nil } ?? web
            wv.takeSnapshot(with: nil) { img, _ in
                if let img, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff), let png = rep.representation(using: .png, properties: [:]) {
                    try? png.write(to: URL(fileURLWithPath: selfTestOut).appendingPathComponent("\(name).png"))
                }
                self.selfTestReply(id, "true")
            }
        case "selftest-native":
            let appearance = window.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua])?.rawValue ?? "?"
            let visible = projectWindows.filter { $0.isVisible }
            let info: [String: Any] = ["windows": 1 + visible.count, "appearance": appearance, "titles": visible.map { $0.title },
                                       "keyWindow": NSApp.keyWindow?.title ?? "", "visible": window.occlusionState.contains(.visible)]
            let json = String(data: try! JSONSerialization.data(withJSONObject: info), encoding: .utf8)!
            selfTestReply(id, json)
        case "selftest-focus":
            NSApp.activate(ignoringOtherApps: true)
            window.level = .floating   // autoteste: por cima das outras janelas, para continuar em foco
            window.makeKeyAndOrderFront(nil)
            window.makeFirstResponder(web)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { self.selfTestReply(id, self.window.isKeyWindow ? "true" : "false") }
        case "selftest-fullscreen":
            window.level = .normal   // janela "flutuante" (modo de teste) não entra em tela cheia
            if !window.styleMask.contains(.fullScreen) { window.toggleFullScreen(nil) }
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.selfTestReply(id, self.window.styleMask.contains(.fullScreen) ? "true" : "false") }
        case "selftest-close":
            window.performClose(nil)   // o botão vermelho
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
                let info: [String: Any] = ["visible": self.window.isVisible, "fullScreen": self.window.styleMask.contains(.fullScreen)]
                self.selfTestReply(id, String(data: try! JSONSerialization.data(withJSONObject: info), encoding: .utf8)!)
            }
        case "selftest-show":
            showWindow()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.selfTestReply(id, self.window.isVisible ? "true" : "false") }
        case "selftest-quit":
            NSApp.terminate(nil)   // o mesmo do ⌘Q / menu "Sair"
        case "selftest-done":
            selfTestFinish((body["result"] as? String) ?? "{}")
        default:
            break
        }
    }

    func selfTestFinish(_ json: String) {
        try? json.write(toFile: URL(fileURLWithPath: selfTestOut).appendingPathComponent("result.json").path, atomically: true, encoding: .utf8)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { NSApp.terminate(nil) }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
