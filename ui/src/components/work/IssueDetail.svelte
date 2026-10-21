<script lang="ts">
  // Issue do GitHub ou work item do Azure aberto no app: descrição renderizada (Markdown ou o HTML do Azure, sempre
  // sanitizado), etiquetas, responsável, itens ligados e a discussão — com comentar e "Implementar" direto, num projeto
  // local escolhido aqui (o work item do Azure não diz o repositório: sugere os clones do mesmo projeto do Azure).
  // Tudo editável no lugar: título, estado, responsável, etiquetas/tags, sprint, área, prioridade e a descrição. A tela
  // muda na hora (otimista); se o GitHub/Azure recusar, volta ao que era e avisa.
  import { Bot, Check, CheckCircle2, CircleDot, ExternalLink, KanbanSquare, Link2, MessageSquare, Paperclip, Pencil, Plus, Send, Sparkles, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { fade, fly, slide } from "svelte/transition";
  import { get, post } from "../../lib/api";
  import { repos } from "../../lib/repos.svelte";
  import { go } from "../../lib/router.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { work } from "../../lib/work.svelte";
  import Ago from "../Ago.svelte";
  import Drawer from "../Drawer.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import { htmlText, renderMarkdown, safeHtml } from "./md/render";

  type Comment = { author: string; created: string; markdown?: string; html?: string; pending?: boolean };
  type Detail = { provider: "github" | "azure"; number: number; title: string; state: string; type: string; project: string; author: string;
    assignee: string; created: string; updated: string; labels: string[]; markdown?: string; sections?: { label: string; html: string }[];
    comments: Comment[]; relations: { kind: string; name: string; id?: number; url?: string }[]; url: string;
    iteration?: string; area?: string; priority?: number; effort?: number; milestone?: string };
  type Opt = { name: string; label?: string; category?: string; color?: string | null };
  type Options = { states: Opt[]; labels: Opt[]; people: { id: string; name: string; avatar?: string | null }[]; iterations?: string[]; areas?: string[] };

  let { item, onclose, onboard, onchange }: { item: any; onclose: () => void; onboard?: (i: any) => void; onchange?: (patch: Record<string, any>) => void } = $props();
  let d = $state<Detail | null>(null);
  let err = $state("");
  let reply = $state("");
  let sending = $state(false);
  let opts = $state<Options | null>(null);

  const ref = () => ({ provider: item.provider, account: item.account || undefined, org: item.org, repo: item.repo, number: item.number });
  async function load() {
    try {
      d = await get<Detail>("issue", ref());
      err = "";
      if (!opts) untrack(loadOptions);
    } catch (e: any) { err = e.message || String(e); }
  }
  async function loadOptions() {
    try { opts = await get<Options>("issue/options", { ...ref(), project: d?.project, type: d?.type }); }
    catch { opts = { states: [], labels: [], people: [] }; }   // sem permissão para listar: edita só o que não precisa de lista
  }
  $effect(() => { void item.key; untrack(() => { d = null; opts = null; load(); }); });
  $effect(() => { if (!repos.loaded) untrack(() => repos.load(false)); });

  // ------------------------------------------------------------ edição (otimista, com volta atrás se falhar)
  let busy = $state<Record<string, boolean>>({});
  let flashed = $state<Record<string, number>>({});
  let shaken = $state("");
  const gh = $derived(item.provider === "github");
  const STATE_PT: Record<string, string> = { open: "Aberta", closed: "Fechada", OPEN: "Aberta", CLOSED: "Fechada" };
  const stateLabel = (s?: string) => (gh ? STATE_PT[s || ""] || s : s) || "—";
  const doneState = $derived.by(() => {
    const s = d?.state || item.state;
    if (gh) return String(s).toLowerCase() === "closed";
    const o = opts?.states.find(x => x.name === s);
    return o ? o.category === "Completed" || o.category === "Removed" : /^(closed|done|removed|resolved|conclu)/i.test(s || "");
  });
  const stateTone = $derived(doneState ? "done" : (opts?.states.find(x => x.name === d?.state)?.category === "InProgress" ? "prog" : "open"));
  const assignees = $derived((d?.assignee || "").split(",").map(s => s.trim()).filter(Boolean));
  const labelColor = (n: string) => opts?.labels.find(l => l.name === n)?.color || item.labels?.find((l: any) => l.name === n)?.color || null;

  /** Itens da lista (fora da gaveta) com o que mudou: o pai aplica na linha. */
  function sync(x: Detail) {
    onchange?.({ title: x.title, state: x.state, updated: x.updated,
      labels: x.labels.map(n => ({ name: n, color: labelColor(n) })),
      assignees: (x.assignee || "").split(",").map(s => s.trim()).filter(Boolean).map(n => item.assignees?.find((a: any) => a.login === n) || { login: n, avatar: null }) });
  }
  async function save(field: string, changes: Record<string, any>, apply: (x: Detail) => void, okText?: string) {
    if (!d) return;
    const snap = $state.snapshot(d) as Detail;
    apply(d);
    sync(d);
    busy = { ...busy, [field]: true };
    try {
      const r = await post<Detail>("issue/edit", { ...ref(), key: item.key, changes });
      d = { ...r, comments: d?.comments.filter(c => c.pending).length ? [...r.comments, ...d!.comments.filter(c => c.pending)] : r.comments };
      sync(r);
      flashed = { ...flashed, [field]: Date.now() };
      if (okText) ui.toast(okText, "ok");
    } catch (e) {
      d = snap;
      sync(snap);
      shaken = field;
      setTimeout(() => { if (shaken === field) shaken = ""; }, 500);
      ui.error(e);
    }
    const b = { ...busy }; delete b[field]; busy = b;
  }

  // título
  let editTitle = $state(false);
  let titleDraft = $state("");
  function startTitle() { titleDraft = d?.title || item.title; editTitle = true; }
  function commitTitle() {
    const t = titleDraft.trim();
    editTitle = false;
    if (!t || !d || t === d.title) return;
    save("title", { title: t }, x => (x.title = t));
  }
  const focus = (el: HTMLElement) => { el.focus(); (el as HTMLInputElement).select?.(); };

  // estado, responsável, etiquetas, sprint, área, prioridade
  function setState(s: string) {
    if (!d || s === d.state) return;
    save("state", { state: s }, x => (x.state = s), gh ? (s === "closed" ? "Issue fechada" : "Issue reaberta") : `Agora em ${s}`);
  }
  function setAssignee(id: string) {
    if (!d) return;
    if (gh) {
      const next = id && !assignees.includes(id) ? [...assignees, id] : assignees;
      if (next === assignees) return;
      save("assignee", { assignees: next }, x => (x.assignee = next.join(", ")));
    } else {
      const p = opts?.people.find(x => x.id === id);
      save("assignee", { assignee: id || "" }, x => (x.assignee = p?.name || ""));
    }
  }
  function dropAssignee(login: string) {
    const next = assignees.filter(a => a !== login);
    save("assignee", { assignees: next }, x => (x.assignee = next.join(", ")));
  }
  const azAssigneeId = $derived(opts?.people.find(p => p.name === d?.assignee)?.id || "");
  function addLabel(n: string) {
    n = n.trim();
    if (!d || !n || d.labels.includes(n)) return;
    const next = [...d.labels, n];
    save("labels", { labels: next }, x => (x.labels = next));
  }
  function dropLabel(n: string) {
    if (!d) return;
    const next = d.labels.filter(l => l !== n);
    save("labels", { labels: next }, x => (x.labels = next));
  }
  let tagDraft = $state("");
  const freeLabels = $derived((opts?.labels || []).filter(l => !d?.labels.includes(l.name)));
  function setField(field: "iteration" | "area" | "priority", v: any) {
    if (!d || v === d[field]) return;
    save(field, { [field]: v }, x => ((x as any)[field] = v));
  }

  // descrição: Markdown no GitHub (escrever/visualizar); no Azure cada seção é HTML, editado no próprio texto formatado
  const SECTION_REF: Record<string, string> = { "Descrição": "System.Description", "Passos para reproduzir": "Microsoft.VSTS.TCM.ReproSteps",
    "Critérios de aceite": "Microsoft.VSTS.Common.AcceptanceCriteria", "Informações do sistema": "Microsoft.VSTS.TCM.SystemInfo" };
  let editBody = $state<string | null>(null);   // "body" (GitHub) ou o rótulo da seção do Azure
  let bodyDraft = $state("");
  let preview = $state(false);
  let rich: HTMLDivElement | undefined = $state();
  function startBody(label = "body", html = "") {
    editBody = label;
    preview = false;
    bodyDraft = label === "body" ? d?.markdown || "" : html;
  }
  function commitBody() {
    if (!d || !editBody) return;
    const label = editBody;
    if (label === "body") {
      const md = bodyDraft;
      editBody = null;
      if (md === (d.markdown || "")) return;
      save("body", { body: md }, x => (x.markdown = md), "Descrição salva");
    } else {
      const html = rich?.innerHTML ?? bodyDraft;
      const refName = SECTION_REF[label] || "System.Description";
      editBody = null;
      save("body", { html: { [refName]: html } }, x => {
        const secs = x.sections || [];
        x.sections = secs.some(s => s.label === label) ? secs.map(s => (s.label === label ? { ...s, html } : s)) : [...secs, { label, html }];
      }, `${label} salva`);
    }
  }
  const newSection = $derived(/bug|defeito|defect/i.test(d?.type || "") ? "Passos para reproduzir" : "Descrição");
  function bodyKeys(e: KeyboardEvent) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); commitBody(); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); editBody = null; }
  }

  // ------------------------------------------------------------ onde implementar
  const azOrg = $derived(item.provider === "azure" ? (item.url.match(/dev\.azure\.com\/([^/]+)/)?.[1] || item.url.match(/\/\/([^.]+)\.visualstudio/)?.[1] || "") : "");
  const candidates = $derived.by(() => {
    const n = (s?: string | null) => (s || "").toLowerCase();
    const pool = repos.local.filter(r => r.exists);
    const fit = item.provider === "github"
      ? pool.filter(r => r.provider === "github" && n(r.slug) === n(item.repo))
      : pool.filter(r => r.provider === "azure" && n(r.slug).startsWith(`${n(azOrg)}/${n(item.repo)}/`));
    const openIds = new Set(work.projects.map(p => p.id));
    const rank = (id: string) => (id === work.active ? 0 : openIds.has(id) ? 1 : 2);
    return [...fit].sort((a, b) => rank(a.id) - rank(b.id) || a.name.localeCompare(b.name));
  });
  let target = $state("");
  $effect(() => {
    const c = candidates;
    if (!c.some(r => r.id === target)) untrack(() => (target = c[0]?.id || (item.provider === "azure" ? work.active || "" : "")));
  });
  const others = $derived(repos.local.filter(r => r.exists && !candidates.some(c => c.id === r.id)).sort((a, b) => a.name.localeCompare(b.name)));

  /** O pedido para o agente: o conteúdo inteiro (descrição e discussão), não só o link. */
  function promptOf() {
    const kind = item.provider === "github" ? "a issue" : `o work item (${d?.type || item.type || "item"})`;
    const head = `Implemente ${kind} #${item.number}: ${d?.title || item.title}\n${item.url}`;
    if (!d) return `${head}\n\nLeia a descrição completa no link antes de começar.`;
    const body = d.provider === "github" ? (d.markdown || "").trim() : (d.sections || []).map(s => `## ${s.label}\n${htmlText(s.html)}`).join("\n\n");
    const talk = d.comments.slice(-15).map(c => `- ${c.author} (${c.created?.slice(0, 10)}): ${(c.markdown ?? htmlText(c.html || "")).trim().slice(0, 1500)}`).join("\n");
    return [head, d.labels.length ? `Etiquetas: ${d.labels.join(", ")}` : "", body ? `\n${body.slice(0, 12000)}` : "", talk ? `\n## Discussão\n${talk}` : ""].filter(Boolean).join("\n");
  }
  async function into(kind: "ask" | "task", flow?: string) {
    if (!target) return ui.toast("Escolha o projeto onde implementar", "info");
    try {
      const projectId = await work.open(target);
      if (!projectId) return;
      const text = promptOf();
      if (kind === "ask") work.pendingAsk = { projectId, preset: { title: item.title, text, workItem: item, flow } };
      else work.pendingTask = { projectId, preset: { title: item.title, prompt: text, workItem: item,
        kind: /bug|defeito|defect/i.test(item.type || "") || item.labels?.some((l: any) => /bug/i.test(l.name)) ? "fix" : "feature" } };
      go("/work/" + projectId);
      onclose();
    } catch (e) { ui.error(e); }
  }
  /** Comentário otimista: aparece na hora (esmaecido até o servidor confirmar); se falhar, sai e o texto volta à caixa. */
  async function send(closeToo = false) {
    const text = reply.trim();
    if (!text || !d) return;
    sending = true;
    const mine: Comment = { author: "você", created: new Date().toISOString(), ...(gh ? { markdown: text } : { html: renderMarkdown(text) }), pending: true };
    d.comments = [...d.comments, mine];
    reply = "";
    try {
      await post("issue/comment", { ...ref(), text: gh ? text : renderMarkdown(text) });
      if (closeToo) setState("closed");
      await load();
    } catch (e) {
      if (d) d.comments = d.comments.filter(c => c !== mine && !c.pending);
      reply = text;
      ui.error(e);
    }
    sending = false;
  }
