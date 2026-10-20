// Executar e depurar (como no Visual Studio / VS Code): as configurações do projeto (detectadas, do launch.json do
// VS Code e as salvas no app), as sessões ao vivo (espera longa em /api/debug/poll), breakpoints por projeto, a pilha
// de chamadas, variáveis, inspeção e o console de depuração. Atalhos: F5 depurar/continuar, Ctrl+F5 sem depurar,
// Shift+F5 parar, ⌘/Ctrl+Shift+F5 reiniciar, F9 breakpoint, F10/F11/Shift+F11 passo a passo.
import { get, post } from "./api";
import { setBuildProblems, type Problem } from "./editorstate.svelte";
import { ui } from "./ui.svelte";

export type LaunchCfg = { id: string; name: string; type: string; request?: string; source: "detected" | "vscode" | "codeck"; kind: string; group: string;
  debug: boolean; run: boolean; why?: string | null; device?: boolean; url?: string | null; profile?: string | null; project?: string | null;
  browser?: boolean; main?: boolean; variant?: string | null; detail?: string; envKeys?: string[]; envFile?: string | null; compound?: string[];
  preLaunchTask?: string | null };
export type LaunchList = { configs: LaunchCfg[]; hidden: string[]; sync: "auto" | "vscode" | "off"; root: string; vscode: { launch: boolean; tasks: boolean } };
export type Bp = { line: number; enabled?: boolean; condition?: string; hitCondition?: string; logMessage?: string };
export type Frame = { id: number; name: string; line: number; col: number; path: string | null; abs: string | null; source?: string; ref?: number; hint?: string; external?: boolean };
export type Session = { id: string; kind: "debug" | "run"; name: string; configId: string; repoId: string; taskId: string | null; group: string; parent: string | null;
  status: "booting" | "building" | "starting" | "running" | "stopped" | "ended"; error: string | null; exitCode: number | null; terms: string[]; buildTerm?: string | null;
  started: number; ended: number | null; adapter: "dotnet" | "js" | "dart" | null; noDebug?: boolean; device?: string | null; url?: string | null;
  threads: { id: number; name: string }[]; stopped: null | { threadId: number; reason: string; text?: string; description?: string; all?: boolean; top: Frame | null; exception?: any };
  outSeq: number; verified?: Record<string, { line: number; asked: number; verified: boolean; message?: string }[]>; hot?: boolean;
  /** ligando o emulador/simulador (nome) · como lembrar o aparelho que a sessão acabou usando (avd:<nome> no Android) */
  boot?: string | null; devicePref?: string | null;
  /** Flutter: URI da VM (o DevTools conecta nela), modo, extensões de serviço disponíveis e o estado delas */
  flutter?: { vmUri: string | null; mode: string | null; tools: boolean; exts: string[]; state: Record<string, string> } | null;
  caps: { exceptionFilters: { filter: string; label: string; default?: boolean; description?: string }[]; setVariable?: boolean; conditional?: boolean; logPoints?: boolean; hitConditional?: boolean } };
export type Variable = { name: string; value: string; type?: string; ref: number; evaluateName?: string; hint?: string };
/** offline: emulador Android (id "avd:<nome>") ou simulador do iOS desligado — liga ao executar (ou ao escolher). */
export type Device = { id: string; name: string; platform: string; emulator: boolean; supported: boolean; sdk?: string; avd?: string | null; offline?: boolean; booting?: boolean };
type Adapters = Record<"dotnet" | "js" | "dart", { ok: boolean; name: string; installable: boolean; note: string }>;
type OutLine = { seq: number; cat: string; text: string };

const LS = "codeck.debug";
type Saved = { sel: Record<string, string>; dev: Record<string, string>; watch: Record<string, string[]> };
function readSaved(): Saved { try { return { sel: {}, dev: {}, watch: {}, ...JSON.parse(localStorage.getItem(LS) || "{}") }; } catch { return { sel: {}, dev: {}, watch: {} }; } }
const ANSI = /\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)/g;
export const KIND_LABEL: Record<string, string> = { dotnet: ".NET", nest: "NestJS", next: "Next.js", react: "React", web: "Web", node: "Node", script: "Script",
  flutter: "Flutter", dart: "Dart", browser: "Navegador", go: "Go", rust: "Rust", docker: "Docker", compound: "Composta", other: "Outro" };

