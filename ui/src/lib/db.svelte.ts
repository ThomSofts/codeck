// Bancos de dados: o cadastro (bancos, ambientes, vínculos com projetos) e as bancadas abertas — uma por projeto
// (aba Banco) e uma por banco (seção Dados). A bancada guarda a conexão, o catálogo e as abas de consulta com os
// resultados: trocar de modo ou de tela e voltar encontra tudo como estava.
import { ApiError, get, post } from "./api";
import { ui } from "./ui.svelte";

export type Engine = "sqlserver" | "postgres" | "mysql" | "sqlite" | "mongodb" | "firebase" | "libsql" | "redis";
/** bancos de documentos: comandos no estilo do shell, sem transação (produção não tem Confirmar/Desfazer) */
export const isDoc = (e: Engine | null | undefined) => e === "mongodb" || e === "firebase" || e === "redis";
export type EnvKind = "dev" | "hml" | "prod";
export interface DbTls { mode: "verify" | "pin" | "off"; pin: string; legacy: boolean; rc4?: boolean; offAck?: boolean; offPublicAck?: boolean }
export interface DbEnv { id: string; kind: EnvKind; label: string; host: string; port: number | null; database: string; user: string; file: string;
  tls: DbTls; readOnly: boolean; hasPassword: boolean; timeoutSec: number | null;
  ssh?: { host: string; port: number; user: string; key: string } | null }
export interface DbLink { repo: string; alias: string; env: string | null; agents?: boolean; agentsProdRead?: boolean; agentsWrite?: boolean }
export interface DbBank { id: string; name: string; engine: Engine; folder: string; color: string; notes: string; envs: DbEnv[]; projects: DbLink[];
  created?: string; link?: DbLink }
export interface DbPlugin { engine: Engine; label: string; installed: boolean; origin: string | null; problem: string | null; version?: string | null }
export interface DbPrefs { maxRows: number; timeoutSec: number; history: boolean; historyProd: boolean; copyFormat: CopyFormat;
  png: { dest: "clipboard" | "file" | "both"; dir: string }; queries: "local" | "repo" }
export type CopyFormat = "tsv" | "csv" | "json" | "markdown" | "insert";
export interface DbSession { id: string; bank: string; env: string; engine: Engine; kind: EnvKind; repo: string | null; database: string;
  readOnly: boolean; unlocked: boolean; server: string; tls: CertInfo | null; pendingTx: { id: string; expires: string } | null;
  noWrite?: string | null; app?: AppState }
export interface AppState { device: string; deviceName: string; deviceKind: "android" | "ios-sim" | "ios" | "macos" | "windows"; rel: string;
  format: "sqlite" | "hive" | "sembast" | "prefs"; direct: boolean; dirty: boolean; backup: boolean; editable: boolean; running: boolean }
export interface FlutterInfo { flutter: boolean; kinds?: string[]; openable?: string[]; unsupported?: string[]; packages?: string[]; ids?: Record<string, any>; names?: string[] }
export interface AppDevice { id: string; name: string; kind: AppState["deviceKind"]; appId: boolean; editable: boolean; running: boolean }
export interface AppFile { path: string; rel: string; kind: AppState["format"]; size: number | null; mtime: number | null }
export interface CertInfo { sha256: string; subject: string; issuer: string; notAfter: string; version: string; cipher: string; problem?: string; detail?: string }
export interface Column { name: string; type: string }
export interface Result { statement: string; offset: number; columns?: Column[]; rows?: any[][]; affected?: number; truncated?: boolean; total?: number;
  messages?: string[]; ms: number }
export interface DbObject { schema: string; name: string; kind: "table" | "view" | "procedure" | "function" }
export interface TableInfo { schema: string; name: string; columns: { name: string; type: string; nullable: boolean; default: string | null; pk: number; identity: boolean }[];
  fks: { name: string; columns: string[]; refSchema: string; refTable: string; refColumns: string[] }[];
  indexes: { name: string; columns: string[]; unique: boolean; primary: boolean }[] }
export interface Analysis { offset: number; first: string; write: boolean; txControl: boolean; noWhere: boolean; drop: boolean; alter: boolean; exec: boolean }

