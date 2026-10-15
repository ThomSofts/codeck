<script lang="ts">
  // "Pedir à IA" completo (o rápido é o campo no painel da direita): escreva o pedido (ou escolha uma issue/work item),
  // escolha o fluxo e pronto — roda aqui mesmo no checkout/tarefa ou vira uma tarefa (branch + worktree + agente).
  // A conta vem a do projeto (a última usada nele); pular permissões é dos ajustes do projeto.
  import { ClipboardList, GitBranch, Hammer, Lightbulb, ShieldOff, Sparkles } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { kbd } from "../../lib/keys";
  import { prefs } from "../../lib/prefs.svelte";
  import { store } from "../../lib/store.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { FLOWS, work, type Flow, type Project, type Task } from "../../lib/work.svelte";
  import Drawer from "../Drawer.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import Switch from "../Switch.svelte";
  import AgentIcon from "./AgentIcon.svelte";

  let { project, task = null, preset = null, onclose, ondone }:
    { project: Project; task?: Task | null; preset?: { title?: string; text?: string; workItem?: any; flow?: Flow } | null; onclose: () => void;
      ondone?: (r: { projectId: string; taskId: string | null; termId?: string }) => void } = $props();

  let text = $state(untrack(() => preset?.text || ""));
  let title = $state(untrack(() => preset?.title || ""));
  let workItem = $state<any>(untrack(() => preset?.workItem || null));
  let flow = $state<Flow>(untrack(() => preset?.flow || prefs.get("ai.defaultFlow")));
  // o padrão é rodar onde você está (checkout ou tarefa aberta); "tarefa nova" fica lembrado para a próxima vez
  const WT = "codeck.ask.worktree";
  let worktree = $state(untrack(() => { try { return localStorage.getItem(WT) === "1"; } catch { return false; } }));
  $effect(() => { const w = worktree; try { localStorage.setItem(WT, w ? "1" : "0"); } catch { /* sem armazenamento */ } });
  let account = $state<string | null>(untrack(() => work.defaultAccount(project)));
  let busy = $state(false);
  let q = $state("");
  const accounts = $derived(work.ai.filter(a => a.installed));
  const issues = $derived((store.s?.issues || []).filter(i => (!project.provider || i.provider === project.provider)
    && (!q || `${i.number} ${i.title}`.toLowerCase().includes(q.toLowerCase()))).slice(0, 40));
  const effTitle = $derived(title.trim() || text.trim().split("\n")[0].slice(0, 70));
  function pick(i: any) {
    workItem = workItem?.key === i.key ? null : i;
    if (workItem) {
      title = i.title;
      text = `${i.provider === "github" ? "Issue" : i.type || "Work item"} #${i.number}: ${i.title}\n${i.url || ""}`;
    }
  }
  async function go(f: Flow) {
    if (!text.trim()) return ui.toast("Diga o que a IA deve fazer", "info");
    flow = f;
    busy = true;
    const prog = ui.progress(worktree ? "Criando a tarefa e abrindo o agente…" : "Abrindo o agente…");
    try {
      const r = await work.askAi({ projectId: project.id, title: effTitle, text, flow: f, accountId: account, worktree, taskId: task?.id || null,
        kind: workItem && /bug|fix/i.test(workItem.type || "") ? "fix" : undefined,
        workItem: workItem ? { number: workItem.number, title: workItem.title, url: workItem.url, provider: workItem.provider } : null });
      prog.done(f === "plan" ? "A IA está planejando" : f === "implement" ? "A IA está implementando" : "A IA está planejando — aprove o plano no terminal");
      ondone?.(r);
    } catch (e) { prog.fail(e); }
    busy = false;
  }
  function onKey(e: KeyboardEvent) { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); go(flow); } }
  const ICON = { plan: Lightbulb, "plan-implement": ClipboardList, implement: Hammer } as const;
</script>