class Debug {
  lists = $state<Record<string, LaunchList | null>>({});
  loadingList = $state<Record<string, boolean>>({});
  sessions = $state<Session[]>([]);
  bps = $state<Record<string, Record<string, Bp[]>>>({});
  exc = $state<Record<string, Record<string, string[]>>>({});
  adapters = $state<Adapters | null>(null);
  devices = $state<Device[]>([]);
  offline = $state<Device[]>([]);
  devicesErr = $state<string | null>(null);
  devicesLoading = $state(false);
  saved = $state<Saved>(readSaved());
  /** sessão/thread/quadro em foco (pilha de chamadas → variáveis, inspeção, console) */
  focus = $state<{ sid: string | null; threadId: number | null; frameId: number | null }>({ sid: null, threadId: null, frameId: null });
  frames = $state<Record<string, Frame[]>>({});
  /** onde a execução parou (seta amarela no editor) */
  current = $state<{ repoId: string; taskId: string | null; path: string; line: number; col: number; sid: string } | null>(null);
  output = $state<Record<string, OutLine[]>>({});
  watchValues = $state<Record<string, { value?: string; error?: string; ref?: number; type?: string }>>({});
  /** quem abre arquivo/terminal na tela (o Work registra) */
  opener: ((repoId: string, taskId: string | null, path: string, line: number) => void) | null = null;
  termFocus: ((repoId: string, taskId: string | null, termId: string) => void) | null = null;
  panelOpen: ((repoId: string) => void) | null = null;
  devtoolsOpen: ((repoId: string, taskId: string | null, page: string) => void) | null = null;
  private seq = 0;
  private polling = false;
  private synced = false;
  private outSeen: Record<string, number> = {};
  private buildPolls = new Map<string, ReturnType<typeof setInterval>>();
  private lastStopped: Record<string, number> = {};
  private prefSeen = new Set<string>();

  key = (repoId: string, taskId: string | null | undefined) => `${repoId}|${taskId || ""}`;
  private persist() { try { localStorage.setItem(LS, JSON.stringify(this.saved)); } catch { /* sem armazenamento */ } }

