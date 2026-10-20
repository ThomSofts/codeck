<script lang="ts">
  import type { Source } from "../lib/types";
  // Barra lateral. Expandida: menus com contadores, os projetos abertos (em grupos, compactos) e as coleções de
  // repositórios. Recolhida (⌘\ / Ctrl+\): só ícones — passar o mouse abre um popover com o submenu de cada item.
  import { BarChart3, Gauge, Code2, RefreshCw, CircleDot, FolderGit2, GitPullRequest, Hammer, History, Inbox, Pin, Rocket, Search, Settings, Zap,
    KanbanSquare, PanelLeftClose, PanelLeftOpen, ChevronRight, LayoutGrid } from "@lucide/svelte";
  import { BRAND } from "../lib/brand";
  import { post } from "../lib/api";
  import { kb } from "../lib/keybindings.svelte";
  import { prefs } from "../lib/prefs.svelte";
  import { repos } from "../lib/repos.svelte";
  import { work, type Project } from "../lib/work.svelte";
  import AgentIcon from "./work/AgentIcon.svelte";
  import { go, router } from "../lib/router.svelte";
  import { store } from "../lib/store.svelte";
  import { ui } from "../lib/ui.svelte";
  import { time } from "../lib/format";
  import Mark from "./Mark.svelte";
  import CollectionsTree from "./repo/CollectionsTree.svelte";
  import ProviderIcon from "./ProviderIcon.svelte";
  import Switch from "./Switch.svelte";

  const collapsed = $derived(prefs.get("sidebar.collapsed"));
  const s = $derived(store.s);
  const running = $derived(s ? s.builds.filter(b => b.status !== "completed").length : 0);
  const nav = $derived([
    { group: "Trabalho" },
    { id: "projects", label: "Projetos", icon: Code2, count: work.needsYou || undefined, hot: true, live: work.agents.some(a => a.session?.status === "working"), fly: "work" },
    { id: "board", label: "Quadro", icon: KanbanSquare },
    { id: "ai", label: "Uso de IA", icon: Gauge },
    { group: "Visão geral" },
    { id: "inbox", label: "Fila", icon: Inbox, count: store.inbox.length + (s?.deploys.length || 0), hot: true },
    { id: "prs", label: "Pull requests", icon: GitPullRequest, count: s ? s.myPrs.length + store.open.length : undefined },
    { id: "builds", label: "Builds e Actions", icon: Hammer, count: running || undefined, live: running > 0 },
    { id: "deploys", label: "Deploys", icon: Rocket, count: s?.deploys.length, hot: true },
    { id: "issues", label: "Issues e tarefas", icon: CircleDot, count: s?.issues.length },
    { group: "Código" },
    { id: "repos", label: "Repositórios", icon: FolderGit2, count: repos.local.filter(r => r.exists && !/[\\/]\.worktrees[\\/]/.test(r.path)).length || undefined, fly: "repos" },
    { group: "Configurar" },
    { id: "automation", label: "Automação", icon: Zap },
    { id: "analytics", label: "Análise", icon: BarChart3 },
    { id: "history", label: "Histórico", icon: History },
    { id: "settings", label: "Contas e ajustes", icon: Settings },
  ] as any[]);

  let navEl: HTMLElement | undefined = $state();
  let ind = $state({ y: 0, h: 0, ready: false });
  $effect(() => {
    void router.view; void router.param; void repos.pinned.length; void repos.catalogs.length; void repos.tags.length; void repos.favorites.length;
    void collapsed; void work.projects.length; void work.groups; void openClosed;
    requestAnimationFrame(place);
  });
  function place() {
    const on = navEl?.querySelector<HTMLElement>(".item.on");
    ind = on ? { y: on.offsetTop, h: on.offsetHeight, ready: true } : { ...ind, ready: false };
  }
  // grupo do catálogo abrindo/fechando muda a altura da árvore: o marcador do item ativo acompanha
  let treeEl: HTMLElement | undefined = $state();
  $effect(() => {
    if (!treeEl) return;
    const ro = new ResizeObserver(() => place());
    ro.observe(treeEl);
    return () => ro.disconnect();
  });
  // "Projetos" fica marcado no hub e dentro de um projeto; "Repositórios" só na lista de locais
  const isOn = (id: string) => (id === "projects" ? router.view === "projects" || ((router.view === "work" || router.view === "repo") && !router.parts[1] && !work.projects.length)
    : id === "board" ? router.view === "board" || (router.view === "work" && router.parts[1] === "board")
    : (router.view === id && !(id === "repos" && router.param)));
  const paused = $derived(!!s?.rules.settings.paused);
  async function toggleAuto(on: boolean) {
    try {
      await post("rules", { ...s!.rules, settings: { ...s!.rules.settings, paused: !on } });
      ui.toast(on ? "Automação ligada" : "Automação pausada — nada é aprovado sozinho");
      store.load();
    } catch (e) { ui.error(e); }
  }
  // cada item da barra mostra a leitura da própria fonte (sem acender nada no topo)
  const SRC_OF: Record<string, Source[]> = { inbox: ["prs", "deploys"], prs: ["prs"], builds: ["builds"], deploys: ["deploys"], issues: ["issues"] };
  const SRC_LABEL: [Source, string][] = [["prs", "PRs"], ["builds", "builds"], ["deploys", "deploys"], ["issues", "issues"]];
  const syncText = $derived(store.error ? "backend fora do ar" : store.offline ? "sem conexão" : s?.polling ? `lendo ${s.polling}…` : store.refreshing ? "pedindo leitura…"
    : s?.lastPoll ? `lido às ${time(s.lastPoll)}` : "primeira leitura…");
  async function manualRefresh() {
    const ok = await store.refresh();
    ui.toast(ok ? "Tudo atualizado" : "A leitura está demorando — os dados chegam assim que ela terminar", ok ? "ok" : "info");
  }
  const sourceErrors = $derived(s ? { ...s.errors, ...s.buildErrors, ...s.deployErrors } : {});

  // ------------------------------------------------------------ projetos abertos (compactos, por grupo)
  const OPEN_KEY = "codeck.side.openClosed";
  let openClosed = $state((() => { try { return localStorage.getItem(OPEN_KEY) === "1"; } catch { return false; } })());
  function toggleOpenList() { openClosed = !openClosed; try { localStorage.setItem(OPEN_KEY, openClosed ? "1" : "0"); } catch { /* sem armazenamento */ } }
  const MAX_OPEN = 7;
  const openRuns = $derived.by(() => {
    const out: { g: ReturnType<typeof work.groupOf>; items: Project[] }[] = [];
    const seen = new Set<string>();
    for (const p of work.projects) {
      const g = work.groupOf(p.id);
      if (!g) { out.push({ g: null, items: [p] }); continue; }
      if (seen.has(g.id)) continue;
      seen.add(g.id);
      out.push({ g, items: work.projects.filter(x => work.groupOf(x.id)?.id === g.id) });
    }
    return out;
  });
  const projOn = (id: string) => router.view === "work" && (router.parts[1] === id || (!router.parts[1] && work.active === id));
  const agentsOf = (id: string) => work.agents.filter(a => a.project.id === id);

  // ------------------------------------------------------------ recolhida: popover com o submenu
  let fly = $state<{ id: string; label: string; top: number; count?: number } | null>(null);
  let flyTimer: ReturnType<typeof setTimeout> | undefined;
  function showFly(e: MouseEvent, n: any) {
    if (!collapsed) return;
    clearTimeout(flyTimer);
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    fly = { id: n.fly || "", label: n.label, top: r.top, count: n.count };
  }
  function hideFly() { clearTimeout(flyTimer); flyTimer = setTimeout(() => (fly = null), 160); }
  function keepFly() { clearTimeout(flyTimer); }
  $effect(() => { void router.path; fly = null; });   // navegou: o popover fecha
  function toggleCollapsed() { prefs.set("sidebar.collapsed", !collapsed); fly = null; }
  $effect(() => {
    const offs = [kb.on("codeck.toggleNav", () => toggleCollapsed()), kb.on("workbench.action.openSettings", () => go("/settings")),
      kb.on("workbench.action.openGlobalKeybindings", () => go("/settings/shortcuts"))];
    return () => { for (const off of offs) off(); };
  });
