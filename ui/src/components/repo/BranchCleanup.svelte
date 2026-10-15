<script lang="ts">
  // Limpar branches locais pela principal: busca no servidor (com prune), compara cada branch com origin/<principal> e
  // recomenda — mergeada, squash/rebase detectado, remoto apagado com os commits ainda no servidor. As recomendadas vêm
  // marcadas com o motivo; "para avaliar" (parada, remoto apagado com commits só aqui) vêm desmarcadas; o resto só
  // informa por que fica. Confirma antes, e o backend reanalisa na hora de apagar.
  import { AlertTriangle, ChevronRight, CloudOff, GitBranch, GitMerge, RefreshCw, Trash2 } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { get, post } from "../../lib/api";
  import { ui } from "../../lib/ui.svelte";
  import Drawer from "../Drawer.svelte";
  import Switch from "../Switch.svelte";

  type Item = { name: string; sha: string; upstream: string | null; gone: boolean; days: number; subject: string; kind: "merged" | "squash" | "gone" | "stale" | "unmerged" | "keep";
    reason: string; detail: string; recommended: boolean; selectable: boolean; force: boolean; remote: string | null };
  type Plan = { main: string | null; base: string | null; remote: string | null; current: string | null; fetched: boolean; fetchError: string | null;
    pruned: string[]; staleDays: number; branches: Item[] };

  let { repoId, onclose, ondone }: { repoId: string; onclose: () => void; ondone: () => void } = $props();
  let plan = $state<Plan | null>(null);
  let error = $state<string | null>(null);
  let picked = $state<Record<string, boolean>>({});
  let remoteToo = $state(false);
  let busy = $state(false);
  let showKept = $state(false);

  async function load(fetch = true) {
    plan = null; error = null;
    try {
      const p = await get<Plan>("repo/branch-cleanup", { id: repoId, fetch: fetch ? 1 : 0 });
      plan = p;
      picked = Object.fromEntries(p.branches.filter(b => b.selectable).map(b => [b.name, b.recommended]));
    } catch (e: any) { error = e.message; }
  }
  $effect(() => { void repoId; untrack(() => load()); });

  const rec = $derived(plan?.branches.filter(b => b.selectable && b.recommended) || []);
  const maybe = $derived(plan?.branches.filter(b => b.selectable && !b.recommended) || []);
  const kept = $derived(plan?.branches.filter(b => !b.selectable) || []);
  const chosen = $derived(plan?.branches.filter(b => b.selectable && picked[b.name]) || []);
  const remotes = $derived(chosen.filter(b => b.remote).map(b => b.remote!));
  const age = (d: number) => (d < 1 ? "hoje" : d === 1 ? "ontem" : d < 60 ? `${d} dias` : d < 730 ? `${Math.floor(d / 30)} meses` : `${Math.floor(d / 365)} anos`);
  const TONE: Record<Item["kind"], string> = { merged: "good", squash: "accent", gone: "info", stale: "warn", unmerged: "neutral", keep: "neutral" };
  const setAll = (list: Item[], v: boolean) => (picked = { ...picked, ...Object.fromEntries(list.map(b => [b.name, v])) });

  async function apply() {
    if (!plan || !chosen.length) return;
    const forced = chosen.filter(b => b.force);
    const risky = chosen.filter(b => b.kind === "stale" || (b.kind === "gone" && !b.recommended));
    const ok = await ui.ask({
      title: `Apagar ${chosen.length} branch${chosen.length > 1 ? "es" : ""} local${chosen.length > 1 ? "is" : ""}?`,
      detail: chosen.slice(0, 14).map(b => `${b.name} — ${b.reason}`).concat(chosen.length > 14 ? [`+${chosen.length - 14}`] : []),
      message: [
        forced.length ? `${forced.length} não ${forced.length > 1 ? "são ancestrais" : "é ancestral"} de ${plan.base}: o Git só apaga com -D (forçado).` : "",
        risky.length ? `${risky.length} ${risky.length > 1 ? "têm" : "tem"} commits que podem não estar em lugar nenhum além desta máquina.` : "",
        remoteToo && remotes.length ? `Também apaga no servidor: ${remotes.join(", ")}.` : "",
      ].filter(Boolean).join(" ") || "Todas já estão na principal — nada se perde.",
      confirm: "Apagar", danger: forced.length > 0 || risky.length > 0,
    });
    if (!ok) return;
    busy = true;
    try {
      const r = await post<{ deleted: string[]; remoteDeleted: string[]; failed: { name: string; error: string }[] }>("repo/branch-cleanup", {
        id: repoId, remote: remoteToo, branches: chosen.map(b => ({ name: b.name, sha: b.sha, force: b.force })) });
      const extra = r.remoteDeleted.length ? ` (+${r.remoteDeleted.length} no servidor)` : "";
      if (r.failed.length) ui.toast(`${r.deleted.length} apagada(s)${extra} · ${r.failed.length} ficou(aram): ${r.failed.map(f => `${f.name} — ${f.error}`).join("; ")}`, "info");
      else ui.toast(`${r.deleted.length} branch(es) apagada(s)${extra}`);
      ondone();
      if (r.failed.length) await load(false); else onclose();
    } catch (e) { ui.error(e); }
    busy = false;
  }