export interface QueryTab {
  id: string; title: string; kind: "sql" | "table"; sql: string;
  table?: { schema: string; name: string; kind: string };
  results: Result[]; pick: number; running: boolean; queryId: string | null; ms: number | null; ranAt: number | null;
  error: { message: string; offset?: number } | null;
  info?: TableInfo | null;
  pendingTx?: { id: string; expires: string } | null;
  /** aba aberta de uma consulta salva: ⌘S grava nela */
  saved?: { id: string; scope: "bank" | "project" } | null;
}
export interface SavedQuery { id: string; name: string; sql: string; scope: "bank" | "project"; store?: "local" | "repo"; updated: string }
export interface Bench {
  key: string; repo: string | null; bank: string | null; env: string | null;
  session: DbSession | null; connecting: boolean; problem: string | null;
  objects: DbObject[] | null; filter: string; tabs: QueryTab[]; active: string | null;
  infos: Record<string, TableInfo>;
  /** banco do app Flutter: aparelho e arquivo escolhidos */
  app?: { device: string | null; path: string | null; live: boolean } | null;
}

export const ENGINE_LABEL: Record<Engine, string> = { sqlserver: "SQL Server", postgres: "PostgreSQL", mysql: "MySQL / MariaDB", sqlite: "SQLite",
  mongodb: "MongoDB", firebase: "Firebase", libsql: "libSQL / Turso", redis: "Redis" };