</script>

<Drawer title={`${item.provider === "github" ? "Issue" : d?.type || item.type || "Work item"} #${item.number}`} subtitle={item.repo} {onclose} width={780}>
  <div class="id">
    {#if editTitle}
      <input class="input ttl-in" bind:value={titleDraft} use:focus onblur={commitTitle}
        onkeydown={(e) => { if (e.key === "Enter") { e.preventDefault(); commitTitle(); } else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); editTitle = false; } }} />
    {:else}
      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <h3 class="ttl" class:busy={busy.title} class:shake={shaken === "title"} title={d ? "Clique para editar o título" : ""} onclick={() => d && startTitle()}
        onkeydown={(e) => e.key === "Enter" && d && startTitle()}>
        {#key flashed.title}<span class="fl">{d?.title || item.title}</span>{/key}
        {#if d}<Pencil size={13} class="pen" />{/if}
      </h3>
    {/if}
    <div class="meta small">
      <ProviderIcon provider={item.provider} size={13} />
      {#if d}
        <label class="stsel {stateTone}" class:busy={busy.state} class:shake={shaken === "state"} title="Estado">
          {#if doneState}<CheckCircle2 size={12} />{:else}<CircleDot size={12} />{/if}
          {#key d.state}<span in:fly={{ y: 6, duration: 220 }}>{stateLabel(d.state)}</span>{/key}
          <select value={d.state} onchange={(e) => setState(e.currentTarget.value)} disabled={busy.state}>
            {#if !opts?.states.some(s => s.name === d!.state)}<option value={d.state}>{stateLabel(d.state)}</option>{/if}
            {#each opts?.states || [] as s (s.name)}<option value={s.name}>{s.label || s.name}</option>{/each}
          </select>
        </label>
      {:else}<span class="pill info">{stateLabel(item.state)}</span>{/if}
      {#if d?.author}<span class="muted">aberta por {d.author}{#if d.created} <Ago iso={d.created} prefix="há " />{/if}</span>{/if}
      {#if d?.updated}{#key d.updated}<span class="muted" in:fade>· atualizada <Ago iso={d.updated} prefix="há " /></span>{/key}{/if}
      <a class="lnk" href={item.url} target="_blank" rel="noopener"><ExternalLink size={12} /> Abrir no {item.provider === "github" ? "GitHub" : "Azure"}</a>
    </div>

    {#if d}
      <div class="fields small" in:fade={{ duration: 160 }}>
        <span class="fk">Responsável</span>
        <div class="fv" class:busy={busy.assignee} class:shake={shaken === "assignee"}>
          {#if gh}
            {#each assignees as a (a)}<span class="chip" transition:fly={{ x: -6, duration: 160 }}>{a}<button class="x" title="Tirar" onclick={() => dropAssignee(a)}><X size={10} /></button></span>{/each}
            <select class="mini" value="" onchange={(e) => { setAssignee(e.currentTarget.value); e.currentTarget.value = ""; }} title="Atribuir">
              <option value="">{assignees.length ? "+" : "Ninguém — atribuir…"}</option>
              {#each (opts?.people || []).filter(p => !assignees.includes(p.id)) as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
            </select>
          {:else}
            <select class="mini wide" value={azAssigneeId || (d.assignee ? "__cur" : "")} onchange={(e) => setAssignee(e.currentTarget.value)}>
              <option value="">Ninguém</option>
              {#if d.assignee && !azAssigneeId}<option value="__cur" disabled>{d.assignee}</option>{/if}
              {#each opts?.people || [] as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
            </select>
          {/if}
        </div>

        <span class="fk">{gh ? "Etiquetas" : "Tags"}</span>
        <div class="fv" class:busy={busy.labels} class:shake={shaken === "labels"}>
          {#each d.labels as l (l)}
            <span class="chip lc" style="--c:{labelColor(l) || 'var(--muted)'}" transition:fly={{ x: -6, duration: 160 }}>{l}<button class="x" title="Tirar" onclick={() => dropLabel(l)}><X size={10} /></button></span>
          {/each}
          {#if gh}
            <select class="mini" value="" onchange={(e) => { addLabel(e.currentTarget.value); e.currentTarget.value = ""; }} title="Adicionar etiqueta">
              <option value="">{d.labels.length ? "+" : "Adicionar…"}</option>
              {#each freeLabels as l (l.name)}<option value={l.name}>{l.name}</option>{/each}
            </select>
          {:else}
            <span class="tagin"><Plus size={11} /><input list="wi-tags" placeholder="tag" bind:value={tagDraft}
              onkeydown={(e) => { if (e.key === "Enter") { e.preventDefault(); addLabel(tagDraft); tagDraft = ""; } }} /></span>
            <datalist id="wi-tags">{#each freeLabels as l (l.name)}<option value={l.name}></option>{/each}</datalist>
          {/if}
        </div>

        {#if !gh}
          <span class="fk">Sprint</span>
          <div class="fv" class:busy={busy.iteration} class:shake={shaken === "iteration"}>
            <select class="mini wide" value={d.iteration || ""} onchange={(e) => setField("iteration", e.currentTarget.value)}>
              {#if d.iteration && !opts?.iterations?.includes(d.iteration)}<option value={d.iteration}>{d.iteration}</option>{/if}
              {#each opts?.iterations || [] as p (p)}<option value={p}>{p.split("\\").slice(1).join(" › ") || p}</option>{/each}
            </select>
          </div>
          <span class="fk">Área</span>
          <div class="fv" class:busy={busy.area} class:shake={shaken === "area"}>
            <select class="mini wide" value={d.area || ""} onchange={(e) => setField("area", e.currentTarget.value)}>
              {#if d.area && !opts?.areas?.includes(d.area)}<option value={d.area}>{d.area}</option>{/if}
              {#each opts?.areas || [] as p (p)}<option value={p}>{p.split("\\").slice(1).join(" › ") || p}</option>{/each}
            </select>
          </div>
          <span class="fk">Prioridade</span>
          <div class="fv" class:busy={busy.priority} class:shake={shaken === "priority"}>
            <select class="mini" value={String(d.priority || "")} onchange={(e) => setField("priority", Number(e.currentTarget.value) || null)}>
              {#if !d.priority}<option value="">—</option>{/if}
              {#each [1, 2, 3, 4] as p (p)}<option value={String(p)}>{p}</option>{/each}
            </select>
            {#if d.effort}<span class="muted">· esforço {d.effort}</span>{/if}
          </div>
        {:else if d.milestone}
          <span class="fk">Marco</span><div class="fv">{d.milestone}</div>
        {/if}
      </div>
    {/if}

    <div class="impl card">
      <span class="small muted">Implementar em</span>
      <select class="input sm" bind:value={target}>
        {#if !candidates.length && !target}<option value="">Escolha o projeto…</option>{/if}
        {#if candidates.length}<optgroup label="Deste {item.provider === 'github' ? 'repositório' : 'projeto do Azure'}">{#each candidates as r (r.id)}<option value={r.id}>{r.name}{r.slug ? ` — ${r.slug}` : ""}</option>{/each}</optgroup>{/if}
        <optgroup label="Outros projetos">{#each others as r (r.id)}<option value={r.id}>{r.name}</option>{/each}</optgroup>
      </select>
      <button class="btn sm primary" disabled={!target} title="Manda a issue inteira (descrição e discussão) para o agente implementar" onclick={() => into("ask", "implement")}><Sparkles size={13} /> Implementar com IA</button>
      <button class="btn sm" disabled={!target} onclick={() => into("ask", "plan-implement")}>Planejar e implementar</button>
      <button class="btn sm ghost" disabled={!target} title="Branch + worktree + agente, com o formulário completo" onclick={() => into("task")}><Bot size={13} /> Nova tarefa</button>
      {#if onboard}<button class="btn sm ghost" onclick={() => onboard!(item)}><KanbanSquare size={13} /> Quadro</button>{/if}
    </div>

    {#if err}<p class="small err">Não consegui ler: {err}</p>
    {:else if !d}<div class="shimw"><span class="shim"></span><span class="shim"></span><span class="shim"></span><span class="shim"></span></div>
    {:else}
      <div class="body" class:busy={busy.body} class:shake={shaken === "body"}>
        {#if d.provider === "github"}
          <h4 class="sec">Descrição {#if editBody !== "body"}<button class="ed" onclick={() => startBody()}><Pencil size={11} /> Editar</button>{/if}</h4>
          {#if editBody === "body"}
            <div class="editor" transition:slide={{ duration: 180 }}>
              <div class="etabs"><button class:on={!preview} onclick={() => (preview = false)}>Escrever</button><button class:on={preview} onclick={() => (preview = true)}>Visualizar</button>
                <span class="tiny muted grow">Markdown · ⌘↵ salva · Esc cancela</span></div>
              {#if preview}<div class="doc pv">{#if bodyDraft.trim()}{@html renderMarkdown(bodyDraft)}{:else}<span class="muted small">Nada para visualizar.</span>{/if}</div>
              {:else}<textarea class="input" rows="12" bind:value={bodyDraft} use:focus onkeydown={bodyKeys}></textarea>{/if}
              <div class="eacts"><button class="btn sm ghost" onclick={() => (editBody = null)}>Cancelar</button><button class="btn sm primary" onclick={commitBody}><Check size={13} /> Salvar</button></div>
            </div>
          {:else if d.markdown?.trim()}{#key flashed.body}<div class="doc fl">{@html renderMarkdown(d.markdown)}</div>{/key}
          {:else}<button class="empty-desc" onclick={() => startBody()}><Plus size={13} /> Escrever uma descrição</button>{/if}
        {:else}
          {#each d.sections || [] as s (s.label)}
            <h4 class="sec">{s.label} {#if editBody !== s.label}<button class="ed" onclick={() => startBody(s.label, safeHtml(s.html))}><Pencil size={11} /> Editar</button>{/if}</h4>
            {#if editBody === s.label}
              <div class="editor" transition:slide={{ duration: 180 }}>
                <div class="doc rich" contenteditable="true" role="textbox" tabindex="0" aria-multiline="true" bind:this={rich} use:focus onkeydown={bodyKeys}>{@html bodyDraft}</div>
                <div class="eacts"><span class="tiny muted grow">Texto formatado · ⌘↵ salva · Esc cancela</span><button class="btn sm ghost" onclick={() => (editBody = null)}>Cancelar</button>
                  <button class="btn sm primary" onclick={commitBody}><Check size={13} /> Salvar</button></div>
              </div>
            {:else}{#key flashed.body}<div class="doc fl">{@html safeHtml(s.html)}</div>{/key}{/if}
          {:else}
            {#if editBody === newSection}
              <h4 class="sec">{newSection}</h4>
              <div class="editor" transition:slide={{ duration: 180 }}>
                <div class="doc rich" contenteditable="true" role="textbox" tabindex="0" aria-multiline="true" bind:this={rich} use:focus onkeydown={bodyKeys}></div>
                <div class="eacts"><span class="tiny muted grow">⌘↵ salva · Esc cancela</span><button class="btn sm ghost" onclick={() => (editBody = null)}>Cancelar</button>
                  <button class="btn sm primary" onclick={commitBody}><Check size={13} /> Salvar</button></div>
              </div>
            {:else}<button class="empty-desc" onclick={() => startBody(newSection, "")}><Plus size={13} /> Escrever {newSection.toLowerCase()}</button>{/if}
          {/each}
        {/if}
      </div>

      {#if d.relations.length}
        <h4 class="sec">Ligados</h4>
        <div class="rels small">
          {#each d.relations as r, i (i)}
            {#if r.kind === "item"}<span class="chip"><Link2 size={11} /> {r.name} #{r.id}</span>
            {:else}<a class="chip" href={r.url} target="_blank" rel="noopener">{#if r.kind === "file"}<Paperclip size={11} />{:else}<Link2 size={11} />{/if} {r.name}</a>{/if}
          {/each}
        </div>
      {/if}

      <h4 class="sec"><MessageSquare size={13} /> Discussão {d.comments.length ? `(${d.comments.length})` : ""}</h4>
      {#each d.comments as c, i (c.created + c.author + i)}
        <div class="cm" class:pending={c.pending} in:fly={{ y: 8, duration: 240 }}>
          <div class="small"><b>{c.author}</b> <span class="muted">{#if c.pending}enviando…{:else}<Ago iso={c.created} prefix="há " />{/if}</span></div>
          <div class="doc">{@html c.markdown !== undefined ? renderMarkdown(c.markdown) : safeHtml(c.html || "")}</div>
        </div>
      {:else}<p class="muted small">Nenhum comentário.</p>{/each}
      <div class="reply">
        <textarea class="input" rows="3" bind:value={reply} placeholder={gh ? "Comentar… (Markdown)" : "Comentar…"} onkeydown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); } }}></textarea>
        <div class="racts">
          {#if gh}
            {#if doneState}<button class="btn sm ghost" disabled={busy.state} onclick={() => setState("open")}><CircleDot size={13} /> Reabrir</button>
            {:else}<button class="btn sm ghost" disabled={busy.state || sending} onclick={() => (reply.trim() ? send(true) : setState("closed"))}><CheckCircle2 size={13} /> {reply.trim() ? "Comentar e fechar" : "Fechar issue"}</button>{/if}
          {/if}
          <button class="btn sm" disabled={!reply.trim() || sending} onclick={() => send()}><Send size={13} /> Comentar</button>
        </div>
      </div>
    {/if}
  </div>
</Drawer>

<style>
  .id { display: flex; flex-direction: column; gap: 10px; }
  .ttl { margin: 0; font-size: 17px; line-height: 1.35; cursor: text; border-radius: 6px; padding: 2px 4px; margin-left: -4px; transition: background var(--t-fast); }
  .ttl:hover { background: var(--surface-2); }
  .ttl :global(.pen) { color: var(--muted); opacity: 0; margin-left: 6px; vertical-align: middle; transition: opacity var(--t-fast); }
  .ttl:hover :global(.pen) { opacity: 1; }
  .ttl-in { font-size: 16px; font-weight: 600; height: 34px; }
  .meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .lnk { display: inline-flex; align-items: center; gap: 4px; color: var(--accent); text-decoration: none; margin-left: auto; }
  .chip { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 99px; border: 1px solid var(--line-2); color: var(--text-2);
    font-size: 11.5px; text-decoration: none; }
  a.chip:hover { color: var(--text); border-color: var(--line-3); }
  .chip.lc { color: var(--c); background: color-mix(in srgb, var(--c) 14%, transparent); border-color: color-mix(in srgb, var(--c) 30%, transparent); font-weight: 600; }
  .x { display: grid; place-items: center; width: 14px; height: 14px; margin-right: -4px; border: 0; border-radius: 50%; background: none; color: inherit; opacity: 0.55; cursor: pointer; padding: 0; }
  .x:hover { opacity: 1; background: color-mix(in srgb, currentColor 15%, transparent); }

  /* estado: um pill que é um select por cima (troca no clique, com a cor da categoria) */
  .stsel { position: relative; display: inline-flex; align-items: center; gap: 5px; height: 22px; padding: 0 9px; border-radius: 99px; font: 600 11.5px/1 var(--font);
    cursor: pointer; overflow: hidden; transition: background var(--t) var(--ease), color var(--t) var(--ease); }
  .stsel.open { background: var(--info-soft); color: var(--info); }
  .stsel.prog { background: var(--warn-soft); color: var(--warn); }
  .stsel.done { background: var(--good-soft); color: var(--good); }
  .stsel select { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
  .stsel:hover { filter: brightness(1.1); }

  .fields { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 7px 14px; align-items: center; padding: 10px 12px; border: 1px solid var(--line);
    border-radius: 10px; background: var(--surface-2); }
  .fk { color: var(--muted); }
  .fv { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; min-height: 24px; border-radius: 6px; transition: opacity var(--t-fast); }
  .mini { height: 24px; padding: 0 6px; border: 1px dashed var(--line-2); border-radius: 99px; background: none; color: var(--text-2); font: 12px var(--font);
    cursor: pointer; max-width: 220px; }
  .mini.wide { border-style: solid; border-radius: 6px; max-width: 100%; min-width: 180px; }
  .mini:hover, .mini:focus { border-color: var(--accent); color: var(--text); outline: none; }
  .tagin { display: inline-flex; align-items: center; gap: 3px; height: 22px; padding: 0 8px; border: 1px dashed var(--line-2); border-radius: 99px; color: var(--muted); }
  .tagin:focus-within { border-color: var(--accent); }
  .tagin input { width: 80px; border: 0; background: none; color: var(--text); font: 12px var(--font); outline: none; }

  .busy { opacity: 0.6; pointer-events: none; }
  .shake { animation: shake 0.42s var(--ease); }
  .fl { animation: flash 1.1s var(--ease); border-radius: 6px; }
  @keyframes shake { 20%, 60% { transform: translateX(-4px); } 40%, 80% { transform: translateX(4px); } }

  .impl { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 10px; }
  .impl select { min-width: 200px; flex: 1; }
  .sec { display: flex; align-items: center; gap: 6px; margin: 10px 0 0; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
  .ed { display: inline-flex; align-items: center; gap: 4px; margin-left: auto; padding: 2px 7px; border: 0; border-radius: 6px; background: none; color: var(--muted);
    font: 500 11.5px var(--font); text-transform: none; letter-spacing: 0; cursor: pointer; opacity: 0.7; transition: opacity var(--t-fast), background var(--t-fast); }
  .ed:hover { opacity: 1; background: var(--surface-2); color: var(--text); }
  .body { display: grid; gap: 8px; transition: opacity var(--t-fast); }
  .empty-desc { display: inline-flex; align-items: center; gap: 6px; justify-self: start; padding: 8px 12px; border: 1px dashed var(--line-2); border-radius: 8px;
    background: none; color: var(--muted); font: 12.5px var(--font); cursor: pointer; }
  .empty-desc:hover { color: var(--text); border-color: var(--accent); }
  .editor { display: grid; gap: 6px; }
  .editor textarea { width: 100%; resize: vertical; font-family: var(--mono); font-size: 12.5px; line-height: 1.55; }
  .etabs { display: flex; align-items: center; gap: 2px; }
  .etabs button { padding: 4px 10px; border: 0; border-radius: 6px; background: none; color: var(--muted); font: 500 12px var(--font); cursor: pointer; }
  .etabs button.on { background: var(--surface-3); color: var(--text); }
  .eacts { display: flex; align-items: center; justify-content: flex-end; gap: 6px; }
  .pv, .rich { min-height: 120px; padding: 10px 12px; border: 1px solid var(--line-2); border-radius: 8px; background: var(--bg-2); }
  .rich { outline: none; }
  .rich:focus { border-color: var(--accent); box-shadow: var(--ring); }
  .rels { display: flex; flex-wrap: wrap; gap: 6px; }
  .doc { font-size: 13.5px; line-height: 1.6; color: var(--text); overflow-wrap: anywhere; }
  .doc :global(img) { max-width: 100%; }
  .doc :global(pre) { overflow: auto; padding: 10px; border-radius: 8px; background: var(--bg-2); }
  .doc :global(code) { font-family: var(--mono); font-size: 12.5px; }
  .doc :global(a) { color: var(--accent); }
  .doc :global(table) { border-collapse: collapse; }
  .doc :global(td), .doc :global(th) { border: 1px solid var(--line); padding: 4px 8px; }
  .doc :global(> :first-child) { margin-top: 0; }
  .cm { padding: 10px 12px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface-2); display: grid; gap: 4px; transition: opacity var(--t); }
  .cm.pending { opacity: 0.55; border-style: dashed; }
  .reply { display: grid; gap: 6px; }
  .reply textarea { width: 100%; resize: vertical; }
  .racts { display: flex; justify-content: flex-end; gap: 6px; }
  .err { color: var(--bad); }
  .shimw { display: grid; gap: 10px; }
  .shimw .shim { height: 12px; }
  .shimw .shim:nth-child(2) { width: 70%; }
  .shimw .shim:nth-child(3) { width: 85%; }
  .shimw .shim:nth-child(4) { width: 40%; }
</style>
