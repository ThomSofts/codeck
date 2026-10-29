<script lang="ts" module>
  let boardsCache: { boards: Board[]; errors: Record<string, string> } | null = null;   // a lista de quadros vale pela sessão
  type Board = { id: string; provider: "azure" | "github"; org: string; project: string; title: string; team?: string; url: string; number?: number };
</script>

<script lang="ts">
  // Sprints e projetos: a sprint de um time do Azure Boards (colunas = categoria de estado: a fazer → em andamento →
  // feito) ou um Project do GitHub (colunas = campo Status). Arrastar um cartão muda o estado/status lá; clicar abre a
  // gaveta da issue/work item (editar, comentar, "Implementar com IA" num projeto local); o ✦ do cartão manda direto
  // para a IA com o item referenciado. Rascunho do Project vira issue num repositório dele.
  import { ArrowUpRight, CalendarRange, Clock, ExternalLink, FileText, GitPullRequest, KanbanSquare, MessageSquare, RefreshCw, Sparkles, Bot, CircleDot, Users } from "@lucide/svelte";
  import { flip } from "svelte/animate";
  import { untrack } from "svelte";
  import { get, post } from "../lib/api";
  import { askIssue, issueToBoard, startIssueTask } from "../lib/issues";
  import { matchesAssignee, people, personOf } from "../lib/people";
  import { go } from "../lib/router.svelte";
  import { ui } from "../lib/ui.svelte";
  import { work } from "../lib/work.svelte";
  import Drawer from "../components/Drawer.svelte";
  import Empty from "../components/Empty.svelte";
  import Menu from "../components/Menu.svelte";
  import Page from "../components/Page.svelte";
  import ProviderIcon from "../components/ProviderIcon.svelte";
  import Skeleton from "../components/Skeleton.svelte";
  import Toolbar from "../components/Toolbar.svelte";
  import IssueDetail from "../components/work/IssueDetail.svelte";
  import { openPr } from "../components/pr/history";

  type Sprint = { id: string; name: string; start?: string | null; finish?: string | null; timeFrame?: string | null };
  type Col = { id: string; name: string; color?: string | null };
  type Item = any;
  type Data = { id: string; provider: "azure" | "github"; sprint: Sprint | null; sprints: Sprint[]; sprintLabel?: string; columns: Col[]; items: Item[];
    statusField?: string; repos?: string[]; title?: string; url?: string };

  const LS = "codeck.sprints.board";
  let boards = $state(boardsCache);
  let bid = $state<string>((() => { try { return localStorage.getItem(LS) || ""; } catch { return ""; } })());
  let sprint = $state<string | null>(null);
  let data = $state<Data | null>(null);
  let err = $state("");
  let loading = $state(false);
  let q = $state("");
  let who = $state("");

  async function loadBoards(fresh = false) {
    if (boards && !fresh) return;
    try { boards = boardsCache = await get("boards"); }
    catch (e: any) { boards = { boards: [], errors: { geral: e.message || String(e) } }; }
  }
  $effect(() => { untrack(() => loadBoards()); });
  const list = $derived(boards?.boards || []);
  const board = $derived(list.find(b => b.id === bid) || null);
  $effect(() => {   // sem escolha (ou o quadro sumiu): o primeiro da lista
    if (list.length && !board) untrack(() => pick(list[0].id));
  });
  function pick(id: string) {
    bid = id; sprint = null; data = null; err = "";
    try { localStorage.setItem(LS, id); } catch { /* sem armazenamento */ }
  }

  let pending = 0;   // movimentos em voo: a releitura não pode desfazer o que a tela acabou de mover
  async function load(quiet = false) {
    const id = bid, sp = sprint;
    if (!id) return;
    if (!quiet) loading = true;
    try {
      const r = await get<Data>("board", { id, sprint: sp || undefined });
      // igual ao que está na tela: mantém o mesmo objeto (nada pisca); trocou de quadro no meio: descarta
      if (id === bid && sp === sprint && !pending && JSON.stringify(r) !== JSON.stringify(data)) data = r;
      err = "";
    } catch (e: any) { if (id === bid) err = e.message || String(e); }
    if (!quiet) loading = false;
  }
  $effect(() => { void bid; void sprint; untrack(() => load()); });
  // ao vivo: relê a cada 45 s com a janela visível (outra pessoa moveu um cartão, a IA terminou uma task…)
  $effect(() => {
    const t = setInterval(() => { if (document.visibilityState === "visible" && !dragKey && !opened) load(true); }, 45000);
    return () => clearInterval(t);
  });

  // ------------------------------------------------------------ filtros
  const items = $derived((data?.items || []).filter((i: Item) => matchesAssignee(i.assignees, who)
    && (!q || `${i.number ?? ""} ${i.title} ${i.type} ${(i.labels || []).map((l: any) => l.name).join(" ")} ${(i.assignees || []).map((a: any) => a.login).join(" ")} ${i.parent?.title || ""}`
      .toLowerCase().includes(q.toLowerCase()))));
  const byCol = (c: string) => items.filter((i: Item) => (i.column || "") === c);
  const whoOptions = $derived.by(() => {
    const ps = Object.keys(people()).sort((a, b) => a.localeCompare(b));
    const loose = new Map<string, number>();
    for (const i of data?.items || []) for (const a of i.assignees || []) if (a.login && !personOf(a)) loose.set(a.login, (loose.get(a.login) || 0) + 1);
    return { ps, loose: [...loose.entries()].sort((a, b) => a[0].localeCompare(b[0])) };
  });

  // ------------------------------------------------------------ sprint: datas e andamento
  // datas da sprint são dias (o Azure manda meia-noite UTC): só a parte da data, senão no Brasil virava o dia anterior
  const day = (iso: string, t: string) => new Date(iso.slice(0, 10) + t);
  const fmt = (iso?: string | null) => (iso ? day(iso, "T12:00:00").toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }).replace(".", "") : "");
  const daysLeft = $derived.by(() => {
    const f = data?.sprint?.finish;
    if (!f || data?.sprint?.timeFrame !== "current") return null;
    return Math.max(0, Math.ceil((day(f, "T23:59:59").getTime() - Date.now()) / 864e5));
  });
  const doneCol = $derived(data ? (data.provider === "azure" ? "Completed" : data.columns.find(c => /done|feito|conclu|closed|pronto/i.test(c.name))?.id ?? null) : null);
  const progress = $derived.by(() => {
    const all = data?.items || [];
    const done = doneCol == null ? 0 : all.filter((i: Item) => i.column === doneCol).length;
    return { done, total: all.length, pct: all.length ? Math.round((done / all.length) * 100) : 0 };
  });
  const colColor = (c: Col) => c.color || ({ Proposed: "var(--muted)", InProgress: "var(--accent)", Resolved: "var(--info)", Completed: "var(--good)" } as Record<string, string>)[c.id] || "var(--muted)";
  const hours = (c: string) => byCol(c).reduce((n: number, i: Item) => n + (Number(i.remaining) || 0), 0);
  // cor do tipo do Azure (a mesma do Boards) e o tipo do GitHub
  const TYPE: Record<string, string> = { Bug: "#cc293d", Task: "#f2cb1d", "Product Backlog Item": "#009ccc", "User Story": "#009ccc", Feature: "#773b93",
    Epic: "#ff7b00", Issue: "#3fb950", PR: "#a371f7", Rascunho: "#8b949e", Impediment: "#cc293d" };
  const typeColor = (i: Item) => TYPE[i.type] || "var(--muted)";
  const initials = (n: string) => n.split(/[\s.@_-]+/).filter(Boolean).slice(0, 2).map(x => x[0]?.toUpperCase()).join("");

  // ------------------------------------------------------------ arrastar entre colunas (otimista; volta se recusar)
  let dragKey = $state<string | null>(null);
  let overCol = $state<string | null>(null);
  function startDrag(e: DragEvent, i: Item) {
    dragKey = i.key;
    e.dataTransfer?.setData("text/plain", i.key);
    if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
  }
  function over(e: DragEvent, c: string) { if (!dragKey) return; e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = "move"; overCol = c; }
  async function dropOn(c: string) {
    const it = data?.items.find((x: Item) => x.key === dragKey);
    dragKey = null; overCol = null;
    if (!it || (it.column || "") === c || !data) return;
    await moveTo(it, c);
  }
  async function moveTo(it: Item, c: string) {
    if (!data) return;
    const before = { column: it.column, state: it.state };
    it.column = c;
    if (data.provider === "azure") it.state = data.columns.find(x => x.id === c)?.name || it.state;
    pending++;
    try {
      const r = await post<{ state?: string }>("board/move", { id: data.id, column: c,
        item: { number: it.number, type: it.type, repo: it.repo, itemId: it.itemId, statusField: data.statusField } });
      if (r.state) it.state = r.state;
      it.flash = true;
      setTimeout(() => (it.flash = false), 2200);
    } catch (e) { Object.assign(it, before); ui.error(e); }
    pending--;
  }
  const moveItems = (it: Item) => (data?.columns || []).filter(c => c.id !== (it.column || "")).map(c => ({ label: `Mover para ${c.name}`, onclick: () => moveTo(it, c.id) }));

  // ------------------------------------------------------------ abrir, IA, rascunho → issue
  let opened = $state<Item | null>(null);
  let draft = $state<Item | null>(null);
  function open(i: Item) {
    if (i.kind === "draft") draft = i;
    else if (i.kind === "pr") openPr(i.key);
    else opened = i;
  }
  /** Rascunho não tem número nem repositório: vai o texto dele, no projeto ativo. */
  function askDraft(i: Item, flow?: string) {
    work.askFrom(null, { title: i.title, text: `${i.title}\n\n${i.body || ""}`.trim(), flow });
  }
  function cardMenu(i: Item) {
    if (i.kind === "draft") return [
      { label: "Implementar com IA", icon: Sparkles, onclick: () => askDraft(i, "implement") },
      { label: "Planejar com IA", icon: Sparkles, onclick: () => askDraft(i, "plan") },
      { separator: true },
      ...(data?.repos || []).map(r => ({ label: `Transformar em issue em ${r}`, icon: CircleDot, onclick: () => toIssue(i, r) })),
      ...(data?.repos?.length ? [] : [{ label: "Ligue um repositório ao Project para transformar em issue", disabled: true }]),
      { separator: true }, ...moveItems(i),
    ];
    if (i.kind === "pr") return [{ label: "Abrir a PR no app", icon: GitPullRequest, onclick: () => openPr(i.key) }, { separator: true }, ...moveItems(i),
      { separator: true }, { label: "Abrir no navegador", icon: ExternalLink, href: i.url }];
    return [
      { label: "Implementar direto com IA", icon: Sparkles, onclick: () => askIssue(i, "implement") },
      { label: "Planejar e implementar com IA", icon: Sparkles, onclick: () => askIssue(i, "plan-implement") },
      { label: "Planejar com IA", icon: Sparkles, onclick: () => askIssue(i, "plan") },
      { label: "Começar tarefa (formulário completo)", icon: Bot, onclick: () => startIssueTask(i) },
      { label: "Adicionar ao quadro local", icon: KanbanSquare, onclick: () => issueToBoard(i) },
      { separator: true }, ...moveItems(i),
      { separator: true }, { label: "Abrir no navegador", icon: ExternalLink, href: i.url },
    ];
  }
  async function toIssue(i: Item, repo: string) {
    const prog = ui.progress(`Criando a issue em ${repo}…`);
    try {
      const r = await post<{ number: number; url: string }>("board/draft-to-issue", { id: data!.id, itemId: i.itemId, repo });
      prog.done(`Issue #${r.number} criada em ${repo}`);
      draft = null;
      await load(true);
    } catch (e) { prog.fail(e); }
  }
  const scopeErr = $derived(/escopo project|acesso aos Projects/i.test(err) || Object.values(boards?.errors || {}).some(v => /escopo project|acesso aos Projects/i.test(v)));
  const label = (b: Board) => (b.provider === "azure" ? `${b.project} · ${b.title}` : b.title);
  const groups = $derived.by(() => {
    const m = new Map<string, Board[]>();
    for (const b of list) { const k = b.provider === "azure" ? `Azure · ${b.org}` : `GitHub · ${b.org}`; m.set(k, [...(m.get(k) || []), b]); }
    return [...m.entries()];
  });
