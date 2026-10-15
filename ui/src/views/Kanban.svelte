<script lang="ts">
  // Quadro: kanban editável (colunas e cartões seus). Um cartão pode ser só um título para lembrar depois; descrição,
  // checklist, anexos, prazo e etiquetas são opcionais. A IA é uma automação a mais: com projetos no cartão, o botão
  // "IA" planeja/implementa (tarefa em worktree + agente) e, com "mover sozinho", o cartão anda — sempre com aviso e
  // registro no histórico. A aba "Tarefas dos agentes" é o quadro automático das tarefas em worktree.
  import { AlignLeft, ArrowUpRight, CalendarClock, CheckSquare, ClipboardList, Columns3, Flag, Hammer, Lightbulb, Link2Off, Paperclip, Pencil, Plus,
    Settings2, Sparkles, SquarePen, Trash2, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { flip } from "svelte/animate";
  import { ago, checklist, isImage, kanban, labelColor, LIVE, PRIORITY, type Card, type Column } from "../lib/kanban.svelte";
  import { repos } from "../lib/repos.svelte";
  import { go, router } from "../lib/router.svelte";
  import { ui } from "../lib/ui.svelte";
  import { work, type Flow } from "../lib/work.svelte";
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
  import FileThumb from "../components/kanban/FileThumb.svelte";

  const tab = $derived(router.parts[1] === "agents" ? "agents" : "cards");
  $effect(() => kanban.watch());
  $effect(() => { if (!repos.loaded) untrack(() => repos.load(false)); });

  let q = $state("");
  let groupF = $state("any");
  let projF = $state("any");
  let prioF = $state("any");
  let editing = $state<{ card: Card | null; column?: string | null; title?: string; ai?: boolean } | null>(null);
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
    return kanban.cards.filter(c => (!t || `${c.title} ${c.description} ${c.labels.join(" ")} ${c.files.map(f => f.name).join(" ")}`.toLowerCase().includes(t))
      && (groupF === "any" || (groupF === "none" ? !c.groupId : c.groupId === groupF))
      && (projF === "any" || c.projects.includes(projF) || c.refs.includes(projF))
      && (prioF === "any" || c.priority === prioF));
  });
  const byCol = (id: string) => filtered.filter(c => c.column === id).sort((a, b) => a.order - b.order);
  const working = $derived(kanban.cards.filter(c => c.live?.status === "working").length);
  const need = $derived(kanban.cards.filter(c => c.live?.status === "needs-you").length);
  const projectsUsed = $derived([...new Set(kanban.cards.flatMap(c => [...c.projects, ...c.refs]))].map(id => repos.byId(id)).filter(Boolean));
  const filtering = $derived(!!q.trim() || groupF !== "any" || projF !== "any" || prioF !== "any");
  const colName = (id: string) => kanban.columns.find(x => x.id === id)?.name || id;

  // ------------------------------------------------------------ cartão rápido (só título)
  let adding = $state<string | null>(null);
  let draft = $state("");
  const defaultCol = () => kanban.columns.find(x => x.role === "todo")?.id || kanban.columns[0]?.id || null;
  function startAdd(col: string | null) {
    if (!col) return;
    adding = col;
    draft = "";
    requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-composer="${col}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  }
  function addKey(e: KeyboardEvent, col: string) {
    if (e.key === "Escape") { e.stopPropagation(); adding = null; return; }
    if (e.key !== "Enter" || e.isComposing) return;
    e.preventDefault();
    if ((e.metaKey || e.ctrlKey) && draft.trim()) { editing = { card: null, column: col, title: draft.trim() }; adding = null; return; }
    const t = draft.trim();
    if (!t) return;
    kanban.quickAdd(col, t);
    draft = "";   // fica aberto para o próximo
  }
  // N: novo cartão rápido (fora de campo de texto e sem gaveta aberta)
  $effect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (tab !== "cards" || editing || running || columnsOpen || ui.dialog || ui.palette || e.metaKey || e.ctrlKey || e.altKey) return;
      const el = e.target as HTMLElement;
      if (el?.closest?.("input, textarea, select, [contenteditable]")) return;
      if (e.key === "n" || e.key === "N") { e.preventDefault(); startAdd(defaultCol()); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ------------------------------------------------------------ renomear no lugar
  let renaming = $state<string | null>(null);
  let rnText = $state("");
  function startRename(c: Card) { renaming = c.id; rnText = c.title; }
  function endRename(save: boolean) {
    const id = renaming;
    renaming = null;
    const c = kanban.cards.find(x => x.id === id);
    if (save && c && rnText.trim() && rnText.trim() !== c.title) kanban.rename(c.id, rnText.trim());
  }
  const autofocus = (el: HTMLInputElement) => { el.focus(); el.select(); };

  // ------------------------------------------------------------ arrastar e soltar (cartões entre colunas)
  let dragId = $state<string | null>(null);
  let drop = $state<{ col: string; index: number } | null>(null);
  function over(e: DragEvent, colId: string) {
    if (!dragId) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
    const list = (e.currentTarget as HTMLElement).querySelectorAll<HTMLElement>("[data-card]");
    let index = 0;
    for (const el of list) { if (el.dataset.card === dragId) continue; const r = el.getBoundingClientRect(); if (e.clientY > r.top + r.height / 2) index++; }
    if (drop?.col !== colId || drop.index !== index) drop = { col: colId, index };
  }
  function dropped(e: DragEvent, colId: string) {
    if (!dragId) return;
    e.preventDefault();
    const id = dragId, at = drop;
    endDrag();
    if (!at) return;
    // soltou no mesmo lugar: não manda nada
    const cur = byCol(colId).filter(x => x.id !== id);
    const c = kanban.cards.find(x => x.id === id);
    if (c && c.column === colId && byCol(colId).findIndex(x => x.id === id) === at.index) return;
    kanban.move(id, colId, Math.min(at.index, cur.length));
  }
  function startDrag(e: DragEvent, c: Card) {
    dragId = c.id;
    kanban.dragging = true;
    if (e.dataTransfer) { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", c.id); }
  }
  function endDrag() { dragId = null; drop = null; kanban.dragging = false; }

  // ------------------------------------------------------------ arquivos soltos num cartão
  const hasFiles = (e: DragEvent) => !!e.dataTransfer?.types?.includes("Files");
  let fileOver = $state<string | null>(null);
  function fileDrag(e: DragEvent, c: Card) {
    if (dragId || !hasFiles(e) || c.id.startsWith("tmp-")) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    fileOver = c.id;
  }
  function fileDrop(e: DragEvent, c: Card) {
    if (dragId || !hasFiles(e)) return;
    e.preventDefault();
    e.stopPropagation();
    fileOver = null;
    if (e.dataTransfer?.files.length) kanban.attach(c.id, e.dataTransfer.files);
  }
  // arquivo solto fora de um cartão: o webview não pode "navegar" para o arquivo
  $effect(() => {
    const stop = (e: DragEvent) => { if (hasFiles(e)) { e.preventDefault(); if (e.type === "drop") fileOver = null; } };
    window.addEventListener("dragover", stop);
    window.addEventListener("drop", stop);
    return () => { window.removeEventListener("dragover", stop); window.removeEventListener("drop", stop); };
  });
  let picker: HTMLInputElement | undefined = $state();
  let pickFor: string | null = null;
  function pick(c: Card) { pickFor = c.id; picker?.click(); }

  // ------------------------------------------------------------ menus
  const aiItems = (c: Card) => c.projects.length ? [
    { label: "Planejar", icon: Lightbulb, hint: "investiga e devolve um plano", onclick: () => (running = { card: c, flow: "plan" }) },
    { label: "Planejar e implementar", icon: ClipboardList, hint: "você aprova o plano", onclick: () => (running = { card: c, flow: "plan-implement" }) },
    { label: "Implementar", icon: Hammer, onclick: () => (running = { card: c, flow: "implement" }) },
  ] : [{ label: "Pedir à IA… (escolher o projeto)", icon: Sparkles, onclick: () => (editing = { card: c, ai: true }) }];
  const taskItems = (c: Card) => c.tasks.length ? [
    { label: "Abrir a tarefa da IA", icon: ArrowUpRight, onclick: () => kanban.openTask(c) },
    { label: "Desvincular a tarefa", icon: Link2Off, onclick: () => kanban.unlink(c) },
  ] : [];
  const cardMenu = (c: Card) => [
    { label: "Abrir", icon: SquarePen, onclick: () => (editing = { card: c }) },
    { label: "Renomear", icon: Pencil, kbd: "F2", onclick: () => startRename(c) },
    { label: "Anexar arquivo…", icon: Paperclip, onclick: () => pick(c) },
    ...taskItems(c),
    { separator: true },
    { heading: "IA (opcional)" },
    ...aiItems(c),
    { separator: true },
    { heading: "Mover para" },
    ...kanban.columns.filter(x => x.id !== c.column).map(x => ({ label: x.name, icon: Columns3, onclick: () => kanban.move(c.id, x.id, 0) })),
    { separator: true },
    { label: "Excluir", icon: Trash2, danger: true, onclick: () => confirmDelete(c) },
  ];
  async function confirmDelete(c: Card) {
    if (await ui.ask({ title: `Excluir “${c.title}”?`, message: c.files.length ? `Os ${c.files.length} anexo(s) vão junto.` : undefined, confirm: "Excluir", danger: true }))
      kanban.deleteCard(c.id);
  }
  function cardKey(e: KeyboardEvent, c: Card) {
    if (e.key === "F2") { e.preventDefault(); startRename(c); }
    else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); confirmDelete(c); }
  }

  const isPast = (d: string | null) => !!d && new Date(d + "T23:59:59").getTime() < Date.now();
  const fmtDue = (d: string) => new Date(d + "T12:00:00").toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }).replace(".", "");
  // relógio dos "há N min" (o polling não troca os cartões se nada mudou)
  let now = $state(Date.now());
  $effect(() => { const t = setInterval(() => (now = Date.now()), 30000); return () => clearInterval(t); });

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

