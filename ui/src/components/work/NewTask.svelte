<script lang="ts">
  // Nova tarefa: branch + worktree próprio + (opcional) um ou mais agentes já com o prompt.
  // Vários agentes = fan-out: cada um no SEU worktree, para comparar e ficar com o melhor.
  import { GitBranch, Rocket, ShieldOff, Sparkles } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { get, post } from "../../lib/api";
  import { store } from "../../lib/store.svelte";
  import type { Project } from "../../lib/work.svelte";
  import { work } from "../../lib/work.svelte";
  import { ui } from "../../lib/ui.svelte";
  import Drawer from "../Drawer.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import Segmented from "../Segmented.svelte";
  import AgentIcon from "./AgentIcon.svelte";
  import { repos } from "../../lib/repos.svelte";

  let { project, preset = null, onclose, oncreated }:
    { project: Project; preset?: { title?: string; prompt?: string; kind?: string; workItem?: any; base?: string; reviewOf?: any } | null; onclose: () => void; oncreated: (taskIds: string[]) => void } = $props();

  let title = $state(untrack(() => preset?.title || ""));
  let kind = $state(untrack(() => preset?.kind || "feature"));
  let base = $state(untrack(() => preset?.base || ""));
  let prompt = $state(untrack(() => preset?.prompt || ""));
  let mode = $state("default");
  let chosen = $state<string[]>(untrack(() => (work.defaultAccount(project) ? [work.defaultAccount(project)!] : [])));
  let branches = $state<string[]>([]);
  let busy = $state(false);
  let workItem = $state<any>(untrack(() => preset?.workItem || null));
  let linked = $state<string[]>([]);
  let linkQ = $state("");
  // outros repositórios para a mesma tarefa (sem os worktrees, que também ficam registrados)
  const others = $derived(repos.local.filter(r => r.exists && r.id !== project.id && !/[\\/]\.worktrees[\\/]/.test(r.path)
    && (!linkQ || r.name.toLowerCase().includes(linkQ.toLowerCase()))).slice(0, 30));
  const slug = $derived(title.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "tarefa");
  const items = $derived((store.s?.issues || []).filter(i => !project.provider || i.provider === project.provider).slice(0, 60));

  const pid = $derived(project.id);   // a prop troca de objeto a cada leitura: as branches só são relidas se o projeto mudar
  $effect(() => {
    get<any>("repo/refs", { id: pid }).then(r => {
      branches = [...new Set([...(r.remote || []).map((b: any) => b.name).filter((n: string) => !n.endsWith("/HEAD")), ...(r.local || []).map((b: any) => b.name)])];
      if (!base) base = branches.find(b => /origin\/(develop|main|master)$/.test(b)) || r.default || branches[0] || "";
    }).catch(() => {});
  });
  function pickItem(i: any) {
    workItem = i;
    if (!title) title = i.title;
    if (!prompt) prompt = `Implemente o ${i.provider === "github" ? "issue" : "work item"} #${i.number}: ${i.title}\n${i.url || ""}`;
  }
  const toggle = (id: string) => (chosen = chosen.includes(id) ? chosen.filter(x => x !== id) : [...chosen, id]);

  async function create() {
    if (!title.trim()) return ui.toast("Diga o que é a tarefa", "info");
    busy = true;
    const prog = ui.progress(chosen.length > 1 ? `Criando ${chosen.length} worktrees…` : "Criando o worktree…");
    try {
      const ids: string[] = [];
      // fan-out: um worktree por agente (branch com sufixo do agente); sem agente, um worktree só
      const runs = chosen.length > 1 ? chosen : [chosen[0] || null];
      for (const aid of runs) {
        const acc = work.account(aid);
        const sfx = chosen.length > 1 && acc ? `-${acc.provider}-${acc.name}`.toLowerCase().replace(/[^a-z0-9-]/g, "") : "";
        const t = await post<any>("ws/task", { repoId: project.id, title: title.trim() + (sfx ? ` (${acc!.label} · ${acc!.name})` : ""),
          kind, slug: slug + sfx, base, prompt: prompt.trim() || title.trim(), agents: aid ? [aid] : [], mode,
          workItem: workItem ? { number: workItem.number, title: workItem.title, url: workItem.url, provider: workItem.provider } : null,
          group: chosen.length > 1 ? slug : null, linked, reviewOf: preset?.reviewOf || null });
        ids.push(t.id);
      }
      prog.done(chosen.length > 1 ? `${ids.length} agentes trabalhando em paralelo` : "Tarefa criada");
      await work.load();
      oncreated(ids);
    } catch (e) { prog.fail(e); }
    busy = false;
  }
