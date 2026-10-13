<script lang="ts">
  // Cartão do quadro: o que fazer, em qual grupo e em quais projetos. Cada projeto entra como "muda" (a IA altera; um
  // worktree em cada, mesma branch) ou "consulta" (a IA lê, não altera); o principal (★) é onde a IA roda.
  import { Eye, FolderPlus, Layers, Pencil, Sparkles, Star, Trash2 } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { kanban, PRIORITY, type Card, type Priority } from "../../lib/kanban.svelte";
  import { repos } from "../../lib/repos.svelte";
  import { store } from "../../lib/store.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { work } from "../../lib/work.svelte";
  import Drawer from "../Drawer.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import Segmented from "../Segmented.svelte";

  let { card = null, column = null, onclose, onrun }: { card?: Card | null; column?: string | null; onclose: () => void; onrun?: (c: Card) => void } = $props();
  const c0 = untrack(() => card);
  let title = $state(c0?.title || "");
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
  function setRole(id: string, role: string) {
    projects = projects.filter(x => x !== id);
    refs = refs.filter(x => x !== id);
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

  async function save(run = false) {
    if (!title.trim()) return ui.toast("Dê um título ao cartão", "info");
    busy = true;
    const saved = await kanban.saveCard({ id: c0?.id, title: title.trim(), description, column: col, priority, labels: labelList, groupId, projects, refs,
      primary, workItem: workItem ? { number: workItem.number, title: workItem.title, url: workItem.url, provider: workItem.provider, key: workItem.key } : null, due: due || null });
    busy = false;
    if (!saved) return;
    onclose();
    if (run) { const fresh = kanban.cards.find(x => x.id === saved.id); if (fresh) onrun?.(fresh); }
  }
  async function remove() {
    if (!c0 || !(await ui.ask({ title: `Excluir “${c0.title}”?`, message: "As tarefas e worktrees que a IA criou para ele continuam nos projetos.", confirm: "Excluir", danger: true }))) return;
    await kanban.deleteCard(c0.id);
    onclose();
  }
  async function newGroup() {
    const g = await work.newGroup(projects);
    if (g) groupId = g.id;
  }
</script>

<Drawer title={c0 ? "Cartão" : "Novo cartão"} subtitle="O que fazer, em qual grupo e em quais projetos — a IA usa tudo isso como contexto" {onclose} width={680}>
  <div class="f">
    <!-- svelte-ignore a11y_autofocus -->
    <input class="input big" bind:value={title} placeholder="Título — ex.: Cobrança recorrente: novo campo de vencimento nas 4 APIs" autofocus={!c0} />

    <div class="desc">
      <div class="dh"><span class="label">Descrição</span><span class="muted tiny">critérios de aceite, contexto, links</span>
        {#if description}<button class="btn sm ghost" onclick={() => (preview = !preview)}>{#if preview}<Pencil size={12} /> Editar{:else}<Eye size={12} /> Ver{/if}</button>{/if}</div>
      {#if preview && description}
        <button class="pv" onclick={() => (preview = false)} title="Clique para editar">{description}</button>
      {:else}
        <textarea class="input" rows="7" bind:value={description} placeholder={"- [ ] O que precisa acontecer\n- [ ] Como saber que está pronto\n\nArquivos, endpoints, decisões…"}></textarea>
      {/if}
    </div>

    <div class="row">
      <label class="label">Coluna<select class="input" bind:value={col}>{#each kanban.columns as c (c.id)}<option value={c.id}>{c.name}</option>{/each}</select></label>
      <label class="label">Prazo<input class="input" type="date" bind:value={due} /></label>
    </div>
    <div class="row">
      <div class="label">Prioridade
        <Segmented size="sm" bind:value={priority} options={(["low", "normal", "high", "urgent"] as Priority[]).map(p => ({ value: p, label: PRIORITY[p].label }))} />
      </div>
    </div>
    <label class="label">Etiquetas <span class="muted">separadas por vírgula</span>
      <input class="input" bind:value={labels} placeholder="back-end, bug, cliente X" />
      {#if allLabels.length}<div class="chips">{#each allLabels as l (l)}<button class="chip" onclick={() => (labels = [...labelList, l].join(", "))}>+ {l}</button>{/each}</div>{/if}
    </label>

    <div class="label">Grupo de projetos
      <div class="grow-row">
        <select class="input" value={groupId || ""} onchange={(e) => (groupId = (e.target as HTMLSelectElement).value || null)}>
          <option value="">Sem grupo</option>{#each work.groups as g (g.id)}<option value={g.id}>{g.name} ({g.repoIds.length})</option>{/each}
        </select>
        <button class="btn sm" onclick={newGroup}><FolderPlus size={13} /> Novo grupo</button>
        {#if group}<button class="btn sm ghost" onclick={useGroup} title="Põe os projetos do grupo como consulta"><Layers size={13} /> Usar os projetos do grupo</button>{/if}
      </div>
    </div>

    <div class="label">Projetos <span class="muted">— <b>muda</b>: a IA altera (worktree na mesma branch) · <b>consulta</b>: só lê · <Star size={10} /> onde a IA roda</span></div>
    <input class="input" bind:value={q} placeholder="filtrar projetos…" />
    <div class="projs">
      {#each list as r (r.id)}
        {@const role = roleOf(r.id)}
        {@const g = work.groupOf(r.id)}
        <div class="pr" class:on={role !== "none"}>
          <ProviderIcon provider={r.provider || null} size={13} />
          <span class="grow ell"><b>{r.name}</b>{#if g}<span class="gdot" style="background:{g.color}" title={g.name}></span>{/if}<span class="tiny muted"> {r.path.replace(/^\/Users\/[^/]+/, "~")}</span></span>
          {#if role === "change"}
            <button class="star" class:on={primary === r.id} title={primary === r.id ? "A IA roda aqui" : "Rodar a IA neste projeto"} onclick={() => (primary = r.id)}><Star size={13} /></button>
          {/if}
          <div class="seg">
            <button class:on={role === "none"} onclick={() => setRole(r.id, "none")}>—</button>
            <button class:on={role === "change"} onclick={() => setRole(r.id, "change")}>muda</button>
            <button class:on={role === "ref"} onclick={() => setRole(r.id, "ref")}>consulta</button>
          </div>
        </div>
      {:else}<div class="small muted">Nenhum projeto clonado com esse nome.</div>{/each}
    </div>
    {#if projects.length > 1}<p class="tiny muted">A IA roda em <b>{repos.byId(primary || "")?.name}</b> e cria a mesma branch em {projects.filter(x => x !== primary).map(x => repos.byId(x)?.name).join(", ")}.</p>{/if}

    {#if issues.length}
      <details class="wi" open={!!workItem}>
        <summary>{workItem ? `Ligado a #${workItem.number} ${workItem.title}` : "Ligar a uma issue / work item (opcional)"}</summary>
        <div class="wil">{#each issues as i (i.key)}<button class:on={workItem?.key === i.key} onclick={() => { workItem = workItem?.key === i.key ? null : i; if (!title) title = i.title; }}><ProviderIcon provider={i.provider} size={12} /> <b>#{i.number}</b> <span class="ell">{i.title}</span></button>{/each}</div>
      </details>
    {/if}
  </div>
  {#snippet footer()}
    {#if c0}<button class="btn ghost danger" onclick={remove}><Trash2 size={14} /> Excluir</button>{/if}
    <span class="spacer"></span>
    <button class="btn" onclick={onclose}>Cancelar</button>
    <button class="btn" disabled={busy || !title.trim()} onclick={() => save(false)}>Salvar</button>
    <button class="btn primary" disabled={busy || !title.trim() || !projects.length} title={projects.length ? "" : "Marque ao menos um projeto que muda"} onclick={() => save(true)}><Sparkles size={14} /> Salvar e pedir à IA</button>
  {/snippet}
</Drawer>

<style>
  .f { display: grid; gap: 12px; padding-top: 12px; }
  .big { height: 40px; font-size: 15px; font-weight: 600; }
  .desc { display: grid; gap: 6px; }
  .dh { display: flex; align-items: center; gap: 8px; }
  .dh .btn { margin-left: auto; }
  textarea { resize: vertical; min-height: 120px; font: 13px/1.5 var(--font); padding: 8px 10px; height: auto; }
  .pv { white-space: pre-wrap; text-align: left; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface-2); color: var(--text-2);
    font: 13px/1.5 var(--font); cursor: text; max-height: 260px; overflow: auto; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .label { display: grid; gap: 6px; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { height: 22px; padding: 0 8px; border-radius: 99px; border: 1px dashed var(--line-3); background: none; color: var(--muted); font: 11.5px var(--font); cursor: pointer; }
  .chip:hover { color: var(--text); border-color: var(--accent); }
  .grow-row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .grow-row .input { flex: 1; min-width: 180px; }
  .projs { display: grid; grid-template-columns: minmax(0, 1fr); gap: 2px; max-height: 300px; overflow: auto; padding: 4px; border-radius: 10px; border: 1px solid var(--line); background: var(--bg-2); }
  .pr { display: flex; align-items: center; gap: 8px; padding: 5px 6px; border-radius: 8px; font-size: 12.5px; color: var(--text-2); }
  .pr.on { background: var(--surface-2); color: var(--text); }
  .pr .grow { flex: 1; min-width: 0; }
  .gdot { display: inline-block; width: 7px; height: 7px; border-radius: 2px; margin-left: 6px; }
  .seg { display: flex; gap: 1px; padding: 2px; border-radius: 7px; background: var(--bg-2); border: 1px solid var(--line); flex: none; }
  .seg button { height: 22px; padding: 0 8px; border: 0; border-radius: 5px; background: none; color: var(--muted); font: 600 11px var(--font); cursor: pointer; }
  .seg button.on { background: var(--surface-3); color: var(--text); }
  .star { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--faint); cursor: pointer; }
  .star.on { color: var(--warn); }
  .star.on :global(svg) { fill: currentColor; }
  .wi summary { cursor: pointer; font-size: 13px; color: var(--text-2); }
  .wil { display: grid; gap: 2px; max-height: 180px; overflow: auto; margin-top: 6px; }
  .wil button { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border: 0; border-radius: 7px; background: none; color: var(--text-2);
    font: 12.5px var(--font); text-align: left; cursor: pointer; min-width: 0; }
  .wil button:hover, .wil button.on { background: var(--accent-soft); color: var(--text); }
  .spacer { flex: 1; }
  .danger:hover { color: var(--bad); }
</style>