  // ------------------------------------------------------------ configurações
  async load(repoId: string, taskId: string | null) {
    const k = this.key(repoId, taskId);
    if (this.loadingList[k]) return;
    this.loadingList = { ...this.loadingList, [k]: true };
    try { this.lists = { ...this.lists, [k]: await get<LaunchList>("launch/configs", { repoId, taskId }) }; }
    catch (e) { this.lists = { ...this.lists, [k]: null }; ui.error(e); }
    finally { this.loadingList = { ...this.loadingList, [k]: false }; }
    this.ensurePoll();
  }
  list(repoId: string, taskId: string | null): LaunchCfg[] { return this.lists[this.key(repoId, taskId)]?.configs || []; }
  /** A escolhida (lembrada por projeto); sem escolha, a "principal" detectada: API web .NET, Nest/Next/React, Flutter. */
  selected(repoId: string, taskId: string | null): LaunchCfg | null {
    const l = this.list(repoId, taskId);
    const id = this.saved.sel[repoId];
    return l.find(c => c.id === id) || this.best(l);
  }
  best(l: LaunchCfg[]): LaunchCfg | null {
    const score = (c: LaunchCfg) => (c.source === "codeck" ? 60 : c.source === "vscode" ? 50 : 0) + (c.kind === "dotnet" && c.url ? 40 : 0) + (c.kind === "dotnet" ? 30 : 0)
      + (c.main ? 30 : 0) + (["nest", "next", "react", "flutter"].includes(c.kind) ? 15 : 0) + (c.profile === "https" ? -2 : 0) + (c.variant ? -20 : 0)
      + (c.browser ? -5 : 0) + (c.kind === "script" ? -30 : 0) + (c.type === "compound" ? 5 : 0);
    return [...l].sort((a, b) => score(b) - score(a))[0] || null;
  }
  select(repoId: string, id: string) { this.saved = { ...this.saved, sel: { ...this.saved.sel, [repoId]: id } }; this.persist(); }
  device(repoId: string): string | null { return this.saved.dev[repoId] || null; }
  /** O aparelho escolhido, ligado ou desligado (o emulador Android é lembrado pelo AVD: o serial muda a cada vez). */
  deviceInfo(repoId: string): Device | null {
    const id = this.device(repoId);
    return id ? this.devices.find(d => d.id === id || (d.avd && `avd:${d.avd}` === id)) || this.offline.find(d => d.id === id) || null : null;
  }
  setDevice(repoId: string, id: string) { this.saved = { ...this.saved, dev: { ...this.saved.dev, [repoId]: id } }; this.persist(); }
  pickDevice(repoId: string, d: Device) {
    this.setDevice(repoId, d.avd ? `avd:${d.avd}` : d.id);
    if (d.offline && !d.booting) {
      post("debug/emulator", { id: d.id }).then(() => { ui.toast(`Ligando ${d.name}… (o F5 espera ele ficar pronto)`); this.loadDevices(); }).catch(ui.error);
    }
  }

  async loadDevices(force = false) {
    this.devicesLoading = true;
    try {
      const r = await get<{ devices: Device[]; offline: Device[]; error: string | null }>("debug/devices", { force: force ? 1 : undefined });
      this.devices = r.devices; this.offline = r.offline || []; this.devicesErr = r.error;
    }
    catch (e) { this.devicesErr = (e as any)?.message || String(e); }
    finally { this.devicesLoading = false; }
  }

  // ------------------------------------------------------------ sessões
  scopeSessions(repoId: string, taskId: string | null) { return this.sessions.filter(s => s.repoId === repoId && (s.taskId || null) === (taskId || null)); }
  /** sessões vivas "de topo" do escopo (sem as filhas do js-debug) */
  live(repoId: string, taskId: string | null) { return this.scopeSessions(repoId, taskId).filter(s => s.status !== "ended" && !s.parent); }
  /** a sessão que os botões de passo controlam: a parada (a mais recente), senão a em foco, senão a primeira depurando */
  active(repoId: string, taskId: string | null): Session | null {
    const all = this.scopeSessions(repoId, taskId).filter(s => s.status !== "ended" && s.kind === "debug");
    return all.filter(s => s.status === "stopped").sort((a, b) => (this.lastStopped[b.id] || 0) - (this.lastStopped[a.id] || 0))[0]
      || all.find(s => s.id === this.focus.sid) || all.find(s => s.threads.length) || all[0] || null;
  }
  runningOf(repoId: string, taskId: string | null, configId: string) { return this.live(repoId, taskId).filter(s => s.configId === configId); }

  ensurePoll() {
    if (this.polling) return;
    this.polling = true;
    const loop = async () => {
      while (this.polling) {
        try {
          // a 1ª leitura só sincroniza (responde na hora, sem esperar): os sinais antigos não se repetem e o 1º
          // F5 depois de abrir o app já chega como novidade (antes, ele vinha na 1ª resposta e o foco se perdia)
          const first = !this.synced;
          const r = await get<{ seq: number; sessions: Session[]; signals: any[] }>("debug/poll", { after: this.seq, wait: first ? 0 : 25 });
          this.synced = true;
          this.seq = r.seq;
          this.apply(r.sessions, first ? [] : r.signals);
        } catch { await new Promise(res => setTimeout(res, 2000)); }
      }
    };
    loop();
  }