</script>

{#snippet row(b: Item)}
  <label class="it" class:off={!b.selectable} class:on={picked[b.name]}>
    {#if b.selectable}<input type="checkbox" bind:checked={picked[b.name]} />{:else}<span class="ck-x"></span>{/if}
    <div class="main">
      <div class="l1"><span class="nm ell" title={b.name}>{b.name}</span><span class="pill {b.selectable && !b.recommended && b.kind === 'merged' ? 'neutral' : TONE[b.kind]}">{b.reason}</span></div>
      <div class="l2">
        {#if b.detail}<span class:warnt={/só nesta máquina/.test(b.detail)}>{b.detail}</span><span class="sep">·</span>{/if}
        <span class="ell sub" title={b.subject}>{b.subject}</span>
      </div>
    </div>
    <span class="when" title="último commit">{age(b.days)}</span>
  </label>
{/snippet}

<Drawer title="Limpar branches locais" subtitle={plan?.base ? `Comparando com ${plan.base}${plan.fetched ? " — buscado agora no servidor" : ""}` : "Recomenda pela branch principal"} width={600} {onclose}>
  {#if error}
    <div class="note bad"><AlertTriangle size={14} /><span class="grow">{error}</span><button class="btn sm" onclick={() => load()}>Tentar de novo</button></div>
  {:else if !plan}
    <div class="loading"><RefreshCw size={14} class="spin" /> Buscando no servidor e comparando com a principal…</div>
    <div class="sk">{#each Array(5) as _, i (i)}<i class="shim"></i>{/each}</div>
  {:else}
    {#if plan.fetchError}<div class="note warn"><CloudOff size={14} /><span>Não deu para buscar no servidor ({plan.fetchError}). A análise usa o que já estava nesta máquina.</span></div>{/if}
    {#if !plan.base}<div class="note warn"><AlertTriangle size={14} /><span>Sem main/master (nem origin/HEAD) para comparar — nada é recomendado.</span></div>{/if}
    {#if plan.pruned.length}
      <div class="note"><GitMerge size={14} /><span><b>{plan.pruned.length}</b> referência(s) remota(s) apagada(s) no servidor saíram daqui: <span class="mono">{plan.pruned.slice(0, 6).join(", ")}{plan.pruned.length > 6 ? "…" : ""}</span></span></div>
    {/if}

    <section>
      <header class="gh"><h4>Recomendadas</h4><span class="cnt">{rec.length}</span><span class="hint">já estão em {plan.main ?? "—"} ou no servidor</span>
        {#if rec.length}<button class="lk" onclick={() => setAll(rec, !rec.every(b => picked[b.name]))}>{rec.every(b => picked[b.name]) ? "Desmarcar" : "Marcar"} todas</button>{/if}</header>
      {#each rec as b (b.name)}{@render row(b)}{:else}<div class="empty">Nada para limpar — nenhuma branch mergeada em {plan.main ?? "principal"}.</div>{/each}
    </section>

    {#if maybe.length}
      <section>
        <header class="gh"><h4>Para avaliar</h4><span class="cnt">{maybe.length}</span><span class="hint">paradas ou com o remoto apagado — confira antes</span></header>
        {#each maybe as b (b.name)}{@render row(b)}{/each}
      </section>
    {/if}

    {#if kept.length}
      <section>
        <button class="gh tog" onclick={() => (showKept = !showKept)} aria-expanded={showKept}>
          <ChevronRight size={13} class="chev {showKept ? 'rot' : ''}" /><h4>Ficam</h4><span class="cnt">{kept.length}</span><span class="hint">atual, principal, longa vida, em worktree ou não mergeadas</span></button>
        {#if showKept}{#each kept as b (b.name)}{@render row(b)}{/each}{/if}
      </section>
    {/if}

    {#if remotes.length}
      <div class="remote">
        <Switch bind:checked={remoteToo} label={`Apagar também no servidor (${remotes.length})`} hint={`Já mergeadas e ainda em ${plan.remote}: ${remotes.map(r => r.split("/").slice(1).join("/")).slice(0, 4).join(", ")}${remotes.length > 4 ? "…" : ""}`} />
      </div>
    {/if}
  {/if}

  {#snippet footer()}
    <span class="sum">{#if plan}<GitBranch size={13} /> {chosen.length} de {rec.length + maybe.length} marcada(s){/if}</span>
    <span class="grow"></span>
    <button class="btn ghost" onclick={() => load()} disabled={!plan || busy} title="Busca de novo no servidor e refaz a análise"><RefreshCw size={14} /> Reanalisar</button>
    <button class="btn danger" disabled={!chosen.length || busy} onclick={apply}><Trash2 size={14} /> {busy ? "Apagando…" : `Apagar ${chosen.length || ""}`}</button>
  {/snippet}
</Drawer>

<style>
  .loading { display: flex; align-items: center; gap: 8px; padding: 16px 0 10px; color: var(--text-2); font-size: 13px; }
  .sk { display: grid; gap: 8px; }
  .sk i { height: 46px; border-radius: 10px; }
  .note { display: flex; align-items: flex-start; gap: 9px; margin-top: 14px; padding: 9px 12px; border-radius: 10px; font-size: 12.5px; color: var(--text-2);
    background: var(--surface-2); border: 1px solid var(--line); }
  .note :global(svg) { flex: none; margin-top: 2px; }
  .note.warn { background: var(--warn-soft); color: var(--text); border-color: color-mix(in srgb, var(--warn) 30%, transparent); }
  .note.warn :global(svg) { color: var(--warn); }
  .note.bad { background: var(--bad-soft); color: var(--bad); align-items: center; border-color: transparent; }
  .note .mono { color: var(--text); }
  section { margin-top: 18px; }
  .gh { display: flex; align-items: baseline; gap: 8px; width: 100%; padding: 0 0 6px; border: 0; background: none; color: inherit; font: inherit; text-align: left; }
  .gh.tog { cursor: pointer; align-items: center; }
  .gh.tog:hover h4 { color: var(--text); }
  h4 { margin: 0; font-size: 13px; font-weight: 650; letter-spacing: -0.005em; }
  .cnt { font: 600 11.5px/1 var(--font); color: var(--muted); font-variant-numeric: tabular-nums; }
  .hint { font-size: 12px; color: var(--muted); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .lk { border: 0; background: none; padding: 0; color: var(--accent); font: 550 12px var(--font); cursor: pointer; white-space: nowrap; }
  .lk:hover { text-decoration: underline; }
  .it { display: grid; grid-template-columns: 18px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 9px 10px; margin: 0 -10px; border-radius: 9px;
    cursor: pointer; transition: background var(--t-fast); }
  .it:hover { background: var(--surface-2); }
  .it.on { background: color-mix(in srgb, var(--accent) 6%, transparent); }
  .it.on:hover { background: color-mix(in srgb, var(--accent) 10%, transparent); }
  .it.off { cursor: default; }
  .it.off:hover { background: none; }
  .it.off .nm { color: var(--text-2); }
  input[type="checkbox"] { width: 15px; height: 15px; margin: 0; accent-color: var(--accent); cursor: pointer; }
  .ck-x { width: 15px; height: 15px; border-radius: 4px; border: 1px dashed var(--line-3); }
  .main { display: grid; gap: 3px; min-width: 0; }
  .l1 { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .nm { font: 600 12.5px/1.3 var(--mono); color: var(--text); }
  .l1 .pill { flex: none; }
  .l2 { display: flex; align-items: center; gap: 6px; min-width: 0; font-size: 12px; color: var(--muted); }
  .l2 > span:first-child { white-space: nowrap; }
  .sub { flex: 1; }
  .sep { color: var(--faint); }
  .warnt { color: var(--warn); font-weight: 550; }
  .when { font-size: 11.5px; color: var(--muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
  .empty { padding: 10px 0; font-size: 12.5px; color: var(--muted); }
  .remote { margin-top: 18px; padding: 12px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--line); }
  .sum { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-2); font-variant-numeric: tabular-nums; }
  .grow { flex: 1; min-width: 0; }
</style>
