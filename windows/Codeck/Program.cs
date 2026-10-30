// Codeck para Windows: janela (WebView2) para a tela do backend em Python, ícone na bandeja com o contador,
// notificações que abrem o item e atualização pelo ThomSoft Setup (`--update --wait-pid`).
//
// O mesmo contrato do app do macOS (macos/Codeck.swift): sobe backend\server.py com o Python embutido e uma
// chave nova por execução — sem ela o backend não responde, então nenhum outro programa da máquina age por você.
// Desenvolvimento: CODECK_ATTACH=1 + CODECK_PORT conecta num backend já rodando; CODECK_BACKEND_DIR e
// CODECK_PYTHON apontam para o código do repositório e para o python do PATH.
using System.Diagnostics;
using System.Drawing.Drawing2D;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using Microsoft.Win32;

namespace Codeck;

static class Program
{
    [STAThread]
    static void Main()
    {
        using var single = new Mutex(true, @"Local\Codeck.Single", out var first);
        using var showSignal = new EventWaitHandle(false, EventResetMode.AutoReset, @"Local\Codeck.Show");
        if (!first)
        {
            showSignal.Set(); // já está aberto: só traz a janela para a frente
            return;
        }
        ApplicationConfiguration.Initialize();
        Application.Run(new MainForm(showSignal));
    }
}

sealed class MainForm : Form
{
    const string ProductId = "codeck";
    const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";

    static readonly Dictionary<string, string?> Env = Environment.GetEnvironmentVariables()
        .Cast<System.Collections.DictionaryEntry>().ToDictionary(e => (string)e.Key, e => (string?)e.Value, StringComparer.OrdinalIgnoreCase);

    readonly bool attach = Env.GetValueOrDefault("CODECK_ATTACH") == "1";
    readonly int port = int.TryParse(Env.GetValueOrDefault("CODECK_PORT"), out var p) ? p : 47821;
    readonly string token;
    readonly string baseUrl;
    readonly string dataDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Codeck");
    readonly HttpClient http = new() { Timeout = TimeSpan.FromSeconds(4) };
    readonly WebView2 web = new() { Dock = DockStyle.Fill };
    CoreWebView2Environment? envWv;   // o mesmo ambiente serve às janelas de projeto
    // Autoteste do app de desktop (scripts/test-desktop / CI): roteiro JS rodando DENTRO desta janela
    readonly string? selfTest = Environment.GetEnvironmentVariable("CODECK_SELFTEST");
    readonly string selfOut = Environment.GetEnvironmentVariable("CODECK_SELFTEST_OUT") ?? Path.GetTempPath();
    bool selfStarted;
    bool lastLight;
    readonly NotifyIcon tray = new();
    readonly ToolStripMenuItem autostartItem = new("Iniciar com o Windows");
    readonly System.Windows.Forms.Timer timer = new() { Interval = 15000 };
    readonly Icon baseIcon, windowIcon;
    readonly IntPtr job = Job.Create();
    readonly (string Version, int Build, string UpdateUrl) office = ReadOffice();
    Process? backend;
    bool quitting, loaded, hintShown;
    int lastSeq = -1;
    string? lastTarget;
    bool? holdAwake;          // segurando o PC acordado (Configurações → Geral → "Com a tela bloqueada…")
    bool screensaverOn;

    // Modo attach (depuração): a chave do backend vem de CODECK_TOKEN ou do arquivo que ele gravou (CODECK_TOKEN_FILE)
    static string AttachToken()
    {
        var t = Env.GetValueOrDefault("CODECK_TOKEN");
        if (!string.IsNullOrEmpty(t)) return t;
        var file = Env.GetValueOrDefault("CODECK_TOKEN_FILE");
        try { return string.IsNullOrEmpty(file) ? "" : File.ReadAllText(file).Trim(); } catch (Exception) { return ""; }
    }