  private apply(list: Session[], signals: any[]) {
    const prev = new Map(this.sessions.map(s => [s.id, s]));
    this.sessions = list;
    for (const s of list) {
      const p = prev.get(s.id);
      if (s.outSeq && s.outSeq !== (this.outSeen[s.id] || 0)) this.fetchOutput(s.id);
      if (s.status === "building" && s.buildTerm && !this.buildPolls.has(s.id)) this.watchBuild(s);
      if (p && p.status !== "ended" && s.status === "ended" && !s.parent) this.ended(s);
      if (s.status === "stopped" && p?.status !== "stopped") this.lastStopped[s.id] = Date.now();
      // o backend escolheu/ligou o aparelho: fica lembrado para o próximo F5
      if (s.devicePref && !s.parent && !this.prefSeen.has(s.id)) { this.prefSeen.add(s.id); if (this.saved.dev[s.repoId] !== s.devicePref) this.setDevice(s.repoId, s.devicePref); }
    }
    // a seta amarela some quando a sessão continua/termina
    if (this.current && !list.some(s => s.id === this.current!.sid && s.status === "stopped")) {
      const other = list.find(s => s.status === "stopped" && s.stopped?.top?.path);
      this.current = other ? { repoId: other.repoId, taskId: other.taskId, path: other.stopped!.top!.path!, line: other.stopped!.top!.line, col: other.stopped!.top!.col, sid: other.id } : null;
      if (!other && this.focus.sid && !list.some(s => s.id === this.focus.sid && s.status === "stopped")) this.focus = { ...this.focus, frameId: null };
    }
    for (const g of signals) this.signal(g);
  }

  private signal(g: any) {
    if (g.type === "open" && g.url) window.open(g.url, "_blank");
    else if (g.type === "focus" && g.term) this.termFocus?.(g.repoId, g.taskId || null, g.term);
    else if (g.type === "notice") ui.toast(g.text, g.level === "error" ? "error" : "info");
    else if (g.type === "devices") this.loadDevices();
    else if (g.type === "stopped" && g.top) {
      const s = this.sessions.find(x => x.id === g.session);
      this.focus = { sid: g.session, threadId: s?.stopped?.threadId ?? null, frameId: g.top.id };
      this.frames = { ...this.frames };
      if (g.top.path) {
        this.current = { repoId: g.repoId, taskId: g.taskId || null, path: g.top.path, line: g.top.line, col: g.top.col, sid: g.session };
        this.opener?.(g.repoId, g.taskId || null, g.top.path, g.top.line);
      }
      if (s?.stopped?.threadId != null) this.loadStack(g.session, s.stopped.threadId);
      this.refreshWatch();
      if (g.reason === "exception") ui.toast(`Exceção: ${s?.stopped?.exception?.description || s?.stopped?.text || "parou numa exceção"}`, "error");
    }
  }

  private ended(s: Session) {
    if (s.error?.startsWith("need-adapter:")) return this.offerInstall(s.error.split(":")[1] as any, s);
    if (s.error) ui.toast(`${s.name}: ${s.error}`, "error");
    else if (s.kind === "debug" && !s.noDebug) ui.toast(`${s.name} terminou${s.exitCode != null ? ` (código ${s.exitCode})` : ""}`, s.exitCode ? "error" : "info");
  }

  private watchBuild(s: Session) {
    const k = this.key(s.repoId, s.taskId);
    const t = setInterval(async () => {
      const cur = this.sessions.find(x => x.id === s.id);
      try {
        const r = await get<{ problems: Problem[]; done: boolean }>("dotnet/problems", { termId: s.buildTerm });
        setBuildProblems(r.problems.map(p => ({ ...p, scope: k })));
        if (r.done || !cur || cur.status !== "building") { clearInterval(t); this.buildPolls.delete(s.id); }
      } catch { clearInterval(t); this.buildPolls.delete(s.id); }
    }, 1000);
    this.buildPolls.set(s.id, t);
  }

