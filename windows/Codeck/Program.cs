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

    public MainForm(EventWaitHandle showSignal)
    {
        AdoptLegacyData();
        token = attach ? Env.GetValueOrDefault("CODECK_TOKEN") ?? "" : Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N");
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
        var psi = new ProcessStartInfo(python, $"\"{script}\"")
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
            $"window.CODECK_TOKEN = {JsonSerializer.Serialize(token)}; window.CODECK_PLATFORM = 'windows';" +
            (selfTest != null ? " window.__CD_SELFTEST = true;" : ""));
        core.NewWindowRequested += (_, e) => { e.Handled = true; OpenExternal(e.Uri); }; // target=_blank → navegador
        core.NavigationStarting += (_, e) =>
        {
            if (e.Uri.StartsWith("http", StringComparison.OrdinalIgnoreCase) && !e.Uri.StartsWith(baseUrl, StringComparison.OrdinalIgnoreCase))
            {
                e.Cancel = true;
                OpenExternal(e.Uri);
            }
        };
        core.WebMessageReceived += (_, e) => OnWebMessage(e.WebMessageAsJson);
        core.NavigateToString(Splash("Iniciando…"));
    }

    static void OpenExternal(string url) => Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });

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

    static string Splash(string text) => $$"""
        <html><body style="margin:0;height:100vh;display:grid;place-items:center;font:15px 'Segoe UI',sans-serif;background:#0f1115;color:#b4bac6">
        <div style="text-align:center;max-width:520px;padding:0 24px"><div style="margin:0 auto 14px;width:56px"><svg width="56" height="56" viewBox="0 0 512 512" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M435.7 78.5 L444.4 81.6 L452.6 85.8 L460.2 91.1 L467.1 97.3 L473.0 104.4 L478.0 112.2 L482.0 120.5 L484.8 129.3 L486.4 138.4 L486.9 147.6 L486.1 156.8 L484.1 165.9 L403.6 446.8 L400.4 455.5 L396.2 463.8 L391.0 471.3 L384.7 478.2 L377.7 484.2 L369.9 489.2 L361.6 493.1 L352.8 495.9 L343.7 497.6 L334.4 498.0 L325.2 497.2 L316.2 495.3 L100.8 433.5 L92.1 430.4 L83.9 426.2 L76.3 420.9 L69.4 414.7 L63.5 407.6 L58.5 399.8 L54.5 391.5 L51.7 382.7 L50.1 373.6 L49.6 364.4 L50.4 355.2 L52.4 346.1 L132.9 65.2 L136.0 56.5 L140.3 48.2 L145.5 40.7 L151.8 33.8 L158.8 27.8 L166.6 22.8 L174.9 18.9 L183.7 16.1 L192.8 14.4 L202.1 14.0 L211.3 14.8 L220.3 16.7 Z" fill="#B9C6FB"/><path d="M379.5 50.6 L388.5 52.4 L397.2 55.5 L405.5 59.6 L413.1 64.8 L420.0 71.0 L426.0 78.0 L431.1 85.7 L435.1 94.0 L438.0 102.8 L439.7 111.9 L440.3 121.1 L439.6 130.3 L398.9 419.8 L397.0 428.8 L394.0 437.6 L389.8 445.8 L384.6 453.5 L378.5 460.3 L371.5 466.4 L363.7 471.4 L355.4 475.5 L346.6 478.4 L337.6 480.1 L328.3 480.6 L319.1 479.9 L97.2 448.7 L88.2 446.8 L79.4 443.8 L71.2 439.6 L63.5 434.4 L56.7 428.3 L50.6 421.3 L45.6 413.6 L41.5 405.2 L38.6 396.5 L36.9 387.4 L36.4 378.2 L37.1 368.9 L77.8 79.5 L79.6 70.4 L82.7 61.7 L86.8 53.5 L92.0 45.8 L98.2 38.9 L105.2 32.9 L112.9 27.8 L121.3 23.8 L130.0 20.9 L139.1 19.2 L148.3 18.7 L157.5 19.4 Z" fill="#7F95F6"/><path d="M319.9 30.7 L329.1 31.3 L338.2 33.1 L346.9 36.1 L355.2 40.2 L362.9 45.3 L369.8 51.4 L375.9 58.4 L381.0 66.0 L385.1 74.3 L388.1 83.1 L389.9 92.1 L390.5 101.4 L390.5 393.7 L389.9 402.9 L388.1 411.9 L385.1 420.7 L381.0 429.0 L375.9 436.7 L369.8 443.6 L362.9 449.7 L355.2 454.8 L346.9 458.9 L338.2 461.9 L329.1 463.7 L319.9 464.3 L95.8 464.3 L86.6 463.7 L77.5 461.9 L68.7 458.9 L60.5 454.8 L52.8 449.7 L45.8 443.6 L39.7 436.7 L34.6 429.0 L30.5 420.7 L27.5 411.9 L25.7 402.9 L25.1 393.7 L25.1 101.4 L25.7 92.1 L27.5 83.1 L30.5 74.3 L34.6 66.0 L39.7 58.4 L45.8 51.4 L52.8 45.3 L60.5 40.2 L68.7 36.1 L77.5 33.1 L86.6 31.3 L95.8 30.7 Z" fill="url(#g)"/><path d="M299.3 341.4 L294.5 345.9 L289.6 350.1 L284.5 354.1 L279.1 357.9 L273.6 361.4 L268.0 364.6 L262.1 367.5 L256.2 370.2 L250.1 372.5 L243.9 374.5 L237.6 376.3 L231.3 377.7 L224.9 378.8 L218.4 379.6 L211.9 380.1 L205.4 380.3 L198.9 380.1 L192.4 379.6 L185.9 378.8 L179.5 377.7 L173.1 376.3 L166.8 374.5 L160.7 372.5 L154.6 370.2 L148.6 367.5 L142.8 364.6 L137.1 361.4 L131.6 357.9 L126.3 354.1 L121.2 350.1 L116.2 345.9 L111.5 341.4 L107.0 336.7 L102.8 331.7 L98.8 326.6 L95.0 321.3 L91.5 315.8 L88.3 310.1 L85.4 304.3 L82.7 298.3 L80.4 292.2 L78.3 286.0 L76.6 279.8 L75.2 273.4 L74.1 267.0 L73.3 260.5 L72.8 254.0 L72.6 247.5 L72.8 241.0 L73.3 234.5 L74.1 228.0 L75.2 221.6 L76.6 215.3 L78.3 209.0 L80.4 202.8 L82.7 196.7 L85.4 190.7 L88.3 184.9 L91.5 179.3 L95.0 173.8 L98.8 168.4 L102.8 163.3 L107.0 158.4 L111.5 153.6 L116.2 149.1 L121.2 144.9 L126.3 140.9 L131.6 137.1 L137.1 133.6 L142.8 130.4 L148.6 127.5 L154.6 124.9 L160.7 122.5 L166.8 120.5 L173.1 118.7 L179.5 117.3 L185.9 116.2 L192.4 115.4 L198.9 114.9 L205.4 114.8 L211.9 114.9 L218.4 115.4 L224.9 116.2 L231.3 117.3 L237.6 118.7 L243.9 120.5 L250.1 122.5 L256.2 124.9 L262.1 127.5 L268.0 130.4 L273.6 133.6 L279.1 137.1 L284.5 140.9 L289.6 144.9 L294.5 149.1 L299.3 153.6 L270.0 182.9 L266.7 179.8 L263.3 176.9 L259.8 174.1 L256.1 171.6 L252.3 169.2 L248.4 167.0 L244.4 164.9 L240.3 163.1 L236.2 161.5 L231.9 160.1 L227.6 158.9 L223.2 157.9 L218.8 157.2 L214.3 156.6 L209.9 156.3 L205.4 156.2 L200.9 156.3 L196.4 156.6 L192.0 157.2 L187.6 157.9 L183.2 158.9 L178.9 160.1 L174.6 161.5 L170.4 163.1 L166.3 164.9 L162.3 167.0 L158.4 169.2 L154.6 171.6 L151.0 174.1 L147.4 176.9 L144.0 179.8 L140.8 182.9 L137.7 186.2 L134.8 189.6 L132.0 193.1 L129.4 196.8 L127.0 200.5 L124.8 204.4 L122.8 208.5 L121.0 212.6 L119.4 216.7 L118.0 221.0 L116.8 225.3 L115.8 229.7 L115.0 234.1 L114.5 238.6 L114.2 243.0 L114.0 247.5 L114.2 252.0 L114.5 256.5 L115.0 260.9 L115.8 265.3 L116.8 269.7 L118.0 274.0 L119.4 278.3 L121.0 282.5 L122.8 286.6 L124.8 290.6 L127.0 294.5 L129.4 298.3 L132.0 301.9 L134.8 305.5 L137.7 308.8 L140.8 312.1 L144.0 315.2 L147.4 318.1 L151.0 320.9 L154.6 323.5 L158.4 325.9 L162.3 328.1 L166.3 330.1 L170.4 331.9 L174.6 333.5 L178.9 334.9 L183.2 336.1 L187.6 337.1 L192.0 337.9 L196.4 338.4 L200.9 338.7 L205.4 338.9 L209.9 338.7 L214.3 338.4 L218.8 337.9 L223.2 337.1 L227.6 336.1 L231.9 334.9 L236.2 333.5 L240.3 331.9 L244.4 330.1 L248.4 328.1 L252.3 325.9 L256.1 323.5 L259.8 320.9 L263.3 318.1 L266.7 315.2 L270.0 312.1 Z" fill="#FFFFFF"/><path d="M321.2 326.7 L321.0 329.9 L320.6 333.1 L319.9 336.2 L318.9 339.2 L317.7 342.2 L316.3 345.0 L314.5 347.7 L312.6 350.2 L310.5 352.6 L308.1 354.7 L305.6 356.7 L302.9 358.4 L300.1 359.9 L297.1 361.1 L294.1 362.0 L291.0 362.7 L287.8 363.1 L284.6 363.3 L281.4 363.1 L278.3 362.7 L275.2 362.0 L272.1 361.1 L269.2 359.9 L266.3 358.4 L263.7 356.7 L261.1 354.7 L258.8 352.6 L256.6 350.2 L254.7 347.7 L253.0 345.0 L251.5 342.2 L250.3 339.2 L249.3 336.2 L248.6 333.1 L248.2 329.9 L248.1 326.7 L248.2 323.6 L248.6 320.4 L249.3 317.3 L250.3 314.2 L251.5 311.3 L253.0 308.5 L254.7 305.8 L256.6 303.3 L258.8 300.9 L261.1 298.7 L263.7 296.8 L266.3 295.1 L269.2 293.6 L272.1 292.4 L275.2 291.4 L278.3 290.8 L281.4 290.3 L284.6 290.2 L287.8 290.3 L291.0 290.8 L294.1 291.4 L297.1 292.4 L300.1 293.6 L302.9 295.1 L305.6 296.8 L308.1 298.7 L310.5 300.9 L312.6 303.3 L314.5 305.8 L316.3 308.5 L317.7 311.3 L318.9 314.2 L319.9 317.3 L320.6 320.4 L321.0 323.6 Z" fill="#FFFFFF"/><path d="M125.0 247.5 L124.9 250.3 L124.5 253.0 L123.9 255.7 L123.1 258.3 L122.0 260.9 L120.8 263.3 L119.3 265.7 L117.6 267.9 L115.7 269.9 L113.7 271.8 L111.5 273.4 L109.2 274.9 L106.7 276.2 L104.2 277.3 L101.5 278.1 L98.8 278.7 L96.1 279.1 L93.3 279.2 L90.6 279.1 L87.8 278.7 L85.1 278.1 L82.5 277.3 L80.0 276.2 L77.5 274.9 L75.2 273.4 L73.0 271.8 L70.9 269.9 L69.1 267.9 L67.4 265.7 L65.9 263.3 L64.6 260.9 L63.6 258.3 L62.8 255.7 L62.2 253.0 L61.8 250.3 L61.7 247.5 L61.8 244.7 L62.2 242.0 L62.8 239.3 L63.6 236.7 L64.6 234.1 L65.9 231.7 L67.4 229.3 L69.1 227.2 L70.9 225.1 L73.0 223.3 L75.2 221.6 L77.5 220.1 L80.0 218.8 L82.5 217.8 L85.1 216.9 L87.8 216.3 L90.6 216.0 L93.3 215.8 L96.1 216.0 L98.8 216.3 L101.5 216.9 L104.2 217.8 L106.7 218.8 L109.2 220.1 L111.5 221.6 L113.7 223.3 L115.7 225.1 L117.6 227.2 L119.3 229.3 L120.8 231.7 L122.0 234.1 L123.1 236.7 L123.9 239.3 L124.5 242.0 L124.9 244.7 Z" fill="#FFFFFF"/><path d="M326.0 168.3 L325.9 171.9 L325.4 175.5 L324.6 179.0 L323.5 182.4 L322.1 185.8 L320.5 189.0 L318.5 192.0 L316.3 194.9 L313.9 197.6 L311.2 200.0 L308.4 202.2 L305.3 204.1 L302.1 205.8 L298.8 207.2 L295.3 208.3 L291.8 209.1 L288.2 209.5 L284.6 209.7 L281.0 209.5 L277.4 209.1 L273.9 208.3 L270.5 207.2 L267.1 205.8 L263.9 204.1 L260.9 202.2 L258.0 200.0 L255.3 197.6 L252.9 194.9 L250.7 192.0 L248.8 189.0 L247.1 185.8 L245.7 182.4 L244.6 179.0 L243.8 175.5 L243.4 171.9 L243.2 168.3 L243.4 164.7 L243.8 161.1 L244.6 157.6 L245.7 154.1 L247.1 150.8 L248.8 147.6 L250.7 144.5 L252.9 141.7 L255.3 139.0 L258.0 136.6 L260.9 134.4 L263.9 132.4 L267.1 130.7 L270.5 129.4 L273.9 128.3 L277.4 127.5 L281.0 127.0 L284.6 126.9 L288.2 127.0 L291.8 127.5 L295.3 128.3 L298.8 129.4 L302.1 130.7 L305.3 132.4 L308.4 134.4 L311.2 136.6 L313.9 139.0 L316.3 141.7 L318.5 144.5 L320.5 147.6 L322.1 150.8 L323.5 154.1 L324.6 157.6 L325.4 161.1 L325.9 164.7 Z" fill="#22C38E"/><path d="M300.4 168.3 L300.4 169.7 L300.2 171.0 L299.9 172.4 L299.5 173.7 L299.0 175.0 L298.3 176.2 L297.6 177.4 L296.7 178.5 L295.8 179.5 L294.8 180.4 L293.7 181.2 L292.5 182.0 L291.3 182.6 L290.0 183.2 L288.7 183.6 L287.4 183.9 L286.0 184.1 L284.6 184.1 L283.2 184.1 L281.9 183.9 L280.5 183.6 L279.2 183.2 L277.9 182.6 L276.7 182.0 L275.5 181.2 L274.4 180.4 L273.4 179.5 L272.5 178.5 L271.6 177.4 L270.9 176.2 L270.3 175.0 L269.7 173.7 L269.3 172.4 L269.0 171.0 L268.8 169.7 L268.8 168.3 L268.8 166.9 L269.0 165.5 L269.3 164.2 L269.7 162.9 L270.3 161.6 L270.9 160.4 L271.6 159.2 L272.5 158.1 L273.4 157.1 L274.4 156.1 L275.5 155.3 L276.7 154.6 L277.9 153.9 L279.2 153.4 L280.5 153.0 L281.9 152.7 L283.2 152.5 L284.6 152.4 L286.0 152.5 L287.4 152.7 L288.7 153.0 L290.0 153.4 L291.3 153.9 L292.5 154.6 L293.7 155.3 L294.8 156.1 L295.8 157.1 L296.7 158.1 L297.6 159.2 L298.3 160.4 L299.0 161.6 L299.5 162.9 L299.9 164.2 L300.2 165.5 L300.4 166.9 Z" fill="#FFFFFF"/><defs><linearGradient id="g" x1="0" y1="512" x2="512" y2="0" gradientUnits="userSpaceOnUse"><stop stop-color="#6D4AF0"/><stop offset="1" stop-color="#2F8CF0"/></linearGradient><linearGradient id="ink" x1="0" y1="512" x2="512" y2="0" gradientUnits="userSpaceOnUse"><stop stop-color="#5A36E6"/><stop offset="1" stop-color="#2F7FE8"/></linearGradient><linearGradient id="bg" x1="51" y1="461" x2="461" y2="51" gradientUnits="userSpaceOnUse"><stop stop-color="#4B2FC9"/><stop offset="1" stop-color="#2F86EE"/></linearGradient></defs></svg></div>{{text}}</div></body></html>
        """;
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
            await core.AddScriptToExecuteOnDocumentCreatedAsync(
                $"window.CODECK_TOKEN = {JsonSerializer.Serialize(token)}; window.CODECK_PLATFORM = 'windows';");
            core.NewWindowRequested += (_, e) => { e.Handled = true; Process.Start(new ProcessStartInfo(e.Uri) { UseShellExecute = true }); };
            core.Navigate(baseUrl + "#" + hash);
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
