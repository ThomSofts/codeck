<script lang="ts">
  import { AlertTriangle, Check, GitBranch, MessageSquare } from "@lucide/svelte";
  import Ago from "../Ago.svelte";
  import { store } from "../../lib/store.svelte";
  import type { PR } from "../../lib/types";
  import Avatar from "../Avatar.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import { VOTES } from "./votes";

  // checked: null = sem caixa de marcar; true/false = modo "Copiar em lote" (o clique na linha marca/desmarca)
  let { pr, selected = false, onselect, actions = undefined, showVote = true, checked = null }:
    { pr: PR; selected?: boolean; onselect: () => void; actions?: import("svelte").Snippet; showVote?: boolean; checked?: boolean | null } = $props();
  const v = $derived(VOTES[pr.myVote]);
  const conflict = $derived(pr.mergeStatus === "conflicts");
  const phase = $derived(store.votes[pr.key]?.phase);
  // revisão da IA (regra "Revisar com IA"): situação em uma etiqueta
  const ai = $derived.by<[string, string] | null>(() => {
    const r = store.s?.aiReviews?.[pr.key];
    if (!r) return null;
    if (r.status === "queued") return ["IA na fila", "neutral"];
    if (r.status === "running") return ["IA revisando…", "accent"];
    if (r.status === "error") return ["IA falhou", "bad"];
    const n = r.findings?.length || 0;
    return r.verdict === "approve" ? [n ? `IA ✓ · ${n} sugestão(ões)` : "IA ✓", "good"] : [`IA · ${n} ponto(s)`, "warn"];
  });
</script>

<div class="list-row pr vote-{phase || 'idle'}" class:picking={checked !== null} class:sel={selected} class:conflict data-row={pr.key} aria-busy={phase === "sending"} onclick={onselect} role="button" tabindex="-1"
  onkeydown={(e) => e.key === "Enter" && onselect()}>
  {#if checked !== null}<span class="ck" class:on={checked} aria-hidden="true">{#if checked}<Check size={12} strokeWidth={3} />{/if}</span>{/if}
  <Avatar name={pr.creatorName} src={pr.creatorAvatar} size={32} />
  <div class="grow">
    <div class="t"><span class="num">#{pr.prId}</span><span class="title ell">{pr.title}</span></div>
    <div class="meta">
      <span class="row" style="gap:5px"><ProviderIcon provider={pr.provider} size={12} />{pr.org}<span class="faint">/</span>{pr.repo}</span>
      <span class="branch"><GitBranch size={11} />{pr.source} → <b>{pr.target}</b></span>
      <span>{pr.creatorName.split(" ").slice(0, 2).join(" ")} · <Ago iso={pr.created} /></span>
      {#if conflict}<span class="pill solid-bad"><AlertTriangle size={11} /> Conflito</span>{/if}
      {#if pr.isDraft}<span class="pill neutral">rascunho</span>{/if}
      {#if pr.build === "ok"}<span class="pill good">Build ✓</span>{:else if pr.build === "failed"}<span class="pill bad">Build ✕</span>{:else if pr.build === "running" || pr.build === "pending"}<span class="pill warn">Build ⟳</span>{/if}
      {#if showVote && v}{#key pr.myVote}<span class="pill {v[1]} vpill">{v[0]}</span>{/key}{/if}
      {#if pr.approvals}<span class="pill neutral" title={pr.reviewers.filter(r => r.vote >= 5).map(r => r.name).join(", ")}><Check size={11} /> {pr.approvals}</span>{/if}
      {#if ai}<span class="pill {ai[1]}" title="Revisão da IA">🤖 {ai[0]}</span>
      {:else if pr.ruleId}<span class="pill accent" title="Regra de automação">⚡ auto{pr.waiting ? ` · aguardando ${pr.waiting}` : ""}</span>{/if}
      {#each pr.blockers || [] as b (b.code)}<span class="pill {b.code === 'waiting' ? 'warn' : 'bad'}">{b.label}</span>{/each}
    </div>
  </div>
  <div class="acts" onclick={(e) => e.stopPropagation()} role="presentation">{#if actions}{@render actions()}{/if}</div>
</div>

<style>
  .t { display: flex; align-items: baseline; gap: 7px; min-width: 0; }
  .num { color: var(--muted); font-weight: 550; font-variant-numeric: tabular-nums; flex-shrink: 0; font-size: 12.5px; }
  .title { font-weight: 600; }
  .faint { color: var(--faint); }
  .acts { display: flex; gap: 6px; align-items: center; }
  .picking { grid-template-columns: auto auto minmax(0, 1fr) auto; }   /* a caixa de marcar ganha a própria coluna */
  .ck { flex: none; width: 18px; height: 18px; border-radius: 5px; border: 1.5px solid var(--line-3); display: grid; place-items: center;
    color: var(--accent-ink); transition: background var(--t-fast), border-color var(--t-fast); }
  .ck.on { background: var(--accent); border-color: var(--accent); animation: pop 0.3s var(--spring); }
  .conflict { background: color-mix(in srgb, var(--bad-soft) 55%, transparent); }
  /* voto: enviando (luz atravessando a linha) → feito (verde) → saindo (recolhe e as de baixo sobem) */
  .vote-sending { background-image: linear-gradient(100deg, transparent 30%, var(--accent-soft) 50%, transparent 70%); background-size: 250% 100%;
    animation: shimmer 1.2s linear infinite; }
  .vote-sending .grow { opacity: 0.72; transition: opacity var(--t); }
  .vote-done, .vote-leaving { background: var(--good-soft); transition: background 0.3s var(--ease); }
  .vote-done::after, .vote-leaving::after { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--good);
    animation: grow-y 0.35s var(--spring) both; }
  .vote-leaving { overflow: hidden; animation: leave 0.34s var(--ease) forwards; }
  .vote-error { animation: shake 0.42s var(--ease); background: var(--bad-soft); }
  .vpill { animation: pop 0.4s var(--spring); }
  @keyframes grow-y { from { transform: scaleY(0); } }
  @keyframes leave { 0% { max-height: 90px; } 35% { opacity: 1; transform: none; } 100% { max-height: 0; padding-top: 0; padding-bottom: 0; opacity: 0;
    transform: translateX(28px); border-top-color: transparent; } }
  @keyframes shake { 20%, 60% { transform: translateX(-5px); } 40%, 80% { transform: translateX(5px); } }
  .conflict::after { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--bad); }
</style>