    public MainForm(EventWaitHandle showSignal)
    {
        AdoptLegacyData();
        token = attach ? AttachToken() : Convert.ToHexString(System.Security.Cryptography.RandomNumberGenerator.GetBytes(32));
        baseUrl = $"http://127.0.0.1:{port}/";
        http.DefaultRequestHeaders.Add("X-Codeck-Token", token);
        baseIcon = LoadIcon(SystemInformation.SmallIconSize);   // bandeja
        windowIcon = LoadIcon(SystemInformation.IconSize);      // barra de tarefas / Alt+Tab
        RefreshShellIconsOnUpgrade();

        Text = "Codeck";
        Icon = windowIcon;
        MinimumSize = new Size(760, 520);
        StartPosition = FormStartPosition.CenterScreen;
        Size = new Size(1440, 900);
        Controls.Add(web);

        var menu = new ContextMenuStrip();
        menu.Items.Add("Abrir Codeck", null, (_, _) => ShowMain());
        menu.Items.Add("Ler o Azure agora", null, async (_, _) => await RefreshNow());
        menu.Items.Add("Procurar atualização", null, async (_, _) => { ShowMain(); await Js("window.checkUpdate && window.checkUpdate(true)"); });
        menu.Items.Add(new ToolStripSeparator());
        autostartItem.Click += (_, _) => ToggleAutostart();
        menu.Items.Add(autostartItem);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Sair do Codeck", null, (_, _) => Quit());
        menu.Opening += (_, _) => autostartItem.Checked = AutostartEnabled();
        tray.Icon = baseIcon;
        tray.Text = "Codeck";
        tray.ContextMenuStrip = menu;
        tray.Visible = true;
        tray.DoubleClick += (_, _) => ShowMain();
        tray.BalloonTipClicked += async (_, _) => { ShowMain(); if (lastTarget != null) await OpenTarget(lastTarget); };

        timer.Tick += async (_, _) => await Poll();
        SetHold(true);   // até o backend dizer o modo: o padrão é continuar trabalhando
        SystemEvents.PowerModeChanged += OnPowerMode;
        SystemEvents.SessionSwitch += OnSessionSwitch;
        new Thread(() => { while (showSignal.WaitOne()) BeginInvoke(ShowMain); }) { IsBackground = true }.Start();
        Load += async (_, _) => await Start();
    }

    // ------------------------------------------------------------------ backend

