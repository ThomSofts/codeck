<script lang="ts">
  // Linha do tempo "até o deploy" de uma PR: Aprovada → Merge → Build → Deploy, com o estado ao vivo de cada passo
  // (lido pelo backend/pilot/cascade.py a cada poucos segundos). Com `pr` e sem acompanhamento: o botão para começar.
  // `compact`: só os quatro pontos e o passo atual (doca, listas).
  import { Check, Clock, ExternalLink, GitMerge, Hammer, LoaderCircle, Minus, Radio, Rocket, Square, ThumbsUp, X } from "@lucide/svelte";
  import { cascade, RESULT_TEXT, STATUS_TEXT, STEP_LABEL } from "../../lib/cascade.svelte";
  import { ago } from "../../lib/format";
  import type { CascadeItem, PR } from "../../lib/types";

  let { pr = undefined, item = undefined, compact = false }: { pr?: PR; item?: CascadeItem | null; compact?: boolean } = $props();

  const it = $derived(item ?? (pr ? cascade.of(pr.key) : null));
  const ORDER = ["approved", "merge", "build", "deploy"] as const;
  const ICON = { approved: ThumbsUp, merge: GitMerge, build: Hammer, deploy: Rocket };
  const live = $derived(!!it && it.stage !== "finished");
  const current = $derived(it ? (it.stage === "finished" ? null : it.stage) : null);
  const now = $derived(it ? it.steps[current || "deploy"] : null);
  const resultCls = $derived(it?.result === "succeeded" ? "good" : it?.result === "failed" ? "bad" : "neutral");
  let busy = $state(false);

  async function start() { if (!pr) return; busy = true; try { await cascade.follow(pr); } finally { busy = false; } }
</script>

