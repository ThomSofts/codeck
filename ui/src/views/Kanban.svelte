<script lang="ts">
  // Quadro: kanban editável (colunas e cartões seus) que a IA pode planejar e implementar — cada cartão diz o grupo e
  // os projetos; "Planejar"/"Implementar" no cartão cria a tarefa (worktrees) e abre o agente com todo o contexto.
  // A aba "Tarefas dos agentes" é o quadro automático das tarefas em worktree, pelo estado dos agentes.
  import { ArrowLeftRight, CalendarClock, ClipboardList, Columns3, GripVertical, Hammer, Layers, Lightbulb, Pencil, Plus, Settings2, Sparkles, Star, Trash2, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { kanban, PRIORITY, type Card, type Column } from "../lib/kanban.svelte";
  import { repos } from "../lib/repos.svelte";
  import { go, router } from "../lib/router.svelte";
  import { ui } from "../lib/ui.svelte";
  import { STATUS, work, type Flow } from "../lib/work.svelte";
  import Drawer from "../components/Drawer.svelte";
  import Empty from "../components/Empty.svelte";
  import Menu from "../components/Menu.svelte";
  import Page from "../components/Page.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Switch from "../components/Switch.svelte";
  import Toolbar from "../components/Toolbar.svelte";
  import Board from "../components/work/Board.svelte";
  import CardEditor from "../components/kanban/CardEditor.svelte";
  import CardRun from "../components/kanban/CardRun.svelte";

  const tab = $derived(router.parts[1] === "agents" ? "agents" : "cards");
  $effect(() => kanban.watch());
  $effect(() => { if (!repos.loaded) untrack(() => repos.load(false)); });

  let q = $state("");
  let groupF = $state("any");
  let projF = $state("any");
  let prioF = $state("any");
  let editing = $state<{ card: Card | null; column?: string | null } | null>(null);
  let running = $state<{ card: Card; flow: Flow | null } | null>(null);
  let columnsOpen = $state(false);
  // /board/new (⌘K "Novo cartão") e /board/c/<id> abrem o editor
  $effect(() => {
    const p = router.parts;
    if (p[1] === "new") untrack(() => { editing = { card: null }; go("/board", "soft"); });
    else if (p[1] === "c" && p[2] && kanban.loaded) untrack(() => { const c = kanban.cards.find(x => x.id === p[2]); if (c) editing = { card: c }; go("/board", "soft"); });
  });

  const filtered = $derived.by(() => {
    const t = q.trim().toLowerCase();
    return kanban.cards.filter(c => (!t || `${c.title} ${c.description} ${c.labels.join(" ")}`.toLowerCase().includes(t))
      && (groupF === "any" || (groupF === "none" ? !c.groupId : c.groupId === groupF))
      && (projF === "any" || c.projects.includes(projF) || c.refs.includes(projF))
      && (prioF === "any" || c.priority === prioF));
  });
  const byCol = (id: string) => filtered.filter(c => c.column === id).sort((a, b) => a.order - b.order);
  const working = $derived(kanban.cards.filter(c => c.live?.status === "working").length);
  const need = $derived(kanban.cards.filter(c => c.live?.status === "needs-you").length);
  const projectsUsed = $derived([...new Set(kanban.cards.flatMap(c => [...c.projects, ...c.refs]))].map(id => repos.byId(id)).filter(Boolean));

  // ------------------------------------------------------------ arrastar e soltar
  let dragId = $state<string | null>(null);
  let drop = $state<{ col: string; index: number } | null>(null);
  function over(e: DragEvent, colId: string) {
    if (!dragId) return;
    e.preventDefault();
    const list = (e.currentTarget as HTMLElement).querySelectorAll<HTMLElement>("[data-card]");
    let index = 0;
    for (const el of list) { if (el.dataset.card === dragId) continue; const r = el.getBoundingClientRect(); if (e.clientY > r.top + r.height / 2) index++; }
    if (drop?.col !== colId || drop.index !== index) drop = { col: colId, index };
  }
  function dropped(e: DragEvent, colId: string) {
    e.preventDefault();
    if (dragId && drop) kanban.move(dragId, colId, drop.index);
    dragId = null; drop = null;
  }

  const LIVE: Record<string, [string, string]> = { ...STATUS, stopped: ["parada", "neutral"], idle: ["agente aberto", "muted"] };
  const isPast = (d: string | null) => !!d && new Date(d + "T23:59:59").getTime() < Date.now();
  const fmtDue = (d: string) => new Date(d + "T12:00:00").toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
  const cardMenu = (c: Card) => [
    { label: "Editar", icon: Pencil, onclick: () => (editing = { card: c }) },
    { label: "Planejar com IA", icon: Lightbulb, onclick: () => (running = { card: c, flow: "plan" }), disabled: !c.projects.length },
    { label: "Planejar e implementar", icon: ClipboardList, onclick: () => (running = { card: c, flow: "plan-implement" }), disabled: !c.projects.length },
    { label: "Implementar direto", icon: Hammer, onclick: () => (running = { card: c, flow: "implement" }), disabled: !c.projects.length },
    ...(c.live ? [{ label: "Abrir a tarefa", icon: ArrowLeftRight, onclick: () => work.focus(c.live!.repoId, c.live!.taskId) }] : []),
    { separator: true },
    { heading: "Mover para" },
    ...kanban.columns.filter(x => x.id !== c.column).map(x => ({ label: x.name, icon: Columns3, onclick: () => kanban.move(c.id, x.id, 0) })),
    { separator: true },
    { label: "Excluir", icon: Trash2, danger: true, onclick: async () => { if (await ui.ask({ title: `Excluir “${c.title}”?`, confirm: "Excluir", danger: true })) kanban.deleteCard(c.id); } },
  ];

  // ------------------------------------------------------------ colunas
  let cols = $state<Column[]>([]);
  let autoMove = $state(true);
  function openColumns() { cols = kanban.columns.map(c => ({ ...c })); autoMove = kanban.autoMove; columnsOpen = true; }
  const PALETTE = ["#9AA4B2", "#6F8CFF", "#F5B84F", "#B07CFF", "#3CCF91", "#FF6B7D", "#4FC3F7", "#FF8A50"];
  async function saveCols() { if (await kanban.saveColumns(cols, autoMove)) columnsOpen = false; }
  async function renameCol(c: Column) {
    const name = await ui.ask({ title: "Renomear coluna", input: { label: "Nome", value: c.name, required: true }, confirm: "Salvar" });
    if (name) kanban.saveColumns(kanban.columns.map(x => (x.id === c.id ? { ...x, name: String(name).trim() } : x)));
  }
</script>

<Page title="Quadro" sub={`${kanban.cards.length} cartões${working ? ` · ${working} com a IA trabalhando` : ""}${need ? ` · ${need} esperando você` : ""}`}>
  {#snippet actions()}
    {#if tab === "cards"}
      <button class="btn sm" onclick={openColumns}><Settings2 size={14} /> Colunas</button>
      <button class="btn sm primary" onclick={() => (editing = { card: null })}><Plus size={14} /> Cartão</button>
    {/if}
  {/snippet}

  <div class="tabs">
    <Segmented value={tab} onchange={(v) => go(v === "agents" ? "/board/agents" : "/board", "soft")}
      options={[{ value: "cards", label: "Cartões", count: kanban.cards.length }, { value: "agents", label: "Tarefas dos agentes", count: work.projects.reduce((n, p) => n + p.tasks.length, 0) }]} />
  </div>

  {#if tab === "agents"}
    <div class="agents"><Board onopen={(bp, bt) => work.focus(bp.id, bt.id)} /></div>
  {:else}
    <Toolbar bind:query={q} placeholder="Buscar cartão, descrição ou etiqueta…">
      {#snippet left()}
        <select class="input sm" bind:value={groupF}><option value="any">Todos os grupos</option><option value="none">Sem grupo</option>{#each work.groups as g (g.id)}<option value={g.id}>{g.name}</option>{/each}</select>
        <select class="input sm" bind:value={projF}><option value="any">Todos os projetos</option>{#each projectsUsed as r (r!.id)}<option value={r!.id}>{r!.name}</option>{/each}</select>
        <select class="input sm" bind:value={prioF}><option value="any">Qualquer prioridade</option>{#each Object.entries(PRIORITY) as [k, v] (k)}<option value={k}>{v.label}</option>{/each}</select>
      {/snippet}
    </Toolbar>

    {#if kanban.loaded && !kanban.cards.length}
      <div class="empty"><Empty title="Quadro vazio" text="Crie cartões com o que precisa ser feito, diga o grupo e os projetos — e mande a IA planejar ou implementar direto do cartão.">
        <button class="btn primary" onclick={() => (editing = { card: null })}><Plus size={14} /> Primeiro cartão</button></Empty></div>
    {/if}

    <div class="board" class:hidden={kanban.loaded && !kanban.cards.length}>
      {#each kanban.columns as col (col.id)}
        {@const list = byCol(col.id)}
        <section class="col" style="--c:{col.color}" class:target={drop?.col === col.id} ondragover={(e) => over(e, col.id)} ondrop={(e) => dropped(e, col.id)}
          ondragleave={(e) => { if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) drop = null; }} aria-label={col.name}>
          <header>
            <span class="cd"></span><b class="ell">{col.name}</b><span class="n">{list.length}</span>
            <button class="btn sm ghost icon" title="Novo cartão nesta coluna" onclick={() => (editing = { card: null, column: col.id })}><Plus size={14} /></button>
            <Menu items={[{ label: "Renomear", icon: Pencil, onclick: () => renameCol(col) }, { label: "Colunas do quadro…", icon: Settings2, onclick: openColumns }]} />
          </header>
          <div class="cards">
            {#each list as c, i (c.id)}
              {#if drop?.col === col.id && drop.index === i && dragId !== c.id}<div class="ph"></div>{/if}
              {@const g = work.groups.find(x => x.id === c.groupId)}
              {@const lv = c.live ? LIVE[c.live.status] || [c.live.status, "muted"] : null}
              <article class="card kc p-{c.priority}" class:dragging={dragId === c.id} data-card={c.id} draggable="true"
                ondragstart={(e) => { dragId = c.id; e.dataTransfer?.setData("text/plain", c.id); }} ondragend={() => { dragId = null; drop = null; }}
                oncontextmenu={(e) => ui.contextMenu(e, cardMenu(c))}>
                <button class="body" onclick={() => (editing = { card: c })}>
                  <span class="grip"><GripVertical size={12} /></span>
                  <b class="t">{c.title}</b>
                  {#if c.description}<span class="d">{c.description.replace(/^[-*]\s*\[[ xX]\]\s*/gm, "• ").split("\n").filter(Boolean).slice(0, 2).join(" · ")}</span>{/if}
                  <span class="chips">
                    {#if g}<span class="gchip" style="--g:{g.color}"><Layers size={10} /> {g.name}</span>{/if}
                    {#each c.projects as id (id)}{@const r = repos.byId(id)}<span class="pchip" class:prim={id === c.primary}>{#if id === c.primary}<Star size={9} />{/if}{r?.name || "?"}</span>{/each}
                    {#if c.refs.length}<span class="pchip ref" title={c.refs.map(id => repos.byId(id)?.name).join(", ")}>+{c.refs.length} p/ consulta</span>{/if}
                    {#each c.labels as l (l)}<span class="lchip">{l}</span>{/each}
                  </span>
                </button>
                <footer>
                  {#if c.priority !== "normal"}<span class="pill {PRIORITY[c.priority].tone}">{PRIORITY[c.priority].label}</span>{/if}
                  {#if c.due}<span class="due" class:late={isPast(c.due) && col.role !== "done"}><CalendarClock size={11} /> {fmtDue(c.due)}</span>{/if}
                  {#if c.workItem}<a class="wi tiny" href={c.workItem.url} target="_blank" rel="noopener" title={c.workItem.title}>#{c.workItem.number}</a>{/if}
                  <span class="grow"></span>
                  {#if c.live && lv}
                    <button class="live {lv[1]}" class:pulse={c.live.status === "working"} title={`${c.live.title} · ${c.live.branch}`} onclick={() => work.focus(c.live!.repoId, c.live!.taskId)}>
                      <span class="sd"></span>{lv[0]}</button>
                  {:else if c.projects.length}
                    <span class="ai">
                      <button title="Planejar com IA" onclick={() => (running = { card: c, flow: "plan" })}><Lightbulb size={13} /></button>
                      <button title="Planejar e implementar com IA" onclick={() => (running = { card: c, flow: "plan-implement" })}><Sparkles size={13} /></button>
                      <button title="Implementar direto com IA" onclick={() => (running = { card: c, flow: "implement" })}><Hammer size={13} /></button>
                    </span>
                  {/if}
                  <Menu items={cardMenu(c)} />
                </footer>
              </article>
            {/each}
            {#if drop?.col === col.id && drop.index >= list.filter(x => x.id !== dragId).length}<div class="ph"></div>{/if}
            <button class="add" onclick={() => (editing = { card: null, column: col.id })}><Plus size={13} /> Cartão</button>
          </div>
        </section>
      {/each}
    </div>
  {/if}
</Page>

{#if editing}<CardEditor card={editing.card} column={editing.column || null} onclose={() => (editing = null)} onrun={(c) => (running = { card: c, flow: null })} />{/if}
{#if running}<CardRun card={running.card} flow={running.flow} onclose={() => (running = null)} />{/if}

{#if columnsOpen}
  <Drawer title="Colunas do quadro" subtitle="Nome, cor, ordem e o papel de cada uma" onclose={() => (columnsOpen = false)} width={560}>
    <div class="colsf">
      {#each cols as c, i (c.id)}
        <div class="crow">
          <button class="sw" style="background:{c.color}" title="Trocar a cor" onclick={() => (c.color = PALETTE[(PALETTE.indexOf(c.color) + 1) % PALETTE.length])}></button>
          <input class="input" bind:value={c.name} />
          <select class="input role" bind:value={c.role}>
            <option value={null}>—</option><option value="backlog">Backlog</option><option value="todo">A fazer</option>
            <option value="doing">Em andamento (IA começou)</option><option value="review">Revisão (IA terminou)</option><option value="done">Concluído</option>
          </select>
          <button class="btn sm ghost icon" disabled={i === 0} title="Subir" onclick={() => { const x = [...cols]; [x[i - 1], x[i]] = [x[i], x[i - 1]]; cols = x; }}>↑</button>
          <button class="btn sm ghost icon" title="Apagar (os cartões vão para a primeira coluna)" onclick={() => (cols = cols.filter(x => x.id !== c.id))}><X size={13} /></button>
        </div>
      {/each}
      <button class="btn" onclick={() => (cols = [...cols, { id: "", name: "Nova coluna", color: PALETTE[cols.length % PALETTE.length], role: null } as Column])}><Plus size={14} /> Coluna</button>
      <Switch bind:checked={autoMove} label="Mover os cartões sozinho" hint="Para “Em andamento” quando a IA começa e para “Revisão” quando o agente termina" />
    </div>
    {#snippet footer()}<span class="spacer"></span><button class="btn" onclick={() => (columnsOpen = false)}>Cancelar</button><button class="btn primary" onclick={saveCols}>Salvar colunas</button>{/snippet}
  </Drawer>
{/if}

<style>
  .tabs { margin-bottom: 10px; flex: none; }
  .agents { flex: 1; min-height: 0; }
  .input.sm { height: 30px; font-size: 12.5px; padding: 0 8px; width: auto; }
  .empty { padding: 30px 0; }
  .board { flex: 1; min-height: 0; display: flex; gap: 10px; overflow-x: auto; padding-bottom: 8px; align-items: stretch; }
  .board.hidden { display: none; }
  .col { flex: 0 0 290px; display: flex; flex-direction: column; min-height: 0; border-radius: var(--r); background: var(--bg-2); border: 1px solid var(--line);
    transition: border-color var(--t), background var(--t); }
  .col.target { border-color: var(--c); background: color-mix(in srgb, var(--c) 6%, var(--bg-2)); }
  header { display: flex; align-items: center; gap: 8px; padding: 10px 8px 8px 12px; font-size: 13px; }
  .cd { width: 9px; height: 9px; border-radius: 3px; background: var(--c); flex: none; }
  header b { flex: 1; min-width: 0; }
  .n { font: 650 11px var(--font); color: var(--muted); }
  .cards { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding: 2px 8px 10px; }
  .kc { position: relative; display: grid; padding: 0; overflow: hidden; animation: rise 0.25s var(--ease-out) both; transition: transform var(--t) var(--spring), border-color var(--t), opacity var(--t); }
  .kc:hover { border-color: var(--line-3); transform: translateY(-1px); }
  .kc.dragging { opacity: 0.4; }
  .kc::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: transparent; }
  .kc.p-urgent::before { background: var(--bad); } .kc.p-high::before { background: var(--warn); }
  .body { display: grid; gap: 6px; padding: 10px 12px 6px; border: 0; background: none; color: var(--text); font: 13px var(--font); text-align: left; cursor: pointer; position: relative; }
  .grip { position: absolute; right: 6px; top: 8px; color: var(--faint); opacity: 0; cursor: grab; }
  .kc:hover .grip { opacity: 1; }
  .t { font-weight: 600; line-height: 1.35; padding-right: 10px; }
  .d { font-size: 12px; color: var(--muted); line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .gchip { display: inline-flex; align-items: center; gap: 4px; font: 600 10.5px var(--font); padding: 2px 7px; border-radius: 99px; background: color-mix(in srgb, var(--g) 18%, transparent); color: var(--text); }
  .pchip { display: inline-flex; align-items: center; gap: 3px; font: 11px var(--font); padding: 1px 7px; border-radius: 6px; background: var(--surface-3); color: var(--text-2); }
  .pchip.prim { color: var(--text); box-shadow: inset 0 0 0 1px var(--accent-line); }
  .pchip.prim :global(svg) { color: var(--warn); fill: currentColor; }
  .pchip.ref { background: none; border: 1px dashed var(--line-3); color: var(--muted); }
  .lchip { font: 11px var(--font); padding: 1px 7px; border-radius: 99px; border: 1px solid var(--line-2); color: var(--muted); }
  footer { display: flex; align-items: center; gap: 6px; padding: 0 6px 6px 12px; min-height: 30px; }
  .grow { flex: 1; }
  .due { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; color: var(--muted); }
  .due.late { color: var(--bad); font-weight: 600; }
  .wi { color: var(--accent); text-decoration: none; }
  .live { display: inline-flex; align-items: center; gap: 5px; height: 22px; padding: 0 8px; border-radius: 99px; border: 0; background: var(--surface-3); color: var(--text-2);
    font: 600 11px var(--font); cursor: pointer; }
  .live .sd { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); }
  .live.accent { background: var(--accent-soft); color: var(--accent); } .live.accent .sd { background: var(--accent); }
  .live.warn { background: var(--warn-soft); color: var(--warn); } .live.warn .sd { background: var(--warn); }
  .live.good { background: var(--good-soft); color: var(--good); } .live.good .sd { background: var(--good); }
  .pulse .sd { animation: ping 1.2s var(--ease) infinite; }
  @keyframes ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 5px transparent; } }
  .ai { display: inline-flex; gap: 1px; opacity: 0; transition: opacity var(--t-fast); }
  .kc:hover .ai, .kc:focus-within .ai { opacity: 1; }
  .ai button { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--accent); cursor: pointer; }
  .ai button:hover { background: var(--accent-soft); }
  .ph { height: 46px; border-radius: 10px; border: 2px dashed var(--c); background: color-mix(in srgb, var(--c) 8%, transparent); flex: none; }
  .add { display: flex; align-items: center; gap: 6px; height: 30px; padding: 0 10px; border: 1px dashed transparent; border-radius: 9px; background: none; color: var(--muted);
    font: 12.5px var(--font); cursor: pointer; flex: none; }
  .add:hover { border-color: var(--line-3); color: var(--text); }
  .colsf { display: grid; gap: 8px; padding-top: 12px; }
  .crow { display: flex; align-items: center; gap: 6px; }
  .crow .input { flex: 1; }
  .crow .role { flex: 0 0 200px; }
  .sw { width: 22px; height: 22px; border-radius: 6px; border: 0; cursor: pointer; flex: none; }
  .spacer { flex: 1; }
</style>
