<script lang="ts">
  // Fila: tudo que espera você — PRs (Azure + GitHub) e aprovações de deploy/permissões (Azure + GitHub).
  import { AlertTriangle } from "@lucide/svelte";
  import { fmtH, hoursSince } from "../lib/format";
  import { go, router, soft } from "../lib/router.svelte";
  import { store } from "../lib/store.svelte";
  import DeployPane from "../components/deploy/DeployPane.svelte";
  import DeployRow from "../components/deploy/DeployRow.svelte";
  import Empty from "../components/Empty.svelte";
  import Kpi from "../components/Kpi.svelte";
  import Page from "../components/Page.svelte";
  import PrPane from "../components/pr/PrPane.svelte";
  import PrRow from "../components/pr/PrRow.svelte";
  import VoteButton from "../components/pr/VoteButton.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Skeleton from "../components/Skeleton.svelte";
  import SourceFilter from "../components/SourceFilter.svelte";
  import Split from "../components/Split.svelte";
  import Toolbar from "../components/Toolbar.svelte";

  let q = $state("");
  let kind = $state("");
  let org = $state("");
  let conflict = $state(false);

  const s = $derived(store.s);
  const prs = $derived(store.inbox.filter(p => (!org || p.org === org) && (!conflict || p.mergeStatus === "conflicts")
    && (!q || `${p.prId} ${p.title} ${p.repo} ${p.creatorName} ${p.source} ${p.target}`.toLowerCase().includes(q.toLowerCase()))));
  const deps = $derived((s?.deploys || []).filter(d => (!org || d.org === org) && !conflict
    && (!kind || kind === (d.kind === "permission" ? "permission" : "release"))
    && (!q || `${d.pipeline} ${d.stage} ${d.branch} ${d.version} ${d.message} ${d.prNumber || ""}`.toLowerCase().includes(q.toLowerCase()))));
  const showPrs = $derived(!kind || kind === "pr");
  const order = $derived([...deps.map(d => d.key), ...(showPrs ? prs.map(p => p.key) : [])]);
  const selKey = $derived(router.param && order.includes(router.param) ? router.param : order[0] || null);
  const selPr = $derived(s ? [...s.prs].find(p => p.key === selKey) : undefined);
  const selDep = $derived(s?.deploys.find(d => d.key === selKey));

  const today = new Date().toDateString();
  const kpis = $derived.by(() => {
    if (!s) return [];
    const todayVotes = s.activity.filter(a => a.action === "vote" && (a.vote === 10 || a.vote === 5) && new Date(a.ts).toDateString() === today);
    const oldest = store.inbox.reduce<string | null>((m, p) => (!m || p.created < m ? p.created : m), null);
    const permN = s.deploys.filter(d => d.kind === "permission").length;
    return [
      { label: "PRs aguardando meu voto", value: store.inbox.length, sub: `${store.open.length} abertas de outros` },
      { label: "Deploys para aprovar", value: s.deploys.length - permN, sub: s.deploys.length - permN ? "esperando liberação" : "nada parado" },
      { label: "Permissões pendentes", value: permN, sub: permN ? "pipeline travado" : "nenhum pipeline travado", alert: permN > 0 },
      { label: "Aprovadas hoje", value: todayVotes.length, sub: `${todayVotes.filter(a => a.by === "auto").length} auto · ${todayVotes.filter(a => a.by !== "auto").length} manual` },
      { label: "Mais antiga na fila", value: oldest ? fmtH(hoursSince(oldest)) : "—", sub: "aguardando meu voto", alert: (hoursSince(oldest) || 0) > 72 },
      { label: "Com conflito", value: store.inbox.filter(p => p.mergeStatus === "conflicts").length, sub: conflict ? "filtrando — clique para limpar" : "clique para filtrar",
        alert: store.inbox.some(p => p.mergeStatus === "conflicts"), onclick: () => soft(() => { conflict = !conflict; }), active: conflict },
    ];
  });
  const ready = $derived(store.prsReady && store.deploysReady);

  function select(k: string) { go("/inbox/" + encodeURIComponent(k), "soft"); }
  function onkey(e: KeyboardEvent) {
    if ((e.target as HTMLElement).closest("input, textarea, select") || store.hold) return;
    const i = order.indexOf(selKey || "");
    if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); if (order[i + 1]) select(order[i + 1]); }
    if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); if (order[i - 1]) select(order[i - 1]); }
    requestAnimationFrame(() => document.querySelector(`[data-row="${CSS.escape(selKey || "")}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  }
</script>

<svelte:window onkeydown={onkey} />

<Page live={["prs", "deploys"]} title="Fila" sub="Tudo que espera você — PRs, deploys e permissões, do GitHub e do Azure DevOps">
  {#if !ready}
    <Skeleton kpis={6} rows={7} />
  {:else}
    <div class="kpis">{#each kpis as k, i (k.label)}<Kpi {...k} index={i} />{/each}</div>
    <Toolbar bind:query={q} placeholder="Buscar por número, título, repositório, pipeline, branch…">
      {#snippet left()}
        <Segmented bind:value={kind} onchange={() => {}} options={[
          { value: "", label: "Tudo", count: store.inbox.length + (s?.deploys.length || 0) },
          { value: "pr", label: "PRs", count: store.inbox.length },
          { value: "release", label: "Deploys", count: s!.deploys.filter(d => d.kind !== "permission").length },
          { value: "permission", label: "Permissões", count: s!.deploys.filter(d => d.kind === "permission").length }]} />
      {/snippet}
      <SourceFilter bind:value={org} items={[...store.inbox, ...s!.deploys]} />
    </Toolbar>
    {#if store.inbox.some(p => p.mergeStatus === "conflicts") && !conflict}
      <div class="banner"><AlertTriangle size={16} />
        <span><b>{store.inbox.filter(p => p.mergeStatus === "conflicts").length} PR(s) com conflito de merge</b> — o autor precisa resolver antes de completar.</span>
        <span class="spacer"></span><button class="btn sm" onclick={() => soft(() => { conflict = true; })}>Ver só elas</button></div>
    {/if}
    <Split paneKey={selKey} onclose={() => go("/inbox", "soft")}>
      {#snippet list()}
        {#if deps.length}<div class="sect">Deploys e permissões <span>{deps.length}</span></div>{/if}
        {#each deps as d (d.key)}<DeployRow {d} selected={d.key === selKey} onselect={() => select(d.key)} />{/each}
        {#if showPrs && prs.length}<div class="sect">Pull requests <span>{prs.length}</span></div>{/if}
        {#if showPrs}
          {#each prs as p (p.key)}
            <PrRow pr={p} selected={p.key === selKey} onselect={() => select(p.key)}>
              {#snippet actions()}<VoteButton pr={p} v={10} cls="good" leaves>Aprovar</VoteButton>{/snippet}
            </PrRow>
          {/each}
        {/if}
        {#if !order.length}
          <Empty done={!q && !org && !kind && !conflict} title={q || org || kind || conflict ? "Nada com esses filtros" : "Fila zerada"}
            text={q || org || kind || conflict ? "Tente limpar a busca ou os filtros." : "Nenhuma PR, deploy ou permissão esperando você."} />
        {/if}
      {/snippet}
      {#snippet pane()}
        {#if selDep}<DeployPane d={selDep} />{:else if selPr}<PrPane pr={selPr} leaves />{/if}
      {/snippet}
    </Split>
  {/if}
</Page>

<style>
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 14px; flex: none; }
  .sect { position: sticky; top: 0; z-index: 2; display: flex; align-items: center; gap: 8px; padding: 9px 16px; background: color-mix(in srgb, var(--surface-2) 92%, transparent);
    backdrop-filter: blur(8px); border-bottom: 1px solid var(--line); font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
  .sect span { color: var(--text-2); }
  .banner { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; padding: 10px 12px 10px 14px; border-radius: 12px; background: var(--bad-soft);
    color: var(--bad); border: 1px solid color-mix(in srgb, var(--bad) 30%, transparent); font-size: 13px; flex: none; animation: rise 0.35s var(--ease-out); }
  .banner b { color: var(--text); }
</style>
