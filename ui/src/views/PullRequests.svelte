<script lang="ts">
  import { ArchiveRestore, History } from "@lucide/svelte";
  import { archive } from "../lib/actions";
  import { go, router, soft } from "../lib/router.svelte";
  import { store } from "../lib/store.svelte";
  import type { PR } from "../lib/types";
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

  const TABS = ["review", "mine", "all", "archived"];
  const tab = $derived(TABS.includes(router.parts[1]) ? router.parts[1] : "review");
  const paramKey = $derived(router.parts.slice(2).join("/") ? decodeURIComponent(router.parts.slice(2).join("/")) : "");
  let q = $state("");
  let org = $state("");

  const s = $derived(store.s);
  const base = $derived<PR[]>(!s ? [] : tab === "review" ? store.inbox : tab === "mine" ? s.myPrs : tab === "all" ? store.open : store.archived);
  const rows = $derived(base.filter(p => (!org || p.org === org)
    && (!q || `${p.prId} ${p.title} ${p.repo} ${p.creatorName} ${p.source} ${p.target}`.toLowerCase().includes(q.toLowerCase()))));
  const selKey = $derived(paramKey && rows.some(p => p.key === paramKey) ? paramKey : rows[0]?.key || null);
  const sel = $derived(rows.find(p => p.key === selKey));
  const blocked = $derived((s?.myPrs || []).filter(p => p.blockers?.length));

  function setTab(t: string) { soft(() => go(`/prs/${t}`, "soft")); }
  function select(k: string) { go(`/prs/${tab}/${encodeURIComponent(k)}`, "soft"); }
</script>

<Page live={["prs"]} title="Pull requests" sub="GitHub e Azure DevOps num lugar só">
  {#if !store.prsReady}
    <Skeleton kpis={4} rows={8} />
  {:else}
    <div class="kpis">
      <Kpi index={0} label="Para revisar" value={store.inbox.length} sub="esperando o seu voto" onclick={() => setTab("review")} active={tab === "review"} />
      <Kpi index={1} label="Minhas abertas" value={s!.myPrs.length} sub={`${s!.myPrs.filter(p => p.isDraft).length} rascunho(s)`} onclick={() => setTab("mine")} active={tab === "mine"} />
      <Kpi index={2} label="Minhas travadas" value={blocked.length} sub="conflito, build ou voto contra" alert={blocked.length > 0} onclick={() => setTab("mine")} />
      <Kpi index={3} label="Abertas de outros" value={store.open.length} sub={`${store.archived.length} arquivada(s)`} onclick={() => setTab("all")} active={tab === "all"} />
    </div>
    <Toolbar bind:query={q} placeholder="Buscar PR por número, título, repositório, autor, branch…">
      {#snippet left()}
        <Segmented value={tab} onchange={setTab} options={[
          { value: "review", label: "Para revisar", count: store.inbox.length }, { value: "mine", label: "Minhas", count: s!.myPrs.length },
          { value: "all", label: "Abertas", count: store.open.length }, { value: "archived", label: "Arquivadas", count: store.archived.length }]} />
      {/snippet}
      <SourceFilter bind:value={org} items={base} />
      <button class="btn ghost hist" onclick={() => go("/history/prs")} title="Histórico de PRs: votos, aprovações do piloto, comentários (H no painel: só a PR aberta)">
        <History size={14} /> Histórico</button>
    </Toolbar>
    <Split paneKey={selKey} onclose={() => go(`/prs/${tab}`, "soft")}>
      {#snippet list()}
        {#each rows as p (p.key)}
          <PrRow pr={p} selected={p.key === selKey} onselect={() => select(p.key)} showVote={tab !== "mine"}>
            {#snippet actions()}
              {#if tab === "archived"}<button class="btn sm" onclick={() => archive([p.key], false)}><ArchiveRestore size={13} /> Restaurar</button>
              {:else if tab !== "mine" && p.myVote !== 10}<VoteButton pr={p} v={10} cls="good" leaves={tab === "review"}>Aprovar</VoteButton>{/if}
            {/snippet}
          </PrRow>
        {:else}
          <Empty done={tab === "review" && !q && !org} title={tab === "review" ? "Nada para revisar" : tab === "mine" ? "Nenhuma PR sua aberta" : tab === "archived" ? "Nada arquivado" : "Nenhuma PR aberta"}
            text={q || org ? "Nada bate com os filtros." : tab === "mine" ? "Quando abrir uma, ela aparece aqui com o que estiver travando." : ""} />
        {/each}
      {/snippet}
      {#snippet pane()}{#if sel}<PrPane pr={sel} mine={tab === "mine"} leaves={tab === "review"} />{/if}{/snippet}
    </Split>
  {/if}
</Page>

<style>
  .hist { flex: none; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin-bottom: 14px; flex: none; }
</style>
