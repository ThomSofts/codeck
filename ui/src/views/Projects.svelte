<script lang="ts">
  // Hub de projetos: no topo, os ABERTOS (cartões com o estado dos agentes), os fixados e os recentes; abaixo, todos os
  // clones desta máquina numa lista densa (feita para centenas de repositórios), com busca, filtros, ordem e seções
  // recolhíveis (grupo, conta ou pasta). Teclado: digitar busca · ↑/↓ escolhe · Enter abre · ⌘/Ctrl+Enter abre sem sair
  // daqui · Esc limpa.
  import { ArrowDown, ArrowUp, Check, ChevronDown, Code2, FolderGit2, FolderOpen, FolderPlus, Layers, LayoutGrid, List, Pencil, Pin, PinOff, Play, Search, Settings2, Sparkles, Terminal, Trash2, X } from "@lucide/svelte";
  import { tick, untrack } from "svelte";
  import { get, post } from "../lib/api";
  import { ago } from "../lib/format";
  import { kbd, matches } from "../lib/keys";
  import { fileManagerName } from "../lib/native";
  import { prefs } from "../lib/prefs.svelte";
  import { repos } from "../lib/repos.svelte";
  import { go, router } from "../lib/router.svelte";
  import type { LocalRepo } from "../lib/types";
  import { ui } from "../lib/ui.svelte";
  import { work, type Group } from "../lib/work.svelte";
  import Empty from "../components/Empty.svelte";
  import Menu from "../components/Menu.svelte";
  import Page from "../components/Page.svelte";
  import ProviderIcon from "../components/ProviderIcon.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Skeleton from "../components/Skeleton.svelte";
  import AgentIcon from "../components/work/AgentIcon.svelte";
  import OpenNow from "../components/hub/OpenNow.svelte";
  import { agentsByProject, noAgents, tone } from "../components/hub/open";

  type Stat = { focusS: number; focus30: number; sessions30: number; cost30: number; lastAgent: string | null; lastOpened?: string; opens?: number };
  const NOSTAT: Stat = { focusS: 0, focus30: 0, sessions30: 0, cost30: 0, lastAgent: null };
  let stats = $state<Record<string, Stat>>({});
  let q = $state("");
  let filter = $state("all");
  let provider = $state("any");
  let groupFilter = $state("any");
  let selected = $state<string[]>([]);
  let hi = $state<string | null>(null);
  let searchEl: HTMLInputElement | undefined = $state();
  const sort = $derived(prefs.get("hub.sort"));
  const groupBy = $derived(prefs.get("hub.group"));
  const pinned = $derived(prefs.get("hub.pinned"));
  const pinnedSet = $derived(new Set(pinned));
  const collapsed = $derived(new Set(prefs.get("hub.collapsed")));

  async function loadStats() { try { stats = (await get<{ stats: Record<string, Stat> }>("ws/hub")).stats; } catch (e) { ui.error(e); } }
  $effect(() => { untrack(() => { loadStats(); repos.load(); }); });

  const isWt = (p: string) => /[\\/]\.worktrees[\\/]/.test(p);
  const home = (p: string) => p.replace(/^\/Users\/[^/]+|^C:\\Users\\[^\\]+/i, "~");
  const all = $derived(repos.local.filter(r => r.exists && !isWt(r.path)));
  // muitos repositórios: lista densa por padrão (os cartões continuam como opção)
  const view = $derived.by(() => { const v = prefs.get("hub.view"); return v === "auto" ? (all.length > 24 ? "list" : "grid") : v; });
  const openIds = $derived(new Set(work.projects.map(p => p.id)));
  const ags = $derived(agentsByProject());
  const st = (id: string): Stat => stats[id] || NOSTAT;

  // uma passada por repositório com tudo que a lista precisa (busca, ordem, último acesso) — barato para centenas
  type Row = { r: LocalRepo; last: number; hay: string; name: string; g: Group | null; weight: number };
  const rows = $derived.by<Row[]>(() => all.map(r => {
    const s = st(r.id), g = work.groupOf(r.id);
    const last = Math.max(new Date(s.lastOpened || 0).getTime(), new Date(s.lastAgent || 0).getTime());
    return { r, last, g, name: r.name.toLowerCase(), weight: s.focus30 + s.sessions30 * 600,
      hay: `${r.name} ${home(r.path)} ${r.slug || ""} ${g?.name || ""} ${r.status?.branch || ""}`.toLowerCase() };
  }));

  const terms = $derived(q.trim().toLowerCase().split(/\s+/).filter(Boolean));
  const list = $derived.by(() => {
    const t = terms, unused = Date.now() - 30 * 864e5;
    const out = rows.filter(x => (!t.length || t.every(p => x.hay.includes(p)))
      && (provider === "any" || (provider === "local" ? !x.r.provider : x.r.provider === provider))
      && (groupFilter === "any" || (groupFilter === "none" ? !x.g : x.g?.id === groupFilter))
      && (filter === "all" || (filter === "open" ? openIds.has(x.r.id) : filter === "pinned" ? pinnedSet.has(x.r.id) : filter === "dirty" ? (x.r.status?.changes || 0) > 0
        : filter === "agents" ? (ags.get(x.r.id)?.n || 0) > 0 : filter === "unused" ? x.last < unused : true)));
    const by: Record<string, (a: Row, b: Row) => number> = {
      recent: (a, b) => b.last - a.last || a.name.localeCompare(b.name),
      most: (a, b) => b.weight - a.weight || b.last - a.last,
      least: (a, b) => a.weight - b.weight || a.last - b.last,
      ai: (a, b) => st(b.r.id).sessions30 - st(a.r.id).sessions30 || st(b.r.id).cost30 - st(a.r.id).cost30,
      opens: (a, b) => (st(b.r.id).opens || 0) - (st(a.r.id).opens || 0),
      commit: (a, b) => new Date(b.r.lastCommit?.date || 0).getTime() - new Date(a.r.lastCommit?.date || 0).getTime(),
      name: (a, b) => a.name.localeCompare(b.name),
    };
    const cmp = by[sort] || by.recent;
    // com busca: quem COMEÇA com o termo vem primeiro, depois quem tem o termo no nome, depois o resto (pasta, grupo…)
    const rank = (x: Row) => (!t.length ? 0 : x.name.startsWith(t[0]) ? 0 : t.every(p => x.name.includes(p)) ? 1 : 2);
    return out.sort((a, b) => rank(a) - rank(b) || cmp(a, b));
  });

  type Sec = { key: string; label: string; color: string | null; items: Row[]; group: Group | null; provider?: string | null };
  const sections = $derived.by<Sec[]>(() => {
    if (groupBy === "none") return [{ key: "all", label: "", color: null, items: list, group: null }];
    const m = new Map<string, Sec>();
    for (const x of list) {
      const r = x.r;
      let key = "", label = "", color: string | null = null, group: Group | null = null, prov: string | null = null;
      if (groupBy === "group") { group = x.g; key = group?.id || "~"; label = group?.name || "Sem grupo"; color = group?.color || null; }
      else if (groupBy === "account") { prov = r.provider || null; key = r.provider ? `${r.provider}:${(r.slug || "").split("/")[0]}` : "~"; label = r.provider ? `${(r.slug || "").split("/")[0]}` : "Sem remoto"; }
      else { key = r.path.replace(/[\\/][^\\/]+$/, ""); label = home(key); }
      key = `${groupBy}:${key}`;
      if (!m.has(key)) m.set(key, { key, label, color, items: [], group, provider: prov });
      m.get(key)!.items.push(x);
    }
    const tilde = (s: Sec) => s.key.endsWith(":~");
    return [...m.values()].sort((a, b) => (tilde(a) ? 1 : tilde(b) ? -1 : groupBy === "group" ? work.groups.findIndex(g => g.id === a.group?.id) - work.groups.findIndex(g => g.id === b.group?.id) : a.label.localeCompare(b.label)));
  });
  const toggleSec = (key: string) => { const c = prefs.get("hub.collapsed"); prefs.set("hub.collapsed", collapsed.has(key) ? c.filter(x => x !== key) : [...c, key].slice(-150)); };
  // a busca abre as seções recolhidas (senão o resultado ficava escondido)
  const isShut = (key: string) => collapsed.has(key) && !terms.length;
  const visible = $derived(sections.filter(s => !isShut(s.key)).flatMap(s => s.items));

  const counts = $derived.by(() => {
    let open = 0, dirty = 0, agents = 0, pin = 0;
    for (const x of rows) {
      if (openIds.has(x.r.id)) open++;
      if ((x.r.status?.changes || 0) > 0) dirty++;
      if (ags.get(x.r.id)?.n) agents++;
      if (pinnedSet.has(x.r.id)) pin++;
    }
    return { all: rows.length, open, dirty, agents, pin };
  });

  // acesso rápido: fixados e os últimos acessados que não estão abertos
  const pinnedRows = $derived(pinned.map(id => rows.find(x => x.r.id === id)).filter((x): x is Row => !!x));
  const recent = $derived(rows.filter(x => x.last && !openIds.has(x.r.id) && !pinnedSet.has(x.r.id)).sort((a, b) => b.last - a.last).slice(0, 8));

  function dur(s: number) {
    if (!s) return "—";
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
    const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    return h >= 100 ? `${h} h` : `${h} h${m ? ` ${String(m).padStart(2, "0")}` : ""}`;
  }
  async function open(r: LocalRepo, mode: "go" | "ask" | "stay" = "go") {
    try {
      const id = await work.open(r.id);
      if (mode === "ask") work.focus(id, null);
      else if (mode === "go") go("/work/" + id, "soft");
      else ui.toast(`${r.name} aberto nas abas`);
    } catch (e) { ui.error(e); }
  }
  const togglePin = (id: string) => prefs.set("hub.pinned", pinnedSet.has(id) ? pinned.filter(x => x !== id) : [...pinned, id].slice(-60));
  const toggleSel = (id: string) => (selected = selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id]);
  async function groupSelected(gid?: string) {
    if (gid) { for (const id of selected) await work.assignGroup(id, gid); }
    else await work.newGroup(selected);
    selected = [];
  }
  async function openSelected() { for (const id of selected) await work.open(id); const l = selected[selected.length - 1]; selected = []; go("/work/" + l, "soft"); }
  const repoMenu = (r: LocalRepo) => {
    const g = work.groupOf(r.id);
    return [
      { label: openIds.has(r.id) ? "Ir para o projeto" : "Abrir projeto", icon: Play, onclick: () => open(r), kbd: "Enter" },
      ...(openIds.has(r.id) ? [] : [{ label: "Abrir sem sair do hub", icon: Layers, onclick: () => open(r, "stay"), kbd: kbd("mod+enter") }]),
      { label: "Pedir à IA…", icon: Sparkles, onclick: () => open(r, "ask") },
      { label: pinnedSet.has(r.id) ? "Desafixar do topo" : "Fixar no topo", icon: pinnedSet.has(r.id) ? PinOff : Pin, onclick: () => togglePin(r.id) },
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
  const groupMenu = (g: Group) => [
    { label: `Abrir todos (${g.repoIds.length})`, icon: Play, onclick: () => work.openGroup(g.id) },
    { label: "Renomear…", icon: Pencil, onclick: () => renameGroup(g) },
    { label: "Trocar a cor", icon: Settings2, onclick: () => work.saveGroup({ id: g.id, color: PALETTE[(PALETTE.indexOf(g.color) + 1) % PALETTE.length] }) },
    { separator: true },
    { label: "Apagar grupo (os projetos ficam)", icon: Trash2, danger: true, onclick: () => work.deleteGroup(g.id) },
  ];
  const sortBy = (k: string) => prefs.set("hub.sort", k);

  // ------------------------------------------------------------ teclado
  $effect(() => { void q; void filter; void provider; void groupFilter; hi = null; });
  async function reveal(id: string | null) {
    await tick();
    if (id) document.querySelector<HTMLElement>(`.hub [data-rid="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest" });
  }
  function move(d: number) {
    if (!visible.length) return;
    const i = hi ? visible.findIndex(x => x.r.id === hi) : -1;
    hi = visible[Math.max(0, Math.min(visible.length - 1, i < 0 ? (d > 0 ? 0 : visible.length - 1) : i + d))].r.id;
    reveal(hi);
  }
  function onKey(e: KeyboardEvent) {
    if (router.view !== "projects" || ui.dialog || ui.menu) return;
    const t = e.target as HTMLElement;
    const inSearch = t === searchEl, typing = !inSearch && !!t?.closest?.("input, textarea, select, [contenteditable]");
    if (typing || document.querySelector("[role=dialog]")) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); move(e.key === "ArrowDown" ? 1 : -1); return; }
    if (e.key === "Enter" && (inSearch || hi)) {
      const x = visible.find(v => v.r.id === hi) || (inSearch ? visible[0] : null);
      if (!x) return;
      e.preventDefault();
      open(x.r, matches(e, "mod+enter") && !openIds.has(x.r.id) ? "stay" : "go");
      return;
    }
    if (e.key === "Escape") {
      if (q) { q = ""; e.preventDefault(); } else if (hi) hi = null; else if (selected.length) selected = [];
      else if (inSearch) searchEl?.blur();
      return;
    }
    if (inSearch) return;
    // digitar em qualquer lugar do hub vai para a busca (a tecla cai no campo)
    if ((e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey && e.key !== " ") || e.key === "/") {
      if (e.key === "/") e.preventDefault();
      searchEl?.focus();
    }
  }
</script>

<svelte:window onkeydown={onKey} />

{#snippet pinBtn(id: string)}
  <button class="pin" class:on={pinnedSet.has(id)} title={pinnedSet.has(id) ? "Desafixar do topo" : "Fixar no topo"} onclick={(e) => { e.stopPropagation(); togglePin(id); }}>
    <Pin size={12} />
  </button>
{/snippet}

{#snippet chip(x: Row)}
  <button class="chip" onclick={() => open(x.r)} oncontextmenu={(e) => ui.contextMenu(e, repoMenu(x.r))} title={home(x.r.path)} style={x.g ? `--g:${x.g.color}` : ""}>
    <ProviderIcon provider={x.r.provider || null} size={12} />
    <span class="ell">{x.r.name}</span>
    {#if openIds.has(x.r.id)}<span class="odot" title="aberto"></span>{:else if x.last}<span class="ago">{ago(new Date(x.last).toISOString())}</span>{/if}
  </button>
{/snippet}

{#snippet state(r: LocalRepo)}
  {@const a = ags.get(r.id) || noAgents}
  {#if r.status?.changes}<span class="pill warn" title="alterações não commitadas">{r.status.changes}</span>{/if}
  {#if r.status?.ahead}<span class="pill accent" title="commits para enviar"><ArrowUp size={10} />{r.status.ahead}</span>{/if}
  {#if r.status?.behind}<span class="pill info" title="commits para receber"><ArrowDown size={10} />{r.status.behind}</span>{/if}
  {#if a.n}<span class="ags {tone(a)}" title={a.need ? "agente precisando de você" : a.working ? "agente trabalhando" : "agente aberto"}>
    {#each a.list.slice(0, 3) as ag (ag.id)}<AgentIcon provider={ag.provider} size={12} />{/each}{#if a.need}<b>!</b>{/if}</span>{/if}
{/snippet}

<Page title="Projetos" sub={`${all.length} repositórios clonados · ${counts.open} abertos${work.groups.length ? ` · ${work.groups.length} grupos` : ""}`}>
  {#snippet actions()}
    <button class="btn sm" onclick={() => work.newGroup([])}><FolderPlus size={14} /> Novo grupo</button>
    <button class="btn sm" onclick={() => go("/repos")}><FolderGit2 size={14} /> Repositórios</button>
  {/snippet}

  <div class="hub">
    <OpenNow />

    {#if pinnedRows.length || recent.length || work.groups.length}
      <div class="quick">
        {#if pinnedRows.length}
          <div class="qrow"><span class="ql"><Pin size={12} /> Fixados</span><div class="chips">{#each pinnedRows as x (x.r.id)}{@render chip(x)}{/each}</div></div>
        {/if}
        {#if recent.length}
          <div class="qrow"><span class="ql">Recentes</span><div class="chips">{#each recent as x (x.r.id)}{@render chip(x)}{/each}
            {#if !pinnedRows.length}<span class="tiny muted qh">fixe os que você mais usa com <Pin size={10} /></span>{/if}</div></div>
        {/if}
        {#if work.groups.length}
          <div class="qrow"><span class="ql"><Layers size={12} /> Grupos</span><div class="chips">
            {#each work.groups as g (g.id)}
              {@const openN = g.repoIds.filter(id => openIds.has(id)).length}
              {@const busy = g.repoIds.some(id => ags.get(id)?.working)}
              <span class="gchip" class:on={groupFilter === g.id} style="--g:{g.color}">
                <button class="gmain" title="Filtrar por este grupo" onclick={() => (groupFilter = groupFilter === g.id ? "any" : g.id)}>
                  <span class="gd"></span><b class="ell">{g.name}</b><span class="gn">{g.repoIds.length}</span>
                  {#if openN}<span class="gopen" title="abertos">{openN} aberto{openN === 1 ? "" : "s"}</span>{/if}
                  {#if busy}<span class="live"></span>{/if}
                </button>
                <Menu items={groupMenu(g)} />
              </span>
            {/each}
          </div></div>
        {/if}
      </div>
    {/if}

    <!-- filtros: grudam no topo enquanto a lista rola -->
    <div class="filters">
      <div class="f1">
        <label class="search"><Search size={14} />
          <input bind:this={searchEl} bind:value={q} placeholder={`Buscar entre ${all.length} projetos — nome, pasta, grupo ou branch`} aria-label="Buscar projeto" />
          {#if q}<button class="clr" title="Limpar (Esc)" onclick={() => { q = ""; searchEl?.focus(); }}><X size={11} /></button>{:else}<span class="kbd">/</span>{/if}
        </label>
        <Segmented size="sm" bind:value={filter} options={[{ value: "all", label: "Todos", count: counts.all }, { value: "open", label: "Abertos", count: counts.open },
          ...(counts.pin ? [{ value: "pinned", label: "Fixados", count: counts.pin }] : []),
          { value: "agents", label: "Com agente", count: counts.agents }, { value: "dirty", label: "Com alterações", count: counts.dirty }, { value: "unused", label: "Parados há 30 d" }]} />
      </div>
      <div class="f2">
        <select class="input sm" bind:value={provider} aria-label="Origem"><option value="any">Qualquer origem</option><option value="github">GitHub</option><option value="azure">Azure DevOps</option><option value="local">Sem remoto</option></select>
        <select class="input sm" bind:value={groupFilter} aria-label="Grupo"><option value="any">Todos os grupos</option><option value="none">Sem grupo</option>{#each work.groups as g (g.id)}<option value={g.id}>{g.name}</option>{/each}</select>
        <span class="tiny muted shown">{list.length === all.length ? "" : `${list.length} de ${all.length}`}</span>
        <span class="grow"></span>
        <label class="small muted"><span class="lbl">Ordenar</span>
          <select class="input sm" value={sort} onchange={(e) => sortBy((e.target as HTMLSelectElement).value)}>
            <option value="recent">Últimos acessados</option><option value="most">Mais usados (30 d)</option><option value="least">Menos usados (30 d)</option>
            <option value="ai">Mais sessões de IA</option><option value="opens">Mais vezes aberto</option><option value="commit">Último commit</option><option value="name">Nome</option>
          </select></label>
        <label class="small muted"><span class="lbl">Agrupar</span>
          <select class="input sm" value={groupBy} onchange={(e) => prefs.set("hub.group", (e.target as HTMLSelectElement).value)}>
            <option value="none">Não agrupar</option><option value="group">Grupo</option><option value="account">Conta / organização</option><option value="folder">Pasta</option>
          </select></label>
        <div class="vt" role="group" aria-label="Exibição">
          <button class:on={view === "list"} title="Lista" onclick={() => prefs.set("hub.view", "list")}><List size={14} /></button>
          <button class:on={view === "grid"} title="Cartões" onclick={() => prefs.set("hub.view", "grid")}><LayoutGrid size={14} /></button>
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
    </div>

    {#if !repos.loaded}<Skeleton rows={8} />
    {:else if !list.length}
      <Empty title={q || filter !== "all" || provider !== "any" || groupFilter !== "any" ? "Nada com esses filtros" : "Nenhum repositório clonado ainda"}
        text={all.length ? "" : "Configure as pastas base das contas em Repositórios — os clones dentro delas aparecem aqui sozinhos."}>
        {#if !all.length}<button class="btn primary" onclick={() => go("/repos")}><FolderGit2 size={14} /> Ir para Repositórios</button>
        {:else}<button class="btn sm" onclick={() => { q = ""; filter = "all"; provider = "any"; groupFilter = "any"; }}>Limpar filtros</button>{/if}
      </Empty>
    {:else}
      <div class="listwrap" class:grid-v={view === "grid"}>
        {#if view === "list"}
          <div class="lhead" role="row">
            <span></span>
            <button class="hc" class:on={sort === "name"} onclick={() => sortBy("name")}>Projeto</button>
            <span class="hc c-br">Branch · estado</span>
            <button class="hc c-last" class:on={sort === "recent"} onclick={() => sortBy("recent")}>Acesso</button>
            <button class="hc c-focus" class:on={sort === "most" || sort === "least"} onclick={() => sortBy(sort === "most" ? "least" : "most")} title="Seu tempo com o projeto na tela (30 dias)">Seu tempo{#if sort === "most"} ↓{:else if sort === "least"} ↑{/if}</button>
            <button class="hc c-ai" class:on={sort === "ai"} onclick={() => sortBy("ai")} title="Sessões de IA (30 dias)">IA</button>
            <button class="hc c-commit" class:on={sort === "commit"} onclick={() => sortBy("commit")}>Último commit</button>
            <span></span>
          </div>
        {/if}
        {#each sections as sec (sec.key)}
          {@const shut = isShut(sec.key)}
          {#if sec.label}
            <div class="sec" class:shut style={sec.color ? `--g:${sec.color}` : ""}>
              <button class="sh" onclick={() => toggleSec(sec.key)} aria-expanded={!shut}>
                <ChevronDown size={14} class="chev" />
                {#if sec.color}<span class="gd"></span>{:else if sec.provider}<ProviderIcon provider={sec.provider} size={13} />{/if}
                <b class="ell">{sec.label}</b><span class="n">{sec.items.length}</span>
                {#if sec.items.some(x => openIds.has(x.r.id))}<span class="on-n">{sec.items.filter(x => openIds.has(x.r.id)).length} aberto(s)</span>{/if}
              </button>
              {#if sec.group}<button class="btn sm ghost" onclick={() => work.openGroup(sec.group!.id)}><Play size={12} /> Abrir todos</button>{/if}
            </div>
          {/if}
          {#if !shut}
            <div class={view === "grid" ? "grid" : "rows"}>
              {#each sec.items as x, i (x.r.id)}
                {@const r = x.r}
                {@const s = st(r.id)}
                {@const isOpen = openIds.has(r.id)}
                {@const sel = selected.includes(r.id)}
                {#if view === "list"}
                  <div class="row" class:sel class:open={isOpen} class:hi={hi === r.id} class:pinned={pinnedSet.has(r.id)} data-rid={r.id} role="button" tabindex="-1"
                    style="--i:{Math.min(i, 16)};{x.g ? `--g:${x.g.color}` : ''}" onclick={() => open(r)} onkeydown={() => {}} oncontextmenu={(e) => ui.contextMenu(e, repoMenu(r))}>
                    <button class="ck" class:on={sel} class:any={selected.length > 0} title="Selecionar" onclick={(e) => { e.stopPropagation(); toggleSel(r.id); }}>{#if sel}<Check size={11} />{/if}</button>
                    <span class="c-name">
                      <ProviderIcon provider={r.provider || null} size={14} />
                      <b class="ell">{r.name}</b>
                      {#if isOpen}<span class="opill">aberto</span>{/if}
                      {#if x.g && groupBy !== "group"}<span class="gt" title={`Grupo ${x.g.name}`}><span class="gd"></span>{x.g.name}</span>{/if}
                      <span class="path ell" title={r.path}>{home(r.path)}</span>
                    </span>
                    <span class="c-br"><span class="mono br ell">{r.status?.branch || ""}</span>{@render state(r)}</span>
                    <span class="c-last tiny">{x.last ? ago(new Date(x.last).toISOString()) : "nunca"}</span>
                    <span class="c-focus tiny">{dur(s.focus30)}</span>
                    <span class="c-ai tiny" title={s.cost30 ? `US$ ${s.cost30.toFixed(2)} em 30 dias` : ""}>{s.sessions30 ? `${s.sessions30} sess.` : "—"}</span>
                    <span class="c-commit tiny ell" title={r.lastCommit?.subject || ""}>{r.lastCommit ? ago(r.lastCommit.date) : "—"}</span>
                    <span class="acts" role="presentation" onclick={(e) => e.stopPropagation()}>
                      {@render pinBtn(r.id)}
                      <button class="btn sm ghost icon" title="Pedir à IA" onclick={() => open(r, "ask")}><Sparkles size={13} /></button>
                      <button class="btn sm go" class:primary={isOpen} onclick={() => open(r)}>{isOpen ? "Ir" : "Abrir"}</button>
                      <Menu items={repoMenu(r)} />
                    </span>
                  </div>
                {:else}
                  <div class="pc" class:sel class:open={isOpen} class:hi={hi === r.id} data-rid={r.id} role="button" tabindex="-1"
                    style="--i:{Math.min(i, 16)};{x.g ? `--g:${x.g.color}` : ''}" onclick={() => open(r)} onkeydown={() => {}} oncontextmenu={(e) => ui.contextMenu(e, repoMenu(r))}>
                    <button class="ck" class:on={sel} class:any={selected.length > 0} title="Selecionar" onclick={(e) => { e.stopPropagation(); toggleSel(r.id); }}>{#if sel}<Check size={11} />{/if}</button>
                    <div class="top">
                      <span class="ic"><ProviderIcon provider={r.provider || null} size={16} /></span>
                      <div class="nm"><b class="ell">{r.name}</b><span class="tiny muted ell" title={r.path}>{home(r.path)}</span></div>
                      {#if isOpen}<span class="opill">aberto</span>{/if}
                    </div>
                    <div class="meta">
                      {#if x.g && groupBy !== "group"}<span class="gt"><span class="gd"></span>{x.g.name}</span>{/if}
                      {#if r.status?.branch}<span class="mono br ell">{r.status.branch}</span>{/if}
                      {@render state(r)}
                    </div>
                    <div class="use tiny muted">
                      <span>{x.last ? "acessado há " + ago(new Date(x.last).toISOString()) : "nunca aberto"}</span>
                      {#if s.focus30}<span title="Seu tempo com o projeto (30 dias)">⏱ {dur(s.focus30)}</span>{/if}
                      {#if s.sessions30}<span title="Sessões de IA (30 dias)">✦ {s.sessions30}{s.cost30 ? ` · US$ ${s.cost30.toFixed(2)}` : ""}</span>{/if}
                      {#if r.lastCommit}<span class="ell" title={r.lastCommit.subject}>commit {ago(r.lastCommit.date)}</span>{/if}
                    </div>
                    <div class="acts" role="presentation" onclick={(e) => e.stopPropagation()}>
                      {@render pinBtn(r.id)}
                      <span class="grow"></span>
                      <button class="btn sm ghost icon" title="Pedir à IA" onclick={() => open(r, "ask")}><Sparkles size={13} /></button>
                      <Menu items={repoMenu(r)} />
                      <button class="btn sm" class:primary={isOpen} onclick={() => open(r)}><Play size={12} /> {isOpen ? "Ir" : "Abrir"}</button>
                    </div>
                  </div>
                {/if}
              {/each}
            </div>
          {/if}
        {/each}
        <p class="keys tiny muted"><span class="kbd">↑</span><span class="kbd">↓</span> escolher · <span class="kbd">Enter</span> abrir · <span class="kbd">{kbd("mod+enter")}</span> abrir sem sair daqui · <span class="kbd">Esc</span> limpar · digite para buscar</p>
      </div>
    {/if}
  </div>
</Page>

<style>
  .hub { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; display: flex; flex-direction: column; gap: 12px; padding-bottom: 20px; container-type: inline-size; }
  .grow { flex: 1; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
  .gd { width: 8px; height: 8px; border-radius: 50%; background: var(--g); flex: none; display: inline-block; }
  .live { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: hub-ping 1.2s var(--ease) infinite; flex: none; }

  /* acesso rápido */
  .quick { display: grid; gap: 7px; padding: 0 2px; }
  .qrow { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .ql { display: inline-flex; align-items: center; gap: 5px; width: 78px; flex: none; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
  .chips { display: flex; gap: 6px; overflow-x: auto; min-width: 0; padding: 2px 1px; scrollbar-width: none; align-items: center; }
  .chip { display: inline-flex; align-items: center; gap: 6px; height: 27px; max-width: 220px; padding: 0 10px 0 9px; border-radius: 99px; border: 1px solid var(--line-2);
    background: var(--surface); color: var(--text-2); font: 550 12.5px var(--font); cursor: pointer; flex: none; position: relative;
    transition: border-color var(--t-fast), color var(--t-fast), transform var(--t) var(--spring), background var(--t-fast); }
  .chip[style*="--g"] { box-shadow: inset 2px 0 0 var(--g); }
  .chip:hover { border-color: var(--line-3); color: var(--text); background: var(--surface-2); transform: translateY(-1px); }
  .ago { font-size: 10.5px; color: var(--faint); font-variant-numeric: tabular-nums; }
  .odot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
  .qh { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; padding-left: 4px; }
  .gchip { display: inline-flex; align-items: center; height: 27px; padding-right: 2px; border-radius: 99px; border: 1px solid var(--line-2); flex: none;
    background: linear-gradient(90deg, color-mix(in srgb, var(--g) 16%, transparent), transparent 80%), var(--surface); transition: border-color var(--t-fast); }
  .gchip.on { border-color: var(--g); }
  .gchip :global(.btn.sm.icon) { width: 22px; height: 22px; }
  .gmain { display: inline-flex; align-items: center; gap: 6px; height: 100%; padding: 0 4px 0 10px; border: 0; background: none; color: var(--text); font: 12.5px var(--font); cursor: pointer; max-width: 260px; }
  .gmain b { font-weight: 600; }
  .gn { font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .gopen { font-size: 10.5px; font-weight: 600; color: var(--accent); white-space: nowrap; }

  /* filtros grudados */
  .filters { position: sticky; top: 0; z-index: 5; display: grid; gap: 8px; padding: 8px 0 8px; margin-top: 2px; background: var(--bg);
    box-shadow: 0 6px 10px -8px rgba(0, 0, 0, 0.35); }
  .f1, .f2 { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .search { flex: 1 1 280px; display: flex; align-items: center; gap: 8px; height: 32px; padding: 0 8px 0 11px; border-radius: 9px; border: 1px solid var(--line-2);
    background: var(--bg-2); color: var(--muted); transition: border-color var(--t), box-shadow var(--t); }
  .search:focus-within { border-color: var(--accent); box-shadow: var(--ring); }
  .search input { flex: 1; min-width: 0; border: 0; outline: none; background: none; color: var(--text); font: 13px var(--font); }
  .clr { display: grid; place-items: center; width: 18px; height: 18px; border: 0; border-radius: 50%; background: var(--surface-3); color: var(--text-2); cursor: pointer; }
  .f2 label { display: inline-flex; align-items: center; gap: 6px; }
  .input.sm { height: 28px; font-size: 12.5px; padding: 0 8px; width: auto; }
  .shown { font-variant-numeric: tabular-nums; }
  .vt { display: flex; gap: 2px; padding: 2px; border-radius: 8px; background: var(--bg-2); border: 1px solid var(--line); }
  .vt button { display: grid; place-items: center; width: 28px; height: 22px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; }
  .vt button.on { background: var(--surface-3); color: var(--text); }
  .selbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 7px 12px; border-radius: 12px; background: var(--accent-soft);
    border: 1px solid var(--accent-line); animation: hub-rise 0.2s var(--ease-out); }

  /* lista densa */
  .listwrap { --cols: 20px minmax(240px, 2.4fr) minmax(170px, 1.5fr) 72px 78px 64px 92px 150px; display: grid; gap: 0; }
  .lhead { display: grid; grid-template-columns: var(--cols); align-items: center; gap: 10px; height: 26px; padding: 0 10px; }
  .hc { border: 0; background: none; padding: 0; text-align: left; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted);
    cursor: pointer; white-space: nowrap; }
  span.hc { cursor: default; }
  .hc:hover, .hc.on { color: var(--text); }
  .rows { display: grid; border-radius: 12px; border: 1px solid var(--line); background: var(--surface); overflow: hidden; }
  .row { position: relative; display: grid; grid-template-columns: var(--cols); align-items: center; gap: 10px; height: 36px; padding: 0 10px; cursor: pointer;
    border-top: 1px solid var(--line); scroll-margin: 130px 0 12px; content-visibility: auto; contain-intrinsic-size: auto 36px;
    animation: hub-fade 0.28s var(--ease-out) both; animation-delay: calc(var(--i) * 12ms); transition: background var(--t-fast); }
  .row:first-child { border-top: 0; }
  .row::before { content: ""; position: absolute; left: 0; top: 7px; bottom: 7px; width: 3px; border-radius: 0 3px 3px 0; background: var(--g, transparent); }
  .row:hover { background: var(--surface-2); }
  .row.hi { background: var(--surface-3); box-shadow: inset 0 0 0 1px var(--accent-line); }
  .row.sel { background: color-mix(in srgb, var(--accent-soft) 70%, var(--surface)); }
  .row.open .c-name b { color: var(--accent); }
  .c-name { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .c-name b { font-weight: 620; font-size: 13px; flex: 0 1 auto; }
  .c-name :global(svg) { flex: none; }
  .path { flex: 1 1 0; font-size: 11.5px; color: var(--faint); }
  .opill { font: 650 10px/1 var(--font); padding: 3px 6px; border-radius: 99px; background: var(--accent); color: var(--accent-ink); flex: none; letter-spacing: 0.02em; }
  .gt { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 600; color: var(--text-2); padding: 1px 7px 1px 6px; border-radius: 99px;
    background: color-mix(in srgb, var(--g) 15%, transparent); flex: none; max-width: 130px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .gt .gd { width: 6px; height: 6px; }
  .c-br { display: flex; align-items: center; gap: 5px; min-width: 0; }
  .br { font-size: 11px; color: var(--muted); min-width: 0; flex: 0 1 auto; }
  .c-br :global(.pill), .meta :global(.pill) { font-size: 10.5px; padding: 1px 6px; display: inline-flex; align-items: center; gap: 2px; flex: none; }
  .ags { display: inline-flex; align-items: center; gap: 2px; padding: 1px 5px; border-radius: 99px; background: var(--surface-3); flex: none; }
  .ags.accent { box-shadow: 0 0 0 1.5px var(--accent); animation: hub-ping 1.3s var(--ease) infinite; }
  .ags.warn { box-shadow: 0 0 0 1.5px var(--warn); }
  .ags b { font: 800 10.5px/1 var(--font); color: var(--warn); }
  .c-last, .c-focus, .c-ai, .c-commit { color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .acts { display: flex; align-items: center; justify-content: flex-end; gap: 2px; }
  .row .acts > :not(.go):not(.pin.on) { opacity: 0; transition: opacity var(--t-fast); }
  .row:hover .acts > *, .row.hi .acts > * { opacity: 1; }
  .row .go { height: 24px; min-width: 52px; justify-content: center; }
  .row:not(:hover):not(.hi):not(.open) .go { --b-bg: transparent; --b-line: transparent; color: var(--muted); }
  .pin { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--faint); cursor: pointer;
    transition: color var(--t-fast), background var(--t-fast), transform var(--t) var(--spring); }
  .pin:hover { background: var(--surface-3); color: var(--text); }
  .pin.on { color: var(--warn); }
  .pin:active { transform: scale(0.85); }
  .ck { display: grid; place-items: center; width: 16px; height: 16px; border-radius: 5px; border: 1px solid var(--line-3); background: var(--surface); color: #fff;
    cursor: pointer; padding: 0; opacity: 0; transition: opacity var(--t-fast); }
  .row:hover .ck, .pc:hover .ck, .ck.on, .ck.any { opacity: 1; }
  .ck.on { background: var(--accent); border-color: var(--accent); }

  /* seções */
  .sec { display: flex; align-items: center; gap: 8px; margin: 14px 2px 6px; }
  .sec:first-of-type { margin-top: 4px; }
  .sh { display: inline-flex; align-items: center; gap: 7px; border: 0; background: none; padding: 2px 4px 2px 0; color: var(--text-2); font: 13px var(--font); cursor: pointer; min-width: 0; }
  .sh:hover { color: var(--text); }
  .sh b { font-weight: 650; color: var(--text); }
  .sh :global(.chev) { color: var(--muted); transition: transform var(--t) var(--ease); flex: none; }
  .sec.shut .sh :global(.chev) { transform: rotate(-90deg); }
  .sec .n { font-size: 11px; color: var(--faint); font-variant-numeric: tabular-nums; }
  .on-n { font-size: 11px; font-weight: 600; color: var(--accent); white-space: nowrap; }

  /* cartões */
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); gap: 10px; }
  .pc { position: relative; display: grid; gap: 8px; padding: 12px 12px 10px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface);
    cursor: pointer; text-align: left; scroll-margin: 130px 0 12px; animation: hub-rise 0.3s var(--ease-out) both; animation-delay: calc(var(--i) * 18ms);
    content-visibility: auto; contain-intrinsic-size: auto 150px; transition: border-color var(--t), transform var(--t) var(--spring), box-shadow var(--t); }
  .pc[style*="--g"] { box-shadow: inset 3px 0 0 var(--g); }
  .pc:hover { border-color: var(--line-3); transform: translateY(-2px); }
  .pc.hi { border-color: var(--accent); }
  .pc.open { border-color: var(--accent-line); }
  .pc.sel { border-color: var(--accent); background: color-mix(in srgb, var(--accent-soft) 60%, var(--surface)); }
  .pc .ck { position: absolute; top: 10px; right: 10px; }
  .top { display: flex; align-items: center; gap: 10px; min-width: 0; padding-right: 22px; }
  .ic { width: 32px; height: 32px; border-radius: 9px; display: grid; place-items: center; background: var(--surface-2); border: 1px solid var(--line); flex: none; }
  .nm { display: grid; min-width: 0; flex: 1; }
  .nm b { font-weight: 650; }
  .meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-height: 20px; }
  .use { display: flex; flex-wrap: wrap; gap: 4px 12px; }
  .pc .acts { gap: 4px; }
  .pc .acts .pin:not(.on) { opacity: 0; }
  .pc:hover .acts .pin { opacity: 1; }

  .keys { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; justify-content: center; margin: 16px 0 0; }

  @container (max-width: 1040px) { .listwrap { --cols: 20px minmax(220px, 2.4fr) minmax(150px, 1.5fr) 64px 70px 150px; } .c-ai, .c-commit { display: none; } }
  @container (max-width: 820px) { .listwrap { --cols: 20px minmax(180px, 2fr) minmax(120px, 1.3fr) 60px 150px; } .c-focus { display: none; } .path { display: none; } }
  @container (max-width: 900px) { .f2 .lbl, .shown { display: none; } }

  @keyframes hub-rise { from { opacity: 0; transform: translateY(6px); } }
  @keyframes hub-fade { from { opacity: 0; transform: translateX(-4px); } }
  @keyframes hub-ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 5px transparent; } }
  @media (prefers-reduced-motion: reduce) { .row, .pc, .live, .ags.accent, .selbar { animation: none; } .pc:hover, .chip:hover { transform: none; } }
</style>