</script>

{#snippet openList(compact: boolean)}
  {#each openRuns as run (run.g ? "g:" + run.g.id : run.items[0].id)}
    {#if run.g}
      {@const g = run.g}
      <button class="item sub pg" style="--g:{g.color}" onclick={() => work.toggleGroup(g.id)} title={g.collapsed ? "Expandir o grupo" : "Recolher o grupo"}>
        <ChevronRight size={11} class="chev {g.collapsed ? '' : 'open'}" /><span class="gdot"></span><span class="lbl">{g.name}</span><span class="n">{run.items.length}</span>
      </button>
      {#if !g.collapsed}
        {#each run.items as x (x.id)}{@render projItem(x, true)}{/each}
      {/if}
    {:else}
      {@render projItem(run.items[0], false)}
    {/if}
  {/each}
  {#if compact && work.projects.length > MAX_OPEN}<button class="item sub more" onclick={() => go("/projects")}>todos os projetos…</button>{/if}
{/snippet}

{#snippet projItem(x: Project, inGroup: boolean)}
  {@const ags = agentsOf(x.id)}
  <button class="item sub proj" class:ing={inGroup} class:on={projOn(x.id)} onclick={() => go("/work/" + x.id)} title={x.path}>
    <span class="lbl">{x.name}</span>
    {#each ags.slice(0, 3) as a (a.term.id)}<span class="ag" class:busy={a.session?.status === "working"} class:need={a.session?.status === "needs-you"}><AgentIcon provider={a.term.meta.provider} size={11} /></span>{/each}
  </button>
{/snippet}

<aside class="side" class:collapsed>
  <div class="brand">
    <span class="mk"><Mark size={26} /></span>
    {#if !collapsed}<div class="bn"><b>{BRAND.name}</b><span>{BRAND.short}</span></div>{/if}
  </div>

  <button class="search" onclick={() => (ui.palette = true)} title={collapsed ? `Buscar ou ir para… (${kb.label("workbench.action.showCommands")})` : ""}>
    <Search size={15} />{#if !collapsed}<span>Buscar ou ir para…</span><span class="kbd">{kb.label("workbench.action.showCommands")}</span>{/if}
  </button>

  <nav bind:this={navEl}>
    <span class="ind" class:ready={ind.ready} style="transform:translateY({ind.y}px);height:{ind.h}px"></span>
    {#each nav as n, i (n.id || n.group || i)}
      {#if n.group}
        {#if collapsed}<div class="sep"></div>{:else}<div class="grp">{n.group}</div>{/if}
      {:else}
        <button class="item" class:on={isOn(n.id)} onclick={() => go("/" + n.id)} onmouseenter={(e) => showFly(e, n)} onmouseleave={hideFly} aria-label={n.label}>
          <n.icon size={16} />
          {#if !collapsed}<span class="lbl">{n.label}</span>{/if}
          {#if n.live}<span class="live"></span>{/if}
          {#if SRC_OF[n.id]?.some(x => store.loadingOf(x))}<span class="ld" title="lendo agora…"></span>{/if}
          {#if n.count !== undefined && n.count !== null}<span class="count" class:hot={n.hot && n.count > 0 && !isOn(n.id)}>{n.count}</span>{/if}
        </button>
        {#if !collapsed && n.id === "projects" && work.projects.length && prefs.get("sidebar.openProjects")}
          <button class="item sub head" onclick={toggleOpenList}>
            <ChevronRight size={11} class="chev {openClosed ? '' : 'open'}" /><span class="lbl">Abertos</span><span class="n">{work.projects.length}</span>
          </button>
          {#if !openClosed}<div class="openlist" class:clip={work.projects.length > MAX_OPEN}>{@render openList(true)}</div>{/if}
        {/if}
        {#if !collapsed && n.id === "repos"}
          <div class="tree" bind:this={treeEl}><CollectionsTree compact /></div>
          {#each repos.pinned as r (r.id)}
            <button class="item sub" class:on={router.view === "repo" && router.param === r.id} onclick={() => go("/repo/" + r.id)}>
              <Pin size={12} /><span class="lbl">{r.name}</span>
              {#if r.status?.changes}<span class="chg" title="alterações não commitadas">{r.status.changes}</span>{/if}
            </button>
          {/each}
        {/if}
      {/if}
    {/each}
  </nav>

  <div class="foot">
    {#if !collapsed}
      <Switch checked={!paused} onchange={toggleAuto} label={paused ? "Automação pausada" : "Automação ativa"} />
      <div class="health">
        {#each s?.orgs || [] as o (o)}
          <span class:err={sourceErrors[o]} title={sourceErrors[o] || `Azure DevOps · ${o}`}><ProviderIcon provider="azure" size={12} />{o}</span>
        {/each}
        {#each s?.githubAccounts || [] as a (a.id)}
          <span class:err={sourceErrors["gh:" + a.login]} title={sourceErrors["gh:" + a.login] || `GitHub · @${a.login}`}><ProviderIcon provider="github" size={12} />{a.login}</span>
        {/each}
      </div>
    {/if}
    <div class="sync" class:on={store.refreshing && !store.offline} class:off={!!store.error || store.offline}>
      {#if !collapsed}
        <span class="state">
          <span class="pulse"></span>
          {#if store.error || store.offline || !s?.lastPoll}{#key syncText}<span class="txt">{syncText}</span>{/key}
          {:else}<span class="srcs">{#each SRC_LABEL as [k, l] (k)}<button class="src" class:on={store.loadingOf(k)} title={store.loadingOf(k) ? `lendo ${l}…` : store.updatedOf(k) ? `${l}: lido às ${time(store.updatedOf(k)!)} — clique para ler agora` : `${l}: ainda não lido`}
            onclick={() => store.refreshSource(k)}>{l}</button>{/each}</span>{/if}
        </span>
      {/if}
      <button class="btn ghost sm icon" title={store.refreshing ? "Lendo tudo…" : "Ler tudo agora"} aria-label="Atualizar" disabled={store.refreshing} onclick={manualRefresh}>
        <RefreshCw size={14} class={store.refreshing ? "spin" : ""} />
      </button>
      <button class="btn ghost sm icon" title={`${collapsed ? "Expandir" : "Recolher"} a barra lateral (${kb.label("codeck.toggleNav")})`} onclick={toggleCollapsed}>
        {#if collapsed}<PanelLeftOpen size={15} />{:else}<PanelLeftClose size={15} />{/if}
      </button>
    </div>
  </div>
</aside>

{#if collapsed && fly}
  <div class="fly card" style="top:{Math.min(fly.top - 6, window.innerHeight - 120)}px" role="menu" tabindex="-1" onmouseenter={keepFly} onmouseleave={hideFly}>
    <div class="fh">{fly.label}{#if fly.count}<span class="count">{fly.count}</span>{/if}</div>
    {#if fly.id === "work"}
      <button class="item sub" onclick={() => { fly = null; go("/projects"); }}><LayoutGrid size={13} /><span class="lbl">Hub de projetos</span></button>
      {#if work.projects.length}<div class="fsep">Abertos</div><div class="flist">{@render openList(false)}</div>{/if}
    {:else if fly.id === "repos"}
      <button class="item sub" onclick={() => { fly = null; go("/repos"); }}><FolderGit2 size={13} /><span class="lbl">Repositórios locais</span></button>
      <div class="flist"><CollectionsTree compact /></div>
      {#each repos.pinned as r (r.id)}
        <button class="item sub" onclick={() => { fly = null; go("/repo/" + r.id); }}><Pin size={12} /><span class="lbl">{r.name}</span></button>
      {/each}
    {/if}
  </div>
{/if}

<style>
  .side { width: var(--sidebar-w); flex: none; height: 100%; display: flex; flex-direction: column; gap: 12px; padding: 16px 10px 12px;
    background: var(--bg-2); border-right: 1px solid var(--line); transition: width 0.25s var(--ease-out), padding 0.25s var(--ease-out); }
  .side.collapsed { width: 60px; padding: 16px 8px 12px; }
  .brand { display: flex; align-items: center; gap: 10px; padding: 2px 8px 4px; }
  .collapsed .brand { padding: 2px 4px 4px; justify-content: center; }
  .mk { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line-2);
    box-shadow: var(--shadow-1); transition: transform var(--t-slow) var(--spring); flex: none; }
  .brand:hover .mk { transform: rotate(-8deg) scale(1.05); }
  .bn { display: grid; line-height: 1.15; white-space: nowrap; }
  .bn b { font-size: 15px; letter-spacing: -0.02em; }
  .bn span { font-size: 11px; color: var(--muted); }
  .search { display: flex; align-items: center; gap: 8px; height: 32px; padding: 0 8px 0 10px; border-radius: 9px; border: 1px solid var(--line);
    background: var(--surface); color: var(--muted); font: 13px var(--font); cursor: pointer; transition: border-color var(--t), color var(--t); white-space: nowrap; overflow: hidden; }
  .collapsed .search { justify-content: center; padding: 0; }
  .search:hover { border-color: var(--line-2); color: var(--text-2); }
  .search span:nth-child(2) { flex: 1; text-align: left; }
  nav { position: relative; flex: 1; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column; gap: 1px; margin: 0 -2px; padding: 0 2px; }
  .ind { position: absolute; left: 2px; right: 2px; top: 0; border-radius: 8px; background: var(--accent-soft); opacity: 0; pointer-events: none;
    transition: transform 0.42s var(--ease-out), height 0.42s var(--ease-out), opacity 0.2s; }
  .ind::before { content: ""; position: absolute; left: -10px; top: 22%; bottom: 22%; width: 3px; border-radius: 0 3px 3px 0; background: var(--accent); }
  .collapsed .ind::before { left: -8px; }
  .ind.ready { opacity: 1; }
  .grp { font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.08em; color: var(--faint); padding: 14px 10px 6px; white-space: nowrap; }
  .sep { height: 1px; margin: 8px 6px; background: var(--line); }
  .item { position: relative; z-index: 1; display: flex; align-items: center; gap: 10px; height: 32px; padding: 0 10px; border: 0; border-radius: 8px; flex: none;
    background: none; color: var(--text-2); font: 500 13px var(--font); cursor: pointer; text-align: left; transition: color var(--t), background var(--t), padding var(--t) var(--ease); }
  .collapsed nav .item { justify-content: center; padding: 0; }
  .item:hover { color: var(--text); background: color-mix(in srgb, var(--surface-2) 60%, transparent); }
  .side:not(.collapsed) .item:hover:not(.on) { padding-left: 12px; }
  .item.on { color: var(--text); font-weight: 600; background: none; }
  .item.on :global(svg) { color: var(--accent); }
  .item.sub { height: 27px; padding-left: 36px; font-size: 12.5px; gap: 8px; }
  .side:not(.collapsed) .item.sub:hover:not(.on) { padding-left: 38px; }
  .item.sub.head { height: 24px; padding-left: 22px; font: 600 11.5px var(--font); color: var(--muted); }
  .item.sub.pg { height: 25px; padding-left: 30px; font-weight: 600; color: var(--text-2); }
  .item.sub.proj.ing { padding-left: 46px; }
  .side:not(.collapsed) .item.sub.proj.ing:hover:not(.on) { padding-left: 48px; }
  .item.sub.more { color: var(--accent); font-size: 12px; }
  .item :global(.chev) { flex: none; transition: transform var(--t) var(--ease); }
  .item :global(.chev.open) { transform: rotate(90deg); }
  .gdot { width: 8px; height: 8px; border-radius: 3px; background: var(--g); flex: none; }
  .n { font-size: 11px; color: var(--faint); font-variant-numeric: tabular-nums; }
  .openlist { display: flex; flex-direction: column; gap: 1px; }
  .openlist.clip { max-height: 230px; overflow-y: auto; overflow-x: hidden; mask-image: linear-gradient(180deg, #000 85%, transparent); }
  .tree { position: relative; z-index: 1; }
  .ag { display: inline-grid; place-items: center; border-radius: 50%; padding: 1px; }
  .ag.busy { box-shadow: 0 0 0 2px var(--accent-soft); animation: live 1.6s infinite; }
  .ag.need { box-shadow: 0 0 0 2px var(--warn); }
  .lbl { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .count { font: 650 11px/1 var(--font); font-variant-numeric: tabular-nums; padding: 3px 7px; border-radius: 99px; background: var(--surface-2); color: var(--text-2);
    border: 1px solid var(--line); transition: background var(--t), color var(--t); }
  .collapsed nav .count { position: absolute; top: 1px; right: 0; padding: 2px 4px; font-size: 9.5px; min-width: 15px; text-align: center; }
  .collapsed nav .count:not(.hot) { display: none; }
  .item.on .count { background: var(--accent); color: var(--accent-ink); border-color: transparent; }
  .count.hot { background: var(--bad); color: #fff; border-color: transparent; }
  .chg { font: 650 10px/1 var(--font); color: var(--warn); }
  .live { width: 7px; height: 7px; border-radius: 50%; background: var(--warn); box-shadow: 0 0 0 0 var(--warn); animation: live 1.6s infinite; }
  .collapsed nav .live { position: absolute; bottom: 5px; right: 8px; width: 6px; height: 6px; }
  @keyframes live { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--warn) 60%, transparent); } 70% { box-shadow: 0 0 0 6px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
  .foot { display: grid; gap: 10px; padding: 12px 8px 0; border-top: 1px solid var(--line); }
  .collapsed .foot { padding: 10px 0 0; justify-items: center; }
  .health { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 11.5px; color: var(--text-2); }
  .health span { display: inline-flex; align-items: center; gap: 5px; }
  .health .err { color: var(--bad); }
  .sync { display: flex; align-items: center; gap: 4px; font-size: 11.5px; color: var(--muted); min-height: 27px; }
  .collapsed .sync { flex-direction: column; }
  .state { flex: 1; min-width: 0; display: flex; align-items: center; gap: 7px; }
  .txt { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; animation: rise 0.3s var(--ease-out); }
  .sync.on .txt { color: var(--text-2); }
  /* ponto de status: verde parado quando em dia, azul pulsando enquanto lê, vermelho se o backend caiu */
  .pulse { width: 7px; height: 7px; border-radius: 50%; flex: none; background: var(--good); transition: background var(--t); }
  .sync.on .pulse { background: var(--accent); animation: ping 1.2s var(--ease) infinite; }
  .sync.off .pulse { background: var(--bad); }
  @keyframes ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 65%, transparent); } 80%, 100% { box-shadow: 0 0 0 7px transparent; } }
  .collapsed .sync.off :global(.btn:first-child) { color: var(--bad); }
  /* popover da barra recolhida */
  .fly { position: fixed; left: 64px; z-index: 90; min-width: 230px; max-width: 300px; max-height: min(70vh, 560px); overflow: auto; padding: 6px;
    box-shadow: var(--shadow-3); display: flex; flex-direction: column; gap: 1px; animation: pop 0.14s var(--ease-out); }
  @keyframes pop { from { opacity: 0; transform: translateX(-4px); } }
  .fh { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 10px 6px; font: 650 12.5px var(--font); color: var(--text); }
  .fsep { font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.08em; color: var(--faint); padding: 10px 10px 4px; }
  .fly .item.sub { padding-left: 12px; justify-content: flex-start; }
  .fly .item.sub.pg { padding-left: 8px; }
  .fly .item.sub.proj.ing { padding-left: 26px; }
  .flist { display: flex; flex-direction: column; gap: 1px; }
  .flist :global(.it), .flist :global(.gh) { padding-left: 12px !important; }
  .flist :global(.sub) { padding-left: 26px !important; }
  .ld { width: 12px; height: 12px; border-radius: 50%; border: 1.5px solid var(--accent-line); border-top-color: var(--accent); animation: spin 0.9s linear infinite; flex: none; }
  .srcs { display: inline-flex; gap: 2px; flex-wrap: wrap; }
  .src { border: 0; background: none; padding: 1px 4px; border-radius: 5px; color: var(--muted); font: 500 11px var(--font); cursor: pointer; transition: color var(--t), background var(--t); }
  .src:hover { color: var(--text); background: var(--surface-2); }
  .src.on { color: var(--accent); background: var(--accent-soft); animation: breathe-src 1.2s var(--ease) infinite; }
  @keyframes breathe-src { 50% { opacity: 0.55; } }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
