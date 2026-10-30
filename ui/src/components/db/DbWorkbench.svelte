<script lang="ts">
  // Bancada de banco de dados: escolhe o banco (no projeto, entre os vinculados) e o ambiente, mostra os objetos e as
  // abas de consulta. Produção abre travada (somente leitura) e com a faixa vermelha; alteração em produção fica numa
  // transação esperando Confirmar/Desfazer, com o tempo correndo.
  import { Bot, Bookmark, BookmarkPlus, Radio, Smartphone, Upload, Undo2, Zap, Braces, ChevronDown, Clock, Database, Eye, FolderGit2, FileCode2, Filter, FunctionSquare, Image, Lock, LockOpen, Play, Plus, RefreshCw, Search, Settings2,
    Square, Table2, TriangleAlert, Unplug, X } from "@lucide/svelte";
  import { onMount, untrack } from "svelte";
  import { get, post } from "../../lib/api";
  import { copyText } from "../../lib/clipboard";
  import { db, ENGINE_LABEL, envName, isDoc, KIND_LABEL, quoteFor, type Bench, type DbBank, type DbObject, type QueryTab, type SavedQuery, type TableInfo, type AppDevice, type AppFile } from "../../lib/db.svelte";
  import { sqlLiteral } from "../../lib/dbcopy";
  import { ago } from "../../lib/format";
  import { ui } from "../../lib/ui.svelte";
  import Drawer from "../Drawer.svelte";
  import Empty from "../Empty.svelte";
  import BankEditor from "./BankEditor.svelte";
  import PngDialog from "./PngDialog.svelte";
  import ResultGrid from "./ResultGrid.svelte";
  import SqlEditor from "./SqlEditor.svelte";

  let { repo = null, bankId = null, onmanage = undefined }: { repo?: string | null; bankId?: string | null; onmanage?: () => void } = $props();

  const key = untrack(() => (repo ? "p:" + repo : "b:" + bankId));
  const b: Bench = db.bench(key, untrack(() => ({ repo, bank: bankId })));
  let banks = $state<DbBank[]>([]);
  let loaded = $state(false);
  let editing = $state<DbBank | null | "new">(null);
  let png = $state<{ cols: number[]; rows: number[]; tab: QueryTab } | null>(null);
  let saved = $state<SavedQuery[]>([]);
  let savedWhere = $state<"local" | "repo">("local");
  let historyOpen = $state(false);
  let history = $state<{ at: string; ok: boolean; ms: number; sql: string; env: string }[] | null>(null);
  let hq = $state("");
  let edH = $state(Number(localStorage.getItem("codeck.db.edH")) || 220);
  let treeW = $state(Number(localStorage.getItem("codeck.db.treeW")) || 250);
  let structure = $state(false);
  let sqlEd: SqlEditor | undefined = $state();
  let now = $state(Date.now());

  const isApp = $derived(b.bank === "app");
  const appInfo = $derived(repo ? db.flutter[repo] : null);
  const appUsable = $derived(!!appInfo?.openable?.length);
  let appDevices = $state<AppDevice[] | null>(null);
  let appFiles = $state<AppFile[] | null>(null);
  let appProblem = $state<string | null>(null);
  let flash = $state<Set<number>>(new Set());
  const APP_FMT: Record<string, string> = { sqlite: "SQLite", hive: "Hive", sembast: "sembast", prefs: "shared_preferences" };
  const APP_KIND: Record<string, string> = { android: "Android", "ios-sim": "Simulador iOS", ios: "iPhone", macos: "macOS", windows: "Windows" };
  const bank = $derived(isApp && b.session ? ({ id: "app", name: "Banco do app", engine: "sqlite", envs: [], projects: [], folder: "", color: "#3ccf91", notes: "" } as DbBank)
    : banks.find(x => x.id === b.bank) || (isApp ? ({ id: "app", name: "Banco do app", engine: "sqlite", envs: [], projects: [], folder: "", color: "#3ccf91", notes: "" } as DbBank) : null));
  const env = $derived(bank?.envs.find(e => e.id === b.env) || null);
  const tab = $derived(b.tabs.find(t => t.id === b.active) || b.tabs[0]);
  const prod = $derived(env?.kind === "prod");
  const q = $derived(quoteFor(bank?.engine || "postgres"));

  async function loadBanks() {
    if (!db.data) await db.load();
    banks = repo ? await db.loadProject(repo) : (db.data?.banks || []).filter(x => x.id === bankId);
    if (repo && !db.flutter[repo]) await db.loadFlutter(repo);
    loaded = true;
    if (b.bank === "app" && !appUsable) b.bank = null;
    if (b.bank !== "app" && !banks.some(x => x.id === b.bank)) b.bank = banks[0]?.id || (appUsable ? "app" : null);
    if (b.bank === "app") { if (!b.app) b.app = { device: null, path: null, live: true }; loadDevices(); return; }
    const bk = banks.find(x => x.id === b.bank);
    if (bk && !bk.envs.some(e => e.id === b.env)) b.env = bk.link?.env || bk.envs.find(e => e.kind !== "prod")?.id || bk.envs[0]?.id || null;
    if (b.bank && b.env && !b.session && !b.connecting && !b.problem) db.connect(b);
  }
  onMount(() => {
    loadBanks();
    const t = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(t);
  });
  // o cadastro mudou (banco editado em outra tela): relê
  $effect(() => { void db.data?.banks; untrack(() => loaded && loadBanks()); });
  // consultas salvas do banco (e do projeto)
  async function loadSaved() {
    if (!b.bank) { saved = []; return; }
    try { const r = await get("db/queries", { bank: b.bank, repoId: repo }); saved = r.items; savedWhere = r.where; } catch { saved = []; }
  }
  $effect(() => { void b.bank; untrack(loadSaved); });
  function openSaved(q: SavedQuery) {
    const open = b.tabs.find(t => t.saved?.id === q.id);
    if (open) { b.active = open.id; return; }
    const t = { ...db.blankTab(0), title: q.name, sql: q.sql, saved: { id: q.id, scope: q.scope } };
    b.tabs.push(t);
    b.active = t.id;
  }
  async function saveTab(t: QueryTab, rename = false) {
    if (!b.bank || !t.sql.trim()) return;
    if (b.bank === "app") return ui.toast("Consultas salvas valem para os bancos cadastrados — no banco do app, use o histórico", "info");
    let name = t.title, scope: "bank" | "project" = t.saved?.scope || (repo ? "project" : "bank");
    if (!t.saved || rename) {
      const r = await ui.ask({ title: rename ? "Renomear consulta" : "Salvar consulta", confirm: "Salvar",
        input: { label: "Nome", value: /^Consulta \d+$/.test(t.title) ? "" : t.title, required: true } });
      if (typeof r !== "string" || !r.trim()) return;
      name = r.trim();
      if (repo && !t.saved) {
        const w = await ui.ask({ title: `Onde guardar "${name}"?`,
          message: `Do projeto: ${savedWhere === "repo" ? "vai para .codeck-db/queries no repositório (versionada, o time vê)" : "fica só neste computador"}. ` +
            "Do banco: aparece em todos os projetos que usam este banco (só neste computador).",
          confirm: "Do projeto", alt: "Do banco" });
        if (!w) return;
        scope = w === "alt" ? "bank" : "project";
      }
    }
    try {
      const r = await post("db/queries/save", { bank: b.bank, repoId: repo, name, sql: t.sql, scope, id: t.saved?.id });
      t.saved = { id: r.id, scope }; t.title = name;
      saved = r.items;
      ui.toast("Consulta salva");
    } catch (e) { ui.error(e); }
  }
  function savedMenu(e: MouseEvent, q: SavedQuery) {
    e.preventDefault();
    ui.contextMenu(e, [
      { label: "Abrir", icon: Bookmark, onclick: () => openSaved(q) },
      { label: "Renomear…", onclick: async () => { openSaved(q); const t = b.tabs.find(x => x.saved?.id === q.id); if (t) await saveTab(t, true); } },
      { label: "Excluir", danger: true, onclick: async () => {
        if (!(await ui.ask({ title: `Excluir "${q.name}"?`, confirm: "Excluir", danger: true }))) return;
        try { saved = (await post("db/queries/delete", { bank: b.bank, id: q.id, repoId: repo })).items; for (const t of b.tabs) if (t.saved?.id === q.id) t.saved = null; } catch (err) { ui.error(err); }
      } },
    ]);
  }
  async function setWhere(v: "local" | "repo") {
    try { savedWhere = (await post("db/queries/where", { repoId: repo, where: v })).where; ui.toast(v === "repo" ? "Consultas do projeto vão para o repositório" : "Consultas do projeto ficam neste computador"); }
    catch (e) { ui.error(e); }
  }
  async function openHistory() {
    historyOpen = true; history = null;
    try { history = (await get("db/history", { bank: b.bank, repoId: repo })).items; } catch (e) { ui.error(e); history = []; }
  }
  function fromHistory(sql: string) {
    const t = { ...db.blankTab(0), title: "Do histórico", sql };
    b.tabs.push(t); b.active = t.id; historyOpen = false;
  }
  $effect(() => { void b.tabs.map(t => t.sql + t.title); void b.active; void b.env; void b.bank; db.persist(); });

  async function pickEnv(id: string) {
    if (id === b.env) return;
    const e = bank?.envs.find(x => x.id === id);
    if (e?.kind === "prod" && !(await ui.ask({ title: `Abrir PRODUÇÃO · ${bank!.name}?`, message: "Abre somente leitura. Para alterar, você destrava a conexão e confirma cada alteração.", confirm: "Abrir produção" }))) return;
    b.env = id;
    if (repo && bank) post("db/link", { bank: bank.id, repoId: repo, env: id }, { quiet: true }).catch(() => {});   // lembra o ambiente do projeto
    db.connect(b);
  }
  function pickBank(id: string) {
    if (id === b.bank) return;
    if (id === "app") {
      db.disconnect(b);
      b.bank = "app";
      if (!b.app) b.app = { device: null, path: null, live: true };
      loadDevices();
      return;
    }
    b.bank = id;
    const bk = banks.find(x => x.id === id);
    b.env = bk?.link?.env || bk?.envs.find(e => e.kind !== "prod")?.id || bk?.envs[0]?.id || null;
    db.connect(b);
  }

  // ------------------------------------------------------------ banco do app (Flutter)
  async function loadDevices() {
    appProblem = null;
    try {
      const r = await get("db/flutter/devices", { repoId: repo });
      appDevices = r.devices;
      if (!appDevices!.some(d => d.id === b.app?.device)) b.app!.device = appDevices!.find(d => d.appId)?.id || null;
      if (b.app!.device) await loadFiles(!b.session);
    } catch (e: any) { appProblem = e?.message || String(e); appDevices = []; }
  }
  async function loadFiles(connect = true) {
    appFiles = null; appProblem = null;
    try {
      const r = await get("db/flutter/files", { repoId: repo, device: b.app!.device });
      appFiles = r.files;
      if (!appFiles!.some(f => f.path === b.app!.path)) {
        const names = (appInfo?.names || []).map(n => n.toLowerCase());
        b.app!.path = (appFiles!.find(f => names.includes(f.rel.split("/").pop()!.toLowerCase())) || appFiles!.find(f => f.kind === "sqlite") || appFiles![0])?.path || null;
      }
      if (connect && b.app!.path) db.connect(b);
    } catch (e: any) { appProblem = e?.message || String(e); appFiles = []; }
  }
  function pickDevice(id: string) { b.app!.device = id; b.app!.path = null; db.disconnect(b); loadFiles(); }
  function pickFile(path: string) { b.app!.path = path; db.connect(b); }
  // ao vivo: o arquivo mudou no aparelho → relê e destaca as linhas novas/alteradas
  $effect(() => {
    if (!isApp || !b.app?.live || !b.session?.app) return;
    const ms = b.session.app.deviceKind === "ios" ? 10000 : 3000;
    let busy = false;
    const t = setInterval(async () => {
      if (busy || !b.session || tab?.running) return;
      busy = true;
      try {
        const r = await post("db/flutter/sync", { session: b.session.id }, { quiet: true });
        if (b.session) b.session.app = r.app;
        if (r.changed) {
          db.refreshObjects(b);
          if (tab?.ranAt && tab.sql.trim()) {
            const before = new Set((tab.results[tab.pick]?.rows || []).map(x => JSON.stringify(x)));
            await db.run(b, tab, tab.sql);
            const now2 = tab.results[tab.pick]?.rows || [];
            flash = new Set(now2.map((x, i) => (before.has(JSON.stringify(x)) ? -1 : i)).filter(i => i >= 0));
            setTimeout(() => (flash = new Set()), 2600);
          }
        }
      } catch { /* aparelho desconectou: tenta no próximo */ } finally { busy = false; }
    }, ms);
    return () => clearInterval(t);
  });

  // ------------------------------------------------------------ objetos
  const groups = $derived.by(() => {
    const f = b.filter.toLowerCase();
    const list = (b.objects || []).filter(o => !f || o.name.toLowerCase().includes(f) || o.schema.toLowerCase().includes(f));
    const defSchema = bank?.engine === "sqlserver" ? "dbo" : bank?.engine === "postgres" ? "public" : isDoc(bank?.engine) ? (b.session?.database || env?.database || null) : null;
    const by = (k: DbObject["kind"]) => list.filter(o => o.kind === k);
    return { defSchema, items: [["table", "Tabelas", Table2], ["view", "Views", Eye], ["procedure", "Procedures", FileCode2], ["function", "Funções", FunctionSquare]]
      .map(([k, label, icon]) => ({ k: k as string, label: label as string, icon: icon as any, list: by(k as any) })).filter(g => g.list.length) };
  });
  let closedGroups = $state<Record<string, boolean>>({ procedure: true, function: true, saved: false });
  const fullName = (o: { schema: string; name: string }) => (bank?.engine === "sqlite" || (bank?.engine === "mysql") ? q(o.name) : `${q(o.schema)}.${q(o.name)}`);

  function tableSql(o: { schema: string; name: string }, where = "", order: { col: string; desc: boolean } | null = null, limit = 1000) {
    if (bank?.engine === "mongodb") {
      const srt = order ? `.sort({${JSON.stringify(order.col)}: ${order.desc ? -1 : 1}})` : "";
      return `db.getCollection(${JSON.stringify(o.name)}).find(${where.trim() || "{}"})${srt}.limit(${limit})`;
    }
    if (bank?.engine === "redis") return `SCAN 0 MATCH ${where.trim() || o.name} COUNT ${limit}`;
    if (bank?.engine === "firebase") {
      const w = where.trim() ? "." + where.trim().replace(/^\./, "") : "";
      if (env?.host?.startsWith("https://")) return `ref(${JSON.stringify(o.name)})${w}${order ? `.orderByChild(${JSON.stringify(order.col)})` : ""}.limitToFirst(${limit})`;
      return `collection(${JSON.stringify(o.name)})${w}${order ? `.orderBy(${JSON.stringify(order.col)}${order.desc ? ", 'desc'" : ""})` : ""}.limit(${limit})`;
    }
    const w = where.trim() ? ` WHERE ${where.trim()}` : "";
    const ob = order ? ` ORDER BY ${q(order.col)}${order.desc ? " DESC" : ""}` : "";
    return bank?.engine === "sqlserver" ? `SELECT TOP (${limit}) * FROM ${fullName(o)}${w}${ob}` : `SELECT * FROM ${fullName(o)}${w}${ob} LIMIT ${limit}`;
  }
  type TableTab = QueryTab & { where?: string; order?: { col: string; desc: boolean } | null };
  function openTable(o: DbObject, where = "") {
    const existing = b.tabs.find(t => t.kind === "table" && t.table?.schema === o.schema && t.table?.name === o.name && !where) as TableTab | undefined;
    if (existing) { b.active = existing.id; return; }
    const t: TableTab = { ...db.blankTab(0), kind: "table", title: o.name, table: { schema: o.schema, name: o.name, kind: o.kind }, where, order: null, sql: "" };
    t.sql = tableSql(o, where);
    b.tabs.push(t);
    b.active = t.id;
    const live = b.tabs.find(x => x.id === t.id)!;
    db.tableInfo(b, o.schema, o.name).then(info => (live.info = info));
    db.run(b, live, live.sql);
  }
  function rerunTable(t: TableTab) {
    if (!t.table) return;
    t.sql = tableSql(t.table, t.where || "", t.order || null);
    db.run(b, t, t.sql);
  }
  function objMenu(e: MouseEvent, o: DbObject) {
    e.preventDefault();
    ui.contextMenu(e, [
      ...(o.kind === "table" || o.kind === "view" ? [{ label: "Abrir dados", icon: Table2, onclick: () => openTable(o) }] : []),
      { label: isDoc(bank?.engine) ? "Escrever a consulta" : "Escrever SELECT na consulta", icon: Braces, onclick: () => insertInQuery(o.kind === "procedure" ? (bank?.engine === "sqlserver" ? `EXEC ${fullName(o)}` : `CALL ${fullName(o)}()`) : tableSql(o, "", null, 100)) },
      { label: "Copiar nome", onclick: () => copyText(fullName(o)) },
    ]);
  }
  function insertInQuery(text: string) {
    let t = b.tabs.find(x => x.id === b.active && x.kind === "sql") || b.tabs.find(x => x.kind === "sql");
    if (!t) { newTab(); t = b.tabs[b.tabs.length - 1]; }
    b.active = t.id;
    t.sql = t.sql.trim() ? t.sql.replace(/\s*$/, "\n\n") + text : text;
  }

  // ------------------------------------------------------------ abas
  function newTab() {
    const n = b.tabs.filter(t => t.kind === "sql").length + 1;
    const t = db.blankTab(n);
    b.tabs.push(t);
    b.active = t.id;
  }
  function closeTab(t: QueryTab) {
    if (t.pendingTx) return ui.toast("Confirme ou desfaça a alteração antes de fechar", "error");
    const i = b.tabs.indexOf(t);
    b.tabs.splice(i, 1);
    if (!b.tabs.length) b.tabs.push(db.blankTab(1));
    if (b.active === t.id) b.active = b.tabs[Math.max(0, i - 1)].id;
  }
  async function renameTab(t: QueryTab) {
    const v = await ui.ask({ title: "Renomear aba", input: { label: "Nome", value: t.title, required: true }, confirm: "Renomear" });
    if (typeof v === "string" && v.trim()) t.title = v.trim().slice(0, 40);
  }

  let runBase = 0;
  function run(sql: string, base: number) {
    runBase = base;
    if (!b.session) return ui.toast("Sem conexão — conecte primeiro", "error");
    db.run(b, tab, sql);
  }
  const errorAt = $derived(tab?.error?.offset != null ? runBase + tab.error.offset : null);
  const res = $derived(tab?.results[tab.pick] || null);
  const affected = $derived((tab?.results || []).filter(r => r.affected != null && !r.columns?.length));
  const messages = $derived((tab?.results || []).flatMap(r => r.messages || []));

  // ------------------------------------------------------------ edição e chave estrangeira
  const editable = $derived.by(() => {
    if (tab?.kind !== "table" || !tab.info || tab.table?.kind !== "table") return null;
    const pk = tab.info.columns.filter(c => c.pk > 0).sort((a, c) => a.pk - c.pk).map(c => c.name);
    return pk.length ? { schema: tab.table.schema, name: tab.table.name, info: tab.info as TableInfo, pk } : null;
  });
  async function onapply(changes: any[]) {
    try {
      const r = await db.apply(b, changes);
      if (!r) return false;
      ui.toast(`${r.affected} ${r.affected === 1 ? "linha alterada" : "linhas alteradas"}`);
      rerunTable(tab as TableTab);
      return true;
    } catch (e) { ui.error(e); return false; }
  }
  function onfk(fk: TableInfo["fks"][number], value: any) {
    const ref = { schema: fk.refSchema, name: fk.refTable, kind: "table" as const };
    const col = (b.infos[`${ref.schema}.${ref.name}`]?.columns.find(c => c.name === fk.refColumns[0])?.type) || "";
    openTable(ref, `${q(fk.refColumns[0])} = ${sqlLiteral(value, bank!.engine, col || (typeof value === "number" ? "INT" : ""))}`);
  }
  function sortBy(col: string) {
    const t = tab as TableTab;
    t.order = t.order?.col === col ? (t.order.desc ? null : { col, desc: true }) : { col, desc: false };
    rerunTable(t);
  }

  function drag(e: PointerEvent, what: "ed" | "tree") {
    e.preventDefault();
    const y0 = e.clientY, x0 = e.clientX, h0 = edH, w0 = treeW;
    const move = (ev: PointerEvent) => {
      if (what === "ed") edH = Math.max(80, Math.min(window.innerHeight - 240, h0 + ev.clientY - y0));
      else treeW = Math.max(180, Math.min(520, w0 + ev.clientX - x0));
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
      localStorage.setItem("codeck.db.edH", String(edH)); localStorage.setItem("codeck.db.treeW", String(treeW)); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }
  const txLeft = $derived(b.session?.pendingTx ? Math.max(0, Math.round((Date.parse(b.session.pendingTx.expires) - now) / 1000)) : 0);
  const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  const footer = $derived(res ? `${(res.rows?.length || 0).toLocaleString("pt-BR")}${res.truncated ? ` de ${res.total != null ? res.total.toLocaleString("pt-BR") : "mais de " + (res.rows?.length || 0).toLocaleString("pt-BR")}` : ""} linhas · ${tab.ms ?? res.ms} ms${tab.ranAt ? " · " + ago(new Date(tab.ranAt).toISOString()) : ""}` : "");
  const sqlSource = { tables: () => b.objects || [], columns: async (s: string, n: string) => (await db.tableInfo(b, s, n))?.columns || [], get engine() { return bank?.engine || "postgres"; } };
</script>

{#if !loaded}
  <div class="center"><span class="muted">Carregando…</span></div>
{:else if !banks.length && !appUsable}
  <div class="center">
    <Empty title={repo ? "Nenhum banco vinculado a este projeto" : "Banco não encontrado"} text="Cadastre o banco (ou escolha um existente) em Dados → Gerenciar e marque este projeto.">
      {#if onmanage}<button class="btn primary" onclick={onmanage}><Database size={15} /> Gerenciar bancos</button>{/if}
    </Empty>
  </div>
{:else}
<div class="wb" class:prod style="--tw:{treeW}px">
  <!-- barra: banco, ambiente, conexão -->
  <div class="top">
    {#if banks.length + (appUsable ? 1 : 0) > 1}
      <select class="select bsel" value={b.bank} onchange={(e) => pickBank((e.target as HTMLSelectElement).value)}>
        {#each banks as x (x.id)}<option value={x.id}>{x.link?.alias || x.name}</option>{/each}
        {#if appUsable}<option value="app">📱 Banco do app</option>{/if}
      </select>
    {:else if isApp}
      <span class="bname"><Smartphone size={14} /><b>Banco do app</b></span>
    {:else}
      <span class="bname"><span class="dot" style="background:{bank?.color}"></span><b>{bank?.link?.alias || bank?.name}</b></span>
    {/if}
    {#if isApp}
      <select class="select asel" value={b.app?.device || ""} title="Aparelho" onchange={(e) => pickDevice((e.target as HTMLSelectElement).value)}>
        {#if !appDevices}<option value="">procurando aparelhos…</option>{:else if !appDevices.length}<option value="">nenhum aparelho ligado</option>{/if}
        {#each appDevices || [] as d (d.id)}<option value={d.id} disabled={!d.appId}>{APP_KIND[d.kind]} · {d.name}{d.appId ? "" : " (sem id do app)"}</option>{/each}
      </select>
      <select class="select asel" value={b.app?.path || ""} title="Arquivo do banco" onchange={(e) => pickFile((e.target as HTMLSelectElement).value)}>
        {#if b.app?.device && !appFiles}<option value="">lendo o app…</option>{:else if appFiles && !appFiles.length}<option value="">nenhum banco achado</option>{/if}
        {#each appFiles || [] as f (f.path)}<option value={f.path}>{f.rel} · {APP_FMT[f.kind]}</option>{/each}
      </select>
      <button class="btn sm ghost" class:on={b.app?.live} title="Ao vivo: relê sozinho quando o app grava, e destaca o que mudou" onclick={() => b.app && (b.app.live = !b.app.live)}><Radio size={13} /> Ao vivo</button>
    {/if}
    <div class="envs" role="tablist" aria-label="Ambiente" class:hidden={isApp}>
      {#each bank?.envs || [] as e (e.id)}
        <button role="tab" class="ek {e.kind}" class:on={e.id === b.env} aria-selected={e.id === b.env} onclick={() => pickEnv(e.id)}>{envName(e)}</button>
      {/each}
    </div>
    <span class="tiny muted conn ell">
      {#if b.connecting}Conectando…{:else if bank && db.plugin(bank.engine) && !db.plugin(bank.engine)!.installed}<button class="link" onclick={async () => { if (await db.installPlugin(bank!.engine)) db.connect(b); }}>Instalar o plugin de {ENGINE_LABEL[bank.engine]}</button>{:else if b.session}{b.session.server}{b.session.tls ? ` · ${b.session.tls.version}` : bank?.engine === "sqlite" ? "" : " · sem criptografia"}{:else if b.problem}<span class="err">{b.problem}</span>{:else if appProblem}<span class="err">{appProblem}</span>{/if}
    </span>
    <span class="grow"></span>
    {#if prod && b.session}
      {#if b.session.readOnly && !b.session.unlocked}
        <button class="btn sm lockb" title="Produção em somente leitura — clique para destravar esta conexão" onclick={() => db.askUnlock(b)}><Lock size={13} /> Somente leitura</button>
      {:else}
        <button class="btn sm danger" title="Alterações liberadas nesta conexão — clique para travar de novo" onclick={() => db.lock(b)}><LockOpen size={13} /> Destravado</button>
      {/if}
    {/if}
    <button class="btn sm ghost icon" title="Reconectar" onclick={() => db.connect(b)}><RefreshCw size={14} /></button>
    {#if b.session}<button class="btn sm ghost icon" title="Desconectar" onclick={() => db.disconnect(b)}><Unplug size={14} /></button>{/if}
    {#if repo && !isApp && bank?.link}
      <button class="btn sm ghost" class:agents={bank.link.agents} title={bank.link.agents ? "Agentes de IA deste projeto podem consultar este banco (MCP) — clique para desligar" : "Liberar este banco para os agentes de IA deste projeto (MCP)"}
        onclick={async () => { if (await db.setAgents(bank!.id, repo!, !bank!.link!.agents)) banks = db.project[repo!] || banks; }}><Bot size={13} /> {bank.link.agents ? "Agentes: sim" : "Agentes"}</button>
    {/if}
    <button class="btn sm ghost icon" title="Histórico de consultas (só neste computador)" onclick={openHistory}><Clock size={14} /></button>
    {#if !isApp}<button class="btn sm ghost icon" title="Configurar este banco" onclick={() => (editing = bank)}><Settings2 size={14} /></button>
    {:else}<button class="btn sm ghost icon" title="Procurar aparelhos e arquivos de novo" onclick={loadDevices}><Smartphone size={14} /></button>{/if}
  </div>
  {#if isApp && b.session?.app}
    {@const a = b.session.app}
    <div class="appbar tiny">
      <span class="pill {a.editable ? 'good' : 'neutral'}">{APP_FMT[a.format]}{a.editable ? "" : " · só leitura"}</span>
      <span class="muted">{a.direct ? "aberto direto no arquivo do app" : a.format !== "sqlite" ? "convertido para consultar (somente leitura)" : a.deviceKind === "ios" ? "cópia — o iPhone físico não recebe o banco de volta" : "cópia do aparelho — edite e envie de volta"}</span>
      {#if appInfo?.unsupported?.length}<span class="muted">· {appInfo.unsupported.join(", ")}: formato próprio, ainda não abre</span>{/if}
      <span class="grow"></span>
      {#if a.direct && a.running}<button class="btn sm" title="O app roda pelo Codeck: hot restart relê o banco" onclick={() => db.appRestart(b)}><Zap size={12} /> Hot restart</button>{/if}
      {#if a.backup}<button class="btn sm ghost" onclick={() => db.appUndo(b)}><Undo2 size={12} /> Desfazer envio</button>{/if}
      {#if a.dirty}<span class="pend">Edições na cópia</span><button class="btn sm primary" onclick={() => db.appPush(b)}><Upload size={12} /> Enviar ao aparelho</button>{/if}
    </div>
  {/if}
  {#if prod}<div class="prodbar"><TriangleAlert size={13} /> PRODUÇÃO · {bank?.name}{env?.database ? " · " + env.database : ""}</div>{/if}
  {#if b.session?.pendingTx}
    <div class="txbar">
      <TriangleAlert size={15} />
      <span><b>Alteração em produção esperando você.</b> {affected.map(a => a.affected).reduce((x, y) => x! + y!, 0) ?? ""} linha(s) afetada(s) — desfeita sozinha em {mmss(txLeft)}.</span>
      <span class="grow"></span>
      <button class="btn sm" onclick={() => db.finishTx(b, tab, false)}>Desfazer</button>
      <button class="btn sm danger-solid" onclick={() => db.finishTx(b, tab, true)}>Confirmar</button>
    </div>
  {/if}

  <div class="main">
    <!-- objetos -->
    <aside class="tree">
      <div class="tf"><Search size={13} /><input class="input" placeholder="Filtrar tabelas…" bind:value={b.filter} />
        <button class="btn sm ghost icon" title="Recarregar objetos" onclick={() => db.refreshObjects(b)}><RefreshCw size={12} /></button></div>
      <div class="tl">
        {#if (saved.length || repo) && !isApp}
          <div class="gh sv">
            <button class="ghb" onclick={() => (closedGroups.saved = !closedGroups.saved)}><ChevronDown size={12} class={closedGroups.saved ? "rot" : ""} /> Consultas salvas <span class="tiny muted">{saved.length}</span></button>
            {#if repo}<button class="btn sm ghost icon wh" title={savedWhere === "repo" ? "Consultas do projeto no repositório (versionadas) — clique para guardar só neste computador" : "Consultas do projeto só neste computador — clique para guardar no repositório"}
              onclick={() => setWhere(savedWhere === "repo" ? "local" : "repo")}>{#if savedWhere === "repo"}<FolderGit2 size={12} />{:else}<Bookmark size={12} />{/if}</button>{/if}
          </div>
          {#if !closedGroups.saved}
            {#each saved.filter(q => !b.filter || q.name.toLowerCase().includes(b.filter.toLowerCase())) as q (q.scope + q.id)}
              <button class="obj" title={q.sql.slice(0, 300)} onclick={() => openSaved(q)} oncontextmenu={(e) => savedMenu(e, q)}>
                {#if q.store === "repo"}<FolderGit2 size={13} />{:else}<Bookmark size={13} />{/if}<span class="ell">{q.name}</span>
                {#if repo}<span class="tiny muted sc">{q.scope === "bank" ? "banco" : "projeto"}</span>{/if}
              </button>
            {/each}
            {#if !saved.length}<p class="tiny muted pad0">⌘S numa consulta salva aqui.</p>{/if}
          {/if}
        {/if}
        {#if b.session && !b.objects}<p class="tiny muted pad">Lendo objetos…</p>{/if}
        {#each groups.items as g (g.k)}
          <button class="gh" onclick={() => (closedGroups[g.k] = !closedGroups[g.k])}><ChevronDown size={12} class={closedGroups[g.k] ? "rot" : ""} /> {g.label} <span class="tiny muted">{g.list.length}</span></button>
          {#if !closedGroups[g.k]}
            {#each g.list.slice(0, 3000) as o (o.schema + "." + o.name)}
              {@const I = g.icon}
              <button class="obj" title={`${o.schema}.${o.name}`} ondblclick={() => (o.kind === "table" || o.kind === "view") && openTable(o)}
                onclick={() => (o.kind === "table" || o.kind === "view") && openTable(o)} oncontextmenu={(e) => objMenu(e, o)}>
                <I size={13} /><span class="ell">{#if o.schema && o.schema !== groups.defSchema && bank?.engine !== "sqlite" && bank?.engine !== "mysql"}<span class="muted">{o.schema}.</span>{/if}{o.name}</span>
              </button>
            {/each}
          {/if}
        {/each}
      </div>
    </aside>
    <div class="vr" role="separator" aria-orientation="vertical" onpointerdown={(e) => drag(e, "tree")}></div>

    <!-- abas -->
    <section class="work">
      <div class="tabs" role="tablist">
        {#each b.tabs as t (t.id)}
          <div class="tab" class:on={t.id === tab?.id} role="tab" tabindex="0" aria-selected={t.id === tab?.id} onclick={() => (b.active = t.id)} onkeydown={(e) => e.key === "Enter" && (b.active = t.id)}
            ondblclick={() => t.kind === "sql" && renameTab(t)} title={t.kind === "table" ? `${t.table?.schema}.${t.table?.name}` : "Dois cliques renomeia"}>
            {#if t.kind === "table"}<Table2 size={12} />{:else}<Braces size={12} />{/if}
            <span class="ell">{t.title}</span>
            {#if t.running}<span class="spin"></span>{/if}
            <button class="x" title="Fechar" onclick={(e) => { e.stopPropagation(); closeTab(t); }}><X size={11} /></button>
          </div>
        {/each}
        <button class="btn sm ghost icon" title="Nova consulta" onclick={newTab}><Plus size={14} /></button>
      </div>

      {#if tab}
        {#if tab.kind === "sql"}
          <div class="ed" style="height:{edH}px">
            {#key tab.id + ":" + bank?.engine}
              <SqlEditor bind:this={sqlEd} value={tab.sql} engine={bank?.engine || "postgres"} source={sqlSource} onchange={(v) => (tab.sql = v)} onrun={(s, base) => run(s, base)} onsave={() => saveTab(tab)} {errorAt} />
            {/key}
          </div>
          <div class="bar">
            {#if tab.running}
              <button class="btn sm danger" onclick={() => db.cancel(b, tab)}><Square size={12} /> Cancelar</button>
            {:else}
              <button class="btn sm primary" disabled={!b.session} onclick={() => sqlEd?.run(false)} title="Executa o comando onde está o cursor (ou a seleção)"><Play size={12} /> Executar <span class="kbd">⌘↩</span></button>
              <button class="btn sm" disabled={!b.session} onclick={() => sqlEd?.run(true)} title="Executa o script inteiro"><Play size={12} /> Tudo <span class="kbd">⇧⌘↩</span></button>
              <button class="btn sm ghost" disabled={!tab.sql.trim()} onclick={() => saveTab(tab)} title={tab.saved ? "Salvar alterações na consulta" : "Salvar esta consulta"}><BookmarkPlus size={13} /> {tab.saved ? "Salvar" : "Salvar…"} <span class="kbd">⌘S</span></button>
            {/if}
            <span class="grow"></span>
            {#if res?.columns?.length}<button class="btn sm ghost" onclick={() => (png = { cols: res!.columns!.map((_, i) => i), rows: res!.rows!.map((_, i) => i), tab })}><Image size={13} /> Imagem</button>{/if}
          </div>
          <div class="hr" role="separator" aria-orientation="horizontal" onpointerdown={(e) => drag(e, "ed")}></div>
        {:else}
          {@const tt = tab as TableTab}
          <div class="bar tbar">
            <Filter size={13} class="muted" />
            <input class="input mono where" placeholder={bank?.engine === "mongodb" ? "{cidade: 'Recife'}  (filtro · Enter aplica)" : bank?.engine === "redis" ? "padrão das chaves: usuario:1*  (Enter aplica)" : bank?.engine === "firebase" ? (env?.host?.startsWith("https://") ? "orderByChild('cidade').equalTo('Recife')" : "where('cidade', '==', 'Recife')") : "WHERE …  (Enter aplica)"} bind:value={tt.where} onkeydown={(e) => e.key === "Enter" && rerunTable(tt)} />
            {#if tab.running}<button class="btn sm danger" onclick={() => db.cancel(b, tab)}><Square size={12} /> Cancelar</button>
            {:else}<button class="btn sm" onclick={() => rerunTable(tt)}><RefreshCw size={12} /> Atualizar</button>{/if}
            <button class="btn sm ghost" class:on={structure} onclick={() => (structure = !structure)}>Estrutura</button>
            {#if res?.columns?.length}<button class="btn sm ghost" onclick={() => (png = { cols: res!.columns!.map((_, i) => i), rows: res!.rows!.map((_, i) => i), tab })}><Image size={13} /> Imagem</button>{/if}
            {#if !editable && tab.info && tab.table?.kind === "table"}<span class="tiny muted" title="Sem chave primária, não dá para saber qual linha alterar com segurança">somente leitura (sem chave primária)</span>{/if}
          </div>
        {/if}

        <div class="out">
          {#if tab.error}
            <div class="errbox"><TriangleAlert size={15} /><pre>{tab.error.message}</pre></div>
          {/if}
          {#if structure && tab.kind === "table" && tab.info}
            <div class="struct">
              <table>
                <thead><tr><th>Coluna</th><th>Tipo</th><th>Nulo</th><th>Padrão</th><th></th></tr></thead>
                <tbody>{#each tab.info.columns as c (c.name)}<tr><td><b>{c.name}</b></td><td class="mono">{c.type}</td><td>{c.nullable ? "sim" : "não"}</td><td class="mono ell">{c.default ?? ""}</td>
                  <td class="tiny">{c.pk ? "🔑 PK" : ""}{c.identity ? " auto" : ""}</td></tr>{/each}</tbody>
              </table>
              {#if tab.info.indexes.length}<h4>Índices</h4><ul>{#each tab.info.indexes as ix (ix.name)}<li><b>{ix.name}</b> ({ix.columns.join(", ")}){ix.primary ? " · primária" : ix.unique ? " · única" : ""}</li>{/each}</ul>{/if}
              {#if tab.info.fks.length}<h4>Chaves estrangeiras</h4><ul>{#each tab.info.fks as fk (fk.name)}<li>{fk.columns.join(", ")} → <b>{fk.refTable}</b> ({fk.refColumns.join(", ")})</li>{/each}</ul>{/if}
            </div>
          {:else}
            {#if tab.results.filter(r => r.columns?.length).length > 1}
              <div class="sets">
                {#each tab.results as r, i (i)}{#if r.columns?.length}<button class="btn sm" class:on={tab.pick === i} onclick={() => (tab.pick = i)}>Resultado {tab.results.slice(0, i + 1).filter(x => x.columns?.length).length} · {r.rows?.length}</button>{/if}{/each}
              </div>
            {/if}
            {#if affected.length || messages.length}
              <div class="msgs tiny">
                {#each affected as a, i (i)}<div>✓ {a.affected?.toLocaleString("pt-BR")} {a.affected === 1 ? "linha afetada" : "linhas afetadas"} <span class="muted">· {a.statement.slice(0, 90)}</span></div>{/each}
                {#each messages as m, i (i)}<div class="muted">{m}</div>{/each}
              </div>
            {/if}
            {#if res?.columns?.length}
              <div class="gridwrap">
                <ResultGrid columns={res.columns} rows={res.rows || []} engine={bank?.engine || "postgres"} copyFormat={db.data?.prefs.copyFormat || "tsv"}
                  editable={editable} {onapply} {onfk} footer={footer}
                  sort={tab.kind === "table" ? (tab as TableTab).order || null : null} onsort={tab.kind === "table" ? sortBy : undefined}
                  onpng={(cols, rows) => (png = { cols, rows, tab })} {flash} />
              </div>
              {#if res.truncated}<div class="trunc tiny">Mostrando as primeiras {res.rows?.length.toLocaleString("pt-BR")} linhas.
                <button class="link" onclick={() => db.run(b, tab, tab.kind === "table" ? tab.sql.replace(/TOP \(\d+\)|LIMIT \d+|limit\(\d+\)|limitToFirst\(\d+\)/i, (m) => m.replace(/\d+/, "10000")) : tab.sql, { maxRows: 10000 })}>Buscar até 10.000</button></div>{/if}
            {:else if !tab.running && !tab.error && !affected.length && tab.ranAt}
              <p class="tiny muted pad">Executado sem resultado ({tab.ms} ms).</p>
            {:else if !tab.ranAt && !tab.running && tab.kind === "sql"}
              <p class="tiny muted pad hint">⌘↩ executa o comando onde está o cursor (ou o trecho selecionado) · ⇧⌘↩ executa tudo · clique numa tabela à esquerda para abrir os dados</p>
            {/if}
          {/if}
        </div>
      {/if}
    </section>
  </div>
</div>
{/if}

{#if historyOpen}
  <Drawer title="Histórico" subtitle={`${bank?.name || ""} — só neste computador${repo ? " · este projeto" : ""}`} onclose={() => (historyOpen = false)} width={640}>
    <div class="hs"><Search size={13} /><input class="input" placeholder="Buscar no histórico…" bind:value={hq} /></div>
    {#if !history}<p class="muted">Carregando…</p>
    {:else if !history.length}<p class="muted">Nada ainda{db.data && !db.data.prefs.history ? " — o histórico está desligado nos Ajustes de dados" : ""}.</p>
    {:else}
      {#each history.filter(h => !hq || h.sql.toLowerCase().includes(hq.toLowerCase())).slice(0, 300) as h, i (i)}
        <button class="hi" onclick={() => fromHistory(h.sql)}>
          <span class="tiny" class:bad={!h.ok}>{h.ok ? "✓" : "✗"}</span>
          <pre>{h.sql.slice(0, 400)}</pre>
          <span class="tiny muted">{ago(h.at)} · {h.ms} ms · {bank?.envs.find(e => e.id === h.env) ? envName(bank.envs.find(e => e.id === h.env)!) : ""}</span>
        </button>
      {/each}
    {/if}
  </Drawer>
{/if}
{#if editing}
  <BankEditor bank={editing === "new" ? null : editing} onclose={() => (editing = null)} onsaved={() => loadBanks()} />
{/if}
{#if png && bank && (env || isApp)}
  {@const r = png.tab.results[png.tab.pick]}
  <PngDialog columns={png.cols.map(i => r.columns![i])} rows={png.rows.map(ri => png!.cols.map(ci => r.rows![ri][ci]))}
    sql={png.tab.kind === "sql" ? r.statement : png.tab.sql} ms={png.tab.ms} totalRows={r.total ?? r.rows!.length} title={bank.link?.alias || bank.name}
    envKind={env?.kind || "dev"} envLabel={env ? envName(env) : (b.session?.app ? APP_KIND[b.session.app.deviceKind] : "app")} database={b.session?.database || env?.database || ""}
    engineLabel={b.session?.app ? APP_FMT[b.session.app.format] : ENGINE_LABEL[bank.engine]} legacy={!!env?.tls.legacy}
    onclose={() => (png = null)} />
{/if}

<style>
  .center { height: 100%; display: grid; place-items: center; }
  .wb { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .top { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid var(--line); flex: none; min-width: 0; }
  .bsel { width: auto; max-width: 240px; height: 28px; }
  .bname { display: inline-flex; align-items: center; gap: 7px; font-size: 13.5px; white-space: nowrap; }
  .dot { width: 9px; height: 9px; border-radius: 50%; }
  .envs { display: inline-flex; background: var(--surface-2); border-radius: 8px; padding: 2px; gap: 2px; }
  .ek { border: 0; background: transparent; color: var(--muted); font: 600 12px var(--font); padding: 4px 10px; border-radius: 6px; cursor: pointer; }
  .ek.on { background: var(--surface); color: var(--text); box-shadow: 0 1px 2px rgba(0,0,0,.2); }
  .ek.on.prod { background: var(--bad); color: #fff; }
  .ek.on.hml { color: var(--warn); }
  .ek.on.dev { color: var(--good); }
  .conn { min-width: 0; max-width: 40%; }
  .err { color: var(--bad); }
  .lockb { color: var(--good); }
  .agents { color: var(--accent); background: var(--accent-soft); }
  .asel { width: auto; max-width: 230px; height: 28px; }
  .top .on { background: var(--good-soft); color: var(--good); }
  .hidden { display: none; }
  .appbar { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-bottom: 1px solid var(--line); flex: none; flex-wrap: wrap; }
  .appbar .pend { color: var(--warn); font-weight: 650; }
  .prodbar { display: flex; align-items: center; gap: 6px; justify-content: center; padding: 3px; background: var(--bad); color: #fff; font: 700 11px var(--font); letter-spacing: .06em; flex: none; }
  .wb.prod .tabs { box-shadow: inset 0 -2px 0 color-mix(in srgb, var(--bad) 55%, transparent); }
  .txbar { display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--bad-soft); border-bottom: 1px solid var(--bad); font-size: 13px; flex: none; }
  .txbar :global(svg) { color: var(--bad); }
  .main { flex: 1; min-height: 0; display: grid; grid-template-columns: var(--tw) 4px minmax(0, 1fr); }
  .tree { display: flex; flex-direction: column; min-height: 0; border-right: 1px solid var(--line); }
  .tf { display: flex; align-items: center; gap: 6px; padding: 8px; color: var(--muted); }
  .tf .input { height: 27px; }
  .tl { flex: 1; overflow: auto; padding: 0 4px 10px; }
  .gh { display: flex; align-items: center; gap: 5px; width: 100%; border: 0; background: none; color: var(--text-2); font: 650 11.5px var(--font); padding: 6px 6px 4px; cursor: pointer; text-transform: uppercase; letter-spacing: .03em; }
  .gh :global(.rot) { transform: rotate(-90deg); }
  .obj { display: flex; align-items: center; gap: 7px; width: 100%; border: 0; background: none; color: var(--text); font: 12.5px var(--font); padding: 4px 8px 4px 16px; border-radius: 6px; cursor: pointer; text-align: left; min-width: 0; }
  .obj:hover { background: var(--surface-2); }
  .obj :global(svg) { color: var(--muted); flex: none; }
  .vr { cursor: col-resize; }
  .vr:hover { background: var(--accent-soft); }
  .work { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
  .tabs { display: flex; align-items: center; gap: 2px; padding: 4px 6px 0; border-bottom: 1px solid var(--line); overflow-x: auto; flex: none; }
  .tab { display: flex; align-items: center; gap: 6px; padding: 6px 8px 6px 10px; border-radius: 8px 8px 0 0; font-size: 12.5px; color: var(--muted); cursor: pointer; max-width: 200px; flex: none; }
  .tab.on { background: var(--surface-2); color: var(--text); }
  .tab .x { border: 0; background: none; color: inherit; opacity: .5; cursor: pointer; padding: 2px; border-radius: 4px; display: grid; }
  .tab .x:hover { opacity: 1; background: var(--surface-3); }
  .spin { width: 10px; height: 10px; border: 2px solid var(--accent); border-right-color: transparent; border-radius: 50%; animation: sp .8s linear infinite; }
  @keyframes sp { to { transform: rotate(360deg); } }
  .ed { flex: none; min-height: 80px; border-bottom: 1px solid var(--line); }
  .bar { display: flex; align-items: center; gap: 8px; padding: 6px 10px; flex: none; border-bottom: 1px solid var(--line); }
  .tbar .where { height: 28px; flex: 1; font-size: 12.5px; }
  .bar .on { background: var(--accent-soft); color: var(--accent); }
  .hr { height: 4px; margin-top: -4px; cursor: row-resize; flex: none; position: relative; z-index: 2; }
  .hr:hover { background: var(--accent-soft); }
  .out { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .gridwrap { flex: 1; min-height: 0; }
  .errbox { display: flex; gap: 10px; margin: 10px; padding: 10px 12px; border-radius: var(--r-sm); background: var(--bad-soft); color: var(--text); }
  .errbox :global(svg) { color: var(--bad); flex: none; margin-top: 2px; }
  .errbox pre { margin: 0; white-space: pre-wrap; font: 12.5px var(--mono); }
  .sets { display: flex; gap: 6px; padding: 6px 10px; flex: none; flex-wrap: wrap; }
  .msgs { padding: 6px 12px; border-bottom: 1px solid var(--line); display: grid; gap: 2px; max-height: 120px; overflow: auto; flex: none; font-family: var(--mono); }
  .trunc { padding: 4px 12px 8px; color: var(--muted); flex: none; }
  .link { background: none; border: 0; color: var(--accent); cursor: pointer; font: inherit; padding: 0; }
  .pad { padding: 10px 12px; }
  .hint { line-height: 1.6; }
  .struct { overflow: auto; padding: 10px 14px; font-size: 12.5px; }
  .struct table { border-collapse: collapse; width: 100%; }
  .struct th { text-align: left; color: var(--muted); font-weight: 600; padding: 4px 8px; border-bottom: 1px solid var(--line-2); }
  .struct td { padding: 4px 8px; border-bottom: 1px solid var(--line); max-width: 260px; }
  .struct h4 { margin: 14px 0 6px; font-size: 12.5px; }
  .struct ul { margin: 0; padding-left: 18px; display: grid; gap: 3px; }
  .mono { font-family: var(--mono); }
  .gh.sv { display: flex; align-items: center; padding: 0; }
  .ghb { display: flex; align-items: center; gap: 5px; flex: 1; border: 0; background: none; color: var(--text-2); font: 650 11.5px var(--font); padding: 6px 6px 4px; cursor: pointer; text-transform: uppercase; letter-spacing: .03em; text-align: left; }
  .ghb :global(.rot) { transform: rotate(-90deg); }
  .wh { width: 22px; height: 22px; }
  .sc { margin-left: auto; flex: none; }
  .pad0 { padding: 2px 16px 6px; margin: 0; }
  .hs { display: flex; align-items: center; gap: 8px; color: var(--muted); margin-bottom: 10px; }
  .hi { display: grid; grid-template-columns: 16px 1fr; gap: 2px 8px; width: 100%; text-align: left; border: 0; background: none; color: var(--text); padding: 8px; border-radius: 8px; cursor: pointer; }
  .hi:hover { background: var(--surface-2); }
  .hi pre { margin: 0; font: 12px var(--mono); white-space: pre-wrap; max-height: 80px; overflow: hidden; }
  .hi .tiny.muted { grid-column: 2; }
  .bad { color: var(--bad); }
</style>