    static (string, int, string) ReadOffice()
    {
        // O ThomSoft Setup grava office.json ao lado do .exe: versão, build e onde procurar a próxima.
        try
        {
            var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "office.json"))).RootElement;
            return (doc.GetProperty("version").GetString() ?? "dev", doc.GetProperty("build").GetInt32(),
                    doc.TryGetProperty("updateUrl", out var u) ? u.GetString() ?? "" : "");
        }
        catch { return ("dev", 0, ""); }
    }

    async Task<(int Code, JsonElement? Json)> Get(string path)
    {
        try
        {
            using var r = await http.GetAsync(baseUrl + path);
            var body = await r.Content.ReadAsStringAsync();
            return ((int)r.StatusCode, body.Length > 0 ? JsonDocument.Parse(body).RootElement.Clone() : null);
        }
        catch { return (0, null); }
    }

    async Task Start()
    {
        await InitWebView();
        var (code, _) = await Get("api/summary");
        if (code is 401 or 403) { Fatal($"Outro Codeck já está usando a porta {port}. Feche-o e abra de novo."); return; }
        if (code != 200 && !attach) StartBackend();
        for (var i = 0; i < (attach ? 240 : 80); i++)
        {
            if ((await Get("api/summary")).Code == 200)
            {
                loaded = true;
                if (selfTest != null) web.CoreWebView2.NavigationCompleted += async (_, _) =>
                {
                    if (selfStarted || !web.Source.ToString().StartsWith(baseUrl)) return;
                    selfStarted = true;
                    await Task.Delay(1500);
                    var ctx = Environment.GetEnvironmentVariable("CODECK_SELFTEST_CTX") ?? "{}";
                    await web.CoreWebView2.ExecuteScriptAsync("window.SELFTEST = " + ctx + ";\n" + File.ReadAllText(selfTest) + "\n;0");
                };
                web.CoreWebView2.Navigate(baseUrl);
                timer.Start();
                await Poll();
                return;
            }
            await Task.Delay(500);
        }
        Fatal($"O backend do Codeck não respondeu. Log: {Path.Combine(dataDir, "codeck.log")}");
    }

    void StartBackend()
    {
        var dir = AppContext.BaseDirectory;
        var backendDir = Env.GetValueOrDefault("CODECK_BACKEND_DIR") ?? Path.Combine(dir, "backend");
        var python = Env.GetValueOrDefault("CODECK_PYTHON") ?? Path.Combine(dir, "python", "pythonw.exe");
        var script = Path.Combine(backendDir, "server.py");
        if (!File.Exists(script) || (!File.Exists(python) && Env.GetValueOrDefault("CODECK_PYTHON") == null))
        {
            Fatal("Instalação incompleta: falta o backend ou o Python embutido. Reinstale o Codeck.");
            return;
        }
        Directory.CreateDirectory(dataDir);
        var psi = new ProcessStartInfo(python, $"-I -B -u \"{script}\"")   // -I: PYTHONPATH/PYTHONHOME não entram no backend
        {
            UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = dataDir,
            RedirectStandardOutput = true, RedirectStandardError = true,
        };
        psi.Environment["CODECK_PORT"] = port.ToString();
        psi.Environment["CODECK_TOKEN"] = token;
        psi.Environment["CODECK_PARENT_PID"] = Environment.ProcessId.ToString();
        psi.Environment["CODECK_NATIVE_NOTIFY"] = "1";
        psi.Environment["CODECK_VERSION"] = office.Version;
        psi.Environment["CODECK_BUILD"] = office.Build.ToString();
        psi.Environment["CODECK_PLATFORM"] = "windows";
        psi.Environment["CODECK_UPDATE_URL"] = office.UpdateUrl;
        psi.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
        psi.Environment["PYTHONUNBUFFERED"] = "1";
        psi.Environment["PYTHONIOENCODING"] = "utf-8";
        var log = new StreamWriter(Path.Combine(dataDir, "codeck.log"), append: true) { AutoFlush = true };
        var proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
        proc.OutputDataReceived += (_, e) => { if (e.Data != null) lock (log) log.WriteLine(e.Data); };
        proc.ErrorDataReceived += (_, e) => { if (e.Data != null) lock (log) log.WriteLine(e.Data); };
        proc.Exited += (_, _) =>
        {
            if (quitting) return;
            // caiu sozinho: sobe de novo
            BeginInvoke(async () => { await Task.Delay(3000); if (!quitting) { StartBackend(); await Task.Delay(2000); web.Reload(); } });
        };
        proc.Start();
        Job.Assign(job, proc); // o Windows encerra o backend junto com o app, mesmo se o app cair
        proc.BeginOutputReadLine();
        proc.BeginErrorReadLine();
        backend = proc;
    }

    // ------------------------------------------------------------------ janela

    async Task InitWebView()
    {
        try
        {
            // sem estrangular a tela em segundo plano (janela escondida, protetor de tela): os timers seguem no ritmo
            var opts = new CoreWebView2EnvironmentOptions
            { AdditionalBrowserArguments = "--disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows" };
            envWv = await CoreWebView2Environment.CreateAsync(null, Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Codeck", "WebView2"), opts);
            await web.EnsureCoreWebView2Async(envWv);
        }
        catch (WebView2RuntimeNotFoundException)
        {
            MessageBox.Show("O Codeck precisa do Microsoft Edge WebView2 Runtime. A página de download vai abrir.", "Codeck");
            Process.Start(new ProcessStartInfo("https://go.microsoft.com/fwlink/p/?LinkId=2124703") { UseShellExecute = true });
            Quit();
            return;
        }
        var core = web.CoreWebView2;
        core.Settings.AreDevToolsEnabled = attach;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.AreDefaultContextMenusEnabled = attach;
        await core.AddScriptToExecuteOnDocumentCreatedAsync(
            WindowSafety.TokenScript(baseUrl, token, selfTest != null ? " window.__CD_SELFTEST = true;" : ""));
        WindowSafety.Guard(core, baseUrl);
        core.WebMessageReceived += (_, e) => { if (WindowSafety.FromUs(e.Source, baseUrl)) OnWebMessage(e.WebMessageAsJson); };
        core.NavigateToString(Splash("Iniciando…"));
    }

    void Fatal(string text)
    {
        if (web.CoreWebView2 != null) web.CoreWebView2.NavigateToString(Splash(System.Net.WebUtility.HtmlEncode(text)));
        else MessageBox.Show(text, "Codeck");
    }

    void ShowMain()
    {
        Show();
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        Activate();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (!quitting && e.CloseReason == CloseReason.UserClosing)
        {
            e.Cancel = true; // só esconde: o piloto continua agindo e avisando
            Hide();
            if (!hintShown)
            {
                hintShown = true;
                tray.ShowBalloonTip(4000, "Codeck continua rodando", "Ele segue aprovando e avisando aqui na bandeja. Para fechar de vez: botão direito → Sair.", ToolTipIcon.Info);
            }
            return;
        }
        base.OnFormClosing(e);
    }

    void Quit()
    {
        quitting = true;
        timer.Stop();
        SystemEvents.PowerModeChanged -= OnPowerMode;   // eventos estáticos: soltar antes de sair
        SystemEvents.SessionSwitch -= OnSessionSwitch;
        SetHold(false);
        tray.Visible = false;
        try { if (backend is { HasExited: false }) backend.Kill(true); } catch { }
        Application.Exit();
    }

    async Task Js(string script)
    {
        if (loaded && web.CoreWebView2 != null) await web.CoreWebView2.ExecuteScriptAsync(script);
    }

    async Task OpenTarget(string target) => await Js($"window.openTarget && window.openTarget({JsonSerializer.Serialize(target)})");

    async Task RefreshNow()
    {
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Post, baseUrl + "api/refresh") { Content = new StringContent("{}") };
            req.Headers.Add("X-Codeck", "1");
            await http.SendAsync(req);
        }
        catch { }
        await Task.Delay(6000);
        await Poll();
        web.Reload();
    }

    // ------------------------------------------------------------------ contador e notificações

    async Task Poll()
    {
        var (code, json) = await Get("api/summary");
        var total = code == 200 && json?.TryGetProperty("total", out var t) == true ? t.GetInt32() : 0;
        Text = total > 0 ? $"({total}) Codeck" : "Codeck";
        tray.Text = code != 200 ? "Codeck — backend fora do ar" : total > 0 ? $"Codeck — {total} pendente(s)" : "Codeck — nada pendente";
        SetBadge(total);
        if (code == 200 && json?.TryGetProperty("power", out var pw) == true && pw.TryGetProperty("hold", out var h))
            SetHold(h.ValueKind != JsonValueKind.False);
        CheckScreensaver();
        if (code != 200 || json?.TryGetProperty("notifySeq", out var s) != true) return;
        var seq = s.GetInt32();
        if (lastSeq < 0) { lastSeq = seq; return; } // ao abrir, não repete o que já passou
        if (seq <= lastSeq) return;
        var (_, list) = await Get($"api/notifications?after={lastSeq}");
        if (list?.TryGetProperty("items", out var items) == true)
            foreach (var n in items.EnumerateArray())
            {
                // o tipo do aviso pode estar só com som (a tela toca) — sem balão do sistema
                if (n.TryGetProperty("os", out var osOn) && osOn.ValueKind == JsonValueKind.False) continue;
                lastTarget = n.TryGetProperty("target", out var tg) ? tg.GetString() : null;
                var title = n.GetProperty("title").GetString() ?? "Codeck";
                var body = $"{n.GetProperty("subtitle").GetString()}\n{n.GetProperty("message").GetString()}".Trim();
                tray.ShowBalloonTip(8000, title, body.Length > 250 ? body[..250] : body, ToolTipIcon.Info);
            }
        lastSeq = list?.TryGetProperty("seq", out var ns) == true ? ns.GetInt32() : seq;
    }

    // ------------------------------------------------------------------ tela bloqueada, protetor de tela, suspensão

    // "Continuar trabalhando": o Windows não suspende por ociosidade enquanto o app pedir (o monitor pode apagar).
    // ES_CONTINUOUS vale para a thread que chamou até a próxima chamada — aqui é sempre a thread da janela.
    void SetHold(bool hold)
    {
        if (holdAwake == hold) return;
        holdAwake = hold;
        Native.SetThreadExecutionState(hold ? Native.EsContinuous | Native.EsSystemRequired : Native.EsContinuous);
    }

    void OnPowerMode(object? sender, PowerModeChangedEventArgs e)
    {
        if (e.Mode == PowerModes.Suspend) _ = PowerEvent("sleep");
        else if (e.Mode == PowerModes.Resume) BeginInvoke(async () => { await PowerEvent("wake"); await Poll(); });
    }

    void OnSessionSwitch(object? sender, SessionSwitchEventArgs e)
    {
        if (e.Reason == SessionSwitchReason.SessionLock) _ = PowerEvent("lock");
        else if (e.Reason == SessionSwitchReason.SessionUnlock) BeginInvoke(async () => { await PowerEvent("unlock"); await Poll(); });
    }

    // O Windows não avisa quando o protetor de tela começa: confere a cada leitura do contador (15 s)
    void CheckScreensaver()
    {
        var running = false;
        if (!Native.SystemParametersInfo(Native.SpiGetScreenSaverRunning, 0, ref running, 0) || running == screensaverOn) return;
        screensaverOn = running;
        _ = PowerEvent(running ? "screensaver-start" : "screensaver-stop");
    }

    async Task PowerEvent(string name)
    {
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Post, baseUrl + "api/power/event")
            { Content = new StringContent(JsonSerializer.Serialize(new { @event = name }), System.Text.Encoding.UTF8, "application/json") };
            req.Headers.Add("X-Codeck", "1");
            await http.SendAsync(req);
        }
        catch { }
    }

    int lastBadge = -1;
    void SetBadge(int total)
    {
        if (total == lastBadge) return;
        lastBadge = total;
        var old = tray.Icon;
        if (total <= 0) { tray.Icon = baseIcon; }
        else
        {
            using var bmp = new Bitmap(32, 32);
            using (var g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
                g.DrawIcon(new Icon(windowIcon, 32, 32), 0, 0);
                var label = total > 99 ? "99+" : total.ToString();
                g.FillEllipse(Brushes.Red, 13, 13, 19, 19);
                using var f = new Font("Segoe UI", label.Length > 1 ? 8f : 10f, FontStyle.Bold, GraphicsUnit.Pixel);
                var sz = g.MeasureString(label, f);
                g.DrawString(label, f, Brushes.White, 22.5f - sz.Width / 2, 22.5f - sz.Height / 2);
            }
            var h = bmp.GetHicon();
            tray.Icon = (Icon)Icon.FromHandle(h).Clone();
            Native.DestroyIcon(h);
        }
        if (old != baseIcon) old?.Dispose();
    }

    static Icon LoadIcon(Size size)
    {
        using var s = typeof(MainForm).Assembly.GetManifestResourceStream("Codeck.app.ico");
        return s != null ? new Icon(s, size) : SystemIcons.Application;
    }

    /// O Windows guarda o ícone por caminho do .exe: depois de atualizar por cima, a barra de tarefas e o menu
    /// Iniciar continuariam com o ícone antigo. Na primeira execução de cada versão, pede para ele recarregar.
    void RefreshShellIconsOnUpgrade()
    {
        try
        {
            using var k = Registry.CurrentUser.CreateSubKey(@"Software\ThomSoft\Codeck");
            var current = $"{office.Version}+{office.Build}";
            if ((k.GetValue("IconVersion") as string) == current) return;
            Native.SHChangeNotify(0x08000000, 0x1000, IntPtr.Zero, IntPtr.Zero); // SHCNE_ASSOCCHANGED, SHCNF_FLUSH
            k.SetValue("IconVersion", current);
        }
        catch { }
    }

    // ------------------------------------------------------------------ iniciar com o Windows (mesma chave do ThomSoft Setup)

    static bool AutostartEnabled()
    {
        using var k = Registry.CurrentUser.OpenSubKey(RunKey);
        return k?.GetValue(ProductId) != null;
    }

    static void ToggleAutostart()
    {
        using var k = Registry.CurrentUser.CreateSubKey(RunKey);
        if (k.GetValue(ProductId) != null) k.DeleteValue(ProductId);
        else k.SetValue(ProductId, $"\"{Environment.ProcessPath}\"");
    }

    // ------------------------------------------------------------------ atualização

    void OnWebMessage(string json)
    {
        try
        {
            var msg = JsonDocument.Parse(json).RootElement;
            var type = msg.GetProperty("type").GetString();
            if (type != null && type.StartsWith("selftest-")) { _ = SelfTest(type, msg); return; }
            if (type == "pickFolder") { PickFolder(msg.GetProperty("id").GetString() ?? "", msg.TryGetProperty("title", out var t) ? t.GetString() : null); return; }
            if (type == "theme") { ApplyTheme(msg.TryGetProperty("mode", out var m) && m.GetString() == "light"); return; }
            if (type == "power") { _ = Poll(); return; }   // mudou o modo em Configurações: aplica já
            if (type == "openWindow" && envWv != null)
            {
                var hash = msg.GetProperty("hash").GetString() ?? "";
                var title = msg.TryGetProperty("title", out var tt) ? tt.GetString() ?? "Codeck" : "Codeck";
                new ProjectWindow(envWv, baseUrl, token, hash, title, Icon, BackColor).Show();
                return;
            }
            if (type != "install") return;
            var path = Path.GetFullPath(msg.GetProperty("path").GetString() ?? "");
            var updates = Path.GetFullPath(Path.Combine(dataDir, "updates")) + Path.DirectorySeparatorChar;
            // o backend baixou e conferiu o SHA-256; aqui só aceita o que está na pasta dele
            if (!path.StartsWith(updates, StringComparison.OrdinalIgnoreCase) || !path.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) || !File.Exists(path))
                throw new InvalidOperationException("Instalador fora da pasta de atualizações.");
            Process.Start(new ProcessStartInfo(path, $"--update --wait-pid {Environment.ProcessId}") { UseShellExecute = true });
            Quit();
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Não consegui atualizar: {ex.Message}", "Codeck");
        }
    }

    // A tela manda o tema RESOLVIDO (claro/escuro); a barra de título e o fundo da janela acompanham, para não haver
    // faixa clara sobre o app escuro nem clarão ao redimensionar.
    void ApplyTheme(bool light)
    {
        int dark = light ? 0 : 1;
        DwmSetWindowAttribute(Handle, 20, ref dark, sizeof(int)); // DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 10 20H1+ e 11)
        BackColor = light ? Color.FromArgb(0xf5, 0xf6, 0xfa) : Color.FromArgb(0x0b, 0x0d, 0x12);
        lastLight = light;
    }

    // ---------------------------------------------------------------- autoteste
    static readonly Dictionary<string, string> KeyCodes = new()
    {
        ["Enter"] = "Enter", ["Escape"] = "Escape", ["Tab"] = "Tab", ["Backspace"] = "Backspace", ["F12"] = "F12",
        ["ArrowUp"] = "ArrowUp", ["ArrowDown"] = "ArrowDown", ["ArrowLeft"] = "ArrowLeft", ["ArrowRight"] = "ArrowRight", ["Home"] = "Home", ["End"] = "End",
    };

    async Task SelfTest(string type, JsonElement msg)
    {
        if (selfTest == null) return;
        var id = msg.TryGetProperty("id", out var i) ? i.GetString() : null;
        var target = web;
        if (msg.TryGetProperty("window", out var wn) && wn.ValueKind == JsonValueKind.Number && wn.GetInt32() > 0)
        {
            var pw = Application.OpenForms.OfType<ProjectWindow>().Skip(wn.GetInt32() - 1).FirstOrDefault();
            if (pw != null) target = pw.View;
        }
        string reply = "true";
        switch (type)
        {
            case "selftest-keys":
                // teclas confiáveis (isTrusted) pelo próprio navegador: o mesmo caminho de uma tecla do usuário
                foreach (var k in msg.GetProperty("keys").EnumerateArray())
                {
                    var c = k.TryGetProperty("c", out var cc) ? cc.GetString() ?? "" : "";
                    var n = k.TryGetProperty("n", out var nn) ? nn.GetString() ?? c : c;
                    var vk = k.TryGetProperty("k", out var kk) ? kk.GetInt32() : 0;
                    var m = k.TryGetProperty("m", out var mm) ? mm.GetString() ?? "" : "";
                    var mods = (m.Contains("alt") ? 1 : 0) | (m.Contains("ctrl") ? 2 : 0) | (m.Contains("cmd") ? 4 : 0) | (m.Contains("shift") ? 8 : 0);
                    var special = KeyCodes.ContainsKey(n);
                    var code = special ? KeyCodes[n] : (vk >= 65 && vk <= 90 ? "Key" + (char)vk : vk >= 48 && vk <= 57 ? "Digit" + (char)vk : "");
                    var shortcut = (mods & 6) != 0;
                    var down = new Dictionary<string, object>
                    {
                        ["type"] = special || shortcut ? "rawKeyDown" : "keyDown", ["key"] = special ? n : c, ["code"] = code,
                        ["windowsVirtualKeyCode"] = vk, ["nativeVirtualKeyCode"] = vk, ["modifiers"] = mods,
                    };
                    if (!special && !shortcut) { down["text"] = c; down["unmodifiedText"] = c; }
                    await target.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchKeyEvent", JsonSerializer.Serialize(down));
                    if (n == "Enter")
                        await target.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchKeyEvent", JsonSerializer.Serialize(new { type = "char", text = "\r", key = "Enter", modifiers = mods }));
                    await target.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchKeyEvent", JsonSerializer.Serialize(new
                    {
                        type = "keyUp", key = special ? n : c, code, windowsVirtualKeyCode = vk, nativeVirtualKeyCode = vk, modifiers = mods,
                    }));
                }
                break;
            case "selftest-shot":
                var name = msg.TryGetProperty("name", out var nm) ? nm.GetString() ?? "shot" : "shot";
                using (var fs = File.Create(Path.Combine(selfOut, name + ".png")))
                    await target.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, fs);
                break;
            case "selftest-native":
                var wins = Application.OpenForms.OfType<ProjectWindow>().ToList();
                reply = JsonSerializer.Serialize(new { windows = 1 + wins.Count, appearance = lastLight ? "light" : "dark", titles = wins.Select(w => w.Text).ToArray(), keyWindow = ActiveForm?.Text ?? "", visible = Visible && WindowState != FormWindowState.Minimized });
                break;
            case "selftest-consoles":
                // janelas de console que apareceram desde a 1ª chamada. O backend roda sem console (pythonw): um processo
                // filho sem CREATE_NO_WINDOW abre uma janela — o bug da aba IA da 4.8.1. probe = abre uma de controle,
                // para o teste provar que o detector enxerga (sem isso, "0 janelas" não diria nada)
                ConsoleWatch.Start();
                if (msg.TryGetProperty("probe", out var pb) && pb.ValueKind == JsonValueKind.True)
                {
                    using var probe = Process.Start(new ProcessStartInfo("cmd.exe", "/c ping -n 3 127.0.0.1 >nul") { UseShellExecute = false, CreateNoWindow = false });
                    await Task.Delay(2500);
                    try { probe?.Kill(true); } catch { }
                }
                reply = ConsoleWatch.Shown.ToString();
                break;
            case "selftest-focus":
                Activate();
                web.Focus();
                break;
            case "selftest-done":
                File.WriteAllText(Path.Combine(selfOut, "result.json"), msg.TryGetProperty("result", out var r) ? r.GetString() ?? "{}" : "{}");
                Quit();
                return;
        }
        if (id != null) await web.CoreWebView2.ExecuteScriptAsync($"window.__selftestResolve && window.__selftestResolve({JsonSerializer.Serialize(id)}, {reply})");
    }

    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

    // O app já se chamou Commitdeck e, antes, PR Pilot: a pasta de dados mais recente dos nomes antigos vira a nova
    // (contas, regras, histórico; e, em %LOCALAPPDATA%, o WebView2 com as preferências da tela). O instalador do Codeck
    // já desinstalou os antigos (replaces), mas os dados do usuário ficam no perfil. "Iniciar com o Windows" passa junto.
    void AdoptLegacyData()
    {
        if (Environment.GetEnvironmentVariable("CODECK_DATA") != null) return;   // autoteste: dados próprios
        foreach (var root in new[] { Path.GetDirectoryName(dataDir)!, Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData) })
        {
            var target = Path.Combine(root, "Codeck");
            foreach (var name in new[] { "Commitdeck", "PR Pilot" })
            {
                var legacy = Path.Combine(root, name);
                try { if (!Directory.Exists(target) && Directory.Exists(legacy)) Directory.Move(legacy, target); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }
        try
        {
            using var k = Registry.CurrentUser.CreateSubKey(RunKey);
            foreach (var old in new[] { "commitdeck", "pr-pilot" })
            {
                if (k.GetValue(old) == null) continue;
                k.DeleteValue(old);
                if (!attach) k.SetValue(ProductId, $"\"{Environment.ProcessPath}\"");
            }
        }
        catch { }
    }

    // Seletor de pasta: devolve o caminho para a tela por window.__nativeResolve(id, path|null)
    void PickFolder(string id, string? title)
    {
        BeginInvoke(async () =>
        {
            using var dlg = new FolderBrowserDialog { Description = title ?? "Escolha uma pasta", UseDescriptionForTitle = true, ShowNewFolderButton = true };
            var path = dlg.ShowDialog(this) == DialogResult.OK ? dlg.SelectedPath : null;
            await Js($"window.__nativeResolve && window.__nativeResolve({JsonSerializer.Serialize(id)}, {JsonSerializer.Serialize(path)})");
        });
    }

    /// A tela de abertura animada (brand/splash.html, embutida no .exe). O texto de estado é trocado pela mensagem de
    /// erro quando há (a página percebe e vira um aviso legível).
    static string Splash(string text)
    {
        splashHtml ??= ReadSplash();
        return splashHtml.Replace("Iniciando…", text);
    }
    static string? splashHtml;
    static string ReadSplash()
    {
        using var s = typeof(MainForm).Assembly.GetManifestResourceStream("Codeck.splash.html");
        if (s != null) { using var r = new StreamReader(s, System.Text.Encoding.UTF8); return r.ReadToEnd(); }
        return "<html><body style=\"margin:0;height:100vh;display:grid;place-items:center;font:15px 'Segoe UI',sans-serif;background:#07080d;color:#b4bac6\">Iniciando…</body></html>";
    }
}

