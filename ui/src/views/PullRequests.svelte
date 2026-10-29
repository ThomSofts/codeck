<script lang="ts">
  import { ArchiveRestore, Copy, CopyCheck, History, X } from "@lucide/svelte";
  import { copyText, prLink, prLinks } from "../lib/clipboard";
  import { repos } from "../lib/repos.svelte";
  import { work } from "../lib/work.svelte";
  import Menu from "../components/Menu.svelte";
  import { localClone } from "../components/pr/history";
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

  // ------------------------------------------------------------ copiar em lote: marcar várias e copiar título + link de todas
  // Atalhos de seleção: as visíveis, as da mesma branch/título das marcadas (a feature aberta em várias APIs) e as de
  // um grupo de projetos (ex.: o grupo "APIs"). Vale sobre a lista da aba e dos filtros atuais.
  let picking = $state(false);
  let picked = $state<string[]>([]);
  const pickedPrs = $derived(rows.filter(p => picked.includes(p.key)));
  const toggle = (k: string) => (picked = picked.includes(k) ? picked.filter(x => x !== k) : [...picked, k]);
  const add = (ps: PR[]) => (picked = [...new Set([...picked, ...ps.map(p => p.key)])]);
  function stopPicking() { picking = false; picked = []; }
  $effect(() => { if (picking && !repos.loaded) repos.load(false); });
  $effect(() => { if (picking && !work.loaded) work.load(); });
  const groupOf = (p: PR) => { const l = localClone(p.repoKey); return l ? work.groups.find(g => g.repoIds.includes(l.id)) || null : null; };
  const pickMenu = $derived.by(() => {
    const sel = pickedPrs;
    const branches = new Set(sel.map(p => p.source)), titles = new Set(sel.map(p => p.title.trim().toLowerCase()));
    const sameBranch = rows.filter(p => branches.has(p.source)), sameTitle = rows.filter(p => titles.has(p.title.trim().toLowerCase()));
    const groups = work.groups.map(g => ({ g, ps: rows.filter(p => groupOf(p)?.id === g.id) })).filter(x => x.ps.length);
    return [
      { label: `Todas as visíveis (${rows.length})`, onclick: () => add(rows) },
      { label: `Mesma branch das marcadas${sel.length ? ` (${sameBranch.length})` : ""}`, disabled: !sel.length, hint: "a feature aberta em vários repositórios", onclick: () => add(sameBranch) },
      { label: `Mesmo título das marcadas${sel.length ? ` (${sameTitle.length})` : ""}`, disabled: !sel.length, onclick: () => add(sameTitle) },
      ...(groups.length ? [{ heading: "Grupo de projetos" }, ...groups.map(x => ({ label: `${x.g.name} (${x.ps.length})`, onclick: () => add(x.ps) }))] : []),
      { separator: true }, { label: "Limpar a seleção", disabled: !sel.length, onclick: () => (picked = []) },
    ];
  });
  async function copyPicked() {
    if (!pickedPrs.length) return;
    if (await copyText(prLinks(pickedPrs), `${pickedPrs.length} PR${pickedPrs.length === 1 ? "" : "s"} copiada${pickedPrs.length === 1 ? "" : "s"} — título e link`)) stopPicking();
  }
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
      <button class="btn ghost hist" class:on={picking} onclick={() => (picking ? stopPicking() : (picking = true))}
        title="Marcar várias PRs e copiar o título e o link de todas de uma vez"><CopyCheck size={14} /> Copiar em lote</button>
      <button class="btn ghost hist" onclick={() => go("/history/prs")} title="Histórico de PRs: votos, aprovações do piloto, comentários (H no painel: só a PR aberta)">
        <History size={14} /> Histórico</button>
    </Toolbar>
    <Split resizeKey="prs" defaultFrac={0.55} paneKey={selKey} onclose={() => go(`/prs/${tab}`, "soft")}>
      {#snippet list()}
        {#each rows as p (p.key)}
          <PrRow pr={p} selected={p.key === selKey} onselect={() => (picking ? toggle(p.key) : select(p.key))} showVote={tab !== "mine"}
            checked={picking ? picked.includes(p.key) : null}>
            {#snippet actions()}
              <button class="btn sm ghost icon" title="Copiar título e link" aria-label="Copiar título e link" onclick={() => copyText(prLink(p), "Título e link copiados")}><Copy size={13} /></button>
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
    {#if picking}
      <div class="batch">
        <CopyCheck size={15} /><b>{picked.length ? `${pickedPrs.length} marcada${pickedPrs.length === 1 ? "" : "s"}` : "Marque as PRs na lista"}</b>
        <Menu small={false} align="left" items={pickMenu}>{#snippet trigger()}<span class="btn sm">Selecionar…</span>{/snippet}</Menu>
        {#if pickedPrs.length}<span class="small muted ell prev">{pickedPrs.map(p => `${p.repo} #${p.prId}`).join(", ")}</span>{/if}
        <span class="spacer"></span>
        <button class="btn sm primary" disabled={!pickedPrs.length} onclick={copyPicked}><Copy size={13} /> Copiar {pickedPrs.length || ""}</button>
        <button class="btn sm ghost icon" title="Sair do modo de seleção" aria-label="Sair" onclick={stopPicking}><X size={14} /></button>
      </div>
    {/if}
  {/if}
</Page>

<style>
  .hist { flex: none; }
  .hist.on { color: var(--accent); background: var(--accent-soft); }
  .batch { flex: none; display: flex; align-items: center; gap: 10px; margin-top: 10px; padding: 9px 12px; border-radius: 12px; border: 1px solid var(--accent-line);
    background: var(--surface); box-shadow: var(--shadow-2); font-size: 13px; animation: rise 0.22s var(--ease-out); }
  .batch .prev { min-width: 0; flex: 0 1 auto; max-width: 50%; }
  .spacer { flex: 1; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin-bottom: 14px; flex: none; }
</style>