  async offerInstall(kind: "dotnet" | "js" | "dart", retry?: Session) {
    await this.loadAdapters();
    const a = this.adapters?.[kind];
    if (!a) return;
    if (!a.installable) return ui.toast(a.note, "error");
    const name = { dotnet: "o depurador .NET (netcoredbg)", js: "o depurador JavaScript (js-debug)", dart: "o Flutter" }[kind];
    if (!(await ui.ask({ title: `Instalar ${name}?`, message: `${a.note}. Baixa do GitHub oficial do projeto para a pasta de dados do Codeck — uma vez só.`, confirm: "Baixar e instalar" }))) return;
    const prog = ui.progress(`Baixando ${a.name}…`);
    try {
      this.adapters = await post<Adapters>("debug/install", { kind });
      prog.done(`${a.name} instalado`);
      if (retry) await this.start(retry.repoId, retry.taskId, retry.configId, { noDebug: !!retry.noDebug, device: retry.device || undefined });
    } catch (e) { prog.fail(e); }
  }
  async loadAdapters() { try { this.adapters = await get<Adapters>("debug/adapters"); } catch { /* fica como estava */ } }

  /** F5 (depurar) / Ctrl+F5 (sem depurar). */
  async start(repoId: string, taskId: string | null, configId?: string | null, o: { noDebug?: boolean; device?: string } = {}) {
    const cfg = configId ? this.list(repoId, taskId).find(c => c.id === configId) : this.selected(repoId, taskId);
    if (!cfg) return ui.toast("Nada para executar aqui — sem projeto .NET, package.json, pubspec.yaml ou launch.json", "info");
    // Flutter: manda o escolhido (ou nada) — o backend liga o emulador/simulador se estiver desligado e, sem escolha,
    // usa um celular/emulador ligado ou liga um
    const device = o.device || (cfg.device ? this.device(repoId) : null);
    const prog = ui.progress(o.noDebug ? `Executando ${cfg.name}…` : `Depurando ${cfg.name}…`);
    try {
      const r = await post<{ sessions: Session[] }>("debug/start", { repoId, taskId, configId: cfg.id, noDebug: !!o.noDebug, device });
      for (const s of r.sessions) if (s.error?.startsWith("need-adapter:")) { prog.done("Falta o depurador"); return this.offerInstall(s.error.split(":")[1] as any, s); }
      prog.done(o.noDebug || !cfg.debug ? "Executando" : r.sessions.some(s => s.status === "building") ? "Compilando antes de depurar…" : "Depurando");
      this.ensurePoll();
      if (!o.noDebug && cfg.debug) this.panelOpen?.(repoId);
    } catch (e) { prog.fail(e); }
  }
  async stop(o: { sid?: string; group?: string; repoId?: string }) {
    try { await post("debug/stop", o); } catch (e) { ui.error(e); }
  }
  async stopScope(repoId: string, taskId: string | null) {
    const groups = [...new Set(this.live(repoId, taskId).map(s => s.group))];
    for (const g of groups) await this.stop({ group: g });
    if (!groups.length) ui.toast("Nada rodando", "info");
  }
  async restart(sid: string) {
    try { await post("debug/restart", { sid }); } catch (e) { ui.error(e); }
  }
  async control(s: Session | null, action: "continue" | "pause" | "next" | "stepIn" | "stepOut" | "hotReload" | "hotRestart") {
    if (!s) return;
    const target = this.sessions.find(x => x.id === this.focus.sid && x.status === "stopped" && (x.id === s.id || x.parent === s.id || x.group === s.group)) || s;
    try { await post("debug/control", { sid: target.id, action, threadId: action === "pause" ? undefined : (this.focus.sid === target.id ? this.focus.threadId : null) }); }
    catch (e) { ui.error(e); }
  }

