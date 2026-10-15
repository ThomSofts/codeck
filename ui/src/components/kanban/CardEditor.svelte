<script lang="ts">
  // Cartão do quadro. O essencial é o título; descrição (com checklist "- [ ]"), anexos, prazo, prioridade e etiquetas
  // são opcionais. "Automação com IA" (opcional) diz o grupo e os projetos: Principal (a IA abre e trabalha nele),
  // Também altera (um worktree na mesma branch) ou Só consulta (a IA lê, não altera).
  // Anexos: colar imagem (⌘V), arrastar arquivos para a gaveta ou escolher. No cartão novo, sobem ao salvar.
  import { ArrowUpRight, Download, Eye, FileUp, FolderOpen, FolderPlus, Layers, Link2Off, ListChecks, Paperclip, Pencil, Plus, Sparkles, Star, Trash2, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { ago, fmtSize, isImage, kanban, labelColor, LIVE, MAX_FILE, PRIORITY, type Card, type CardFile, type Priority } from "../../lib/kanban.svelte";
  import { repos } from "../../lib/repos.svelte";
  import { store } from "../../lib/store.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { work } from "../../lib/work.svelte";
  import Drawer from "../Drawer.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import Segmented from "../Segmented.svelte";
  import FileThumb from "./FileThumb.svelte";

  let { card = null, column = null, draft = "", ai = false, onclose, onrun }:
    { card?: Card | null; column?: string | null; draft?: string; ai?: boolean; onclose: () => void; onrun?: (c: Card) => void } = $props();
  const c0 = untrack(() => card);
  let title = $state(c0?.title || untrack(() => draft) || "");
  let description = $state(c0?.description || "");
  let col = $state(c0?.column || untrack(() => column) || kanban.columns.find(x => x.role === "todo")?.id || kanban.columns[0]?.id || "");
  let priority = $state<Priority>(c0?.priority || "normal");
  let labels = $state((c0?.labels || []).join(", "));
  let groupId = $state<string | null>(c0?.groupId || null);
  let projects = $state<string[]>([...(c0?.projects || [])]);
  let refs = $state<string[]>([...(c0?.refs || [])]);
  let primary = $state<string | null>(c0?.primary || null);
  let workItem = $state<any>(c0?.workItem || null);
  let due = $state(c0?.due || "");
  let q = $state("");
  let busy = $state(false);
  let preview = $state(!!c0?.description);
  let aiOpen = $state(!!c0?.projects.length || untrack(() => ai));
  // o cartão como está no quadro agora (anexos, histórico e estado da IA mudam enquanto a gaveta está aberta)
  const cur = $derived(c0 ? kanban.cards.find(x => x.id === c0.id) || c0 : null);

  const isWt = (p: string) => /[\\/]\.worktrees[\\/]/.test(p);
  const group = $derived(work.groups.find(g => g.id === groupId) || null);
  const all = $derived(repos.local.filter(r => r.exists && !isWt(r.path)));
  const list = $derived.by(() => {
    const t = q.trim().toLowerCase();
    const inG = (id: string) => !!group?.repoIds.includes(id);
    return all.filter(r => !t || r.name.toLowerCase().includes(t) || (r.slug || "").toLowerCase().includes(t))
      .sort((a, b) => Number(!projects.includes(a.id) && !refs.includes(a.id)) - Number(!projects.includes(b.id) && !refs.includes(b.id))
        || Number(!inG(a.id)) - Number(!inG(b.id)) || a.name.localeCompare(b.name)).slice(0, t ? 60 : 40);
  });
  const roleOf = (id: string) => (projects.includes(id) ? "change" : refs.includes(id) ? "ref" : "none");
  // os escolhidos, o principal primeiro
  const chosen = $derived([...(primary ? [primary] : []), ...projects.filter(x => x !== primary), ...refs]);
  function setRole(id: string, role: "primary" | "change" | "ref" | "none") {
    projects = projects.filter(x => x !== id);
    refs = refs.filter(x => x !== id);
    if (role === "primary") { projects = [id, ...projects]; primary = id; return; }
    if (role === "change") { projects = [...projects, id]; if (!primary) primary = id; }
    else if (role === "ref") refs = [...refs, id];
    if (primary === id && role !== "change") primary = projects[0] || null;
  }
  function useGroup() {
    if (!group) return;
    for (const id of group.repoIds) if (roleOf(id) === "none" && all.some(r => r.id === id)) refs = [...refs, id];
  }
  const issues = $derived((store.s?.issues || []).slice(0, 80));
  const labelList = $derived(labels.split(",").map(x => x.trim()).filter(Boolean));
  const allLabels = $derived([...new Set(kanban.cards.flatMap(c => c.labels))].filter(l => !labelList.includes(l)).slice(0, 12));
  const colName = (id: string) => kanban.columns.find(x => x.id === id)?.name || id;

  // ------------------------------------------------------------ descrição e checklist
  const lines = $derived(description.split("\n"));
  const CK = /^(\s*[-*]\s*\[)([ xX])(\]\s?)(.*)$/;
  function toggleLine(i: number) {
    const ls = description.split("\n");
    const m = ls[i].match(CK);
    if (!m) return;
    ls[i] = m[1] + (m[2] === " " ? "x" : " ") + m[3] + m[4];
    description = ls.join("\n");
    // cartão existente: marcar um item já vale (não depende de "Salvar")
    if (c0) kanban.setDescription(c0.id, description);
  }
  let ta: HTMLTextAreaElement | undefined = $state();
  function addCheck() {
    preview = false;
    const sep = description && !description.endsWith("\n") ? "\n" : "";
    description = description + sep + "- [ ] ";
    requestAnimationFrame(() => { ta?.focus(); ta?.setSelectionRange(description.length, description.length); });
  }

  // ------------------------------------------------------------ anexos
  let pending = $state<{ file: File; url: string | null }[]>([]);   // cartão novo: sobem ao salvar
  let dropping = $state(false);
  let picker: HTMLInputElement | undefined = $state();
  let viewing = $state<CardFile | null>(null);
  const files = $derived(cur?.files || []);
  async function addFiles(fs: File[]) {
    if (!fs.length) return;
    if (c0) return kanban.attach(c0.id, fs);
    const big = fs.filter(f => f.size > MAX_FILE);
    if (big.length) ui.toast(`${big.map(f => f.name).join(", ")} passa de 25 MB — não anexado`, "error");
    pending = [...pending, ...fs.filter(f => f.size <= MAX_FILE && f.size > 0).map(file => ({ file, url: file.type.startsWith("image/") ? URL.createObjectURL(file) : null }))];
  }
  $effect(() => () => { for (const p of untrack(() => pending)) if (p.url) URL.revokeObjectURL(p.url); });
  // colar imagem/arquivo em qualquer lugar da gaveta (inclusive na descrição): vira anexo
  $effect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const fs = [...(e.clipboardData?.items || [])].filter(i => i.kind === "file").map(i => i.getAsFile()).filter((f): f is File => !!f);
      if (!fs.length) return;
      e.preventDefault();
      addFiles(fs);
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  });
  const hasFiles = (e: DragEvent) => !!e.dataTransfer?.types?.includes("Files");
  function dragOver(e: DragEvent) { if (!hasFiles(e)) return; e.preventDefault(); e.stopPropagation(); dropping = true; }
  function dropFiles(e: DragEvent) {
    if (!hasFiles(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dropping = false;
    addFiles([...(e.dataTransfer?.files || [])]);
  }
  async function removeFile(f: CardFile) {
    if (!c0 || !(await ui.ask({ title: `Remover “${f.name}”?`, confirm: "Remover", danger: true }))) return;
    if (viewing?.id === f.id) viewing = null;
    kanban.removeFile(c0.id, f.id);
  }
  let viewUrl = $state<string | null>(null);
  $effect(() => {
    const f = viewing;
    viewUrl = null;
    if (f && c0) kanban.fileUrl(c0.id, f.id).then(u => { if (viewing?.id === f.id) viewUrl = u; }).catch(e => ui.error(e));
  });

  async function save(run = false) {
    if (!title.trim()) return ui.toast("Dê um título ao cartão", "info");
    busy = true;
    const saved = await kanban.saveCard({ id: c0?.id, title: title.trim(), description, column: col, priority, labels: labelList, groupId, projects, refs,
      primary, workItem: workItem ? { number: workItem.number, title: workItem.title, url: workItem.url, provider: workItem.provider, key: workItem.key } : null, due: due || null });
    if (saved && pending.length) await kanban.attach(saved.id, pending.map(p => p.file));
    busy = false;
    if (!saved) return;
    onclose();
    if (run) { const fresh = kanban.cards.find(x => x.id === saved.id); if (fresh) onrun?.(fresh); }
  }
  async function remove() {
    if (!c0 || !(await ui.ask({ title: `Excluir “${c0.title}”?`, message: `${files.length ? `Os ${files.length} anexo(s) vão junto. ` : ""}As tarefas e worktrees que a IA criou para ele continuam nos projetos.`, confirm: "Excluir", danger: true }))) return;
    await kanban.deleteCard(c0.id);
    onclose();
  }
  async function newGroup() {
    const g = await work.newGroup(projects);
    if (g) groupId = g.id;
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); save(false); }
    if (e.key === "Escape" && viewing) { e.stopPropagation(); viewing = null; }
  }
