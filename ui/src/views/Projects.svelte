<script lang="ts">
  // Hub de projetos: todos os repositórios clonados nesta máquina, com busca, filtros, ordem (últimos acessados, mais e
  // menos usados, sessões de IA, último commit…) e agrupamento (por grupo, conta ou pasta). Grupos de projetos são
  // criados aqui (selecionando) ou nas abas; abrir um projeto o coloca nas abas.
  import { ArrowDown, ArrowUp, Check, Code2, FolderGit2, FolderOpen, FolderPlus, Layers, LayoutGrid, List, Pencil, Play, Settings2, Sparkles, Terminal, Trash2, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { get, post } from "../lib/api";
  import { ago } from "../lib/format";
  import { fileManagerName } from "../lib/native";
  import { prefs } from "../lib/prefs.svelte";
  import { repos } from "../lib/repos.svelte";
  import { go } from "../lib/router.svelte";
  import type { LocalRepo } from "../lib/types";
  import { ui } from "../lib/ui.svelte";
  import { work, type Group } from "../lib/work.svelte";
  import Empty from "../components/Empty.svelte";
  import Menu from "../components/Menu.svelte";
  import Page from "../components/Page.svelte";
  import ProviderIcon from "../components/ProviderIcon.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Skeleton from "../components/Skeleton.svelte";
  import Toolbar from "../components/Toolbar.svelte";
  import AgentIcon from "../components/work/AgentIcon.svelte";

  type Stat = { focusS: number; focus30: number; sessions30: number; cost30: number; lastAgent: string | null; lastOpened?: string; opens?: number };
  let stats = $state<Record<string, Stat>>({});
  let q = $state("");
  let filter = $state("all");
  let provider = $state("any");
  let groupFilter = $state("any");
  let selected = $state<string[]>([]);
  const sort = $derived(prefs.get("hub.sort"));
  const groupBy = $derived(prefs.get("hub.group"));
  const view = $derived(prefs.get("hub.view"));

  async function loadStats() { try { stats = (await get<{ stats: Record<string, Stat> }>("ws/hub")).stats; } catch (e) { ui.error(e); } }
  $effect(() => { untrack(() => { loadStats(); repos.load(); }); });

  const isWt = (p: string) => /[\\/]\.worktrees[\\/]/.test(p);
  const home = (p: string) => p.replace(/^\/Users\/[^/]+|^C:\\Users\\[^\\]+/i, "~");
  const all = $derived(repos.local.filter(r => r.exists && !isWt(r.path)));
  const openIds = $derived(new Set(work.projects.map(p => p.id)));
  const agentsOf = (id: string) => work.agents.filter(a => a.project.id === id);
  const st = (id: string): Stat => stats[id] || { focusS: 0, focus30: 0, sessions30: 0, cost30: 0, lastAgent: null };
  const last = (r: LocalRepo) => Math.max(new Date(st(r.id).lastOpened || 0).getTime(), new Date(st(r.id).lastAgent || 0).getTime());

  const list = $derived.by(() => {
    const t = q.trim().toLowerCase();
    let out = all.filter(r => (!t || `${r.name} ${r.path} ${r.slug || ""} ${work.groupOf(r.id)?.name || ""}`.toLowerCase().includes(t))
      && (provider === "any" || (provider === "local" ? !r.provider : r.provider === provider))
      && (groupFilter === "any" || (groupFilter === "none" ? !work.groupOf(r.id) : work.groupOf(r.id)?.id === groupFilter))
      && (filter === "all" || (filter === "open" ? openIds.has(r.id) : filter === "dirty" ? (r.status?.changes || 0) > 0
        : filter === "agents" ? agentsOf(r.id).length > 0 : filter === "unused" ? Date.now() - last(r) > 30 * 864e5 : true)));
    const by: Record<string, (a: LocalRepo, b: LocalRepo) => number> = {
      recent: (a, b) => last(b) - last(a),
      most: (a, b) => st(b.id).focus30 + st(b.id).sessions30 * 600 - (st(a.id).focus30 + st(a.id).sessions30 * 600) || last(b) - last(a),
      least: (a, b) => st(a.id).focus30 + st(a.id).sessions30 * 600 - (st(b.id).focus30 + st(b.id).sessions30 * 600) || last(a) - last(b),
      ai: (a, b) => st(b.id).sessions30 - st(a.id).sessions30 || st(b.id).cost30 - st(a.id).cost30,
      opens: (a, b) => (st(b.id).opens || 0) - (st(a.id).opens || 0),
      commit: (a, b) => new Date(b.lastCommit?.date || 0).getTime() - new Date(a.lastCommit?.date || 0).getTime(),
      name: (a, b) => a.name.localeCompare(b.name),
    };
    return out.sort(by[sort] || by.recent);
  });
  const sections = $derived.by(() => {
    if (groupBy === "none") return [{ key: "all", label: "", color: null as string | null, items: list, group: null as Group | null }];
    const m = new Map<string, { key: string; label: string; color: string | null; items: LocalRepo[]; group: Group | null }>();
    for (const r of list) {
      let key = "", label = "", color: string | null = null, group: Group | null = null;
      if (groupBy === "group") { group = work.groupOf(r.id); key = group?.id || "~"; label = group?.name || "Sem grupo"; color = group?.color || null; }
      else if (groupBy === "account") { key = r.provider ? `${r.provider}:${(r.slug || "").split("/")[0]}` : "~"; label = r.provider ? `${r.provider === "azure" ? "Azure" : "GitHub"} · ${(r.slug || "").split("/")[0]}` : "Sem remoto"; }
      else { key = r.path.replace(/[\\/][^\\/]+$/, ""); label = home(key); }
      if (!m.has(key)) m.set(key, { key, label, color, items: [], group });
      m.get(key)!.items.push(r);
    }
    return [...m.values()].sort((a, b) => (a.key === "~" ? 1 : b.key === "~" ? -1 : groupBy === "group" ? work.groups.findIndex(g => g.id === a.key) - work.groups.findIndex(g => g.id === b.key) : a.label.localeCompare(b.label)));
  });
  const counts = $derived({ all: all.length, open: all.filter(r => openIds.has(r.id)).length, dirty: all.filter(r => (r.status?.changes || 0) > 0).length,
    agents: all.filter(r => agentsOf(r.id).length).length });

  function dur(s: number) {
    if (!s) return "—";
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
    const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    return h >= 100 ? `${h} h` : `${h} h${m ? ` ${String(m).padStart(2, "0")}` : ""}`;
  }
  async function open(r: LocalRepo, ask = false) {
    try {
      const id = await work.open(r.id);
      if (ask) work.focus(id, null); else go("/work/" + id, "soft");
    } catch (e) { ui.error(e); }
  }
  const toggleSel = (id: string) => (selected = selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id]);
  async function groupSelected(gid?: string) {
    if (gid) { for (const id of selected) await work.assignGroup(id, gid); }
    else await work.newGroup(selected);
    selected = [];
  }
  async function openSelected() { for (const id of selected) await work.open(id); const last = selected[selected.length - 1]; selected = []; go("/work/" + last, "soft"); }
  const repoMenu = (r: LocalRepo) => {
    const g = work.groupOf(r.id);
    return [
      { label: openIds.has(r.id) ? "Ir para o projeto" : "Abrir projeto", icon: Play, onclick: () => open(r) },
      { label: "Gerenciar repositório…", icon: Settings2, onclick: () => (ui.repoHub = { localId: r.id }) },
      { separator: true },
      { label: "Abrir no editor", icon: Code2, onclick: () => post("open", { id: r.id, target: "editor" }).catch(ui.error) },
      { label: `Abrir no ${fileManagerName()}`, icon: FolderOpen, onclick: () => post("open", { id: r.id, target: "files" }).catch(ui.error) },
      { label: "Abrir no terminal", icon: Terminal, onclick: () => post("open", { id: r.id, target: "terminal" }).catch(ui.error) },
      { separator: true },
      { heading: "Grupo" },
      { label: "Novo grupo com este projeto…", icon: FolderPlus, onclick: () => work.newGroup([r.id]) },
      ...work.groups.filter(x => x.id !== g?.id).map(x => ({ label: `Mover para “${x.name}”`, icon: Layers, onclick: () => work.assignGroup(r.id, x.id) })),
      ...(g ? [{ label: `Tirar de “${g.name}”`, icon: X, onclick: () => work.assignGroup(r.id, null) }] : []),
    ];
  };
  async function renameGroup(g: Group) {
    const name = await ui.ask({ title: "Renomear grupo", input: { label: "Nome", value: g.name, required: true }, confirm: "Salvar" });
    if (name) work.saveGroup({ id: g.id, name: String(name).trim() });
  }
  const PALETTE = ["#6F8CFF", "#3CCF91", "#F5B84F", "#FF6B7D", "#B07CFF", "#4FC3F7", "#FF8A50", "#9AA4B2"];
