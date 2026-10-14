<script lang="ts">
  import { fmtMs, hoursSince } from "../lib/format";
  import { go, router, soft } from "../lib/router.svelte";
  import { store } from "../lib/store.svelte";
  import BuildPane from "../components/build/BuildPane.svelte";
  import BuildRow from "../components/build/BuildRow.svelte";
  import Empty from "../components/Empty.svelte";
  import Kpi from "../components/Kpi.svelte";
  import Page from "../components/Page.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Skeleton from "../components/Skeleton.svelte";
  import SourceFilter from "../components/SourceFilter.svelte";
  import Split from "../components/Split.svelte";
  import Toolbar from "../components/Toolbar.svelte";

  let q = $state("");
  let status = $state("");
  let org = $state("");
  let prot = $state(false);
  let mine = $state(false);
  let provider = $state("");

  const s = $derived(store.s);
  const myIds = $derived(Object.values(s?.me || {}).map(m => m?.id));
  const isProt = (br: string) => !!s?.rules.protectedTargets.map(t => t.toLowerCase()).includes(br.toLowerCase());
  const rows = $derived((s?.builds || []).filter(b => (!org || b.org === org) && (!provider || b.provider === provider)
    && (!status || (status === "running" ? b.status !== "completed" : status === "failed" ? ["failed", "partiallySucceeded"].includes(b.result || "") : b.result === "succeeded"))
    && (!prot || isProt(b.branch)) && (!mine || myIds.includes(b.requestedForId))
    && (!q || `${b.pipeline} ${b.number} ${b.branch} ${b.message} ${b.requestedFor} ${b.repo || ""} ${b.prNumber || ""}`.toLowerCase().includes(q.toLowerCase()))));
  const selKey = $derived(router.param && rows.some(b => b.key === router.param) ? router.param : rows[0]?.key || null);
  const sel = $derived(rows.find(b => b.key === selKey));
  const kpis = $derived.by(() => {
    const all = s?.builds || [];
    const day = all.filter(b => (hoursSince(b.queued) || 99) <= 24);
    const done = day.filter(b => b.status === "completed" && b.result !== "canceled");
    const failed = day.filter(b => b.result === "failed");
    const durs = all.filter(b => b.result === "succeeded" && b.started && b.finished).map(b => new Date(b.finished!).getTime() - new Date(b.started!).getTime()).sort((a, b) => a - b);
    return [
      { label: "Rodando agora", value: all.filter(b => b.status !== "completed").length, sub: `${all.filter(b => b.status === "notStarted").length} na fila` },
      { label: "Falharam (24 h)", value: failed.length, sub: `${failed.filter(b => isProt(b.branch)).length} em branch protegida`, alert: failed.length > 0 },
      { label: "Sucesso (24 h)", value: done.length ? Math.round((100 * done.filter(b => b.result === "succeeded").length) / done.length) + "%" : "—", sub: `${done.length} concluídos` },
      { label: "Duração mediana", value: durs.length ? fmtMs(durs[Math.floor(durs.length / 2)]) : "—", sub: "builds com sucesso" },
      { label: "Esperando você", value: all.filter(b => b.waiting || s?.deploys.some(d => d.buildId === b.id)).length, sub: "aprovação ou permissão" },
    ];
  });
</script>

<Page live={["builds"]} title="Builds e Actions" sub="Azure Pipelines e GitHub Actions dos repositórios que você acompanha">
  {#if !store.buildsReady}
    <Skeleton kpis={5} rows={8} />
  {:else}
    <div class="kpis">{#each kpis as k, i (k.label)}<Kpi {...k} index={i} />{/each}</div>
    <Toolbar bind:query={q} placeholder="Buscar pipeline, workflow, branch, PR, commit, pessoa…">
      {#snippet left()}
        <Segmented bind:value={status} options={[{ value: "", label: "Todos" }, { value: "running", label: "Rodando" }, { value: "failed", label: "Falharam" }, { value: "ok", label: "Sucesso" }]} />
        <Segmented bind:value={provider} options={[{ value: "", label: "Tudo" }, { value: "github", label: "Actions" }, { value: "azure", label: "Azure" }]} />
      {/snippet}
      <SourceFilter bind:value={org} items={s!.builds} />
      <button class="btn sm" class:primary={prot} onclick={() => soft(() => { prot = !prot; })}>🔒 Protegidas</button>
      <button class="btn sm" class:primary={mine} onclick={() => soft(() => { mine = !mine; })}>Os meus</button>
    </Toolbar>
    <Split paneKey={selKey} onclose={() => go("/builds", "soft")}>
      {#snippet list()}
        <div class="lh">{rows.length} de {s!.builds.length} execuções · mais novas primeiro</div>
        {#each rows as b (b.key)}<BuildRow {b} selected={b.key === selKey} onselect={() => go("/builds/" + encodeURIComponent(b.key), "soft")} />
        {:else}<Empty title="Nenhum build" text={s!.githubAccounts.length ? "Nada bate com os filtros." : "Conecte o GitHub para ver as Actions também."} />{/each}
      {/snippet}
      {#snippet pane()}{#if sel}<BuildPane b={sel} />{/if}{/snippet}
    </Split>
  {/if}
</Page>

<style>
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-bottom: 14px; flex: none; }
  .lh { position: sticky; top: 0; z-index: 2; padding: 9px 16px; font-size: 12px; color: var(--muted); background: color-mix(in srgb, var(--surface) 92%, transparent);
    backdrop-filter: blur(8px); border-bottom: 1px solid var(--line); }
</style>