/// Job Object com KILL_ON_JOB_CLOSE: quando o app sai (ou cai), o Windows encerra o backend junto.
/// Um projeto numa janela só dele (ex.: outro monitor): mesma chave, mesmo servidor; a tela entra no modo "solo".
sealed class ProjectWindow : Form
{
    readonly WebView2 view = new() { Dock = DockStyle.Fill };
    public WebView2 View => view;

    public ProjectWindow(CoreWebView2Environment env, string baseUrl, string token, string hash, string title, Icon? icon, Color back)
    {
        Text = title;
        Icon = icon;
        BackColor = back;
        Size = new Size(1280, 820);
        MinimumSize = new Size(760, 520);
        StartPosition = FormStartPosition.CenterScreen;
        Controls.Add(view);
        Load += async (_, _) =>
        {
            await view.EnsureCoreWebView2Async(env);
            var core = view.CoreWebView2;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.AreDevToolsEnabled = false;
            core.Settings.AreDefaultContextMenusEnabled = false;
            await core.AddScriptToExecuteOnDocumentCreatedAsync(WindowSafety.TokenScript(baseUrl, token, ""));
            WindowSafety.Guard(core, baseUrl);
            core.Navigate(baseUrl + "#" + hash);
        };
    }
}

// A janela guarda a chave da API (que abre terminais): só a nossa tela roda nela, e para fora só vai http(s)/e-mail.
static class WindowSafety
{
    static string Origin(string baseUrl) => baseUrl.TrimEnd('/');