</script>

<Page title="Sprints e projetos" sub="A sprint de cada time do Azure Boards e os Projects do GitHub em colunas — arraste para mudar o estado, clique para ver e mandar para a IA">
  {#if !boards}
    <Skeleton rows={6} />
  {:else if !list.length}
    <Empty title="Nenhum quadro encontrado" text={Object.keys(boards.errors).length ? Object.entries(boards.errors).map(([k, v]) => `${k}: ${v}`).join(" · ")
      : "Conecte uma organização do Azure DevOps ou uma conta do GitHub com Projects em Contas e ajustes."}>
      <button class="btn" onclick={() => go("/settings/accounts")}>Contas e ajustes</button>
      <button class="btn ghost" onclick={() => loadBoards(true)}><RefreshCw size={14} /> Procurar de novo</button>
    </Empty>
  {:else}
    <Toolbar bind:query={q} placeholder="Buscar por título, número, tipo, etiqueta, responsável…">
      {#snippet left()}
        <select class="select bsel" value={bid} onchange={(e) => pick((e.currentTarget as HTMLSelectElement).value)} title="Quadro">
          {#each groups as [g, bs] (g)}<optgroup label={g}>{#each bs as b (b.id)}<option value={b.id}>{label(b)}</option>{/each}</optgroup>{/each}
        </select>
        {#if data?.sprints?.length}
          <select class="select ssel" value={data.sprint?.id || ""} onchange={(e) => (sprint = (e.currentTarget as HTMLSelectElement).value || null)} title={data.sprintLabel || "Sprint"}>
            {#if data.provider === "github"}<option value="">Todas as {(data.sprintLabel || "iterações").toLowerCase()}</option>{/if}
            {#each data.sprints as sp (sp.id)}<option value={sp.id}>{sp.name}{sp.timeFrame === "current" ? " · atual" : sp.timeFrame === "past" ? " · encerrada" : ""}</option>{/each}
          </select>
        {/if}
      {/snippet}
      <select class="select" style="width:auto;min-width:160px" bind:value={who} title="Responsável">
        <option value="">Qualquer responsável</option>
        <option value="-">Sem responsável</option>
        {#if whoOptions.ps.length}<optgroup label="Pessoas (Configurações)">{#each whoOptions.ps as p (p)}<option value={"p:" + p}>{p}</option>{/each}</optgroup>{/if}
        {#if whoOptions.loose.length}<optgroup label="No quadro">{#each whoOptions.loose as [n, c] (n)}<option value={"u:" + n}>{n} ({c})</option>{/each}</optgroup>{/if}
      </select>
      <button class="btn sm ghost icon" title="Pessoas: juntar os nomes de cada conta" onclick={() => go("/settings/accounts")}><Users size={14} /></button>
      <button class="btn sm ghost icon" title="Ler de novo" onclick={() => { loadBoards(true); load(); }}><RefreshCw size={14} class={loading ? "spin" : ""} /></button>
      {#if board}<a class="btn sm ghost icon" href={data?.url || board.url} target="_blank" rel="noopener" title="Abrir no navegador"><ExternalLink size={14} /></a>{/if}
    </Toolbar>

    {#if data}
      <div class="sum">
        <ProviderIcon provider={data.provider} size={14} />
        {#if data.sprint}<span class="sp"><CalendarRange size={13} /> <b>{data.sprint.name}</b>
          {#if data.sprint.start}<span class="muted">{fmt(data.sprint.start)} – {fmt(data.sprint.finish)}</span>{/if}
          {#if daysLeft !== null}<span class="pill {daysLeft <= 2 ? 'warn' : 'neutral'}">{daysLeft === 0 ? "termina hoje" : `${daysLeft} dia${daysLeft === 1 ? "" : "s"} restante${daysLeft === 1 ? "" : "s"}`}</span>{/if}</span>
        {:else}<span class="muted">{data.title || board?.title}</span>{/if}
        <span class="spacer"></span>
        {#if doneCol != null}<span class="prog" title={`${progress.done} de ${progress.total} concluídos`}><i style="width:{progress.pct}%"></i></span>
          <span class="small muted">{progress.done}/{progress.total} · {progress.pct}%</span>{/if}
      </div>
    {/if}

    {#if err}
      <div class="errbox">{err}{#if scopeErr} <button class="btn sm" onclick={() => go("/settings/accounts")}>Entrar de novo com o GitHub</button>{/if}</div>
    {:else if !data}
      <Skeleton rows={6} />
    {:else}
      <div class="board">
        {#each data.columns as c (c.id)}
          {@const cards = byCol(c.id)}
          {@const h = data.provider === "azure" ? hours(c.id) : 0}
          <section class="col" style="--c:{colColor(c)}" class:target={overCol === c.id} aria-label={c.name}
            ondragover={(e) => over(e, c.id)} ondrop={(e) => { e.preventDefault(); dropOn(c.id); }}
            ondragleave={(e) => { if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) overCol = null; }}>
            <header><span class="cd"></span><b class="ell">{c.name}</b><span class="n">{cards.length}</span>{#if h}<span class="h" title="Trabalho restante"><Clock size={11} /> {h} h</span>{/if}</header>
            <div class="cards">
              {#each cards as i (i.key)}
                <article class="kc" class:dragging={dragKey === i.key} class:flash={i.flash} style="--t:{typeColor(i)}"
                  draggable="true" ondragstart={(e) => startDrag(e, i)} ondragend={() => { dragKey = null; overCol = null; }}
                  oncontextmenu={(e) => ui.contextMenu(e, cardMenu(i))} animate:flip={{ duration: 180 }}>
                  <button class="hit" aria-label={`Abrir “${i.title}”`} onclick={() => open(i)}></button>
                  <div class="top">
                    <span class="ty">{i.type}</span>
                    {#if i.number}<span class="num">#{i.number}</span>{/if}
                    {#if data.provider === "azure" && i.state && i.state !== c.name}<span class="st" style="--s:{i.stateColor || 'var(--muted)'}">{i.state}</span>{/if}
                    <span class="spacer"></span>
                    <span class="act" role="presentation" onclick={(e) => e.stopPropagation()}>
                      <button class="ib ai" title="Implementar direto com IA (o item vai referenciado)" onclick={() => (i.kind === "draft" ? askDraft(i, "implement") : askIssue(i, "implement"))}
                        hidden={i.kind === "pr"}><Sparkles size={13} /></button>
                      <Menu items={cardMenu(i)} />
                    </span>
                  </div>
                  <p class="t">{i.title}</p>
                  {#if i.parent?.title}<p class="par ell" title={`#${i.parent.id} ${i.parent.title}`}><ArrowUpRight size={11} /> {i.parent.title}</p>{/if}
                  {#if i.labels?.length}<div class="lbs">{#each i.labels.slice(0, 3) as l (l.name)}<span class="lb" style="--l:{l.color || 'var(--muted)'}">{l.name}</span>{/each}</div>{/if}
                  <footer>
                    {#if i.kind === "draft"}<span class="m"><FileText size={11} /> rascunho</span>{/if}
                    {#if i.repo && data.provider === "github"}<span class="m ell">{i.repo.split("/")[1]}</span>{/if}
                    {#if i.remaining}<span class="m" title="Trabalho restante"><Clock size={11} /> {i.remaining} h</span>{/if}
                    {#if i.points}<span class="m" title="Pontos">{i.points} pt</span>{/if}
                    {#if i.priority && i.priority <= 1}<span class="m bad" title="Prioridade">P{i.priority}</span>{/if}
                    {#if i.comments}<span class="m"><MessageSquare size={11} /> {i.comments}</span>{/if}
                    <span class="spacer"></span>
                    {#each (i.assignees || []).slice(0, 2) as a (a.login)}
                      {#if a.avatar}<img class="av" src={a.avatar} alt={a.login} title={personOf(a) || a.login} />
                      {:else}<span class="av ini" title={personOf(a) || a.login}>{initials(personOf(a) || a.login)}</span>{/if}
                    {/each}
                  </footer>
                </article>
              {:else}
                <div class="none">{overCol === c.id ? "Soltar aqui" : "—"}</div>
              {/each}
            </div>
          </section>
        {/each}
      </div>
    {/if}
  {/if}
</Page>

{#if opened}<IssueDetail item={opened} onclose={() => { opened = null; load(true); }} onboard={(i) => issueToBoard(i)} onchange={(p) => {
  // a edição da gaveta vale no cartão na hora; a coluna (o estado mudou de categoria) acerta na releitura ao fechar
  for (const x of data?.items || []) if (x.key === opened.key) Object.assign(x, p);
  Object.assign(opened, p);
}} />{/if}

{#if draft}
  <Drawer title={draft.title} subtitle="Rascunho do Project — ainda não é issue" onclose={() => (draft = null)}>
    <div class="dbody">{#if draft.body}{draft.body}{:else}<span class="muted">Sem descrição.</span>{/if}</div>
    {#snippet footer()}
      <button class="btn" onclick={() => askDraft(draft, "implement")}><Sparkles size={14} /> Implementar com IA</button>
      <span class="spacer"></span>
      {#if data?.repos?.length}
        <Menu small={false} items={data.repos.map(r => ({ label: r, icon: CircleDot, onclick: () => toIssue(draft, r) }))}>
          {#snippet trigger()}<span class="btn primary"><CircleDot size={14} /> Transformar em issue</span>{/snippet}</Menu>
      {:else}<span class="small muted">Ligue um repositório ao Project para transformar em issue</span>{/if}
    {/snippet}
  </Drawer>
{/if}

<style>
  .bsel { width: auto; min-width: 230px; max-width: 360px; }
  .ssel { width: auto; min-width: 170px; }
  .sum { display: flex; align-items: center; gap: 10px; margin: 0 2px 10px; flex: none; font-size: 13px; }
  .sp { display: inline-flex; align-items: center; gap: 7px; }
  .spacer { flex: 1; }
  .prog { width: 160px; height: 6px; border-radius: 99px; background: var(--surface-3); overflow: hidden; }
  .prog i { display: block; height: 100%; background: var(--good); border-radius: inherit; transition: width 0.4s var(--ease-out); }
  .errbox { padding: 12px 14px; border-radius: 10px; background: var(--bad-soft); color: var(--bad); font-size: 13px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .board { flex: 1; min-height: 0; display: flex; gap: 12px; overflow-x: auto; padding-bottom: 8px; align-items: stretch; }
  .col { flex: 1 0 280px; max-width: 420px; display: flex; flex-direction: column; min-height: 0; border-radius: var(--r); background: var(--bg-2);
    border: 1px solid var(--line); transition: border-color var(--t), background var(--t); }
  .col.target { border-color: color-mix(in srgb, var(--c) 60%, transparent); background: color-mix(in srgb, var(--c) 6%, var(--bg-2)); }
  header { display: flex; align-items: center; gap: 8px; padding: 11px 12px 8px; font-size: 13px; }
  .cd { width: 9px; height: 9px; border-radius: 3px; background: var(--c); flex: none; }
  header b { flex: 1; min-width: 0; }
  .n { font: 650 11px var(--font); color: var(--muted); font-variant-numeric: tabular-nums; }
  .h { display: inline-flex; align-items: center; gap: 3px; font: 600 11px var(--font); color: var(--text-2); }
  .cards { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding: 2px 8px 10px; }
  .none { padding: 14px; text-align: center; color: var(--faint); font-size: 12px; border: 1px dashed var(--line-2); border-radius: 10px; }
  .kc { position: relative; display: flex; flex-direction: column; gap: 6px; padding: 9px 10px 9px 13px; flex: none; border-radius: 10px; background: var(--surface);
    border: 1px solid var(--line); box-shadow: var(--shadow-1); animation: rise 0.22s var(--ease-out) both;
    transition: border-color var(--t-fast), opacity var(--t-fast), box-shadow var(--t); }
  .kc::before { content: ""; position: absolute; left: 0; top: 8px; bottom: 8px; width: 3px; border-radius: 0 3px 3px 0; background: var(--t); }
  .kc:hover { border-color: var(--line-3); }
  .kc:has(.hit:focus-visible) { box-shadow: var(--ring); border-color: var(--accent); }
  .kc.dragging { opacity: 0.35; }
  .kc.flash { box-shadow: 0 0 0 2px var(--accent-line); }
  .hit { position: absolute; inset: 0; z-index: 0; border: 0; border-radius: inherit; background: none; cursor: pointer; padding: 0; }
  .hit:focus { outline: none; }
  .top, .t, .par, .lbs, footer { position: relative; pointer-events: none; }
  .top { display: flex; align-items: center; gap: 6px; font-size: 11.5px; min-height: 22px; }
  .ty { font: 650 10.5px var(--font); color: color-mix(in srgb, var(--t) 75%, var(--text)); text-transform: uppercase; letter-spacing: 0.04em; }
  .num { color: var(--muted); font-variant-numeric: tabular-nums; }
  .st { display: inline-flex; align-items: center; gap: 4px; color: var(--text-2); }
  .st::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--s); }
  .act { display: inline-flex; align-items: center; gap: 2px; opacity: 0; transition: opacity var(--t-fast); pointer-events: auto; z-index: 1; }
  .kc:hover .act, .kc:focus-within .act { opacity: 1; }
  .ib { display: grid; place-items: center; width: 24px; height: 22px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; }
  .ib:hover { background: var(--surface-3); color: var(--text); }
  .ib.ai { color: var(--accent); }
  .t { margin: 0; font-size: 13px; line-height: 1.4; font-weight: 550; display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  .par { margin: 0; display: flex; align-items: center; gap: 4px; font-size: 11.5px; color: var(--muted); }
  .lbs { display: flex; flex-wrap: wrap; gap: 4px; }
  .lb { display: inline-flex; align-items: center; height: 18px; padding: 0 7px; border-radius: 5px; font: 600 10.5px var(--font);
    background: color-mix(in srgb, var(--l) 16%, transparent); color: color-mix(in srgb, var(--l) 70%, var(--text)); }
  footer { display: flex; align-items: center; gap: 8px; font-size: 11.5px; color: var(--muted); min-height: 20px; }
  .m { display: inline-flex; align-items: center; gap: 3px; min-width: 0; }
  .m.bad { color: var(--bad); font-weight: 650; }
  .av { width: 20px; height: 20px; border-radius: 50%; flex: none; margin-left: -4px; border: 2px solid var(--surface); }
  .ini { display: grid; place-items: center; background: var(--surface-3); color: var(--text-2); font: 650 9px var(--font); }
  .dbody { white-space: pre-wrap; font-size: 13px; color: var(--text-2); padding-top: 12px; }
</style>