{#snippet iaBtn()}<span class="ia"><Sparkles size={12} /> IA</span>{/snippet}

<Page title="Quadro" sub={`${kanban.cards.length} cartões${working ? ` · ${working} com a IA trabalhando` : ""}${need ? ` · ${need} esperando você` : ""}`}>
  {#snippet actions()}
    {#if tab === "cards"}
      <button class="btn sm" onclick={openColumns}><Settings2 size={14} /> Colunas</button>
      <button class="btn sm primary" onclick={() => startAdd(defaultCol())} title="Novo cartão (N)"><Plus size={14} /> Cartão</button>
    {/if}
  {/snippet}

  <div class="tabs">
    <Segmented value={tab} onchange={(v) => go(v === "agents" ? "/board/agents" : "/board", "soft")}
      options={[{ value: "cards", label: "Cartões", count: kanban.cards.length }, { value: "agents", label: "Tarefas dos agentes", count: work.projects.reduce((n, p) => n + p.tasks.length, 0) }]} />
  </div>

  {#if tab === "agents"}
    <div class="agents"><Board onopen={(bp, bt) => work.focus(bp.id, bt.id)} /></div>
  {:else}
    <Toolbar bind:query={q} placeholder="Buscar cartão, descrição, etiqueta ou anexo…">
      {#snippet left()}
        <select class="input sm" bind:value={groupF}><option value="any">Todos os grupos</option><option value="none">Sem grupo</option>{#each work.groups as g (g.id)}<option value={g.id}>{g.name}</option>{/each}</select>
        {#if projectsUsed.length}<select class="input sm" bind:value={projF}><option value="any">Todos os projetos</option>{#each projectsUsed as r (r!.id)}<option value={r!.id}>{r!.name}</option>{/each}</select>{/if}
        <select class="input sm" bind:value={prioF}><option value="any">Qualquer prioridade</option>{#each Object.entries(PRIORITY) as [k, v] (k)}<option value={k}>{v.label}</option>{/each}</select>
      {/snippet}
    </Toolbar>

    {#if kanban.loaded && !kanban.cards.length}
      <div class="empty"><Empty title="Quadro vazio" text="Anote o que precisa ser feito — um título basta. Depois refine, anexe imagens e arquivos e, se quiser, mande a IA planejar ou implementar.">
        <button class="btn primary" onclick={() => startAdd(defaultCol())}><Plus size={14} /> Primeiro cartão</button></Empty></div>
    {/if}

    <div class="board" class:hidden={kanban.loaded && !kanban.cards.length && !adding}>
      {#each kanban.columns as col (col.id)}
        {@const list = byCol(col.id)}
        <section class="col" style="--c:{col.color}" class:target={drop?.col === col.id} ondragover={(e) => over(e, col.id)} ondrop={(e) => dropped(e, col.id)}
          ondragleave={(e) => { if (dragId && !(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) drop = null; }} aria-label={col.name}>
          <header>
            <span class="cd"></span><b class="ell">{col.name}</b><span class="n">{list.length}</span>
            <button class="btn sm ghost icon" title="Novo cartão nesta coluna" onclick={() => startAdd(col.id)}><Plus size={14} /></button>
            <Menu items={[{ label: "Novo cartão detalhado…", icon: SquarePen, onclick: () => (editing = { card: null, column: col.id }) }, { label: "Renomear", icon: Pencil, onclick: () => renameCol(col) },
              { label: "Colunas do quadro…", icon: Settings2, onclick: openColumns }]} />
          </header>
          <div class="cards">
            {#each list as c, i (c.id)}
              {@const cover = c.files.find(isImage)}
              {@const ck = checklist(c.description)}
              {@const lv = c.live ? LIVE[c.live.status] || [c.live.status, "muted"] : null}
              {@const last = c.history?.[c.history.length - 1]}
              {@const byAi = last?.by === "ia" && last.to === c.column}
              {@const prim = c.primary ? repos.byId(c.primary) : null}
              {@const g = work.groups.find(x => x.id === c.groupId)}
              {@const busy = c.live?.status === "working" || c.live?.status === "needs-you"}
              {@const hasMeta = c.priority === "urgent" || c.priority === "high" || !!c.due || !!c.description.trim() || c.files.length > 0 || !!c.workItem || !!c.primary || !!c.groupId}
              <article class="kc" class:dragging={dragId === c.id} class:before={drop?.col === col.id && drop.index === i && dragId !== c.id}
                class:flash={kanban.flashed[c.id]} class:filehover={fileOver === c.id} class:tmp={c.id.startsWith("tmp-")}
                data-card={c.id} draggable={!c.id.startsWith("tmp-") && renaming !== c.id} ondragstart={(e) => startDrag(e, c)} ondragend={endDrag}
                ondragover={(e) => fileDrag(e, c)} ondragleave={(e) => { if (fileOver === c.id && !(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) fileOver = null; }}
                ondrop={(e) => fileDrop(e, c)} oncontextmenu={(e) => ui.contextMenu(e, cardMenu(c))} animate:flip={{ duration: 180 }}>
                <button class="hit" aria-label={`Abrir “${c.title}”`} onclick={() => (editing = { card: c })} onkeydown={(e) => cardKey(e, c)}></button>
                <span class="act more"><Menu items={cardMenu(c)} /></span>
                {#if cover}<div class="cover"><FileThumb cardId={c.id} file={cover} /></div>{/if}
                {#if c.labels.length}
                  <div class="lbs">{#each c.labels.slice(0, 4) as l (l)}<span class="lb" style="--l:{labelColor(l)}">{l}</span>{/each}{#if c.labels.length > 4}<span class="lb more">+{c.labels.length - 4}</span>{/if}</div>
                {/if}
                {#if renaming === c.id}
                  <input class="input rn" bind:value={rnText} use:autofocus onblur={() => endRename(true)}
                    onkeydown={(e) => { if (e.key === "Enter") endRename(true); else if (e.key === "Escape") { e.stopPropagation(); endRename(false); } }} />
                {:else}
                  <p class="t">{c.title}</p>
                {/if}
                {#if c.live && lv}
                  {@const since = c.live.since ? ago(c.live.since, now) : ""}
                  <button class="st {lv[1]}" class:pulse={c.live.status === "working"} onclick={() => kanban.openTask(c)}
                    title={c.live.status === "missing" ? "A tarefa foi removida — clique para desvincular" : `Abrir a tarefa e o agente · ${c.live.title} · ${c.live.branch}`}>
                    <span class="sd"></span><span class="ell">{lv[0]}</span>{#if since && (c.live.status === "working" || c.live.status === "done" || c.live.status === "needs-you")}<span class="ago">{since}</span>{/if}
                    <span class="go"><ArrowUpRight size={12} /></span>
                  </button>
                {/if}
                {#if byAi}<span class="moved" title={`${colName(last!.from)} → ${colName(last!.to)}${last!.why ? ` — ${last!.why}` : ""}`}><Sparkles size={10} /> Movido pela IA {ago(last!.at, now)}</span>{/if}
                {#if hasMeta || (c.projects.length && !busy)}
                <footer class="meta">
                  {#if c.priority === "urgent" || c.priority === "high"}<span class="m {PRIORITY[c.priority].tone}" title={`Prioridade ${PRIORITY[c.priority].label.toLowerCase()}`}><Flag size={11} /> {PRIORITY[c.priority].label}</span>{/if}
                  {#if c.due}<span class="m" class:bad={isPast(c.due) && col.role !== "done"} title="Prazo"><CalendarClock size={11} /> {fmtDue(c.due)}</span>{/if}
                  {#if ck}<span class="m" class:good={ck.done === ck.total} title="Checklist"><CheckSquare size={11} /> {ck.done}/{ck.total}</span>
                  {:else if c.description.trim()}<span class="m" title="Tem descrição"><AlignLeft size={11} /></span>{/if}
                  {#if c.files.length}<span class="m" title={c.files.map(f => f.name).join("\n")}><Paperclip size={11} /> {c.files.length}</span>{/if}
                  {#if c.workItem}<a class="m wi" href={c.workItem.url} target="_blank" rel="noopener" title={c.workItem.title}>#{c.workItem.number}</a>{/if}
                  {#if prim || g}
                    <span class="m where ell" title={[g?.name, ...c.projects.map(id => repos.byId(id)?.name)].filter(Boolean).join(" · ")}>
                      {#if g}<span class="gd" style="background:{g.color}"></span>{/if}{prim?.name || g?.name}{#if c.projects.length > 1}<span class="plus">+{c.projects.length - 1}</span>{/if}
                    </span>
                  {/if}
                  <span class="grow"></span>
                  {#if c.projects.length && !busy}<span class="act"><Menu items={aiItems(c)} trigger={iaBtn} label="IA" /></span>{/if}
                </footer>
                {/if}
                {#if fileOver === c.id}<div class="dropfile"><Paperclip size={14} /> Soltar para anexar</div>{/if}
              </article>
            {/each}
            {#if drop?.col === col.id && drop.index >= list.filter(x => x.id !== dragId).length}<div class="ph"></div>{/if}
            {#if adding === col.id}
              <div class="composer" data-composer={col.id}>
                <!-- svelte-ignore a11y_autofocus -->
                <input class="input" bind:value={draft} autofocus placeholder="Título do cartão" onkeydown={(e) => addKey(e, col.id)}
                  onblur={() => { if (!draft.trim()) setTimeout(() => { if (adding === col.id && !draft.trim()) adding = null; }, 150); }} />
                <div class="ch">
                  <span class="tiny muted" title="⌘Enter abre o cartão completo com o título">Enter cria · Esc fecha</span>
                  <span class="grow"></span>
                  <button class="btn sm ghost icon" title="Fechar (Esc)" onclick={() => (adding = null)}><X size={13} /></button>
                  <button class="btn sm primary" disabled={!draft.trim()} onmousedown={(e) => e.preventDefault()}
                    onclick={() => { kanban.quickAdd(col.id, draft.trim()); draft = ""; }}>Adicionar</button>
                </div>
              </div>
            {:else}
              <button class="add" onclick={() => startAdd(col.id)}><Plus size={13} /> Cartão</button>
            {/if}
          </div>
        </section>
      {/each}
    </div>
  {/if}
</Page>

<input type="file" multiple hidden bind:this={picker} onchange={(e) => { const el = e.currentTarget; if (pickFor && el.files?.length) kanban.attach(pickFor, el.files); el.value = ""; }} />

{#if editing}<CardEditor card={editing.card} column={editing.column || null} draft={editing.title || ""} ai={!!editing.ai} onclose={() => (editing = null)}
  onrun={(c) => (running = { card: c, flow: null })} />{/if}
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
      <Switch bind:checked={autoMove} label="A IA move os cartões"
        hint="Para “Em andamento” quando a IA começa e para “Revisão” quando o agente termina ou precisa de você. Cada movimento aparece num aviso e fica no histórico do cartão; o que você mover à mão não volta sozinho." />
    </div>
    {#snippet footer()}<span class="spacer"></span><button class="btn" onclick={() => (columnsOpen = false)}>Cancelar</button><button class="btn primary" onclick={saveCols}>Salvar colunas</button>{/snippet}
  </Drawer>
{/if}

<style>
  .tabs { margin-bottom: 10px; flex: none; }
  .agents { flex: 1; min-height: 0; }
  .input.sm { height: 30px; font-size: 12.5px; padding: 0 8px; width: auto; }
  .empty { padding: 30px 0; }
  .board { flex: 1; min-height: 0; display: flex; gap: 12px; overflow-x: auto; padding-bottom: 8px; align-items: stretch; }
  .board.hidden { display: none; }
  .col { flex: 0 0 292px; display: flex; flex-direction: column; min-height: 0; border-radius: var(--r); background: var(--bg-2); border: 1px solid var(--line);
    transition: border-color var(--t), background var(--t); }
  .col.target { border-color: color-mix(in srgb, var(--c) 60%, transparent); background: color-mix(in srgb, var(--c) 5%, var(--bg-2)); }
  header { display: flex; align-items: center; gap: 8px; padding: 10px 8px 8px 12px; font-size: 13px; }
  .cd { width: 9px; height: 9px; border-radius: 3px; background: var(--c); flex: none; }
  header b { flex: 1; min-width: 0; }
  .n { font: 650 11px var(--font); color: var(--muted); font-variant-numeric: tabular-nums; }
  .cards { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding: 2px 8px 10px; }

  /* cartão: título primeiro, uma linha de estado, meta compacta. Clique em qualquer parte abre; os controles ficam por cima */
  .kc { position: relative; display: flex; flex-direction: column; gap: 6px; padding: 10px 10px 10px 12px; flex: none; border-radius: 10px;
    background: var(--surface); border: 1px solid var(--line); box-shadow: var(--shadow-1);
    animation: rise 0.22s var(--ease-out) both; transition: border-color var(--t-fast), opacity var(--t-fast), margin var(--t-fast) var(--ease-out), box-shadow var(--t); }
  .kc:hover { border-color: var(--line-3); }
  .kc:has(.hit:focus-visible) { box-shadow: var(--ring); border-color: var(--accent); }
  .kc.dragging { opacity: 0.35; }
  .kc.tmp { opacity: 0.7; }
  .kc.before { margin-top: 54px; }
  .kc.before::before { content: ""; position: absolute; left: 0; right: 0; top: -51px; height: 44px; border-radius: 10px; border: 2px dashed color-mix(in srgb, var(--c) 70%, transparent);
    background: color-mix(in srgb, var(--c) 7%, transparent); pointer-events: none; }
  .kc.flash::after { content: ""; position: absolute; inset: -1px; border-radius: inherit; pointer-events: none; animation: glow 2.4s var(--ease-out) both; }
  @keyframes glow { 0%, 35% { box-shadow: 0 0 0 2px var(--accent-line); } 100% { box-shadow: 0 0 0 2px transparent; } }
  .kc.filehover { border-color: var(--accent); }
  .hit { position: absolute; inset: 0; z-index: 0; border: 0; border-radius: inherit; background: none; cursor: pointer; padding: 0; }
  .hit:focus { outline: none; }
  .cover { margin: -10px -10px 2px -12px; height: 112px; border-radius: 9px 9px 0 0; overflow: hidden; background: var(--surface-3); pointer-events: none; }
  .lbs { display: flex; flex-wrap: wrap; gap: 4px; pointer-events: none; }
  .lb { display: inline-flex; align-items: center; gap: 5px; height: 18px; padding: 0 7px; border-radius: 5px; font: 600 10.5px var(--font);
    background: color-mix(in srgb, var(--l) 16%, transparent); color: color-mix(in srgb, var(--l) 70%, var(--text)); }
  .lb.more { --l: var(--muted); }
  .t { margin: 0; font: 600 13.5px/1.38 var(--font); color: var(--text); overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 4; line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden;
    pointer-events: none; text-wrap: pretty; }
  .rn { position: relative; z-index: 1; height: 30px; font-weight: 600; }

  .st { position: relative; z-index: 1; display: flex; align-items: center; gap: 6px; min-width: 0; height: 24px; margin: 0 -4px; padding: 0 6px; border: 0; border-radius: 6px;
    background: none; color: var(--text-2); font: 600 11.5px var(--font); text-align: left; cursor: pointer; transition: background var(--t-fast); }
  .st:hover { background: var(--surface-3); }
  .st .sd { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); flex: none; }
  .st .ago { font-weight: 500; color: var(--muted); white-space: nowrap; }
  .st .go { margin-left: auto; display: grid; color: var(--muted); opacity: 0; transition: opacity var(--t-fast); }
  .st:hover .go, .st:focus-visible .go { opacity: 1; }
  .st.accent { color: var(--accent); } .st.accent .sd { background: var(--accent); }
  .st.warn { color: var(--warn); } .st.warn .sd { background: var(--warn); }
  .st.good { color: var(--good); } .st.good .sd { background: var(--good); }
  .st.bad { color: var(--bad); } .st.bad .sd { background: var(--bad); }
  .st.muted .sd { background: transparent; box-shadow: inset 0 0 0 1.5px var(--muted); }
  .pulse .sd { animation: ping 1.4s var(--ease) infinite; }
  @keyframes ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 5px transparent; } }
  .moved { position: relative; z-index: 1; align-self: flex-start; display: inline-flex; align-items: center; gap: 5px; font: 500 11px var(--font); color: var(--muted); cursor: default; }
  .moved :global(svg) { color: var(--accent); }

  .meta { display: flex; align-items: center; gap: 10px; min-height: 24px; margin-bottom: -4px; color: var(--muted); font-size: 11.5px; }
  .m { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; font-variant-numeric: tabular-nums; pointer-events: none; }
  .m.bad { color: var(--bad); font-weight: 600; } .m.warn { color: var(--warn); font-weight: 600; } .m.good { color: var(--good); }
  .m.wi { color: var(--accent); pointer-events: auto; position: relative; z-index: 1; }
  .m.wi:hover { text-decoration: underline; }
  .where { min-width: 0; flex: 0 1 auto; color: var(--text-2); }
  .gd { width: 7px; height: 7px; border-radius: 2px; flex: none; }
  .plus { color: var(--muted); margin-left: 2px; }
  .grow { flex: 1; }
  .act { position: relative; z-index: 1; display: inline-flex; margin-left: -6px; }
  .ia { display: inline-flex; align-items: center; gap: 4px; height: 24px; padding: 0 8px; border-radius: 6px; color: var(--accent); font: 600 11.5px var(--font);
    transition: background var(--t-fast); }
  .ia:hover { background: var(--accent-soft); }
  .act :global(.btn.icon) { width: 24px; height: 24px; color: var(--muted); }
  /* ⋯ no canto: aparece ao passar o mouse ou com foco (o clique direito abre o mesmo menu) */
  .more { position: absolute; top: 6px; right: 6px; z-index: 2; margin: 0; opacity: 0; pointer-events: none; transition: opacity var(--t-fast); border-radius: 7px; background: var(--surface); }
  .kc:hover .more, .kc:focus-within .more, .more:has(:global([aria-expanded="true"])) { opacity: 1; pointer-events: auto; }
  .kc:not(:has(.cover)) .t { padding-right: 18px; }
  .dropfile { position: absolute; inset: 0; z-index: 2; display: flex; align-items: center; justify-content: center; gap: 6px; border-radius: inherit;
    background: color-mix(in srgb, var(--accent) 14%, var(--surface)); color: var(--accent); font: 600 12.5px var(--font); pointer-events: none; animation: fade 0.12s both; }

  .ph { height: 44px; border-radius: 10px; border: 2px dashed color-mix(in srgb, var(--c) 70%, transparent); background: color-mix(in srgb, var(--c) 7%, transparent); flex: none; }
  .add { display: flex; align-items: center; gap: 6px; height: 32px; padding: 0 10px; border: 1px dashed transparent; border-radius: 9px; background: none; color: var(--muted);
    font: 12.5px var(--font); cursor: pointer; flex: none; transition: color var(--t-fast), border-color var(--t-fast), background var(--t-fast); }
  .add:hover { border-color: var(--line-3); color: var(--text); background: var(--surface); }
  .composer { display: grid; gap: 6px; padding: 8px; border-radius: 10px; background: var(--surface); border: 1px solid var(--accent-line); flex: none; animation: rise 0.16s var(--ease-out) both; }
  .composer .input { height: 34px; font-weight: 600; }
  .ch { display: flex; align-items: center; gap: 4px; }

  .colsf { display: grid; gap: 8px; padding-top: 12px; }
  .crow { display: flex; align-items: center; gap: 6px; }
  .crow .input { flex: 1; }
  .crow .role { flex: 0 0 200px; }
  .sw { width: 22px; height: 22px; border-radius: 6px; border: 0; cursor: pointer; flex: none; }
  .spacer { flex: 1; }
  @media (prefers-reduced-motion: reduce) {
    .kc, .kc.flash::after, .composer { animation: none; }
    .pulse .sd { animation: none; }
  }
</style>