{#snippet dot(status: string, Icon: any, size: number)}
  <span class="dot {status}">
    {#if status === "done"}<Check size={size} />
    {:else if status === "failed"}<X size={size} />
    {:else if status === "running"}<LoaderCircle size={size} class="spin" />
    {:else if status === "waiting"}<Clock size={size} />
    {:else if status === "skipped"}<Minus size={size} />
    {:else}<Icon size={size} />{/if}
  </span>
{/snippet}

{#if !it}
  {#if pr}
    <div class="start">
      <div class="st-t"><Radio size={14} /><b>Acompanhar até o deploy</b></div>
      <span class="small muted">Segue esta PR em tempo quase real: merge, build do commit integrado e deploy — com aviso a cada passo.</span>
      <button class="btn sm" disabled={busy} onclick={start}><Rocket size={13} /> Acompanhar</button>
    </div>
  {/if}
{:else if compact}
  <div class="mini" title={now ? `${STEP_LABEL[current || "deploy"]}: ${now.label || STATUS_TEXT[now.status]}` : ""}>
    {#each ORDER as k, i (k)}
      {#if i}<span class="bar" class:fill={it.steps[ORDER[i - 1]].status === "done"}></span>{/if}
      {@render dot(it.steps[k].status, ICON[k], 10)}
    {/each}
    <span class="mlbl ell">{#if it.stage === "finished"}{RESULT_TEXT[it.result || ""] || "Encerrado"}{:else}{STEP_LABEL[current || ""]} · {now?.label || STATUS_TEXT[now?.status || "pending"]}{/if}</span>
  </div>
{:else}
  <div class="track" class:live>
    <div class="th">
      <Radio size={13} class={live ? "pulse" : ""} />
      <b>Até o deploy</b>
      {#if it.stage === "finished"}<span class="pill {resultCls}">{RESULT_TEXT[it.result || ""] || "Encerrado"}</span>
      {:else}<span class="small muted">ao vivo · atualizado {ago(it.updatedAt)}</span>{/if}
      <span class="spacer"></span>
      <button class="btn sm ghost" title={live ? "Parar de acompanhar" : "Tirar da lista"} onclick={() => cascade.stop(it.key)}>
        {#if live}<Square size={12} /> Parar{:else}<X size={12} /> Dispensar{/if}</button>
    </div>
    <ol class="steps">
      {#each ORDER as k, i (k)}
        {@const s = it.steps[k]}
        <li class:cur={current === k}>
          <div class="rail">
            {#if i}<span class="bar" class:fill={it.steps[ORDER[i - 1]].status === "done"}></span>{:else}<span class="bar none"></span>{/if}
            {@render dot(s.status, ICON[k], 13)}
            {#if i < ORDER.length - 1}<span class="bar" class:fill={s.status === "done"}></span>{:else}<span class="bar none"></span>{/if}
          </div>
          <b class="sl">{STEP_LABEL[k]}</b>
          <span class="ss {s.status}">{s.label || STATUS_TEXT[s.status]}</span>
          {#if s.at && s.status !== "pending"}<span class="small muted">{ago(s.at)}</span>{/if}
          {#if s.url}<a class="lnk" href={s.url} target="_blank" rel="noopener" title="Abrir no {it.provider === 'github' ? 'GitHub' : 'Azure DevOps'}"><ExternalLink size={11} /></a>{/if}
        </li>
      {/each}
    </ol>
    {#if now?.parts?.length && (now.parts.length > 1 || now.status !== "done")}
      <div class="parts">
        {#each now.parts as p, i (p.name + i)}
          <a class="part" href={p.url || undefined} target="_blank" rel="noopener">{@render dot(p.status, Minus, 9)}<span class="ell">{p.name}</span><em>{STATUS_TEXT[p.status]}</em></a>
        {/each}
      </div>
    {/if}
    {#if it.error}<div class="small err">Última leitura falhou: {it.error} — tentando de novo</div>{/if}
    {#if it.commit}<div class="small muted mono">commit {it.commit.slice(0, 8)} em {it.target}</div>{/if}
  </div>
{/if}

<style>
  .start { display: grid; gap: 6px; justify-items: start; margin-top: 14px; padding: 10px 12px; border: 1px dashed var(--line-2); border-radius: 10px; }
  .st-t { display: flex; align-items: center; gap: 7px; font-size: 13px; }
  .track { margin-top: 14px; padding: 10px 12px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--bg-2); display: grid; gap: 10px; }
  .track.live { border-color: var(--accent-line, var(--line-2)); }
  .th { display: flex; align-items: center; gap: 8px; font-size: 13px; min-width: 0; }
  .th :global(.pulse) { color: var(--accent); animation: breathe 1.4s var(--ease) infinite; }
  @keyframes breathe { 50% { opacity: 0.4; } }
  .steps { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .steps li { display: grid; justify-items: center; text-align: center; gap: 3px; min-width: 0; position: relative; padding: 0 4px; }
  .rail { display: flex; align-items: center; width: 100%; }
  .rail .bar { flex: 1; }
  .sl { font-size: 12px; margin-top: 2px; }
  .cur .sl { color: var(--accent); }
  .ss { font-size: 11.5px; color: var(--text-2); line-height: 1.3; overflow-wrap: anywhere; }
  .ss.failed { color: var(--bad); } .ss.waiting { color: var(--warn); } .ss.done { color: var(--good); }
  .lnk { color: var(--muted); display: inline-grid; }
  .lnk:hover { color: var(--text); }
  .bar { height: 2px; background: var(--line-2); border-radius: 2px; transition: background var(--t); min-width: 6px; }
  .bar.fill { background: var(--good); }
  .bar.none { visibility: hidden; }
  .dot { display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 50%; flex: none; background: var(--surface-2);
    color: var(--muted); border: 1px solid var(--line-2); transition: background var(--t), color var(--t), border-color var(--t); }
  .dot.done { background: var(--good-soft); color: var(--good); border-color: transparent; }
  .dot.failed { background: var(--bad-soft); color: var(--bad); border-color: transparent; }
  .dot.running { background: var(--accent-soft); color: var(--accent); border-color: transparent; box-shadow: 0 0 0 0 var(--accent); animation: ring 1.6s infinite; }
  .dot.waiting { background: var(--warn-soft); color: var(--warn); border-color: transparent; }
  .dot.skipped { opacity: 0.6; }
  @keyframes ring { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 50%, transparent); } 80%, 100% { box-shadow: 0 0 0 6px transparent; } }
  .parts { display: flex; flex-wrap: wrap; gap: 4px 6px; }
  .part { display: inline-flex; align-items: center; gap: 5px; max-width: 100%; padding: 2px 8px 2px 3px; border-radius: 99px; border: 1px solid var(--line);
    font-size: 11.5px; color: var(--text-2); text-decoration: none; }
  .part .dot { width: 16px; height: 16px; }
  .part em { font-style: normal; color: var(--muted); }
  .part:hover { border-color: var(--line-2); color: var(--text); }
  .err { color: var(--bad); }
  .mini { display: flex; align-items: center; min-width: 0; gap: 0; }
  .mini .dot { width: 17px; height: 17px; }
  .mini .bar { width: 10px; flex: none; min-width: 0; }
  .mlbl { margin-left: 8px; font-size: 11.5px; color: var(--text-2); min-width: 0; flex: 1; }
</style>