export const ENGINE_SHORT: Record<Engine, string> = { sqlserver: "MSSQL", postgres: "PG", mysql: "MySQL", sqlite: "SQLite", mongodb: "Mongo", firebase: "Firebase", libsql: "Turso", redis: "Redis" };
export const KIND_LABEL: Record<EnvKind, string> = { dev: "dev", hml: "hml", prod: "PROD" };
export const envName = (e: DbEnv) => e.label || KIND_LABEL[e.kind];
/** Códigos de "sem criptografia": o servidor não tem TLS, ou a conexão já está sem e falta o seu aceite. */
export const TLS_OFF_CODES = ["tls-unsupported", "tls-off-denied", "tls-off-public"];
export const quoteFor = (engine: Engine) => (id: string) =>
  engine === "sqlserver" ? `[${id.replace(/]/g, "]]")}]` : engine === "mysql" ? "`" + id.replace(/`/g, "``") + "`" : `"${id.replace(/"/g, '""')}"`;

let seq = 0;
const newId = (p: string) => `${p}${Date.now().toString(36)}${(seq++).toString(36)}`;
const LS = "codeck.db.benches";

/** O que persiste da bancada entre aberturas do app: abas e textos (nunca resultados — podem ter dados sensíveis). */
function readSaved(): Record<string, { bank: string | null; env: string | null; tabs: { id: string; title: string; kind: "sql" | "table"; sql: string; table?: any; saved?: any }[]; active: string | null }> {
  try { return JSON.parse(localStorage.getItem(LS) || "{}"); } catch { return {}; }
}

class Db {
  data = $state<{ banks: DbBank[]; folders: string[]; prefs: DbPrefs; plugins: DbPlugin[] } | null>(null);
  /** bancos vinculados a cada projeto (com o vínculo: apelido e ambiente ativo) */
  project = $state<Record<string, DbBank[]>>({});
  benches = $state<Record<string, Bench>>({});
  /** o que o projeto Flutter usa de banco local (pubspec + código) */
  flutter = $state<Record<string, FlutterInfo>>({});
  private saved = readSaved();
  private saveTimer: any = null;

  async load() {
    try { this.data = await get("db"); } catch (e) { ui.error(e); }
    return this.data;
  }
  set(d: any) { if (d?.banks) this.data = { banks: d.banks, folders: d.folders, prefs: d.prefs, plugins: d.plugins }; }
  bank(id: string | null | undefined) { return this.data?.banks.find(b => b.id === id) || null; }
  plugin(engine: Engine | null | undefined) { return this.data?.plugins.find(p => p.engine === engine) || null; }

  /** Instala (ou atualiza) o plugin de um banco: baixado da ThomSoft e conferido pelo SHA-256 assinado. */
  async installPlugin(engine: Engine) {
    const label = ENGINE_LABEL[engine];
    const pr = ui.progress(`Baixando o plugin de ${label}…`);
    const timer = setInterval(async () => {
      try {
        const p = (await get("db/plugins/progress"))[engine];
        if (p?.total) pr.update(`Baixando o plugin de ${label}… ${Math.round((p.done / p.total) * 100)}%`);
      } catch { /* só o progresso */ }
    }, 700);
    try {
      this.set(await post("db/plugins/install", { engine }));
      pr.done(`Plugin de ${label} instalado e conferido`);
      return true;
    } catch (e) { pr.fail(e); return false; } finally { clearInterval(timer); }
  }
  async uninstallPlugin(engine: Engine) {
    const ok = await ui.ask({ title: `Remover o plugin de ${ENGINE_LABEL[engine]}?`, message: "Os bancos cadastrados continuam; para conectar, instale de novo.", confirm: "Remover", danger: true });
    if (!ok) return;
    try { this.set(await post("db/plugins/uninstall", { engine })); } catch (e) { ui.error(e); }
  }

  async loadFlutter(repo: string) {
    try { this.flutter[repo] = await get("db/flutter/info", { repoId: repo }); } catch { this.flutter[repo] = { flutter: false }; }
    return this.flutter[repo];
  }
  async loadProject(repo: string) {
    try { const r = await get("db/project", { repoId: repo }); this.project[repo] = r.banks; } catch { /* sem bancos */ }
    return this.project[repo] || [];
  }

  // ------------------------------------------------------------ bancada
  bench(key: string, init: { repo?: string | null; bank?: string | null }): Bench {
    let b = this.benches[key];
    if (!b) {
      const sv = this.saved[key];
      b = {
        key, repo: init.repo ?? null, bank: sv?.bank ?? init.bank ?? null, env: sv?.env ?? null, session: null, connecting: false, problem: null,
        app: (sv as any)?.app ?? null,
        objects: null, filter: "", infos: {},
        tabs: (sv?.tabs || []).map(t => ({ ...t, results: [], pick: 0, running: false, queryId: null, ms: null, ranAt: null, error: null })),
        active: sv?.active ?? null,
      };
      if (!b.tabs.length) b.tabs.push(this.blankTab(1));
      if (!b.tabs.some(t => t.id === b.active)) b.active = b.tabs[0].id;
      this.benches[key] = b;
      b = this.benches[key];
    }
    return b;
  }
  blankTab(n: number): QueryTab {
    return { id: newId("q"), title: `Consulta ${n}`, kind: "sql", sql: "", results: [], pick: 0, running: false, queryId: null, ms: null, ranAt: null, error: null };
  }
  persist() {
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => {
      const out: any = {};
      for (const [k, b] of Object.entries(this.benches))
        out[k] = { bank: b.bank, env: b.env, active: b.active, app: b.app, tabs: b.tabs.map(t => ({ id: t.id, title: t.title, kind: t.kind, sql: t.sql.slice(0, 200_000), table: t.table, saved: t.saved || null })) };
      try { localStorage.setItem(LS, JSON.stringify(out)); } catch { /* cheio: fica só na memória */ }
    }, 400);
  }

  /** Abre (ou reabre) a conexão da bancada no banco/ambiente escolhidos. Certificado novo ou mudado: pergunta. */
  async connect(b: Bench) {
    if (b.bank === "app") return this.connectApp(b);
    if (!b.bank || !b.env) return;
    if (b.session) await this.disconnect(b);
    b.connecting = true; b.problem = null; b.objects = null; b.infos = {};
    // outro banco/ambiente: resultado antigo some (dado de dev nunca aparece debaixo da faixa de produção)
    for (const t of b.tabs) { t.results = []; t.error = null; t.ranAt = null; t.ms = null; t.pendingTx = null; t.info = null; }
    try {
      b.session = await this.openWithCert(b.bank, b.env, b.repo);
      this.refreshObjects(b);
    } catch (e: any) {
      b.problem = e?.message || String(e);
    } finally { b.connecting = false; }
  }
  /** Banco do app: abre o arquivo do aparelho (direto, cópia ou conversão — o backend decide). */
  async connectApp(b: Bench) {
    if (!b.repo || !b.app?.device || !b.app?.path) { if (b.session) await this.disconnect(b); return; }
    if (b.session) await this.disconnect(b);
    b.connecting = true; b.problem = null; b.objects = null; b.infos = {};
    for (const t of b.tabs) { t.results = []; t.error = null; t.ranAt = null; t.ms = null; t.pendingTx = null; t.info = null; }
    try {
      b.session = await post("db/flutter/open", { repoId: b.repo, device: b.app.device, path: b.app.path });
      this.refreshObjects(b);
    } catch (e: any) { b.problem = e?.message || String(e); } finally { b.connecting = false; }
  }
  /** SQL Server sem Service Pack derrubou o TLS 1.0 com CBC: explica e oferece a compatibilidade RC4 (só por escolha). */
  async askRc4(): Promise<boolean> {
    return !!(await ui.ask({
      title: "Ligar a compatibilidade RC4 nesta conexão?",
      message: "O servidor aceita TLS 1.0, mas derruba a conexão quando o cliente divide os registros (proteção que o TLS 1.0 com cifra CBC exige). " +
        "É o SQL Server 2008/2008 R2 sem Service Pack. Com RC4 a conexão continua criptografada e com o certificado fixado — RC4 é uma cifra fraca, " +
        "mas ainda muito melhor que a senha sem criptografia (que é o que ferramentas como o DBeaver/jTDS fazem com esse servidor).",
      detail: ["O certo é atualizar o servidor: SQL Server 2008 R2 SP3 + a atualização de TLS 1.2 (aí não precisa de RC4)."],
      confirm: "Ligar RC4 nesta conexão", danger: true,
    }));
  }
  /** Servidor sem TLS (ou conexão sem criptografia ainda sem o seu aceite): explica e pergunta — nunca cai para texto puro sozinho. */
  async askTlsOff(code: string, pub: boolean): Promise<boolean> {
    return !!(await ui.ask({
      title: code === "tls-unsupported" ? "O servidor não tem criptografia" : "Conectar sem criptografia?",
      message: (code === "tls-unsupported" ? "Este servidor não aceita TLS. " : "Esta conexão está configurada sem criptografia. ") +
        "Sem TLS, usuário, senha e dados passam legíveis por qualquer rede no caminho." +
        (pub ? " E o endereço é público: a senha iria legível pela internet." : " O endereço é de rede local/VPN."),
      detail: ["O certo é ligar o TLS no servidor (ssl = on no PostgreSQL, por exemplo) — aí o Codeck volta a usar criptografia."],
      confirm: pub ? "Conectar sem criptografia pela internet" : "Conectar sem criptografia", danger: true,
    }));
  }
  private async openWithCert(bank: string, env: string, repo: string | null, tries = 0): Promise<DbSession> {
    try {
      return await post("db/open", { bank, env, repoId: repo });
    } catch (e) {
      if (e instanceof ApiError && TLS_OFF_CODES.includes(e.data?.code) && tries < 2) {
        if (!(await this.askTlsOff(e.data.code, !!e.data.data?.public))) throw new Error("Conexão cancelada: o servidor não tem criptografia (TLS)");
        this.set(await post("db/tls-off", { bank, env }));
        return this.openWithCert(bank, env, repo, tries + 1);
      }
      if (e instanceof ApiError && e.data?.code === "legacy-cbc" && tries < 2) {
        if (!(await this.askRc4())) throw new Error("Conexão cancelada: o servidor precisa da compatibilidade RC4 (ou de atualização)");
        this.set(await post("db/rc4", { bank, env, on: true }));
        return this.openWithCert(bank, env, repo, tries + 1);
      }
      if (!(e instanceof ApiError) || !String(e.data?.code || "").startsWith("cert-")) throw e;
      const c: CertInfo = e.data.data;
      const changed = e.data.code === "cert-changed";
      const ok = await ui.ask({
        title: changed ? "O certificado do servidor mudou" : e.data.code === "cert-invalid" ? "Certificado não reconhecido" : "Conferir o certificado do servidor",
        message: changed
          ? "A impressão digital não é a que você fixou. Pode ser uma troca legítima de certificado — ou outro servidor no meio do caminho. Só aceite se o responsável pelo servidor confirmar."
          : "Este servidor usa um certificado que o sistema não reconhece (comum em SQL Server, que gera o próprio). Confira a impressão digital com quem administra o servidor e fixe: daqui em diante o Codeck só aceita este certificado.",
        detail: [`SHA-256: ${c.sha256.replace(/(..)(?!$)/g, "$1:")}`, `Emitido para: ${c.subject || "—"}`, `Válido até: ${c.notAfter?.slice(0, 10) || "—"}`,
          `Protocolo: ${c.version} · ${c.cipher}`, ...(c.detail ? [`Motivo: ${c.detail}`] : [])],
        confirm: changed ? "Aceitar o novo certificado" : "Fixar este certificado", danger: changed,
      });
      if (!ok) throw new Error("Conexão cancelada: certificado não aceito");
      this.set(await post("db/pin", { bank, env, sha256: c.sha256 }));
      return this.openWithCert(bank, env, repo, tries + 1);
    }
  }
  async disconnect(b: Bench) {
    const s = b.session;
    b.session = null;
    if (s) await post("db/close", { session: s.id }, { quiet: true }).catch(() => {});
  }
  async refreshObjects(b: Bench) {
    if (!b.session) return;
    try { b.objects = await post("db/catalog", { session: b.session.id, what: "objects" }, { quiet: true }); }
    catch (e) { b.objects = []; this.handleLost(b, e); }
  }
  async tableInfo(b: Bench, schema: string, name: string): Promise<TableInfo | null> {
    const k = `${schema}.${name}`;
    if (b.infos[k]) return b.infos[k];
    if (!b.session) return null;
    try { const t = await post("db/catalog", { session: b.session.id, what: "table", schema, name }, { quiet: true }); b.infos[k] = t; return t; }
    catch { return null; }
  }
  private handleLost(b: Bench, e: any) {
    const code = e instanceof ApiError ? e.data?.code : null;
    if (code === "no-session" || code === "plugin-died") { b.session = null; b.problem = "A conexão caiu — reconecte"; }
  }

  // ------------------------------------------------------------ consultas
  async run(b: Bench, tab: QueryTab, sql: string, opts: { maxRows?: number } = {}) {
    if (!b.session || tab.running || !sql.trim()) return;
    tab.running = true; tab.error = null;
    tab.queryId = newId("r");
    const started = performance.now();
    let confirm = false;
    try {
      for (let attempt = 0; attempt < 4; attempt++) {
        try {
          const r = await post("db/query", { session: b.session!.id, sql, queryId: tab.queryId, confirm, maxRows: opts.maxRows }, { quiet: true });
          tab.results = r.results; tab.pick = Math.max(0, r.results.findIndex((x: Result) => x.columns?.length));
          if (tab.pick < 0) tab.pick = 0;
          tab.ms = r.ms ?? Math.round(performance.now() - started); tab.ranAt = Date.now();
          tab.pendingTx = r.pendingTx || null;
          if (r.pendingTx && b.session) b.session.pendingTx = r.pendingTx;
          if (b.session?.app && r.results?.some((x: Result) => x.affected)) this.afterAppWrite(b);
          return r;
        } catch (e) {
          if (!(e instanceof ApiError)) throw e;
          const code = e.data?.code;
          if (code === "read-only") {
            if (!(await this.askUnlock(b))) return;
            continue;
          }
          if (code === "confirm") {
            if (!(await this.askConfirm(b, e.data?.data?.analysis || [], sql))) return;
            confirm = true;
            continue;
          }
          if ((code === "no-session" || code === "plugin-died") && attempt === 0) {   // plugin reiniciou: reabre e repete
            await this.connect(b);
            if (!b.session) throw e;
            continue;
          }
          const d = e.data?.data;
          if (d?.results) tab.results = d.results;
          tab.error = { message: e.message, offset: d?.offset };
          tab.ms = Math.round(performance.now() - started); tab.ranAt = Date.now();
          return null;
        }
      }
    } catch (e: any) {
      tab.error = { message: e?.message || String(e) };
    } finally { tab.running = false; tab.queryId = null; }
    return null;
  }
  async cancel(b: Bench, tab: QueryTab) {
    if (b.session && tab.queryId) await post("db/cancel", { session: b.session.id, queryId: tab.queryId }, { quiet: true }).catch(() => {});
  }
  async finishTx(b: Bench, tab: QueryTab | null, commit: boolean) {
    const tx = tab?.pendingTx || b.session?.pendingTx;
    if (!b.session || !tx) return;
    try {
      await post("db/tx", { session: b.session.id, txId: tx.id, commit });
      ui.toast(commit ? "Alteração confirmada em produção" : "Alteração desfeita");
    } catch (e) { ui.error(e); }
    for (const t of b.tabs) if (t.pendingTx?.id === tx.id) t.pendingTx = null;
    if (b.session) b.session.pendingTx = null;
  }

  async askUnlock(b: Bench) {
    const bank = this.bank(b.bank);
    const ok = await ui.ask({
      title: "Destravar produção?",
      message: `${bank?.name || "Este banco"} está em produção, aberto somente para leitura. Destravando, esta conexão pode alterar dados — ` +
        (isDoc(b.session?.engine) ? "cada alteração ainda mostra o que vai rodar e pede confirmação (este banco não tem Desfazer)."
          : "cada alteração ainda mostra o que vai rodar, e fica numa transação esperando você Confirmar ou Desfazer (desfeita sozinha em 5 minutos)."),
      confirm: "Destravar esta conexão", danger: true,
    });
    if (!ok || !b.session) return false;
    b.session = await post("db/unlock", { session: b.session.id, unlocked: true });
    return true;
  }
  async lock(b: Bench) {
    if (b.session) b.session = await post("db/unlock", { session: b.session.id, unlocked: false });
  }
  async askConfirm(b: Bench, analysis: Analysis[], sql: string) {
    const prod = b.session?.kind === "prod";
    const bank = this.bank(b.bank);
    const doc = isDoc(b.session?.engine);
    const lines: string[] = [];
    for (const a of analysis) {
      const stmt = sql.slice(a.offset, a.offset + 160).split("\n")[0].trim();
      if (a.noWhere) lines.push(`⚠ ${a.first} sem WHERE — a tabela inteira: ${stmt}`);
      else if (a.drop) lines.push(`⚠ ${a.first} — apaga estrutura/dados: ${stmt}`);
      else if (a.write) lines.push(`${a.exec ? "Procedure (pode alterar dados)" : a.first}: ${stmt}`);
    }
    return !!(await ui.ask({
      title: prod ? `Alterar PRODUÇÃO · ${bank?.name || ""}` : "Confirmar alteração",
      message: prod && doc ? "Este banco não tem Desfazer: a alteração vale assim que executar. Confira o comando."
        : prod ? "Roda numa transação: depois você vê quantas linhas mudaram e escolhe Confirmar ou Desfazer." : "Este comando mexe em muitos registros ou na estrutura.",
      detail: lines.slice(0, 12), confirm: prod && !doc ? "Executar (e decidir depois)" : "Executar", danger: true,
    }));
  }

  afterAppWrite(b: Bench) {
    const a = b.session?.app;
    if (!a) return;
    if (!a.direct) { a.dirty = true; return; }
    if (a.running) ui.toast("Gravado no banco do app", "ok", { label: "Hot restart", run: () => this.appRestart(b) });
  }
  async appRestart(b: Bench) {
    if (!b.session) return;
    try { await post("db/flutter/restart", { session: b.session.id }); ui.toast("Hot restart ✓ — o app releu o banco"); } catch (e) { ui.error(e); }
  }
  async appPush(b: Bench) {
    const a = b.session?.app;
    if (!b.session || !a) return;
    const ok = await ui.ask({ title: `Enviar o banco ao ${a.deviceName}?`, confirm: "Enviar e reabrir o app",
      message: "O app vai fechar no aparelho; o Codeck guarda o banco atual dele como backup, troca pelo editado e reabre o app (sem rebuild). Se algo der errado, use Desfazer." });
    if (!ok) return;
    const pr = ui.progress("Enviando ao aparelho…");
    try { const r = await post("db/flutter/push", { session: b.session.id }); b.session.app = r.app; pr.done("Banco trocado e app reaberto"); } catch (e) { pr.fail(e); }
  }
  async appUndo(b: Bench) {
    if (!b.session) return;
    if (!(await ui.ask({ title: "Voltar o banco anterior?", message: "Fecha o app, devolve o backup feito antes do envio e reabre.", confirm: "Voltar o backup", danger: true }))) return;
    try { const r = await post("db/flutter/undo", { session: b.session.id }); b.session.app = r.app; ui.toast("Backup devolvido ao aparelho"); } catch (e) { ui.error(e); }
  }

  // ------------------------------------------------------------ agentes de IA (MCP): aprovações
  private asked = new Set<string>();
  private queue: any[] = [];
  private asking = false;
  /** Fica de olho nos pedidos dos agentes (MCP de banco) e pergunta na tela, um de cada vez. */
  watchAgents() {
    const tick = async () => {
      try {
        const r = await get("db/agent/pending");
        for (const p of r.items) if (!this.asked.has(p.id)) { this.asked.add(p.id); this.queue.push(p); }
        this.drain();
      } catch { /* backend reiniciando */ }
    };
    tick();
    setInterval(tick, 2500);
  }
  private async drain() {
    if (this.asking || !this.queue.length) return;
    this.asking = true;
    const p = this.queue.shift();
    try {
      while (ui.dialog) await new Promise(r => setTimeout(r, 400));   // outra pergunta aberta: espera a vez
      const prod = p.env === "prod";
      const r = await ui.ask({
        title: `Agente pede: ${p.why.toLowerCase()}`,
        message: `${p.repoName} · ${p.bankName} (${p.envName}). Sem resposta em 30 minutos, o pedido é negado.`,
        detail: String(p.sql).split("\n").slice(0, 18),
        confirm: "Permitir", cancel: "Negar", danger: p.write || prod,
        check: p.remember ? (p.remember === "agentsWrite" ? "Não perguntar de novo para alterações neste banco (dev/hml)" : "Não perguntar de novo para leituras deste banco") : undefined,
      });
      await post("db/agent/answer", { id: p.id, allow: !!r, remember: r === "check" }, { quiet: true }).catch(() => {});
    } finally { this.asking = false; this.drain(); }
  }
  async setAgents(bank: string, repo: string, on: boolean) {
    if (on && !(await ui.ask({ title: "Liberar este banco para os agentes de IA?",
      message: "Os agentes (Claude, Codex) deste projeto passam a consultar este banco no ambiente ativo, pelo MCP do Codeck. " +
        "Leitura em produção e qualquer alteração pedem a sua aprovação aqui (alteração em produção, sempre). Vale para agentes abertos daqui em diante.",
      confirm: "Liberar" }))) return false;
    try { this.set(await post("db/link", { bank, repoId: repo, flags: { agents: on } })); await this.loadProject(repo); return true; }
    catch (e) { ui.error(e); return false; }
  }

  // ------------------------------------------------------------ edições da grade
  async apply(b: Bench, changes: any[]) {
    if (!b.session) return null;
    const prod = b.session.kind === "prod";
    if (prod && b.session.readOnly && !b.session.unlocked && !(await this.askUnlock(b))) return null;
    const preview = await post("db/apply", { session: b.session.id, changes, dryRun: true });
    const ok = await ui.ask({
      title: `${prod ? "PRODUÇÃO · " : ""}Aplicar ${changes.length} ${changes.length === 1 ? "edição" : "edições"}?`,
      message: isDoc(b.session.engine) ? "O Codeck confere antes que todos os documentos ainda existem; se algum sumiu, nada é aplicado."
        : "Tudo numa transação: ou entram todas, ou nenhuma. Se alguma linha mudou desde que você leu, nada é aplicado.",
      detail: (preview.sql as string[]).slice(0, 30).concat(preview.sql.length > 30 ? [`… e mais ${preview.sql.length - 30}`] : []),
      confirm: "Aplicar", danger: prod,
    });
    if (!ok) return null;
    const r = await post("db/apply", { session: b.session.id, changes, confirm: true });
    if (b.session?.app) this.afterAppWrite(b);
    return r;
  }
}

export const db = new Db();