    /// A chave só entra no quadro principal da página do nosso servidor (nunca num iframe ou outra origem).
    public static string TokenScript(string baseUrl, string token, string extra) =>
        $"if (window === window.top && location.origin === {JsonSerializer.Serialize(Origin(baseUrl))}) {{ " +
        $"window.CODECK_TOKEN = {JsonSerializer.Serialize(token)}; window.CODECK_PLATFORM = 'windows';{extra} }}";

    public static bool FromUs(string source, string baseUrl) =>
        source.StartsWith(baseUrl, StringComparison.OrdinalIgnoreCase);

    /// file://, \\servidor, search-ms:, ms-*: e afins nunca chegam ao shell do Windows.
    public static void OpenExternal(string url)
    {
        if (Uri.TryCreate(url, UriKind.Absolute, out var u) && (u.Scheme is "http" or "https" or "mailto"))
            Process.Start(new ProcessStartInfo(u.AbsoluteUri) { UseShellExecute = true });
    }

    public static void Guard(CoreWebView2 core, string baseUrl)
    {
        core.NewWindowRequested += (_, e) => { e.Handled = true; OpenExternal(e.Uri); }; // target=_blank → navegador
        core.NavigationStarting += (_, e) =>
        {
            var uri = e.Uri;
            if (FromUs(uri, baseUrl) || uri.StartsWith("about:", StringComparison.OrdinalIgnoreCase)
                || uri.StartsWith("data:", StringComparison.OrdinalIgnoreCase)) return;   // data: = splash (NavigateToString)
            e.Cancel = true;
            OpenExternal(uri);
        };
    }
}

