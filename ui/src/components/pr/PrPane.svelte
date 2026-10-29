<script lang="ts" module>
  let lastTab: "info" | "files" = "info";   // a aba escolhida vale para a próxima PR aberta
</script>

<script lang="ts">
  // Painel de detalhes da PR: ações de voto, descrição, revisores e checks/policies. Atalhos para o histórico: o do app
  // filtrado nesta PR (votos, aprovações do piloto, comentários — H) e os commits da branch no clone local (C).
  import { AlertTriangle, Archive, Bot, ExternalLink, Copy, FileDiff, FolderOpen, GitBranch, GitCommitHorizontal, History, Info, WandSparkles } from "@lucide/svelte";
  import { work } from "../../lib/work.svelte";
  import { repos } from "../../lib/repos.svelte";
  import { go, router } from "../../lib/router.svelte";
  import { localClone, openPrCommits, prHistoryPath } from "./history";
  import { store } from "../../lib/store.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { archive } from "../../lib/actions";
  import { dateTime } from "../../lib/format";
  import Ago from "../Ago.svelte";
  import PrFiles from "./PrFiles.svelte";
  import type { PR } from "../../lib/types";
  import Avatar from "../Avatar.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import { POLICY, VOTES } from "./votes";
  import VoteButton from "./VoteButton.svelte";
  import CascadeTrack from "../cascade/CascadeTrack.svelte";
  import Menu from "../Menu.svelte";
  import PrAiReview from "./PrAiReview.svelte";
  import { fixPr, openPrWorkspace } from "./prwork";
  import { copyText, prLink } from "../../lib/clipboard";
  import type { AiFinding } from "../../lib/types";

  let { pr, mine = false, leaves = false }: { pr: PR; mine?: boolean; leaves?: boolean } = $props();
  let tab = $state<"info" | "files">(lastTab);
  let nfiles = $state<number | null>(null);
  function setTab(t: "info" | "files") { tab = lastTab = t; }
  // ponto da revisão da IA → aba de arquivos com o diff aberto naquela linha
  let jumpTo = $state<{ path: string; line: number | null } | null>(null);
  function jump(f: AiFinding) { if (!f.file) return; jumpTo = { path: f.file, line: f.line }; setTab("files"); }
  $effect(() => { if (!work.ai.length) work.loadAi(); });
  const fixItems = $derived([
    { heading: "Ajustar os comentários em aberto com" },
    ...work.ai.filter(a => a.installed).map(a => ({ label: `${a.label} · ${a.name}`, icon: Bot, onclick: () => fixPr(pr, a.id) })),
    ...(work.ai.some(a => a.installed) ? [] : [{ label: "Nenhuma CLI de IA instalada", disabled: true }]),
  ]);

  function reviewWithAi() {
    work.startTask({ provider: pr.provider, org: pr.provider === "github" ? pr.project.split("/")[0] : pr.org, repo: pr.provider === "github" ? pr.project : pr.repo }, {
      title: `Revisar PR #${pr.prId} ${pr.title}`, kind: "review", base: `origin/${pr.source}`, reviewOf: { key: pr.key, prId: pr.prId, url: pr.url },
      prompt: `Revise a pull request #${pr.prId} "${pr.title}" (${pr.source} → ${pr.target}).\n${pr.url}\n\n` +
        `Veja o que mudou com: git diff origin/${pr.target}...HEAD\n` +
        `Aponte bugs, riscos, regressões e o que fere as convenções do projeto (CLAUDE.md/AGENTS.md), citando arquivo e linha. ` +
        `Não altere código: só a revisão, em português, com os achados por gravidade.` + (pr.description ? `\n\nDescrição da PR:\n${pr.description.slice(0, 3000)}` : ""),
    });
  }
  async function doArchive() { await archive([pr.key], !pr.archived); }

  // histórico do app desta PR (o do estado traz os últimos 300; a tela de Histórico lê o arquivo inteiro)
  const events = $derived((store.s?.activity || []).filter(a => a.key === pr.key).length);
  function openHistory() { go(prHistoryPath(pr.key)); }
  const local = $derived(localClone(pr.repoKey));
  $effect(() => { if (!repos.loaded) repos.load(false); });
  const openCommits = () => openPrCommits(pr);
  function onKey(e: KeyboardEvent) {
    if (router.view !== "prs" && router.view !== "inbox") return;   // dentro do projeto o teclado é do terminal/editor
    if (e.metaKey || e.ctrlKey || e.altKey || e.repeat || ui.dialog || store.hold) return;
    if ((e.target as HTMLElement)?.closest?.("input, textarea, select, [contenteditable], .xterm, .monaco-editor") || document.querySelector(".drawer")) return;
    const k = e.key.toLowerCase();
    if (k === "h") { e.preventDefault(); openHistory(); }
    else if (k === "c" && !e.shiftKey) { e.preventDefault(); openCommits(); }
  }
  const btn = (v: number) => pr.myVote !== v;