  // ------------------------------------------------------------ Flutter: DevTools e extensões de serviço
  /** a sessão do Flutter do escopo (a em foco, senão a mais recente) */
  flutterSession(repoId: string, taskId: string | null): Session | null {
    const l = this.live(repoId, taskId).filter(s => s.adapter === "dart" && s.status !== "booting" && s.status !== "building");
    return l.find(s => s.id === this.focus.sid) || l[l.length - 1] || null;
  }
  async devtoolsUrl(s: Session, page = "", embed = false) {
    const theme = document.documentElement.dataset.theme === "light" ? "light" : "dark";
    return (await post<{ url: string }>("debug/devtools", { sid: s.id, page, theme, embed }, { quiet: true })).url;
  }
  async service(s: Session, method: string, params?: Record<string, string>) {
    try { return await post<{ value: string | null; data?: string }>("debug/service", { sid: s.id, method, params }, { quiet: true }); }
    catch (e) { ui.error(e); return null; }
  }

  // ------------------------------------------------------------ pilha, variáveis, inspeção
  async loadStack(sid: string, threadId: number) {
    try {
      const r = await get<{ frames: Frame[] }>("debug/stack", { sid, threadId });
      this.frames = { ...this.frames, [`${sid}:${threadId}`]: r.frames };
      return r.frames;
    } catch { return []; }
  }
  stackOf(sid: string, threadId: number) { return this.frames[`${sid}:${threadId}`] || null; }
  selectFrame(s: Session, threadId: number, f: Frame) {
    this.focus = { sid: s.id, threadId, frameId: f.id };
    if (f.path) {
      this.current = { repoId: s.repoId, taskId: s.taskId, path: f.path, line: f.line, col: f.col, sid: s.id };
      this.opener?.(s.repoId, s.taskId, f.path, f.line);
    } else if (f.external) ui.toast(`Código fora do projeto: ${f.source || f.abs || f.name}`, "info");
    this.refreshWatch();
  }
  async scopes(sid: string, frameId: number) {
    try { return (await get<{ scopes: { name: string; ref: number; expensive: boolean }[] }>("debug/scopes", { sid, frameId })).scopes; } catch { return []; }
  }
  async variables(sid: string, ref: number) {
    try { return (await get<{ variables: Variable[] }>("debug/variables", { sid, ref })).variables; } catch (e) { return [{ name: "erro", value: String((e as any)?.message || e), ref: 0 }]; }
  }
  async evaluate(sid: string, expression: string, frameId: number | null, context: "watch" | "repl" | "hover" = "repl") {
    return post<{ result: string; type?: string; ref: number }>("debug/evaluate", { sid, expression, frameId, context }, { quiet: true });
  }
  async setVariable(sid: string, ref: number, name: string, value: string) {
    return post<{ value: string }>("debug/set-variable", { sid, ref, name, value });
  }

  watches(repoId: string) { return this.saved.watch[repoId] || []; }
  setWatches(repoId: string, list: string[]) { this.saved = { ...this.saved, watch: { ...this.saved.watch, [repoId]: list } }; this.persist(); this.refreshWatch(); }
  async refreshWatch() {
    const s = this.sessions.find(x => x.id === this.focus.sid && x.status === "stopped");
    if (!s) return;
    const out: typeof this.watchValues = {};
    for (const w of this.watches(s.repoId)) {
      try { const r = await this.evaluate(s.id, w, this.focus.frameId, "watch"); out[w] = { value: r.result, ref: r.ref, type: r.type }; }
      catch (e) { out[w] = { error: (e as any)?.message || String(e) }; }
    }
    this.watchValues = out;
  }

  // ------------------------------------------------------------ console de depuração
  async fetchOutput(sid: string) {
    const after = this.outSeen[sid] || 0;
    try {
      const r = await get<{ seq: number; items: OutLine[] }>("debug/output", { sid, after });
      this.outSeen[sid] = r.seq;
      if (r.items.length) {
        const lines = r.items.map(x => ({ ...x, text: x.text.replace(ANSI, "") }));
        this.output = { ...this.output, [sid]: [...(this.output[sid] || []), ...lines].slice(-3000) };
      }
    } catch { /* sessão saiu */ }
  }
  clearOutput(sid: string) { this.output = { ...this.output, [sid]: [] }; }