static class Job
{
    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimit { public long a, b; public uint LimitFlags; public UIntPtr c, d; public uint e; public UIntPtr f; public uint g, h; }
    [StructLayout(LayoutKind.Sequential)]
    struct IoCounters { public ulong a, b, c, d, e, f; }
    [StructLayout(LayoutKind.Sequential)]
    struct ExtendedLimit { public BasicLimit Basic; public IoCounters Io; public UIntPtr a, b, c, d; }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr a, string? name);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr job, int cls, ref ExtendedLimit info, int len);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr proc);

    public static IntPtr Create()
    {
        var job = CreateJobObject(IntPtr.Zero, null);
        var info = new ExtendedLimit { Basic = new BasicLimit { LimitFlags = 0x2000 } }; // KILL_ON_JOB_CLOSE
        SetInformationJobObject(job, 9, ref info, Marshal.SizeOf<ExtendedLimit>());
        return job;
    }

    public static void Assign(IntPtr job, Process p)
    {
        try { AssignProcessToJobObject(job, p.Handle); } catch { }
    }
}

static class Native
{
    public const uint EsContinuous = 0x80000000, EsSystemRequired = 0x00000001;
    public const uint SpiGetScreenSaverRunning = 0x0072;
    [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);
    [DllImport("user32.dll", SetLastError = true)] public static extern bool SystemParametersInfo(uint action, uint param, ref bool value, uint winIni);
    [DllImport("user32.dll")] public static extern bool DestroyIcon(IntPtr h);
    [DllImport("shell32.dll")] public static extern void SHChangeNotify(int eventId, uint flags, IntPtr item1, IntPtr item2);
}