</script>

<svelte:window onkeydown={onKey} />

<div class="pane-h">
  <div class="top">
    <div class="small muted row grow"><ProviderIcon provider={pr.provider} size={12} /><span class="ell">{pr.org} / {pr.repo} · #{pr.prId}</span></div>
    <div class="hist" role="group" aria-label="Histórico">
      <button class="hb" onclick={openHistory} title="Histórico desta PR no app: votos, aprovações do piloto, comentários (H)">
        <History size={13} /> Histórico{#if events}<em>{events}</em>{/if}<kbd>H</kbd></button>
      <button class="hb" onclick={openCommits} class:off={!local}
        title={local ? `Commits de ${pr.source} em ${local.path.replace(/^\/Users\/[^/]+/, "~")} (C)` : `${pr.repo} não está clonado nesta máquina`}>
        <GitCommitHorizontal size={13} /> Commits<kbd>C</kbd></button>
    </div>
  </div>
  <h2>{pr.title}</h2>
  <div class="meta">
    <span class="branch"><GitBranch size={11} />{pr.source} → <b>{pr.target}</b></span>
    <span class="row" style="gap:6px"><Avatar name={pr.creatorName} src={pr.creatorAvatar} size={16} />{pr.creatorName} · <Ago iso={pr.created} /></span>
  </div>
  <div class="acts">
    {#if !mine}
      {#if btn(10)}<VoteButton {pr} v={10} cls="good" {leaves}>Aprovar</VoteButton>{/if}
      {#if btn(5)}<VoteButton {pr} v={5} {leaves}>Aprovar c/ sugestões</VoteButton>{/if}
      {#if btn(-5)}<VoteButton {pr} v={-5} {leaves}>Aguardando autor</VoteButton>{/if}
      {#if btn(-10)}<VoteButton {pr} v={-10} cls="danger" {leaves}>{pr.provider === "github" ? "Pedir mudanças" : "Recusar"}</VoteButton>{/if}
      {#if btn(0) && pr.provider === "azure"}<VoteButton {pr} v={0} cls="ghost" {leaves}>Remover voto</VoteButton>{/if}
    {/if}
    <a class="btn sm" href={pr.url} target="_blank" rel="noopener"><ExternalLink size={13} /> Abrir</a>
    <button class="btn sm" title="Copia o título e o link (uma linha cada)" onclick={() => copyText(prLink(pr), "Título e link copiados")}><Copy size={13} /> Copiar link</button>
    <button class="btn sm" title={mine ? "Abre o projeto na branch da PR (a tarefa dela ou o seu checkout)" : "O código da PR numa tarefa do projeto (worktree): ler, rodar e depurar sem mexer no seu checkout"}
      onclick={() => openPrWorkspace(pr)}><FolderOpen size={13} /> Abrir no projeto</button>
    {#if mine}
      <Menu items={fixItems} small={false} align="left">{#snippet trigger()}<span class="btn sm" title="Um agente na branch da PR resolve os comentários em aberto da revisão (de gente ou da IA) e faz commit — sem push">
        <WandSparkles size={13} /> Ajustar com IA</span>{/snippet}</Menu>
    {/if}
    <button class="btn sm" title="Abre um worktree na branch da PR com um agente revisando" onclick={reviewWithAi}><Bot size={13} /> Revisar com IA</button>
    {#if !mine}<button class="btn sm ghost" onclick={doArchive}><Archive size={13} /> {pr.archived ? "Restaurar" : "Arquivar"}</button>{/if}
  </div>
  <CascadeTrack {pr} />
</div>
<div class="tabs" role="tablist">
  <button role="tab" aria-selected={tab === "info"} class:on={tab === "info"} onclick={() => setTab("info")}><Info size={13} /> Visão geral</button>
  <button role="tab" aria-selected={tab === "files"} class:on={tab === "files"} onclick={() => setTab("files")}><FileDiff size={13} /> Arquivos modificados
    {#if nfiles !== null}<em>{nfiles}</em>{/if}</button>
</div>
{#if tab === "files"}
<div class="pane-b files"><PrFiles {pr} bind:count={nfiles} bind:jump={jumpTo} /></div>
{:else}
<div class="pane-b">
  {#if pr.mergeStatus === "conflicts"}
    <div class="warnbox"><AlertTriangle size={15} /><span><b>{pr.source}</b> tem conflito com <b>{pr.target}</b>. O merge fica bloqueado até o autor atualizar a branch — aprovar não resolve.</span></div>
  {/if}
  <PrAiReview {pr} onjump={jump} />
  <h4>Descrição</h4>
  <div class="desc">{#if pr.description}{pr.description}{:else}<span class="muted">Sem descrição.</span>{/if}</div>
  <div class="small muted" style="margin-top:8px">Criada em {dateTime(pr.created)}{#if pr.autoComplete} · auto-complete ligado{/if}</div>

  <h4>Revisores</h4>
  {#each pr.reviewers as r (r.id || r.name)}
    <div class="kv"><span class="row" style="gap:7px"><Avatar name={r.name} size={18} />{r.name}{#if r.required}<span class="pill neutral">obrigatório</span>{/if}</span>
      {#if VOTES[r.vote]}<span class="pill {VOTES[r.vote][1]}">{VOTES[r.vote][0]}</span>{:else}<span class="small muted">pendente</span>{/if}</div>
  {:else}<div class="small muted">Sem revisores.</div>{/each}

  <h4>{pr.provider === "github" ? "Checks" : "Policies"}</h4>
  {#each pr.policies as p (p.name + p.status)}
    {@const st = POLICY[p.status] || ["?", "neutral"]}
    <div class="kv"><span>{p.name}{#if !p.blocking && pr.provider === "azure"} <span class="small muted">(opcional)</span>{/if}</span><span class="pill {st[1]}">{st[0]} {p.status}</span></div>
  {:else}<div class="small muted">Nenhum check.</div>{/each}
</div>
{/if}

<style>
  .pane-h { padding: 16px 18px 14px; border-bottom: 1px solid var(--line); }
  .top { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .hist { display: inline-flex; flex: none; border: 1px solid var(--line-2); border-radius: var(--r-sm); overflow: hidden; }
  .hb { display: inline-flex; align-items: center; gap: 5px; height: 24px; padding: 0 8px; border: 0; background: none; color: var(--text-2);
    font: 500 12px/1 var(--font); cursor: pointer; white-space: nowrap; transition: background var(--t-fast), color var(--t-fast); }
  .hb + .hb { border-left: 1px solid var(--line-2); }
  .hb:hover { background: var(--surface-2); color: var(--text); }
  .hb:focus-visible { outline: none; box-shadow: inset var(--ring); }
  .hb.off { color: var(--muted); }
  .hb em { font: 600 10.5px/1 var(--font); font-style: normal; color: var(--accent); font-variant-numeric: tabular-nums; }
  .hb kbd { font: 600 9.5px/1 var(--font); color: var(--muted); border: 1px solid var(--line-2); border-radius: 4px; padding: 2px 4px; margin-left: 1px; }
  @media (max-width: 560px) { .hb kbd { display: none; } }
  h2 { margin: 6px 0 8px; font-size: 16.5px; line-height: 1.35; letter-spacing: -0.015em; }
  .acts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
  .pane-b { padding: 6px 18px 18px; animation: fade 0.2s var(--ease); }
  .pane-b.files { padding-top: 12px; }
  .tabs { display: flex; gap: 2px; padding: 6px 12px 0; border-bottom: 1px solid var(--line); }
  .tabs button { position: relative; display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 10px; border: 0; background: none; color: var(--muted);
    font: 550 12.5px/1 var(--font); cursor: pointer; transition: color var(--t-fast); }
  .tabs button:hover { color: var(--text); }
  .tabs button.on { color: var(--text); }
  .tabs button.on::after { content: ""; position: absolute; left: 8px; right: 8px; bottom: -1px; height: 2px; border-radius: 2px; background: var(--accent);
    animation: grow-x 0.25s var(--ease-out); }
  .tabs em { font: 600 10.5px/1 var(--font); font-style: normal; padding: 2px 6px; border-radius: 99px; background: var(--surface-3); color: var(--text-2);
    font-variant-numeric: tabular-nums; animation: pop 0.4s var(--spring); }
  @keyframes grow-x { from { transform: scaleX(0); } }
  h4 { margin: 18px 0 8px; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
  .desc { white-space: pre-wrap; font-size: 13px; color: var(--text-2); max-height: 280px; overflow: auto; background: var(--bg-2); border: 1px solid var(--line);
    border-radius: 10px; padding: 10px 12px; }
  .warnbox { display: flex; gap: 9px; align-items: flex-start; margin-top: 14px; padding: 10px 12px; border-radius: 10px; background: var(--bad-soft);
    color: var(--bad); font-size: 13px; }
  .warnbox :global(svg) { flex-shrink: 0; margin-top: 2px; }
</style>