</script>

<svelte:window onkeydowncapture={onKey} />

<Drawer title={c0 ? "Cartão" : "Novo cartão"} subtitle={c0 ? `Criado ${ago(c0.createdAt)}${cur?.updatedAt && cur.updatedAt !== c0.createdAt ? ` · alterado ${ago(cur.updatedAt)}` : ""}` : "Um título basta — o resto você refina depois"} {onclose} width={680}>
  <div class="f" class:dropping role="region" aria-label="Cartão" ondragover={dragOver} ondragleave={(e) => { if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) dropping = false; }} ondrop={dropFiles}>
    <!-- svelte-ignore a11y_autofocus -->
    <input class="input big" bind:value={title} placeholder="O que precisa ser feito?" autofocus={!c0} />

    <div class="desc">
      <div class="dh"><span class="label">Descrição</span>
        <span class="grow"></span>
        <button class="btn sm ghost" onclick={addCheck} title="Adicionar item de checklist"><ListChecks size={13} /> Item</button>
        {#if description}<button class="btn sm ghost" onclick={() => (preview = !preview)}>{#if preview}<Pencil size={12} /> Editar{:else}<Eye size={12} /> Ver{/if}</button>{/if}
      </div>
      {#if preview && description}
        <div class="pv">
          {#each lines as l, i (i)}
            {@const m = l.match(CK)}
            {#if m}
              <label class="ckl" class:done={m[2] !== " "}><input type="checkbox" checked={m[2] !== " "} onchange={() => toggleLine(i)} /><span>{m[4]}</span></label>
            {:else if l.trim()}
              <p>{l}</p>
            {:else}<span class="gap"></span>{/if}
          {/each}
        </div>
      {:else}
        <textarea class="input" rows="7" bind:this={ta} bind:value={description} placeholder={"Contexto, links, decisões…\n- [ ] Item de checklist\n\nCole uma imagem (⌘V) para anexar"}></textarea>
      {/if}
    </div>

    <div class="atts">
      <div class="dh"><span class="label">Anexos {#if files.length + pending.length}<span class="muted">{files.length + pending.length}</span>{/if}</span>
        <span class="grow"></span>
        <button class="btn sm ghost" onclick={() => picker?.click()}><FileUp size={13} /> Anexar</button>
      </div>
      {#if files.length || pending.length}
        <div class="gal">
          {#each files as f (f.id)}
            <div class="tile">
              <button class="th" title={isImage(f) ? "Ver" : "Abrir no app padrão"} onclick={() => (isImage(f) ? (viewing = f) : kanban.openFile(c0!.id, f.id))}><FileThumb cardId={c0!.id} file={f} /></button>
              <div class="fi"><span class="ell" title={f.name}>{f.name}</span><span class="tiny muted">{fmtSize(f.size)}</span></div>
              <div class="fa">
                <button title="Abrir no app padrão" onclick={() => kanban.openFile(c0!.id, f.id)}><ArrowUpRight size={13} /></button>
                <button title="Mostrar na pasta" onclick={() => kanban.openFile(c0!.id, f.id, true)}><FolderOpen size={13} /></button>
                <button class="del" title="Remover" onclick={() => removeFile(f)}><Trash2 size={13} /></button>
              </div>
            </div>
          {/each}
          {#each pending as p, i (p.url || p.file.name + i)}
            <div class="tile pend">
              <div class="th">{#if p.url}<img src={p.url} alt={p.file.name} />{:else}<span class="ext">{(p.file.name.split(".").pop() || "").slice(0, 4).toUpperCase()}</span>{/if}</div>
              <div class="fi"><span class="ell" title={p.file.name}>{p.file.name}</span><span class="tiny muted">{fmtSize(p.file.size)} · sobe ao salvar</span></div>
              <div class="fa"><button class="del" title="Tirar" onclick={() => { if (p.url) URL.revokeObjectURL(p.url); pending = pending.filter(x => x !== p); }}><X size={13} /></button></div>
            </div>
          {/each}
        </div>
      {:else}
        <button class="dz" onclick={() => picker?.click()}><Paperclip size={14} /> Arraste arquivos para cá, cole uma imagem (⌘V) ou clique para escolher <span class="muted">· até 25 MB cada</span></button>
      {/if}
    </div>

    <div class="row3">
      <label class="label">Coluna<select class="input" bind:value={col}>{#each kanban.columns as c (c.id)}<option value={c.id}>{c.name}</option>{/each}</select></label>
      <label class="label">Prazo<input class="input" type="date" bind:value={due} /></label>
      <div class="label">Prioridade
        <Segmented size="sm" bind:value={priority} options={(["low", "normal", "high", "urgent"] as Priority[]).map(p => ({ value: p, label: PRIORITY[p].label }))} />
      </div>
    </div>
    <label class="label"><span>Etiquetas <span class="muted">separadas por vírgula</span></span>
      <input class="input" bind:value={labels} placeholder="back-end, bug, cliente X" />
      {#if labelList.length || allLabels.length}
        <div class="chips">
          {#each labelList as l (l)}<span class="lb" style="--l:{labelColor(l)}">{l}</span>{/each}
          {#each allLabels as l (l)}<button class="chip" onclick={() => (labels = [...labelList, l].join(", "))}>+ {l}</button>{/each}
        </div>
      {/if}
    </label>

    {#if cur?.tasks.length}
      {@const lv = cur.live}
      <div class="task">
        <span class="sd {lv ? LIVE[lv.status][1] : 'muted'}"></span>
        <span class="grow ell"><b>{lv ? LIVE[lv.status][0] : "Tarefa da IA"}</b>{#if lv?.branch}<span class="tiny muted">{` · ${lv.branch}`}</span>{/if}
          {#if lv?.status === "missing"}<span class="tiny muted">{" · a tarefa foi removida do projeto"}</span>{/if}</span>
        {#if lv?.status !== "missing"}<button class="btn sm" onclick={() => { kanban.openTask(cur); onclose(); }}><ArrowUpRight size={13} /> Abrir a tarefa</button>{/if}
        <button class="btn sm ghost" title="Tira a ligação com a tarefa (a tarefa e o worktree continuam no projeto)" onclick={() => kanban.unlink(cur)}><Link2Off size={13} /> Desvincular</button>
      </div>
    {/if}

    <details class="ai" bind:open={aiOpen}>
      <summary><Sparkles size={13} /> <b>Automação com IA</b> <span class="muted small">opcional — onde a IA trabalha se você pedir</span>
        {#if !aiOpen && projects.length}<span class="pill accent tiny">{projects.length + refs.length} projeto(s)</span>{/if}</summary>
      <div class="aib">
        <div class="label">Grupo de projetos
          <div class="grow-row">
            <select class="input" value={groupId || ""} onchange={(e) => (groupId = (e.target as HTMLSelectElement).value || null)}>
              <option value="">Sem grupo</option>{#each work.groups as g (g.id)}<option value={g.id}>{g.name} ({g.repoIds.length})</option>{/each}
            </select>
            <button class="btn sm" onclick={newGroup}><FolderPlus size={13} /> Novo grupo</button>
          </div>
        </div>

        <div class="label">Projetos</div>
        <div class="where">
          {#each chosen as id (id)}
            {@const r = repos.byId(id)}
            {@const role = id === primary ? "primary" : roleOf(id)}
            <div class="wp" class:prim={role === "primary"}>
              <ProviderIcon provider={r?.provider || null} size={14} />
              <span class="grow ell"><b>{r?.name || "projeto removido"}</b><span class="tiny muted">{" " + (r?.path || "").replace(/^\/Users\/[^/]+/, "~")}</span></span>
              <div class="seg" role="radiogroup" aria-label={`Papel de ${r?.name}`}>
                <button class:on={role === "primary"} title="A IA abre aqui: o terminal, o agente e a branch nascem neste projeto" onclick={() => setRole(id, "primary")}><Star size={11} /> Principal</button>
                <button class:on={role === "change"} title="A IA também altera este projeto (um worktree na mesma branch)" onclick={() => setRole(id, "change")}><Pencil size={11} /> Também altera</button>
                <button class:on={role === "ref"} title="A IA só lê este projeto para entender o contexto — não altera nada" onclick={() => setRole(id, "ref")}><Eye size={11} /> Só consulta</button>
              </div>
              <button class="rm" title="Tirar do cartão" onclick={() => setRole(id, "none")}><X size={13} /></button>
            </div>
          {:else}
            <div class="empty small muted">Sem projeto, o cartão é só seu. Escolha um abaixo para poder pedir à IA.</div>
          {/each}
        </div>
        {#if primary}
          <p class="sum small">
            A IA trabalha em <b>{repos.byId(primary)?.name}</b>{#if projects.length > 1}, criando a mesma branch também em <b>{projects.filter(x => x !== primary).map(x => repos.byId(x)?.name).join(", ")}</b>{/if}{#if refs.length}, e consulta <b>{refs.map(x => repos.byId(x)?.name).join(", ")}</b> sem alterar{/if}{#if files.length + pending.length}; os anexos vão junto{/if}.
          </p>
        {/if}
        <div class="add">
          <input class="input" bind:value={q} placeholder={chosen.length ? "Adicionar outro projeto…" : "Buscar o projeto…"} />
          {#if group}<button class="btn sm ghost" onclick={useGroup} title="Adiciona os projetos do grupo como consulta"><Layers size={13} /> Projetos do grupo</button>{/if}
        </div>
        <div class="projs">
          {#each list.filter(r => roleOf(r.id) === "none") as r (r.id)}
            {@const g = work.groupOf(r.id)}
            <div class="pr">
              <ProviderIcon provider={r.provider || null} size={13} />
              <span class="grow ell"><b>{r.name}</b>{#if g}<span class="gdot" style="background:{g.color}" title={g.name}></span>{/if}<span class="tiny muted">{" " + r.path.replace(/^\/Users\/[^/]+/, "~")}</span></span>
              {#if !primary}<button class="btn sm" onclick={() => setRole(r.id, "primary")}><Star size={12} /> Principal</button>
              {:else}<button class="btn sm" onclick={() => setRole(r.id, "change")}><Plus size={12} /> Altera</button>
                <button class="btn sm ghost" onclick={() => setRole(r.id, "ref")}><Eye size={12} /> Consulta</button>{/if}
            </div>
          {:else}<div class="small muted">Nenhum projeto clonado com esse nome.</div>{/each}
        </div>
      </div>
    </details>

    {#if issues.length}
      <details class="wi" open={!!workItem}>
        <summary>{workItem ? `Ligado a #${workItem.number} ${workItem.title}` : "Ligar a uma issue / work item (opcional)"}</summary>
        <div class="wil">{#each issues as i (i.key)}<button class:on={workItem?.key === i.key} onclick={() => { workItem = workItem?.key === i.key ? null : i; if (!title) title = i.title; }}><ProviderIcon provider={i.provider} size={12} /> <b>#{i.number}</b> <span class="ell">{i.title}</span></button>{/each}</div>
      </details>
    {/if}

    {#if cur?.history?.length}
      <div class="hist">
        <span class="label">Histórico</span>
        {#each [...cur.history].reverse().slice(0, 12) as h (h.at + h.to)}
          <div class="hl"><span class="who" class:ia={h.by === "ia"}>{#if h.by === "ia"}<Sparkles size={10} /> IA{:else}Você{/if}</span>
            <span class="ell">{colName(h.from)} → <b>{colName(h.to)}</b>{#if h.why}<span class="muted">{` — ${h.why}`}</span>{/if}</span>
            <span class="tiny muted when" title={new Date(h.at).toLocaleString("pt-BR")}>{ago(h.at)}</span></div>
        {/each}
      </div>
    {/if}

    {#if dropping}<div class="drop"><Download size={18} /> Soltar para anexar ao cartão</div>{/if}
  </div>
  {#snippet footer()}
    {#if c0}<button class="btn ghost danger" onclick={remove}><Trash2 size={14} /> Excluir</button>{/if}
    <span class="spacer"></span>
    <button class="btn" onclick={onclose}>Cancelar</button>
    {#if projects.length}<button class="btn" disabled={busy || !title.trim()} onclick={() => save(true)} title="Salva e escolhe o que a IA faz"><Sparkles size={14} /> Salvar e pedir à IA</button>{/if}
    <button class="btn primary" disabled={busy || !title.trim()} onclick={() => save(false)} title="⌘Enter">{busy ? "Salvando…" : "Salvar"}</button>
  {/snippet}
</Drawer>

<input type="file" multiple hidden bind:this={picker} onchange={(e) => { const el = e.currentTarget; addFiles([...(el.files || [])]); el.value = ""; }} />

{#if viewing}
  <div class="lightbox" role="dialog" aria-label={viewing.name}>
    <button class="scrim" aria-label="Fechar" onclick={() => (viewing = null)}></button>
    {#if viewUrl}<img src={viewUrl} alt={viewing.name} />{/if}
    <div class="lbbar">
      <span class="ell">{viewing.name}</span><span class="tiny">{fmtSize(viewing.size)}</span><span class="grow"></span>
      <button class="btn sm" onclick={() => kanban.openFile(c0!.id, viewing!.id)}><ArrowUpRight size={13} /> Abrir</button>
      <button class="btn sm" onclick={() => kanban.openFile(c0!.id, viewing!.id, true)}><FolderOpen size={13} /> Mostrar na pasta</button>
      <button class="btn sm ghost icon" title="Fechar (Esc)" onclick={() => (viewing = null)}><X size={15} /></button>
    </div>
  </div>
{/if}

<style>
  .f { position: relative; display: grid; gap: 16px; padding-top: 12px; padding-bottom: 8px; }
  .big { height: 42px; font-size: 16px; font-weight: 650; }
  .desc, .atts { display: grid; gap: 6px; }
  .dh { display: flex; align-items: center; gap: 4px; min-height: 27px; }
  .grow { flex: 1; }
  .label { display: grid; gap: 6px; font-size: 12px; font-weight: 650; color: var(--text-2); }
  .dh .label { display: inline-flex; gap: 6px; }
  .label .muted { font-weight: 500; }
  textarea { resize: vertical; min-height: 130px; font: 13px/1.55 var(--font); padding: 8px 10px; height: auto; }
  .pv { position: relative; display: grid; gap: 2px; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface-2); color: var(--text-2);
    font: 13px/1.55 var(--font); max-height: 320px; overflow: auto; }
  .pv p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--text); }
  .pv .gap { height: 8px; }
  .ckl { display: flex; align-items: flex-start; gap: 8px; padding: 2px 0; cursor: pointer; color: var(--text); }
  .ckl input { margin: 3px 0 0; accent-color: var(--accent); width: 14px; height: 14px; flex: none; cursor: pointer; }
  .ckl.done span { color: var(--muted); text-decoration: line-through; }

  .gal { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
  .tile { display: grid; grid-template-rows: 92px auto auto; border-radius: 10px; border: 1px solid var(--line-2); background: var(--surface-2); overflow: hidden; animation: rise 0.2s var(--ease-out) both; }
  .tile.pend { border-style: dashed; }
  .th { display: block; width: 100%; height: 92px; padding: 0; border: 0; background: var(--surface-3); cursor: zoom-in; overflow: hidden; }
  .th img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .th .ext { display: grid; place-items: center; height: 100%; font: 700 11px var(--font); color: var(--muted); }
  .fi { display: grid; padding: 6px 8px 0; font-size: 12px; min-width: 0; }
  .fa { display: flex; gap: 2px; padding: 2px 4px 4px; }
  .fa button { display: grid; place-items: center; width: 26px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; }
  .fa button:hover { background: var(--surface-3); color: var(--text); }
  .fa .del { margin-left: auto; }
  .fa .del:hover { color: var(--bad); }
  .dz { display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 52px; padding: 10px 12px; border-radius: 10px; border: 1px dashed var(--line-3);
    background: none; color: var(--text-2); font: 12.5px var(--font); cursor: pointer; text-align: center; transition: border-color var(--t-fast), background var(--t-fast); }
  .dz:hover { border-color: var(--accent); background: var(--accent-soft); }
  .drop { position: absolute; inset: 0; z-index: 5; display: flex; align-items: center; justify-content: center; gap: 10px; border-radius: 12px; border: 2px dashed var(--accent);
    background: color-mix(in srgb, var(--accent) 10%, var(--surface)); color: var(--accent); font: 600 14px var(--font); pointer-events: none; animation: fade 0.12s both; }

  .row3 { display: grid; grid-template-columns: 1fr 1fr auto; gap: 12px; align-items: start; }
  @media (max-width: 620px) { .row3 { grid-template-columns: 1fr 1fr; } }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { height: 22px; padding: 0 8px; border-radius: 99px; border: 1px dashed var(--line-3); background: none; color: var(--muted); font: 11.5px var(--font); cursor: pointer; }
  .chip:hover { color: var(--text); border-color: var(--accent); }
  .lb { display: inline-flex; align-items: center; height: 22px; padding: 0 8px; border-radius: 6px; font: 600 11px var(--font);
    background: color-mix(in srgb, var(--l) 16%, transparent); color: color-mix(in srgb, var(--l) 70%, var(--text)); }

  .task { display: flex; align-items: center; gap: 10px; padding: 8px 8px 8px 12px; border-radius: 10px; border: 1px solid var(--line-2); background: var(--surface-2); font-size: 13px; flex-wrap: wrap; }
  .task .grow { min-width: 160px; }
  .sd { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); flex: none; }
  .sd.accent { background: var(--accent); } .sd.warn { background: var(--warn); } .sd.good { background: var(--good); } .sd.bad { background: var(--bad); }
  .sd.muted { background: transparent; box-shadow: inset 0 0 0 1.5px var(--muted); }

  .ai { border-radius: 10px; border: 1px solid var(--line); background: var(--bg-2); }
  .ai summary { display: flex; align-items: center; gap: 8px; padding: 10px 12px; cursor: pointer; font-size: 13px; list-style: none; }
  .ai summary::-webkit-details-marker { display: none; }
  .ai summary :global(svg) { color: var(--accent); }
  .ai summary::after { content: "›"; margin-left: auto; color: var(--muted); transition: transform var(--t-fast); }
  .ai[open] summary::after { transform: rotate(90deg); }
  .aib { display: grid; gap: 10px; padding: 0 12px 12px; }
  .grow-row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .grow-row .input { flex: 1; min-width: 180px; }
  .where { display: grid; gap: 6px; }
  .wp { display: flex; align-items: center; gap: 8px; padding: 8px 8px 8px 10px; border-radius: 10px; border: 1px solid var(--line-2); background: var(--surface-2);
    font-size: 12.5px; animation: rise 0.2s var(--ease-out); flex-wrap: wrap; }
  .wp.prim { border-color: color-mix(in srgb, var(--warn) 55%, transparent); background: color-mix(in srgb, var(--warn) 7%, var(--surface-2)); }
  .wp .grow { flex: 1; min-width: 140px; }
  .wp .seg button { display: inline-flex; align-items: center; gap: 4px; }
  .wp .seg button.on:first-child { color: var(--warn); }
  .rm { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; }
  .rm:hover { background: var(--surface-3); color: var(--bad); }
  .empty { padding: 10px 12px; border-radius: 10px; border: 1px dashed var(--line-3); }
  .sum { margin: 0; padding: 8px 12px; border-radius: 10px; background: var(--accent-soft); color: var(--text-2); }
  .sum b { color: var(--text); }
  .add { display: flex; gap: 6px; }
  .add .input { flex: 1; }
  .projs { display: grid; grid-template-columns: minmax(0, 1fr); gap: 2px; max-height: 220px; overflow: auto; padding: 4px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface); }
  .pr { display: flex; align-items: center; gap: 8px; padding: 5px 6px; border-radius: 8px; font-size: 12.5px; color: var(--text-2); }
  .pr:hover { background: var(--surface-2); color: var(--text); }
  .pr .grow { min-width: 0; }
  .gdot { display: inline-block; width: 7px; height: 7px; border-radius: 2px; margin-left: 6px; }
  .seg { display: flex; gap: 1px; padding: 2px; border-radius: 7px; background: var(--bg-2); border: 1px solid var(--line); flex: none; }
  .seg button { height: 22px; padding: 0 8px; border: 0; border-radius: 5px; background: none; color: var(--muted); font: 600 11px var(--font); cursor: pointer; }
  .seg button.on { background: var(--surface-3); color: var(--text); }
  .wi summary { cursor: pointer; font-size: 13px; color: var(--text-2); }
  .wil { display: grid; gap: 2px; max-height: 180px; overflow: auto; margin-top: 6px; }
  .wil button { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border: 0; border-radius: 7px; background: none; color: var(--text-2);
    font: 12.5px var(--font); text-align: left; cursor: pointer; min-width: 0; }
  .wil button:hover, .wil button.on { background: var(--accent-soft); color: var(--text); }

  .hist { display: grid; gap: 2px; }
  .hist .label { margin-bottom: 4px; }
  .hl { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-2); min-height: 24px; }
  .who { display: inline-flex; align-items: center; gap: 3px; flex: none; width: 52px; font-weight: 600; color: var(--muted); }
  .who.ia { color: var(--accent); }
  .hl .ell { flex: 1; }
  .hl b { color: var(--text); font-weight: 600; }
  .when { flex: none; }
  .spacer { flex: 1; }
  .danger:hover { color: var(--bad); }

  .lightbox { position: fixed; inset: 0; z-index: 60; display: grid; place-items: center; padding: 40px 40px 80px; animation: fade 0.16s both; }
  .lightbox .scrim { position: absolute; inset: 0; border: 0; background: rgba(5, 7, 12, 0.82); cursor: zoom-out; }
  .lightbox img { position: relative; max-width: 100%; max-height: 100%; border-radius: 8px; box-shadow: var(--shadow-3); object-fit: contain; }
  .lbbar { position: absolute; left: 50%; bottom: 20px; transform: translateX(-50%); display: flex; align-items: center; gap: 8px; width: min(640px, calc(100% - 32px));
    padding: 6px 6px 6px 14px; border-radius: 12px; background: var(--elevated); border: 1px solid var(--line-2); box-shadow: var(--shadow-2); font-size: 13px; }
  @media (prefers-reduced-motion: reduce) { .tile, .wp, .drop, .lightbox { animation: none; } }
</style>