/// <summary>Autoteste: conta as janelas de console (conhost e Windows Terminal) que aparecem na tela, de qualquer processo.</summary>
static class ConsoleWatch
{
    delegate void WinEventProc(IntPtr hook, uint ev, IntPtr hwnd, int idObject, int idChild, uint thread, uint time);
    [DllImport("user32.dll")] static extern IntPtr SetWinEventHook(uint min, uint max, IntPtr mod, WinEventProc proc, uint pid, uint tid, uint flags);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr h, System.Text.StringBuilder s, int n);
    static WinEventProc? proc;   // referência viva: o GC não pode recolher o delegate enquanto o gancho existe
    public static int Shown;

    public static void Start()
    {
        if (proc != null) return;
        proc = (_, _, hwnd, idObject, _, _, _) =>
        {
            if (idObject != 0 || hwnd == IntPtr.Zero) return;   // só a janela em si (OBJID_WINDOW)
            var sb = new System.Text.StringBuilder(64);
            GetClassName(hwnd, sb, sb.Capacity);
            var c = sb.ToString();
            if (c == "ConsoleWindowClass" || c == "CASCADIA_HOSTING_WINDOW_CLASS") Interlocked.Increment(ref Shown);
        };
        SetWinEventHook(0x8002, 0x8002, IntPtr.Zero, proc, 0, 0, 0);   // EVENT_OBJECT_SHOW, fora do processo
    }
}