</script>

<Drawer title="Nova tarefa" subtitle={`${project.name} — branch e worktree próprios, sem mexer no seu checkout`} {onclose} width={620}>
  <div class="form">
    <label class="label">O que fazer<input class="input" bind:value={title} placeholder="ex.: Ajustar o cálculo do frete no carrinho" /></label>
    <div class="row2">
      <Segmented size="sm" bind:value={kind} options={[{ value: "feature", label: "feature/" }, { value: "fix", label: "fix/" }, { value: "review", label: "review/" }]} />
      <span class="branch mono"><GitBranch size={12} /> {kind}/{slug}</span>
    </div>
    <label class="label">A partir de
      <select class="input" bind:value={base}>{#each branches as b (b)}<option value={b}>{b}</option>{/each}</select></label>

    {#if items.length}
      <details class="wi" open={!!workItem}>
        <summary>{workItem ? `#${workItem.number} ${workItem.title}` : "Ligar a um work item / issue (opcional)"}</summary>
        <div class="wil">{#each items as i (i.key)}<button class:on={workItem?.key === i.key} onclick={() => pickItem(i)}><ProviderIcon provider={i.provider} size={12} /> <b>#{i.number}</b> <span class="ell">{i.title}</span></button>{/each}</div>
      </details>
    {/if}

    <details class="wi" open={linked.length > 0}>
      <summary>{linked.length ? `Também em: ${linked.map(id => repos.byId(id)?.name).join(", ")}` : "Mesma tarefa em outros repositórios (opcional)"}</summary>
      <p class="small muted">Um worktree em cada, na mesma branch — o agente enxerga todos (ex.: entidades → infra → API).</p>
      <input class="input" bind:value={linkQ} placeholder="filtrar repositórios…" />
      <div class="wil">{#each others as r (r.id)}<button class:on={linked.includes(r.id)} onclick={() => (linked = linked.includes(r.id) ? linked.filter(x => x !== r.id) : [...linked, r.id])}>
        <ProviderIcon provider={r.provider || null} size={12} /> <b>{r.name}</b> <span class="tiny muted ell">{r.path.replace(/^\/Users\/[^/]+/, "~")}</span></button>{/each}</div>
    </details>

    <label class="label">Prompt para o agente <span class="muted">(vazio = o título)</span>
      <textarea class="input" rows="5" bind:value={prompt} placeholder="Contexto, critérios de aceite, arquivos importantes…"></textarea></label>

    <div class="label">Agentes <span class="muted">— marque mais de um para comparar soluções (cada um no próprio worktree)</span></div>
    <div class="accs">
      {#each work.ai.filter(a => a.installed) as a (a.id)}
        <button class="acc" class:on={chosen.includes(a.id)} onclick={() => toggle(a.id)}>
          <AgentIcon provider={a.provider} size={16} />
          <span class="grow"><b>{a.name}</b><span class="tiny muted">{a.label}{a.email ? " · " + a.email : ""}</span></span>
          {#if a.usage?.rateLimits?.[0]}<span class="tiny" class:warn={(a.usage.rateLimits[0].used || 0) > 80}>{Math.round(a.usage.rateLimits[0].used || 0)}%</span>{/if}
        </button>
      {:else}<div class="small muted">Nenhuma CLI de IA encontrada. Instale o Claude Code ou o Codex e configure em Contas e ajustes → IA.</div>{/each}
    </div>
    {#each chosen.map(id => work.account(id)).filter(a => a && (a.usage?.rateLimits || []).some(w => (w.used || 0) >= 85)) as a (a!.id)}
      {@const alt = work.ai.filter(x => x.installed && x.provider === a!.provider && x.id !== a!.id && !chosen.includes(x.id))
        .sort((x, y) => Math.max(...(x.usage?.rateLimits || []).map(w => w.used || 0), 0) - Math.max(...(y.usage?.rateLimits || []).map(w => w.used || 0), 0))[0]}
      <div class="limwarn small">⚠ <b>{a!.name}</b> está em {Math.round(Math.max(...(a!.usage?.rateLimits || []).map(w => w.used || 0)))}% do limite.
        {#if alt}<button class="btn sm" onclick={() => (chosen = [...chosen.filter(x => x !== a!.id), alt.id])}>Usar {alt.name}</button>{/if}</div>
    {/each}
    <div class="row2">
      <span class="small muted">Modo</span>
      <Segmented size="sm" bind:value={mode} options={[{ value: "default", label: "Pergunta antes" }, { value: "acceptEdits", label: "Aceita edições" }, { value: "plan", label: "Só planejar" }]} />
    </div>
    {#if project.settings.bypass}<p class="small byp"><ShieldOff size={12} /> Pular permissões está ligado neste projeto: o agente não pergunta nada{mode === "plan" ? " depois que você aprovar o plano" : ""} (Ajustes do projeto).</p>{/if}
  </div>
  {#snippet footer()}
    <span class="small muted">{chosen.length ? `${chosen.length} agente(s)` : "sem agente — só o worktree"}</span>
    <span class="spacer"></span>
    <button class="btn" onclick={onclose}>Cancelar</button>
    <button class="btn primary" disabled={busy || !title.trim()} onclick={create}>{#if chosen.length > 1}<Sparkles size={14} />{:else}<Rocket size={14} />{/if} {chosen.length > 1 ? `Disparar ${chosen.length} agentes` : "Criar tarefa"}</button>
  {/snippet}
</Drawer>

<style>
  .form { display: grid; gap: 14px; padding-top: 12px; }
  .row2 { display: flex; align-items: center; gap: 12px; }
  .branch { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--text-2); }
  textarea { resize: vertical; min-height: 90px; font: 13px/1.5 var(--font); padding: 8px 10px; height: auto; }
  .accs { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 6px; }
  .acc { display: flex; align-items: center; gap: 10px; padding: 9px 11px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface-2);
    color: var(--text-2); font: 13px var(--font); text-align: left; cursor: pointer; transition: border-color var(--t), background var(--t), transform var(--t-fast); }
  .acc:hover { border-color: var(--line-3); }
  .acc.on { border-color: var(--accent); background: var(--accent-soft); color: var(--text); }
  .acc:active { transform: scale(0.98); }
  .acc .grow { display: grid; min-width: 0; flex: 1; }
  .acc b { color: var(--text); font-weight: 600; }
  .warn { color: var(--warn); font-weight: 650; }
  .wi summary { cursor: pointer; font-size: 13px; color: var(--text-2); }
  .wil { display: grid; gap: 2px; max-height: 180px; overflow: auto; margin-top: 6px; }
  .wil button { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border: 0; border-radius: 7px; background: none; color: var(--text-2);
    font: 12.5px var(--font); text-align: left; cursor: pointer; min-width: 0; }
  .wil button:hover, .wil button.on { background: var(--accent-soft); color: var(--text); }
  .spacer { flex: 1; }
  .limwarn { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 9px; background: var(--warn-soft); color: var(--text-2); }
  .limwarn .btn { margin-left: auto; }
  .byp { display: flex; align-items: center; gap: 6px; margin: 0; padding: 7px 10px; border-radius: 9px; background: var(--warn-soft); color: var(--text-2); }
  .byp :global(svg) { color: var(--warn); flex: none; }
</style>
