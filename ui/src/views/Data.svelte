<script lang="ts">
  // Dados: os bancos cadastrados e quem usa cada um. Duas visões da mesma informação — por banco (com a lista de
  // projetos) e por projeto (com os bancos dele) — e a bancada de cada banco (#/data/<id>).
  import { ArrowLeft, Database, Download, FolderGit2, Link2, Plus, Search, Settings2, SlidersHorizontal } from "@lucide/svelte";
  import { onMount } from "svelte";
  import { get, post } from "../lib/api";
  import { db, ENGINE_LABEL, ENGINE_SHORT, envName, type DbBank } from "../lib/db.svelte";
  import { repos } from "../lib/repos.svelte";
  import { go, router } from "../lib/router.svelte";
  import { ui } from "../lib/ui.svelte";
  import BankEditor from "../components/db/BankEditor.svelte";
  import ImportDialog from "../components/db/ImportDialog.svelte";
  import DbWorkbench from "../components/db/DbWorkbench.svelte";
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
  const prefs = $derived(db.data?.prefs);
  let published = $state<{ version: string; engines: Record<string, { update: boolean }> } | null>(null);
  $effect(() => { if (prefsOpen) get("db/plugins/published").then(r => (published = r)).catch(() => (published = null)); });
  async function setPref(p: any) { try { db.set(await post("db/prefs", p, { quiet: true })); } catch (e) { ui.error(e); } }
</script>

{#if openBank}
  <section class="bench">
    <header class="bh">
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
  <div class="search"><Search size={14} /><input class="input" placeholder={view === "banks" ? "Buscar banco, pasta, servidor…" : "Buscar projeto ou banco…"} bind:value={q} /></div>

  {#if !db.data}
    <p class="muted">Carregando…</p>
  {:else if view === "banks"}
    {#if !db.data.banks.length}
      <Empty title="Nenhum banco ainda" text="Cadastre um banco (SQL Server, PostgreSQL, MySQL/MariaDB ou SQLite) e marque os projetos que o usam. A aba Banco aparece nesses projetos.">
        <button class="btn primary" onclick={() => (editing = "new")}><Plus size={15} /> Novo banco</button>
        <button class="btn" onclick={() => (importing = true)}><Download size={15} /> Importar do DBeaver / Tabularis</button>
      </Empty>
    {/if}
    <div class="list">
      {#each folders as [folder, items] (folder)}
        {#if folder || folders.length > 1}
          <button class="fh" onclick={() => (closed[folder] = !closed[folder])}>{closed[folder] ? "▸" : "▾"} {folder || "Sem pasta"} <span class="tiny muted">{items.length}</span></button>
        {/if}
        {#if !closed[folder]}
          {#each items as b (b.id)}
            <div class="brow" role="button" tabindex="0" onclick={() => go("/data/" + b.id)} onkeydown={(e) => e.key === "Enter" && go("/data/" + b.id)}>
              <span class="dot" style="background:{b.color}"></span>
              <div class="bn"><b class="ell">{b.name}</b><span class="tiny muted ell">{b.envs.map(e => e.host || e.file).filter(Boolean)[0] || ""}{b.envs[0]?.database ? " · " + b.envs[0].database : ""}</span></div>
              <span class="eng tiny">{ENGINE_SHORT[b.engine]}</span>
              <span class="envs">{#each b.envs as e (e.id)}<span class="pill {e.kind === 'prod' ? 'bad' : e.kind === 'hml' ? 'warn' : 'good'}">{envName(e)}</span>{#if e.tls.mode === "off"}<span class="pill neutral" title="sem criptografia">sem TLS</span>{:else if e.tls.rc4}<span class="pill warn" title="servidor antigo: TLS 1.0 com RC4 (compatibilidade)">legado · RC4</span>{:else if e.tls.legacy}<span class="pill warn" title="aceita TLS 1.0/1.1 (servidor antigo)">legado</span>{/if}{/each}</span>
              <span class="np tiny muted" title={b.projects.map(p => repos.byId(p.repo)?.name || p.repo).join(", ")}><FolderGit2 size={12} /> {b.projects.length}</span>
              <button class="btn sm ghost icon" title="Configurar" onclick={(e) => { e.stopPropagation(); editing = b; }}><Settings2 size={14} /></button>
            </div>
          {/each}
        {/if}
      {/each}
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
          <span class="chips">{#each bs as b (b.id)}<button class="chip" style="--c:{b.color}" title="Abrir {b.name}" onclick={() => go("/data/" + b.id)}><span class="dot" style="background:{b.color}"></span>{b.name}</button>{/each}
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
  .bh { display: flex; align-items: center; gap: 10px; padding: 10px 14px 6px; flex: none; }
  .bb { flex: 1; min-height: 0; margin: 0 14px 14px; border: 1px solid var(--line); border-radius: var(--r-lg); background: var(--surface); overflow: hidden; }
  .search { display: flex; align-items: center; gap: 8px; color: var(--muted); margin-bottom: 12px; max-width: 520px; }
  .list { display: flex; flex-direction: column; gap: 4px; overflow: auto; min-height: 0; }
  .fh { border: 0; background: none; color: var(--text-2); font: 680 12px var(--font); text-align: left; padding: 10px 4px 4px; cursor: pointer; text-transform: uppercase; letter-spacing: .03em; }
  .brow, .prow { display: grid; align-items: center; gap: 12px; padding: 10px 12px; border-radius: var(--r); background: var(--surface); border: 1px solid var(--line); }
  .brow { grid-template-columns: auto minmax(0, 1.4fr) 60px minmax(0, 1fr) 50px auto; cursor: pointer; }
  .brow:hover { border-color: var(--line-3); background: var(--surface-2); }
  .prow { grid-template-columns: auto minmax(0, 1fr) minmax(0, 1.4fr) auto; }
  .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .bn { display: flex; flex-direction: column; min-width: 0; gap: 2px; }
  .eng { font-weight: 650; color: var(--text-2); }
  .envs, .chips { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
  .np { display: inline-flex; align-items: center; gap: 4px; }
  .chip { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line-2); background: var(--surface-2); color: var(--text); font: 12px var(--font); padding: 3px 9px; border-radius: 999px; cursor: pointer; }
  .chip .dot { width: 7px; height: 7px; }
  .faint { color: var(--faint); }
  .ptools { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .prefs { display: flex; flex-direction: column; gap: 14px; }
  .sect { font-weight: 680; font-size: 13px; margin-top: 6px; }
  .plug { display: flex; align-items: center; gap: 8px; font-size: 13px; }
  @media (max-width: 860px) { .brow { grid-template-columns: auto minmax(0, 1fr) auto; } .brow .eng, .brow .envs, .brow .np { display: none; } }
</style>