<Drawer title="Pedir à IA" subtitle={`${project.name}${task ? " · tarefa " + task.title : ""}`} {onclose} width={600}>
  <div class="f">
    <!-- svelte-ignore a11y_autofocus -->
    <textarea class="input big" rows="5" bind:value={text} onkeydown={onKey} autofocus
      placeholder="O que a IA deve fazer? Ex.: “No carrinho, o frete não considera o CEP de retirada — corrigir e cobrir com teste.”"></textarea>
    <input class="input" bind:value={title} placeholder={effTitle ? `Título da tarefa: ${effTitle}` : "Título da tarefa (opcional)"} />

    {#if store.s?.issues?.length}
      <details class="iss" open={!!workItem}>
        <summary>{workItem ? `#${workItem.number} ${workItem.title}` : "Ou escolha uma issue / work item"}</summary>
        <input class="input sm" bind:value={q} placeholder="filtrar…" />
        <div class="il">{#each issues as i (i.key)}
          <button class:on={workItem?.key === i.key} onclick={() => pick(i)}><ProviderIcon provider={i.provider} size={12} /><b>#{i.number}</b><span class="ell">{i.title}</span><span class="tiny muted">{i.repo}</span></button>
        {:else}<div class="small muted">Nada.</div>{/each}</div>
      </details>
    {/if}

    <div class="opts">
      <div class="accs">
        {#each accounts as a (a.id)}
          {@const lim = Math.max(0, ...(a.usage?.rateLimits || []).map(w => w.used || 0))}
          {@const st = work.activity[a.id]?.state}
          <button class="acc" class:on={account === a.id} onclick={() => (account = a.id)} title={a.email || a.label}>
            <AgentIcon provider={a.provider} size={14} /><span class="ell">{a.name}</span>
            {#if lim}<span class="tiny" class:warn={lim >= 80}>{Math.round(lim)}%</span>{/if}
            {#if st === "working"}<span class="busy" title="trabalhando em outra coisa agora"></span>{/if}
          </button>
        {:else}<span class="small muted">Nenhuma CLI de IA encontrada — veja Configurações → IA.</span>{/each}
      </div>
      <Switch bind:checked={worktree} label={task ? "Em uma tarefa nova (worktree próprio)" : "Em uma tarefa nova (branch + worktree)"}
        hint={worktree ? "Não mexe no seu checkout; dá para revisar e criar a PR depois" : task ? "Roda dentro desta tarefa" : "Roda direto no checkout principal"} />
      {#if project.settings.bypass}<p class="small byp"><ShieldOff size={12} /> Pular permissões está ligado neste projeto — o agente edita e roda comandos sem perguntar.</p>{/if}
    </div>

    <div class="flows">
      {#each Object.entries(FLOWS) as [k, f] (k)}
        {@const I = ICON[k as Flow]}
        <button class="flow" class:on={flow === k} disabled={busy || !account} onclick={() => go(k as Flow)}>
          <I size={18} /><b>{f.short}</b><span class="tiny muted">{f.hint}</span>
          {#if flow === k}<span class="kbd">{kbd("mod+enter")}</span>{/if}
        </button>
      {/each}
    </div>
    {#if worktree}<p class="tiny muted br"><GitBranch size={11} /> {flow === "plan" ? "plan" : workItem && /bug|fix/i.test(workItem.type || "") ? "fix" : "feature"}/{effTitle.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "tarefa"}</p>{/if}
  </div>
  {#snippet footer()}
    <span class="small muted"><Sparkles size={12} /> {FLOWS[flow].label}</span>
    <span class="spacer"></span>
    <button class="btn" onclick={onclose}>Cancelar</button>
    <button class="btn primary" disabled={busy || !text.trim() || !account} onclick={() => go(flow)}>{busy ? "Enviando…" : FLOWS[flow].short}</button>
  {/snippet}
</Drawer>

<style>
  .f { display: grid; gap: 12px; padding-top: 12px; }
  .big { min-height: 120px; resize: vertical; font: 14px/1.5 var(--font); padding: 10px 12px; height: auto; }
  .iss summary { cursor: pointer; font-size: 13px; color: var(--text-2); }
  .iss .input { margin-top: 8px; height: 30px; }
  .il { display: grid; grid-template-columns: minmax(0, 1fr); gap: 2px; max-height: 200px; overflow: auto; margin-top: 6px; }
  .il button { display: flex; align-items: center; gap: 7px; padding: 6px 8px; border: 0; border-radius: 7px; background: none; color: var(--text-2);
    font: 12.5px var(--font); text-align: left; cursor: pointer; min-width: 0; }
  .il button .ell { flex: 1; min-width: 0; }
  .il button:hover, .il button.on { background: var(--accent-soft); color: var(--text); }
  .opts { display: grid; gap: 12px; }
  .accs { display: flex; flex-wrap: wrap; gap: 6px; }
  .acc { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 10px; border-radius: 99px; border: 1px solid var(--line-2); background: var(--surface-2);
    color: var(--text-2); font: 12.5px var(--font); cursor: pointer; max-width: 200px; position: relative; }
  .acc.on { border-color: var(--accent); background: var(--accent-soft); color: var(--text); }
  .acc .warn { color: var(--warn); font-weight: 650; }
  .busy { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
  .flows { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .flow { position: relative; display: grid; gap: 4px; justify-items: start; padding: 12px; border-radius: 12px; border: 1px solid var(--line-2); background: var(--surface-2);
    color: var(--text); font: 13px var(--font); text-align: left; cursor: pointer; transition: border-color var(--t), transform var(--t) var(--spring); }
  .flow:hover:not(:disabled) { border-color: var(--accent); transform: translateY(-2px); }
  .flow.on { border-color: var(--accent); background: var(--accent-soft); }
  .flow :global(svg) { color: var(--accent); }
  .flow .kbd { position: absolute; top: 8px; right: 8px; }
  .flow:disabled { opacity: 0.55; cursor: default; }
  .br { display: flex; align-items: center; gap: 5px; font-family: var(--mono); margin: -4px 0 0; }
  .spacer { flex: 1; }
  .byp { display: flex; align-items: center; gap: 6px; margin: 0; padding: 7px 10px; border-radius: var(--r-sm); background: var(--warn-soft); color: var(--text-2); }
  .byp :global(svg) { color: var(--warn); flex: none; }
  @media (max-width: 640px) { .flows { grid-template-columns: 1fr; } }
</style>
