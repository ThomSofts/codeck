<script lang="ts">
  // Dados: os bancos cadastrados e quem usa cada um. Duas visões da mesma informação — por banco (cartões com os
  // ambientes, o teste de conexão, os projetos e a segurança) e por projeto (com os bancos dele) — e a bancada de cada
  // banco (#/data/<id>).
  import { Activity, ArrowLeft, ArrowRight, Bot, Database, Download, FolderGit2, Link2, Lock, Plus, Search, Settings2, ShieldAlert, ShieldCheck, SlidersHorizontal } from "@lucide/svelte";
  import { onMount } from "svelte";
  import { get, post } from "../lib/api";
  import { db, ENGINE_LABEL, envName, type DbBank, type DbEnv, type Engine } from "../lib/db.svelte";
  import { repos } from "../lib/repos.svelte";
  import { go, router } from "../lib/router.svelte";
  import { ui } from "../lib/ui.svelte";
  import BankEditor from "../components/db/BankEditor.svelte";
  import ImportDialog from "../components/db/ImportDialog.svelte";
  import DbWorkbench from "../components/db/DbWorkbench.svelte";
  import EngineMark from "../components/db/EngineMark.svelte";
  import Drawer from "../components/Drawer.svelte";
  import Empty from "../components/Empty.svelte";
  import Page from "../components/Page.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Switch from "../components/Switch.svelte";

  let view = $state<"banks" | "projects">((localStorage.getItem("codeck.db.view") as any) || "banks");
  let q = $state("");
  let editing = $state<DbBank | "new" | null>(null);
  let prefsOpen = $state(false);
  let importing = $state(false);
  let picked = $state<Set<string>>(new Set());
  let closed = $state<Record<string, boolean>>({});

  onMount(() => { db.load(); if (!repos.loaded) repos.load(false); });
  $effect(() => localStorage.setItem("codeck.db.view", view));

  const openBank = $derived(router.param ? db.bank(router.param) : null);
  const banks = $derived((db.data?.banks || []).filter(b => !q || [b.name, b.folder, ...b.envs.map(e => e.host + " " + e.database)].join(" ").toLowerCase().includes(q.toLowerCase())));
  const folders = $derived.by(() => {
    const m = new Map<string, DbBank[]>();
    for (const b of banks) { const f = b.folder || ""; if (!m.has(f)) m.set(f, []); m.get(f)!.push(b); }
    return [...m.entries()].sort(([a], [c]) => (a === "" ? 1 : c === "" ? -1 : a.localeCompare(c)));
  });
  const projects = $derived(repos.local.filter(r => r.exists && !/[\\/]\.worktrees[\\/]/.test(r.path)));
  const banksOf = (repo: string) => (db.data?.banks || []).filter(b => b.projects.some(p => p.repo === repo));
  const projRows = $derived(projects.filter(r => !q || r.name.toLowerCase().includes(q.toLowerCase()) || banksOf(r.id).some(b => b.name.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => (banksOf(b.id).length ? 1 : 0) - (banksOf(a.id).length ? 1 : 0) || a.name.localeCompare(b.name)));

  async function toggleLink(repo: string, bank: DbBank, on: boolean) {
    try { db.set(await post("db/links", { bank: bank.id, add: on ? [repo] : [], remove: on ? [] : [repo] })); db.project = {}; } catch (e) { ui.error(e); }
  }
  function bankMenu(e: MouseEvent, repo: string) {
    ui.contextMenu(e, [
      { heading: "Bancos deste projeto" },
      ...(db.data?.banks || []).map(b => {
        const on = b.projects.some(p => p.repo === repo);
        return { label: `${on ? "✓ " : "   "}${b.folder ? b.folder + " · " : ""}${b.name}`, onclick: () => toggleLink(repo, b, !on) };
      }),
      ...(db.data?.banks.length ? [] : [{ label: "Nenhum banco cadastrado", disabled: true }]),
    ]);
  }
  function bulkMenu(e: MouseEvent) {
    const ids = [...picked];
    ui.contextMenu(e, [
      { heading: `Vincular ${ids.length} projeto${ids.length === 1 ? "" : "s"} a…` },
      ...(db.data?.banks || []).map(b => ({ label: `${b.folder ? b.folder + " · " : ""}${b.name}`, onclick: async () => {
        try { db.set(await post("db/links", { bank: b.id, add: ids })); db.project = {}; ui.toast(`${ids.length} projeto(s) vinculado(s) a ${b.name}`); picked = new Set(); } catch (err) { ui.error(err); }
      } })),
      { separator: true },
      { heading: "Desvincular de…" },
      ...(db.data?.banks || []).filter(b => b.projects.some(p => ids.includes(p.repo))).map(b => ({ label: b.name, danger: true, onclick: async () => {
        try { db.set(await post("db/links", { bank: b.id, remove: ids })); db.project = {}; picked = new Set(); } catch (err) { ui.error(err); }
      } })),
    ]);
  }
  // ------------------------------------------------------------ números do topo, conexões abertas e o teste
  const all = $derived(db.data?.banks || []);
  const engines = $derived([...new Set(all.map(b => b.engine))]);
  const prodCount = $derived(all.reduce((n, b) => n + b.envs.filter(e => e.kind === "prod").length, 0));
  const linked = $derived(new Set(all.flatMap(b => b.projects.map(p => p.repo))).size);
  const open = $derived(new Set(Object.values(db.benches).filter(x => x.session).map(x => x.bank)));
  const health = (b: DbBank, e: DbEnv) => db.health[`${b.id}:${e.id}`];
  const plugged = (e: Engine) => !!db.plugin(e)?.installed;
  async function testBank(b: DbBank) { await Promise.all(b.envs.map(e => db.ping(b.id, e.id))); }
  let testing = $state(false);
  async function testAll() {
    testing = true;
    const jobs = all.filter(b => plugged(b.engine)).flatMap(b => b.envs.map(e => () => db.ping(b.id, e.id)));
    const run = async () => { while (jobs.length) await jobs.shift()!(); };
    try { await Promise.all([run(), run(), run()]); } finally { testing = false; }
    const bad = all.flatMap(b => b.envs.filter(e => health(b, e) && !health(b, e)!.ok)).length;
    ui.toast(bad ? `${bad} ambiente(s) com problema` : "Todos os ambientes responderam", bad ? "error" : "ok");
  }
  /** abre a bancada do banco já no ambiente escolhido */
  function openEnv(b: DbBank, e: DbEnv) {
    const bn = db.bench("b:" + b.id, { bank: b.id });
    if (bn.env !== e.id) { bn.env = e.id; if (bn.session) db.connect(bn); }
    go("/data/" + b.id);
  }
  const hostOf = (e?: DbEnv) => (!e ? "" : e.file ? e.file.replace(/^\/Users\/[^/]+/, "~") : `${e.host}${e.port ? ":" + e.port : ""}`);
  const projName = (id: string) => repos.byId(id)?.name || id.split(/[\\/]/).pop() || id;

  const prefs = $derived(db.data?.prefs);
  let published = $state<{ version: string; engines: Record<string, { update: boolean }> } | null>(null);
  $effect(() => { if (prefsOpen) get("db/plugins/published").then(r => (published = r)).catch(() => (published = null)); });
  async function setPref(p: any) { try { db.set(await post("db/prefs", p, { quiet: true })); } catch (e) { ui.error(e); } }
</script>

{#if openBank}
  <section class="bench">
    <header class="bh0">
      <button class="btn sm ghost" onclick={() => go("/data")}><ArrowLeft size={14} /> Bancos</button>
      <span class="tiny muted">{openBank.folder ? openBank.folder + " · " : ""}{ENGINE_LABEL[openBank.engine]}</span>
    </header>
    <div class="bb">{#key openBank.id}<DbWorkbench bankId={openBank.id} />{/key}</div>
  </section>
{:else}
<Page title="Dados" sub="Bancos de dados dos seus projetos — senhas no cofre do sistema, produção travada por padrão">
  {#snippet icon()}<Database size={22} />{/snippet}
  {#snippet actions()}
    <Segmented size="sm" bind:value={view} options={[{ value: "banks", label: "Bancos", count: db.data?.banks.length }, { value: "projects", label: "Projetos" }]} />
    <button class="btn sm ghost icon" title="Ajustes de dados" onclick={() => (prefsOpen = true)}><SlidersHorizontal size={15} /></button>
    <button class="btn sm" title="Trazer conexões do DBeaver, Tabularis e Beekeeper" onclick={() => (importing = true)}><Download size={14} /> Importar</button>
    <button class="btn sm primary" onclick={() => (editing = "new")}><Plus size={14} /> Novo banco</button>
  {/snippet}
  <div class="search"><Search size={14} /><input placeholder={view === "banks" ? "Buscar banco, pasta, servidor…" : "Buscar projeto ou banco…"} bind:value={q} /></div>

  {#if !db.data}
    <p class="muted">Carregando…</p>
  {:else if view === "banks"}
    {#if !db.data.banks.length}
      <div class="hero-empty">
        <div class="marks">{#each ["sqlserver", "postgres", "mysql", "sqlite", "libsql", "mongodb", "firebase", "redis"] as e, i (e)}<span style="--d:{i * 60}ms"><EngineMark engine={e as Engine} size={40} /></span>{/each}</div>
        <h2>Seus bancos, no mesmo lugar do código</h2>
        <p class="muted">SQL Server (inclusive o antigo), PostgreSQL, MySQL/MariaDB, SQLite, libSQL, MongoDB, Firebase e Redis. Senhas no cofre do sistema,
          produção travada por padrão e cada banco ligado aos projetos que o usam — a aba Banco aparece neles.</p>
        <div class="he-acts">
          <button class="btn primary" onclick={() => (editing = "new")}><Plus size={15} /> Novo banco</button>
          <button class="btn" onclick={() => (importing = true)}><Download size={15} /> Importar do DBeaver / Tabularis / Beekeeper</button>
        </div>
      </div>
    {:else}
      <div class="kpis">
        <div class="kpi"><Database size={16} /><b>{all.length}</b><span>{all.length === 1 ? "banco" : "bancos"}</span></div>
        <div class="kpi"><span class="mini">{#each engines.slice(0, 5) as e (e)}<EngineMark engine={e} size={18} />{/each}</span><b>{engines.length}</b><span>{engines.length === 1 ? "tipo" : "tipos"}</span></div>
        <div class="kpi prod"><Lock size={16} /><b>{prodCount}</b><span>{prodCount === 1 ? "produção (travada)" : "produções (travadas)"}</span></div>
        <div class="kpi"><FolderGit2 size={16} /><b>{linked}</b><span>{linked === 1 ? "projeto ligado" : "projetos ligados"}</span></div>
        <div class="kpi live"><span class="ld" class:on={open.size > 0}></span><b>{open.size}</b><span>{open.size === 1 ? "conectado agora" : "conectados agora"}</span></div>
        <span class="grow"></span>
        <button class="btn sm" disabled={testing} title="Abre e fecha uma conexão em cada ambiente: mostra se responde, em quanto tempo e a versão" onclick={testAll}>
          <Activity size={14} class={testing ? "pulse" : ""} /> {testing ? "Testando…" : "Testar todos"}</button>
      </div>
    {/if}
    <div class="list">
      {#each folders as [folder, items] (folder)}
        {#if folder || folders.length > 1}
          <button class="fh" onclick={() => (closed[folder] = !closed[folder])}><span class="chev" class:shut={closed[folder]}>▾</span> {folder || "Sem pasta"} <span class="fc">{items.length}</span></button>
        {/if}
        {#if !closed[folder]}
          <div class="cards">
          {#each items as b, i (b.id)}
            {@const first = b.envs[0]}
            <div class="bc" class:live={open.has(b.id)} style="--bc:{b.color}; --d:{Math.min(i, 12) * 35}ms" role="button" tabindex="0"
              onclick={() => go("/data/" + b.id)} onkeydown={(e) => e.key === "Enter" && go("/data/" + b.id)}>
              <div class="bh">
                <EngineMark engine={b.engine} size={40} />
                <div class="bn">
                  <b class="ell">{b.name}</b>
                  <span class="tiny muted ell">{ENGINE_LABEL[b.engine]}{first?.database ? " · " + first.database : ""}</span>
                </div>
                {#if open.has(b.id)}<span class="pill good conn"><span class="ld on"></span> conectado</span>{/if}
                <button class="btn sm ghost icon" title="Configurar" onclick={(e) => { e.stopPropagation(); editing = b; }}><Settings2 size={14} /></button>
              </div>
              {#if hostOf(first)}<div class="host mono tiny ell" title={hostOf(first)}>{hostOf(first)}</div>{/if}
              {#if b.notes}<p class="notes tiny">{b.notes}</p>{/if}
              <div class="envs">
                {#each b.envs as e (e.id)}
                  {@const h = health(b, e)}
                  <div class="env {e.kind}" role="button" tabindex="0" title={`Abrir ${envName(e)}`} onclick={(ev) => { ev.stopPropagation(); openEnv(b, e); }} onkeydown={(ev) => { if (ev.key === "Enter") { ev.stopPropagation(); openEnv(b, e); } }}>
                    <span class="ek">{envName(e)}</span>
                    <span class="hs" class:ok={h?.ok} class:bad={h && !h.ok} class:busy={h?.busy}></span>
                    <span class="hv tiny ell">
                      {#if h?.busy}testando…{:else if h?.ok}{h.ms} ms · {h.server || "ok"}{:else if h}<span class="err">{h.error}</span>{:else}<span class="faint">{e.readOnly || e.kind === "prod" ? "somente leitura" : "não testado"}</span>{/if}
                    </span>
                    {#if b.engine === "sqlite"}<span></span>{:else if e.tls.mode === "off"}<span class="sec warn" title="sem criptografia"><ShieldAlert size={12} /></span>{:else if e.tls.rc4 || e.tls.legacy}<span class="sec warn" title={e.tls.rc4 ? "servidor antigo: TLS 1.0 com RC4 (compatibilidade)" : "aceita TLS 1.0/1.1 (servidor antigo)"}><ShieldAlert size={12} /><small>{e.tls.rc4 ? "RC4" : "legado"}</small></span>
                    {:else}<span class="sec" title={e.tls.mode === "pin" ? "TLS com certificado fixado" : "TLS verificado"}><ShieldCheck size={12} /></span>{/if}
                    {#if e.ssh}<span class="tag" title="por túnel SSH">SSH</span>{/if}
                    <ArrowRight size={13} class="go" />
                  </div>
                {/each}
              </div>
              <div class="bf">
                <span class="projs" title={b.projects.map(p => projName(p.repo)).join(", ")}>
                  <FolderGit2 size={12} />
                  {#if b.projects.length}{#each b.projects.slice(0, 3) as p (p.repo)}<span class="pj ell">{p.alias || projName(p.repo)}</span>{/each}{#if b.projects.length > 3}<span class="pj more">+{b.projects.length - 3}</span>{/if}
                  {:else}<span class="faint">nenhum projeto</span>{/if}
                </span>
                {#if b.projects.some(p => p.agents)}<span class="ag" title="Agentes de IA de algum projeto consultam este banco (MCP)"><Bot size={12} /></span>{/if}
                {#if !plugged(b.engine)}<button class="btn sm ghost" onclick={(e) => { e.stopPropagation(); db.installPlugin(b.engine); }}>Instalar plugin</button>
                {:else}<button class="btn sm ghost" title="Testar a conexão de cada ambiente" disabled={b.envs.some(e => health(b, e)?.busy)} onclick={(e) => { e.stopPropagation(); testBank(b); }}><Activity size={12} /> Testar</button>{/if}
              </div>
            </div>
          {/each}
          </div>
        {/if}
      {/each}
      {#if q && !banks.length}<p class="muted">Nenhum banco com “{q}”.</p>{/if}
    </div>
  {:else}
    <div class="ptools">
      <span class="tiny muted">{picked.size ? `${picked.size} selecionado(s)` : "Marque projetos para vincular vários de uma vez"}</span>
      <span class="grow"></span>
      {#if picked.size}<button class="btn sm" onclick={bulkMenu}><Link2 size={13} /> Vincular a…</button><button class="btn sm ghost" onclick={() => (picked = new Set())}>Limpar</button>{/if}
    </div>
    <div class="list">
      {#each projRows.slice(0, 600) as r (r.id)}
        {@const bs = banksOf(r.id)}
        <div class="prow">
          <input type="checkbox" checked={picked.has(r.id)} onchange={(e) => { const s = new Set(picked); if ((e.target as HTMLInputElement).checked) s.add(r.id); else s.delete(r.id); picked = s; }} />
          <div class="bn"><b class="ell">{r.name}</b><span class="tiny muted ell">{r.path.replace(/^\/Users\/[^/]+/, "~")}</span></div>
          <span class="chips">{#each bs as b (b.id)}<button class="chip" style="--c:{b.color}" title="Abrir {b.name} · {ENGINE_LABEL[b.engine]}" onclick={() => go("/data/" + b.id)}><EngineMark engine={b.engine} size={16} />{b.name}</button>{/each}
            {#if !bs.length}<span class="tiny faint">sem banco</span>{/if}</span>
          <button class="btn sm ghost" onclick={(e) => bankMenu(e, r.id)}><Database size={13} /> Bancos</button>
        </div>
      {/each}
    </div>
  {/if}
</Page>
{/if}

{#if importing}<ImportDialog onclose={() => (importing = false)} />{/if}
{#if editing}<BankEditor bank={editing === "new" ? null : editing} onclose={() => (editing = null)} />{/if}

{#if prefsOpen && prefs}
  <Drawer title="Ajustes de dados" onclose={() => (prefsOpen = false)} width={520}>
    <div class="prefs">
      <label class="label">Formato do ⌘C na grade
        <select class="select" value={prefs.copyFormat} onchange={(e) => setPref({ copyFormat: (e.target as HTMLSelectElement).value })}>
          <option value="tsv">Texto (cola no Excel)</option><option value="json">JSON</option><option value="csv">CSV</option><option value="markdown">Tabela Markdown</option><option value="insert">INSERT</option>
        </select></label>
      <label class="label">Linhas por consulta (o resto é contado, não baixado)
        <input class="input" type="number" min="10" max="100000" value={prefs.maxRows} onchange={(e) => setPref({ maxRows: Number((e.target as HTMLInputElement).value) })} /></label>
      <label class="label">Tempo limite da consulta (segundos, 0 = sem limite)
        <input class="input" type="number" min="0" max="3600" value={prefs.timeoutSec} onchange={(e) => setPref({ timeoutSec: Number((e.target as HTMLInputElement).value) })} /></label>
      <div class="sect">Imagem do resultado</div>
      <Segmented size="sm" value={prefs.png.dest} onchange={(v) => setPref({ png: { ...prefs.png, dest: v } })}
        options={[{ value: "clipboard", label: "Copiar" }, { value: "file", label: "Salvar arquivo" }, { value: "both", label: "Os dois" }]} />
      <label class="label">Pasta das imagens <input class="input" value={prefs.png.dir} placeholder="~/Downloads" onchange={(e) => setPref({ png: { ...prefs.png, dir: (e.target as HTMLInputElement).value } })} /></label>
      <div class="sect">Consultas salvas dos projetos</div>
      <Segmented size="sm" value={prefs.queries} onchange={(v) => setPref({ queries: v })}
        options={[{ value: "local", label: "Neste computador" }, { value: "repo", label: "No repositório (.codeck-db)" }]} />
      <p class="tiny muted">Padrão para todos os projetos; cada um pode trocar na própria aba Banco. As consultas de um banco (para todos os projetos dele) ficam sempre neste computador.</p>
      <div class="sect">Histórico (só neste computador)</div>
      <Switch checked={prefs.history} label="Guardar as consultas que rodei" onchange={(v) => setPref({ history: v })} />
      <Switch checked={prefs.historyProd} label="Inclusive em produção" disabled={!prefs.history} onchange={(v) => setPref({ historyProd: v })} />
      <div class="sect">Plugins</div>
      <p class="tiny muted">Cada banco tem o seu plugin: instale só os que usar. O download vem da ThomSoft e é conferido pela assinatura antes de rodar.</p>
      {#each db.data?.plugins || [] as p (p.engine)}
        <div class="plug">
          <b>{p.label}</b>
          {#if p.installed}<span class="pill good">{p.origin === "repo" ? "do código" : p.origin === "bundled" ? "junto do app" : `instalado${p.version ? " · " + p.version : ""}`}</span>{/if}
          <span class="grow"></span>
          {#if !p.installed}<button class="btn sm primary" onclick={() => db.installPlugin(p.engine)}>Instalar</button>
          {:else if p.origin === "installed"}
            {#if published?.engines[p.engine]?.update}<button class="btn sm" onclick={() => db.installPlugin(p.engine)}>Atualizar</button>{/if}
            <button class="btn sm ghost" onclick={() => db.uninstallPlugin(p.engine)}>Remover</button>
          {/if}
        </div>
      {/each}
    </div>
  </Drawer>
{/if}

<style>
  .bench { height: 100%; display: flex; flex-direction: column; min-height: 0; }
  .bh0 { display: flex; align-items: center; gap: 10px; padding: 10px 14px 6px; flex: none; }
  .bb { flex: 1; min-height: 0; margin: 0 14px 14px; border: 1px solid var(--line); border-radius: var(--r-lg); background: var(--surface); overflow: hidden; box-shadow: var(--shadow-1); }
  .search { display: flex; align-items: center; gap: 8px; color: var(--muted); margin-bottom: 14px; max-width: 520px; height: 34px; padding: 0 10px; border-radius: 10px;
    border: 1px solid var(--line); background: var(--surface); transition: border-color var(--t-fast), box-shadow var(--t-fast); flex: none; }
  .search:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .search input { flex: 1; border: 0; outline: none; background: none; color: var(--text); font: 13px var(--font); }
  .list { display: flex; flex-direction: column; gap: 6px; overflow: auto; min-height: 0; padding-bottom: 20px; }
  /* números do topo */
  .kpis { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 14px; flex: none; }
  .kpi { display: flex; align-items: center; gap: 8px; padding: 8px 14px; border-radius: 12px; background: var(--surface); border: 1px solid var(--line); }
  .kpi :global(svg) { color: var(--accent); }
  .kpi b { font-size: 17px; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
  .kpi span { font-size: 12px; color: var(--muted); }
  .kpi.prod :global(svg) { color: var(--bad); }
  .kpi .mini { display: flex; }
  .kpi .mini :global(.em) { margin-left: -5px; box-shadow: 0 0 0 2px var(--surface); }
  .kpi .mini :global(.em:first-child) { margin-left: 0; }
  .ld { width: 8px; height: 8px; border-radius: 50%; background: var(--faint); display: inline-block; flex: none; }
  .ld.on { background: var(--good); box-shadow: 0 0 0 3px color-mix(in srgb, var(--good) 22%, transparent); animation: beat 2.4s ease-in-out infinite; }
  @keyframes beat { 50% { opacity: .55; } }
  :global(.pulse) { animation: beat 1s ease-in-out infinite; }
  /* pastas */
  .fh { display: flex; align-items: center; gap: 6px; border: 0; background: none; color: var(--text-2); font: 700 11.5px var(--font); text-align: left; padding: 12px 2px 4px; cursor: pointer; text-transform: uppercase; letter-spacing: .06em; }
  .chev { display: inline-block; transition: transform var(--t-fast); }
  .chev.shut { transform: rotate(-90deg); }
  .fc { font: 650 10.5px var(--font); padding: 1px 7px; border-radius: 99px; background: var(--surface-3); color: var(--text-2); letter-spacing: 0; }
  /* cartões */
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 12px; }
  .bc { position: relative; display: flex; flex-direction: column; gap: 10px; padding: 14px 14px 12px 16px; border-radius: 16px; cursor: pointer; overflow: hidden;
    border: 1px solid var(--line); background: linear-gradient(165deg, color-mix(in srgb, var(--bc) 7%, var(--surface)), var(--surface) 46%);
    box-shadow: var(--shadow-1); animation: rise .38s var(--ease-out) both; animation-delay: var(--d);
    transition: transform var(--t-fast), border-color var(--t-fast), box-shadow var(--t-fast); }
  @keyframes rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
  .bc::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--bc); }
  .bc:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--bc) 50%, var(--line)); box-shadow: 0 18px 36px -22px color-mix(in srgb, var(--bc) 70%, #000); }
  .bc.live { border-color: color-mix(in srgb, var(--good) 35%, var(--line)); }
  .bh { display: flex; align-items: center; gap: 12px; min-width: 0; }
  .bn { display: flex; flex-direction: column; min-width: 0; gap: 2px; flex: 1; }
  .bn b { font-size: 15px; letter-spacing: -0.01em; }
  .conn { display: inline-flex; align-items: center; gap: 5px; flex: none; }
  .host { color: var(--text-2); padding: 5px 9px; border-radius: 8px; background: var(--bg-2); border: 1px solid var(--line); }
  .notes { margin: 0; color: var(--muted); line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .envs { display: grid; gap: 4px; }
  .env { display: grid; grid-template-columns: 58px 10px minmax(0, 1fr) auto auto 14px; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 9px;
    background: var(--surface-2); border: 1px solid transparent; transition: border-color var(--t-fast), background var(--t-fast); }
  .env:hover { border-color: var(--line-2); background: var(--surface-3); }
  .env :global(.go) { color: var(--faint); opacity: 0; transition: opacity var(--t-fast), transform var(--t-fast); }
  .env:hover :global(.go) { opacity: 1; transform: translateX(2px); }
  .ek { font: 700 11px var(--font); text-transform: uppercase; letter-spacing: .04em; padding: 2px 0; border-radius: 6px; text-align: center; color: var(--good); background: var(--good-soft); }
  .env.hml .ek { color: var(--warn); background: var(--warn-soft); }
  .env.prod .ek { color: #fff; background: var(--bad); }
  .hs { width: 8px; height: 8px; border-radius: 50%; background: var(--line-3); }
  .hs.ok { background: var(--good); box-shadow: 0 0 0 3px color-mix(in srgb, var(--good) 20%, transparent); }
  .hs.bad { background: var(--bad); box-shadow: 0 0 0 3px var(--bad-soft); }
  .hs.busy { background: var(--warn); animation: beat .8s ease-in-out infinite; }
  .hv { color: var(--text-2); font-variant-numeric: tabular-nums; }
  .err { color: var(--bad); }
  .faint { color: var(--faint); }
  .sec { display: inline-flex; align-items: center; gap: 3px; color: var(--good); }
  .sec small { font: 700 9.5px var(--font); letter-spacing: .03em; }
  .sec.warn { color: var(--warn); }
  .tag { font: 700 9.5px var(--font); padding: 1px 5px; border-radius: 5px; background: var(--surface); color: var(--text-2); border: 1px solid var(--line-2); }
  .bf { display: flex; align-items: center; gap: 8px; padding-top: 10px; border-top: 1px dashed var(--line-2); min-width: 0; }
  .projs { display: flex; align-items: center; gap: 5px; min-width: 0; flex: 1; color: var(--muted); font-size: 12px; }
  .projs :global(svg) { flex: none; }
  .pj { padding: 1px 8px; border-radius: 99px; background: var(--surface-2); border: 1px solid var(--line); color: var(--text-2); max-width: 120px; font-size: 11.5px; }
  .pj.more { flex: none; }
  .ag { display: grid; place-items: center; width: 22px; height: 22px; border-radius: 7px; background: var(--accent-soft); color: var(--accent); flex: none; }
  /* vazio */
  .hero-empty { display: grid; justify-items: center; text-align: center; gap: 12px; padding: 48px 20px 30px; }
  .hero-empty h2 { margin: 6px 0 0; font-size: 22px; letter-spacing: -0.02em; }
  .hero-empty p { max-width: 620px; margin: 0; line-height: 1.5; }
  .marks { display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; }
  .marks span { animation: float 3.6s ease-in-out infinite, rise .5s var(--ease-out) both; animation-delay: var(--d), var(--d); }
  @keyframes float { 50% { transform: translateY(-5px); } }
  .he-acts { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; margin-top: 6px; }
  /* por projeto */
  .prow { display: grid; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 12px; background: var(--surface); border: 1px solid var(--line);
    grid-template-columns: auto minmax(0, 1fr) minmax(0, 1.4fr) auto; transition: border-color var(--t-fast); }
  .prow:hover { border-color: var(--line-3); }
  .chips { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
  .chip { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line-2); background: var(--surface-2); color: var(--text); font: 12px var(--font); padding: 2px 9px 2px 3px; border-radius: 999px; cursor: pointer; }
  .chip:hover { border-color: var(--c); }
  .ptools { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .prefs { display: flex; flex-direction: column; gap: 14px; }
  .sect { font-weight: 680; font-size: 13px; margin-top: 6px; }
  .plug { display: flex; align-items: center; gap: 8px; font-size: 13px; }
  .mono { font-family: var(--mono); }
  .grow { flex: 1; }
  @media (prefers-reduced-motion: reduce) { .bc, .marks span, .ld.on { animation: none; } }
  @media (max-width: 860px) { .cards { grid-template-columns: 1fr; } .kpi span { display: none; } }
</style>