</script>

<Page title="Projetos" sub={`${all.length} repositórios clonados · ${counts.open} abertos${work.groups.length ? ` · ${work.groups.length} grupos` : ""}`}>
  {#snippet actions()}
    <button class="btn sm" onclick={() => work.newGroup([])}><FolderPlus size={14} /> Novo grupo</button>
    <button class="btn sm" onclick={() => go("/repos")}><FolderGit2 size={14} /> Repositórios</button>
  {/snippet}

  {#if work.groups.length}
    <div class="groups">
      {#each work.groups as g (g.id)}
        {@const openN = g.repoIds.filter(id => openIds.has(id)).length}
        {@const busy = work.agents.some(a => g.repoIds.includes(a.project.id) && a.session?.status === "working")}
        <div class="gcard" style="--g:{g.color}" class:on={groupFilter === g.id}>
          <button class="gmain" onclick={() => (groupFilter = groupFilter === g.id ? "any" : g.id)} title="Filtrar por este grupo">
            <span class="gdot"></span><b class="ell">{g.name}</b>{#if busy}<span class="live"></span>{/if}
            <span class="tiny muted">{g.repoIds.length} projeto{g.repoIds.length === 1 ? "" : "s"}{openN ? ` · ${openN} aberto${openN === 1 ? "" : "s"}` : ""}</span>
          </button>
          <div class="gact">
            <button class="btn sm ghost" title="Abrir todos" onclick={async () => { await work.openGroup(g.id); const id = g.repoIds.find(x => repos.byId(x)); if (id) go("/work/" + id, "soft"); }}><Play size={13} /></button>
            <Menu items={[
              { label: "Renomear…", icon: Pencil, onclick: () => renameGroup(g) },
              { label: "Trocar a cor", icon: Settings2, onclick: () => work.saveGroup({ id: g.id, color: PALETTE[(PALETTE.indexOf(g.color) + 1) % PALETTE.length] }) },
              { separator: true },
              { label: "Apagar grupo (os projetos ficam)", icon: Trash2, danger: true, onclick: () => work.deleteGroup(g.id) },
            ]} />
          </div>
        </div>
      {/each}
    </div>
  {/if}

  <Toolbar bind:query={q} placeholder="Buscar projeto, pasta ou grupo…">
    {#snippet left()}
      <Segmented size="sm" bind:value={filter} options={[{ value: "all", label: "Todos", count: counts.all }, { value: "open", label: "Abertos", count: counts.open },
        { value: "agents", label: "Com agente", count: counts.agents }, { value: "dirty", label: "Com alterações", count: counts.dirty }, { value: "unused", label: "Parados há 30 d" }]} />
    {/snippet}
  </Toolbar>
  <div class="bar">
    <select class="input sm" bind:value={provider}><option value="any">Qualquer origem</option><option value="github">GitHub</option><option value="azure">Azure DevOps</option><option value="local">Sem remoto</option></select>
    <select class="input sm" bind:value={groupFilter}><option value="any">Todos os grupos</option><option value="none">Sem grupo</option>{#each work.groups as g (g.id)}<option value={g.id}>{g.name}</option>{/each}</select>
    <span class="grow"></span>
    <label class="small muted">Ordenar
      <select class="input sm" value={sort} onchange={(e) => prefs.set("hub.sort", (e.target as HTMLSelectElement).value)}>
        <option value="recent">Últimos acessados</option><option value="most">Mais usados (30 d)</option><option value="least">Menos usados (30 d)</option>
        <option value="ai">Mais sessões de IA</option><option value="opens">Mais vezes aberto</option><option value="commit">Último commit</option><option value="name">Nome</option>
      </select></label>
    <label class="small muted">Agrupar
      <select class="input sm" value={groupBy} onchange={(e) => prefs.set("hub.group", (e.target as HTMLSelectElement).value)}>
        <option value="none">Não agrupar</option><option value="group">Grupo</option><option value="account">Conta / organização</option><option value="folder">Pasta</option>
      </select></label>
    <div class="vt">
      <button class:on={view === "grid"} title="Cartões" onclick={() => prefs.set("hub.view", "grid")}><LayoutGrid size={14} /></button>
      <button class:on={view === "list"} title="Lista" onclick={() => prefs.set("hub.view", "list")}><List size={14} /></button>
    </div>
  </div>

  {#if selected.length}
    <div class="selbar">
      <b>{selected.length} selecionado{selected.length === 1 ? "" : "s"}</b>
      <button class="btn sm primary" onclick={() => groupSelected()}><FolderPlus size={13} /> Criar grupo</button>
      {#each work.groups as g (g.id)}<button class="btn sm" onclick={() => groupSelected(g.id)}><span class="dot" style="background:{g.color}"></span> {g.name}</button>{/each}
      <button class="btn sm" onclick={openSelected}><Play size={13} /> Abrir</button>
      <span class="grow"></span>
      <button class="btn sm ghost" onclick={() => (selected = [])}>Limpar</button>
    </div>
  {/if}

  <div class="scroll">
    {#if !repos.loaded}<Skeleton rows={8} />
    {:else if !list.length}
      <Empty title={q || filter !== "all" || provider !== "any" || groupFilter !== "any" ? "Nada com esses filtros" : "Nenhum repositório clonado ainda"}
        text={all.length ? "" : "Configure as pastas base das contas em Repositórios — os clones dentro delas aparecem aqui sozinhos."}>
        {#if !all.length}<button class="btn primary" onclick={() => go("/repos")}><FolderGit2 size={14} /> Ir para Repositórios</button>{/if}
      </Empty>
    {:else}
      {#each sections as sec (sec.key)}
        {#if sec.label}<h3 class="sec">{#if sec.color}<span class="dot" style="background:{sec.color}"></span>{/if}{sec.label}<span class="n">{sec.items.length}</span>
          {#if sec.group}<button class="btn sm ghost" onclick={() => work.openGroup(sec.group!.id)}><Play size={12} /> Abrir todos</button>{/if}</h3>{/if}
        <div class={view === "grid" ? "grid" : "rows"}>
          {#each sec.items as r (r.id)}
            {@const s = st(r.id)}
            {@const g = work.groupOf(r.id)}
            {@const ags = agentsOf(r.id)}
            {@const isOpen = openIds.has(r.id)}
            <div class="pc" class:sel={selected.includes(r.id)} class:open={isOpen} style={g ? `--g:${g.color}` : ""} data-menu-row role="button" tabindex="0"
              onclick={() => open(r)} onkeydown={(e) => e.key === "Enter" && open(r)} oncontextmenu={(e) => ui.contextMenu(e, repoMenu(r))}>
              <button class="ck" class:on={selected.includes(r.id)} title="Selecionar" onclick={(e) => { e.stopPropagation(); toggleSel(r.id); }}>{#if selected.includes(r.id)}<Check size={12} />{/if}</button>
              <div class="top">
                <span class="ic"><ProviderIcon provider={r.provider || null} size={16} /></span>
                <div class="nm"><b class="ell">{r.name}</b><span class="tiny muted ell" title={r.path}>{home(r.path)}</span></div>
                {#if isOpen}<span class="pill accent">aberto</span>{/if}
              </div>
              <div class="meta">
                {#if g}<span class="gtag"><span class="dot"></span>{g.name}</span>{/if}
                {#if r.status?.branch}<span class="mono br">{r.status.branch}</span>{/if}
                {#if r.status?.changes}<span class="pill warn">{r.status.changes} alteraç{r.status.changes === 1 ? "ão" : "ões"}</span>{/if}
                {#if r.status?.ahead}<span class="pill accent"><ArrowUp size={10} />{r.status.ahead}</span>{/if}
                {#if r.status?.behind}<span class="pill info"><ArrowDown size={10} />{r.status.behind}</span>{/if}
                {#each ags.slice(0, 3) as a (a.term.id)}<span class="ag" class:busy={a.session?.status === "working"} class:need={a.session?.status === "needs-you"}><AgentIcon provider={a.term.meta.provider} size={12} /></span>{/each}
              </div>
              <div class="use tiny muted">
                <span title="Último acesso (abrir o projeto ou agente trabalhando nele)">{last(r) ? "acessado há " + ago(new Date(last(r)).toISOString()) : "nunca aberto"}</span>
                <span title="Seu tempo com o projeto na tela nos últimos 30 dias">⏱ {dur(s.focus30)}</span>
                {#if s.sessions30}<span title="Sessões de IA nos últimos 30 dias">✦ {s.sessions30} sess{s.sessions30 === 1 ? "ão" : "ões"}{s.cost30 ? ` · US$ ${s.cost30.toFixed(2)}` : ""}</span>{/if}
                {#if r.lastCommit}<span class="ell" title={r.lastCommit.subject}>último commit {ago(r.lastCommit.date)}</span>{/if}
              </div>
              <div class="acts" role="presentation" onclick={(e) => e.stopPropagation()}>
                <button class="btn sm primary" onclick={() => open(r)}><Play size={12} /> {isOpen ? "Ir" : "Abrir"}</button>
                <button class="btn sm ghost" title="Pedir à IA" onclick={() => open(r, true)}><Sparkles size={13} /></button>
                <Menu items={repoMenu(r)} />
              </div>
            </div>
          {/each}
        </div>
      {/each}
    {/if}
  </div>
</Page>

<style>
  .groups { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 10px; flex: none; }
  .gcard { display: flex; align-items: center; gap: 2px; min-width: 190px; padding: 4px 4px 4px 0; border-radius: 12px; border: 1px solid var(--line-2);
    background: linear-gradient(90deg, color-mix(in srgb, var(--g) 14%, transparent), transparent 70%), var(--surface); flex: none; transition: border-color var(--t); }
  .gcard.on { border-color: var(--g); }
  .gmain { flex: 1; display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 2px 8px; padding: 6px 10px; border: 0; background: none;
    color: var(--text); font: 13px var(--font); text-align: left; cursor: pointer; min-width: 0; }
  .gmain .tiny { grid-column: 2 / 4; }
  .gdot { width: 10px; height: 10px; border-radius: 3px; background: var(--g); }
  .gact { display: flex; align-items: center; }
  .live { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); animation: ping 1.2s var(--ease) infinite; }
  @keyframes ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 6px transparent; } }
  .bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 2px 0 10px; }
  .bar label { display: inline-flex; align-items: center; gap: 6px; }
  .input.sm { height: 30px; font-size: 12.5px; padding: 0 8px; width: auto; }
  .grow { flex: 1; }
  .vt { display: flex; gap: 2px; padding: 2px; border-radius: 8px; background: var(--bg-2); border: 1px solid var(--line); }
  .vt button { display: grid; place-items: center; width: 28px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; }
  .vt button.on { background: var(--surface-3); color: var(--text); }
  .selbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 12px; margin-bottom: 10px; border-radius: 12px; background: var(--accent-soft);
    border: 1px solid var(--accent-line); animation: rise 0.2s var(--ease-out); }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
  .scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; padding-bottom: 20px; }
  .sec { display: flex; align-items: center; gap: 8px; margin: 14px 2px 8px; font-size: 13px; color: var(--text-2); }
  .sec .n { font-size: 11px; color: var(--faint); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; }
  .rows { display: grid; gap: 6px; }
  .pc { position: relative; display: grid; gap: 8px; padding: 12px 12px 10px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface);
    cursor: pointer; text-align: left; animation: rise 0.25s var(--ease-out) both; transition: border-color var(--t), transform var(--t) var(--spring), box-shadow var(--t); }
  .pc[style*="--g"] { box-shadow: inset 3px 0 0 var(--g); }
  .pc:hover { border-color: var(--line-3); transform: translateY(-2px); }
  .pc.sel { border-color: var(--accent); background: color-mix(in srgb, var(--accent-soft) 60%, var(--surface)); }
  .rows .pc { grid-template-columns: minmax(220px, 1.3fr) minmax(160px, 1fr) minmax(200px, 1.2fr) auto; align-items: center; gap: 12px; padding: 8px 12px 8px 36px; }
  .rows .pc:hover { transform: none; }
  .ck { position: absolute; top: 10px; right: 10px; display: grid; place-items: center; width: 18px; height: 18px; border-radius: 5px; border: 1px solid var(--line-3);
    background: var(--surface); color: #fff; cursor: pointer; opacity: 0; transition: opacity var(--t-fast); }
  .rows .ck { left: 10px; right: auto; top: 50%; transform: translateY(-50%); }
  .pc:hover .ck, .ck.on { opacity: 1; }
  .ck.on { background: var(--accent); border-color: var(--accent); }
  .top { display: flex; align-items: center; gap: 10px; min-width: 0; padding-right: 22px; }
  .rows .top { padding-right: 0; }
  .ic { width: 32px; height: 32px; border-radius: 9px; display: grid; place-items: center; background: var(--surface-2); border: 1px solid var(--line); flex: none; }
  .nm { display: grid; min-width: 0; flex: 1; }
  .nm b { font-weight: 650; }
  .meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-height: 20px; }
  .gtag { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; font-weight: 600; color: var(--text-2); padding: 1px 8px 1px 6px; border-radius: 99px;
    background: color-mix(in srgb, var(--g) 16%, transparent); }
  .gtag .dot { background: var(--g); }
  .br { font-size: 11px; color: var(--muted); }
  .ag { display: inline-grid; place-items: center; border-radius: 50%; padding: 1px; }
  .ag.busy { box-shadow: 0 0 0 2px var(--accent-soft); }
  .ag.need { box-shadow: 0 0 0 2px var(--warn); }
  .use { display: flex; flex-wrap: wrap; gap: 4px 12px; }
  .acts { display: flex; align-items: center; gap: 4px; justify-content: flex-end; }
  .grid .acts { opacity: 0.85; }
</style>