  // ------------------------------------------------------------ breakpoints
  async loadBps(repoId: string) {
    if (this.bps[repoId]) return;
    try {
      const r = await get<{ files: Record<string, Bp[]>; exceptions: Record<string, string[]> }>("debug/breakpoints", { repoId });
      this.bps = { ...this.bps, [repoId]: r.files };
      this.exc = { ...this.exc, [repoId]: r.exceptions };
    } catch { this.bps = { ...this.bps, [repoId]: {} }; }
  }
  fileBps(repoId: string, path: string): Bp[] { return this.bps[repoId]?.[path] || []; }
  private async saveFile(repoId: string, path: string, list: Bp[]) {
    this.bps = { ...this.bps, [repoId]: { ...(this.bps[repoId] || {}), [path]: list } };
    if (!list.length) { const c = { ...this.bps[repoId] }; delete c[path]; this.bps = { ...this.bps, [repoId]: c }; }
    try { const r = await post<{ files: Record<string, Bp[]> }>("debug/breakpoints", { repoId, path, breakpoints: list }, { quiet: true }); this.bps = { ...this.bps, [repoId]: r.files }; }
    catch (e) { ui.error(e); }
  }
  toggleBp(repoId: string, path: string, line: number) {
    const l = this.fileBps(repoId, path);
    this.saveFile(repoId, path, l.some(b => b.line === line) ? l.filter(b => b.line !== line) : [...l, { line, enabled: true }].sort((a, b) => a.line - b.line));
  }
  setBp(repoId: string, path: string, line: number, patch: Partial<Bp> | null) {
    const l = this.fileBps(repoId, path).filter(b => b.line !== line);
    const cur = this.fileBps(repoId, path).find(b => b.line === line) || { line, enabled: true };
    this.saveFile(repoId, path, patch === null ? l : [...l, { ...cur, ...patch, line }].sort((a, b) => a.line - b.line));
  }
  /** As linhas mudaram (editou acima): os breakpoints acompanham o texto, como no VS Code. */
  moveBps(repoId: string, path: string, list: Bp[]) { this.saveFile(repoId, path, list); }
  async clearBps(repoId: string, path?: string) {
    try { const r = await post<{ files: Record<string, Bp[]> }>("debug/breakpoints/clear", { repoId, path }); this.bps = { ...this.bps, [repoId]: r.files }; } catch (e) { ui.error(e); }
  }
  async enableAll(repoId: string, on: boolean) {
    for (const [p, l] of Object.entries(this.bps[repoId] || {})) await this.saveFile(repoId, p, l.map(b => ({ ...b, enabled: on })));
  }
  /** confirmado pelo depurador em alguma sessão viva? (oco = ainda não carregou o código / não achou a linha) */
  bpState(repoId: string, path: string, line: number): "verified" | "pending" | "idle" {
    const live = this.sessions.filter(s => s.repoId === repoId && s.status !== "ended" && s.kind === "debug" && !s.noDebug);
    if (!live.length) return "idle";
    return live.some(s => s.verified?.[path]?.some(v => v.asked === line && v.verified)) ? "verified" : "pending";
  }
  async setExceptions(repoId: string, kind: string, filters: string[]) {
    try { const r = await post<{ exceptions: Record<string, string[]> }>("debug/exceptions", { repoId, kind, filters }); this.exc = { ...this.exc, [repoId]: r.exceptions }; }
    catch (e) { ui.error(e); }
  }

  /** Salvou um arquivo: Flutter rodando faz hot reload (como no VS Code). */
  saved_(repoId: string, taskId: string | null, path: string) {
    if (!path.endsWith(".dart")) return;
    if (!this.live(repoId, taskId).some(s => s.adapter === "dart")) return;
    post<{ reloaded: number }>("debug/saved", { repoId, taskId, path }, { quiet: true }).then(r => { if (r.reloaded) ui.toast("Hot reload ⚡"); }).catch(() => {});
  }
}

export const debug = new Debug();
