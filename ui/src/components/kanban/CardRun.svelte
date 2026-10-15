<script lang="ts">
  // Pedir à IA um cartão do quadro (automação opcional): escolhe o fluxo (planejar / planejar e implementar / implementar), a conta, em qual
  // projeto a IA trabalha e quais outros ela também altera (worktree na mesma branch) ou só consulta.
  import { ClipboardList, Hammer, Lightbulb, Star } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { kanban, type Card } from "../../lib/kanban.svelte";
  import { prefs } from "../../lib/prefs.svelte";
  import { repos } from "../../lib/repos.svelte";
  import { FLOWS, work, type Flow } from "../../lib/work.svelte";
  import Drawer from "../Drawer.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import AgentIcon from "../work/AgentIcon.svelte";

  let { card, flow: flow0 = null, onclose }: { card: Card; flow?: Flow | null; onclose: () => void } = $props();
  const c = untrack(() => card);
  let flow = $state<Flow>(untrack(() => flow0) || prefs.get("ai.defaultFlow"));
  let primary = $state<string>(c.primary || c.projects[0] || "");
  let change = $state<string[]>([...c.projects]);
  let refs = $state<string[]>([...c.refs]);
  const prim = $derived(repos.byId(primary));
  let account = $state<string | null>(untrack(() => work.defaultAccount(prim ? { provider: prim.provider, slug: prim.slug } as any : null)));
  let busy = $state(false);
  const group = $derived(work.groups.find(g => g.id === c.groupId) || null);
  const ICON = { plan: Lightbulb, "plan-implement": ClipboardList, implement: Hammer } as const;
  const missing = $derived([...c.projects, ...c.refs].filter(id => !repos.byId(id)?.exists));

  async function go() {
    if (!account || !primary) return;
    busy = true;
    const r = await kanban.run(c, { flow, accountId: account, primary, change: [...new Set([primary, ...change])], refs: refs.filter(x => !change.includes(x) && x !== primary) });
    busy = false;
    if (r) onclose();
  }
  const toggle = (id: string) => {
    if (id === primary) return;
    if (change.includes(id)) { change = change.filter(x => x !== id); refs = [...refs, id]; }
    else { refs = refs.filter(x => x !== id); change = [...change, id]; }
  };
</script>

<Drawer title="Pedir à IA" subtitle={c.title} {onclose} width={600}>
  <div class="f">
    {#if group}<div class="grp" style="--g:{group.color}"><span class="dot"></span>Grupo <b>{group.name}</b><span class="tiny muted">— os {group.repoIds.length} projetos dele vão como contexto</span></div>{/if}

    <div class="label">Onde a IA vai trabalhar</div>
    <div class="projs">
      {#each [...new Set([...c.projects, ...c.refs])] as id (id)}
        {@const r = repos.byId(id)}
        {@const isChange = id === primary || change.includes(id)}
        <div class="pr" class:prim={id === primary}>
          <button class="star" class:on={id === primary} title="Tornar o projeto principal (a IA trabalha aqui)" onclick={() => { primary = id; if (!change.includes(id)) change = [...change, id]; refs = refs.filter(x => x !== id); }}><Star size={14} /></button>
          <ProviderIcon provider={r?.provider || null} size={13} />
          <span class="grow ell"><b>{r?.name || "projeto removido"}</b>{#if !r?.exists}<span class="tiny bad"> não está nesta máquina</span>{/if}</span>
          {#if id === primary}<span class="pill accent">principal — a IA trabalha aqui</span>
          {:else}<button class="pill" class:accent={isChange} class:neutral={!isChange} onclick={() => toggle(id)} title="Clique para alternar entre alterar e só consultar">{isChange ? "também altera" : "só consulta"}</button>{/if}
        </div>
      {:else}<div class="small muted">O cartão não tem projetos — edite e marque ao menos um.</div>{/each}
    </div>

    <div class="label">Conta</div>
    <div class="accs">
      {#each work.ai.filter(a => a.installed) as a (a.id)}
        {@const lim = Math.max(0, ...(a.usage?.rateLimits || []).map(w => w.used || 0))}
        <button class="acc" class:on={account === a.id} onclick={() => (account = a.id)}><AgentIcon provider={a.provider} size={14} /><span class="ell">{a.name}</span>
          {#if lim}<span class="tiny" class:warn={lim >= 80}>{Math.round(lim)}%</span>{/if}</button>
      {:else}<span class="small muted">Nenhuma CLI de IA encontrada — veja Configurações → IA.</span>{/each}
    </div>

    <div class="flows">
      {#each Object.entries(FLOWS) as [k, f] (k)}
        {@const I = ICON[k as Flow]}
        <button class="flow" class:on={flow === k} onclick={() => (flow = k as Flow)}><I size={18} /><b>{f.short}</b><span class="tiny muted">{f.hint}</span></button>
      {/each}
    </div>
    {#if missing.length}<p class="small bad">Clone {missing.map(id => repos.byId(id)?.name || "o projeto").join(", ")} antes — o projeto não está nesta máquina.</p>{/if}
  </div>
  {#snippet footer()}
    <span class="small muted">{change.length > 1 ? `${change.length} worktrees na mesma branch` : "1 worktree"}{refs.length ? ` · ${refs.length} de consulta` : ""}{c.files?.length ? ` · ${c.files.length} anexo(s) no contexto` : ""}</span>
    <span class="spacer"></span>
    <button class="btn" onclick={onclose}>Cancelar</button>
    <button class="btn primary" disabled={busy || !account || !primary || missing.includes(primary)} onclick={go}>{busy ? "Enviando…" : FLOWS[flow].short}</button>
  {/snippet}
</Drawer>

<style>
  .f { display: grid; gap: 12px; padding-top: 12px; }
  .label { font-size: 12px; font-weight: 650; color: var(--text-2); }
  .grp { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 10px; background: color-mix(in srgb, var(--g) 12%, transparent); font-size: 13px; }
  .grp .dot { width: 10px; height: 10px; border-radius: 3px; background: var(--g); }
  .projs { display: grid; grid-template-columns: minmax(0, 1fr); gap: 4px; }
  .pr { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface-2); font-size: 13px; }
  .pr.prim { border-color: var(--accent-line); }
  .pr .grow { flex: 1; min-width: 0; }
  .pr .pill { cursor: pointer; border: 0; }
  .star { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--faint); cursor: pointer; }
  .star.on { color: var(--warn); }
  .star.on :global(svg) { fill: currentColor; }
  .accs { display: flex; flex-wrap: wrap; gap: 6px; }
  .acc { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 10px; border-radius: 99px; border: 1px solid var(--line-2); background: var(--surface-2);
    color: var(--text-2); font: 12.5px var(--font); cursor: pointer; max-width: 200px; }
  .acc.on { border-color: var(--accent); background: var(--accent-soft); color: var(--text); }
  .acc .warn { color: var(--warn); font-weight: 650; }
  .flows { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .flow { display: grid; gap: 4px; justify-items: start; padding: 12px; border-radius: 12px; border: 1px solid var(--line-2); background: var(--surface-2);
    color: var(--text); font: 13px var(--font); text-align: left; cursor: pointer; transition: border-color var(--t); }
  .flow.on { border-color: var(--accent); background: var(--accent-soft); }
  .flow :global(svg) { color: var(--accent); }
  .bad { color: var(--bad); }
  .spacer { flex: 1; }
</style>
