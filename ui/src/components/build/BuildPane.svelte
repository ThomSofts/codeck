<script lang="ts">
  import { Bot, ExternalLink, Play, RotateCcw, Square } from "@lucide/svelte";
  import { work } from "../../lib/work.svelte";
  import { buildAction } from "../../lib/actions";
  import { get } from "../../lib/api";
  import { fmtDur, time } from "../../lib/format";
  import { store } from "../../lib/store.svelte";
  import type { Build } from "../../lib/types";
  import ProviderIcon from "../ProviderIcon.svelte";
  import { buildState, REASON } from "./status";

  let { b }: { b: Build } = $props();
  let detail = $state<any>(null);
  let error = $state<string | null>(null);
  const st = $derived(buildState(b));
  const waiting = $derived(store.s?.deploys.find(d => d.buildId === b.id && d.org === b.org));

  $effect(() => {
    const key = b.key, running = b.status !== "completed";
    void b.result;
    detail = null; error = null;
    const load = () => get("build", { key }).then(d => { if (key === b.key) { detail = d; error = null; } }).catch(e => (error = e.message));
    load();
    if (!running) return;
    // em andamento: as etapas e o que falhou se atualizam sozinhos (sem esperar o ciclo da lista)
    const t = setInterval(() => { if (document.visibilityState === "visible") load(); }, 10000);
    return () => clearInterval(t);
  });
  const failedRun = $derived(["failed", "partiallySucceeded", "canceled"].includes(b.result || ""));
  /** já falhou uma etapa, mas o resto ainda roda: dá para corrigir com IA, mas "tentar de novo" só depois de terminar */
  const failing = $derived(failedRun || b.phase?.state === "failing");
  /** Worktree na branch do build com um agente corrigindo — o prompt já leva o trecho do log de cada etapa que falhou. */
  function fixWithAi() {
    const logs = (detail?.failed || []).map((f: any) => `### ${f.name}\n${(f.logTail || "").slice(-4000)}`).join("\n\n");
    const branch = (b.branch || b.sourceBranch || "").replace(/^refs\/heads\//, "");
    work.startTask({ provider: b.provider, org: b.provider === "github" ? b.project.split("/")[0] : b.org, repo: b.provider === "github" ? b.project : (b.repo || "") }, {
      title: `Corrigir build ${b.pipeline} ${b.number}`, kind: "fix", base: `origin/${branch}`,
      prompt: `O build "${b.pipeline}" ${b.number} falhou na branch ${branch}.\n${b.url}\n\n` +
        `Descubra a causa, corrija e confirme rodando o build/testes localmente. Explique a causa antes de alterar.` +
        (logs ? `\n\nTrechos do log das etapas que falharam:\n${logs}` : ""),
    });
  }
</script>

<div class="pane-h">
  <div class="small muted row"><ProviderIcon provider={b.provider} size={12} />{b.org}{#if b.folder} · {b.folder}{/if} · <span class="pill {st.cls}">{st.icon} {st.label}</span></div>
  <h2>{b.pipeline} <span class="muted">{b.number}</span></h2>
  {#if st.detail}<div class="now {st.cls}">{st.detail}</div>{/if}
  <div class="acts">
    {#if failedRun}<button class="btn sm primary" onclick={() => buildAction(b, "retry")}><RotateCcw size={13} /> Tentar de novo</button>{/if}
    {#if failing}<button class="btn sm" title="Abre um worktree na branch com um agente corrigindo (o log vai junto)" onclick={fixWithAi}><Bot size={13} /> Corrigir com IA</button>{/if}
    {#if b.status === "completed"}<button class="btn sm" onclick={() => buildAction(b, "rerun")}><Play size={13} /> Rodar de novo</button>{/if}
    {#if b.status !== "completed"}<button class="btn sm danger" onclick={() => buildAction(b, "cancel")}><Square size={12} /> Cancelar</button>{/if}
    {#if waiting}<a class="btn sm" href={"#/inbox/" + encodeURIComponent(waiting.key)}>{waiting.kind === "permission" ? "Ver permissão" : "Ver aprovação"}</a>{/if}
    <a class="btn sm ghost" href={b.url} target="_blank" rel="noopener"><ExternalLink size={13} /> Abrir</a>
  </div>
</div>
<div class="pane-b">
  <div class="kv"><span>Branch</span><span class="mono">{b.branch}</span></div>
  <div class="kv"><span>Commit</span><span class="small">{b.message || (b.sourceVersion || "").slice(0, 8) || "—"}</span></div>
  <div class="kv"><span>Disparado por</span><span>{b.requestedFor} <span class="muted small">({REASON[b.reason] || b.reason})</span></span></div>
  <div class="kv"><span>Na fila · início · fim</span><span class="small">{time(b.queued)} · {time(b.started)} · {time(b.finished)}</span></div>
  <div class="kv"><span>Duração</span><span>{fmtDur(b.started, b.finished)}</span></div>

  {#if error}<div class="err">{error}</div>
  {:else if !detail}<div class="sk"><i class="shim" style="width:40%;height:10px"></i><i class="shim" style="width:90%;height:26px"></i><i class="shim" style="width:70%;height:60px"></i></div>
  {:else}
    {#if detail.stages.length}
      <h4>{b.provider === "github" ? "Jobs" : "Etapas"}</h4>
      <div class="stages">{#each detail.stages as x (x.name + x.order)}
        <span class="pill {x.result === 'succeeded' ? 'good' : x.result === 'failed' ? 'bad' : x.state === 'inProgress' ? 'warn' : 'neutral'}">{x.name}</span>{/each}</div>
    {/if}
    {#if detail.failed.length}
      <h4>Onde falhou</h4>
      {#each detail.failed as f (f.name)}
        <div class="fail">
          <b>{f.name}</b> <span class="small muted">{f.type}</span>
          {#each f.issues as i (i.message)}<div class="small" style="color:{i.type === 'error' ? 'var(--bad)' : 'var(--warn)'}">{i.message}</div>{/each}
          {#if f.logTail}<details><summary class="small">trecho do log</summary><pre class="log">{f.logTail}</pre></details>{/if}
        </div>
      {/each}
    {/if}
  {/if}
</div>

<style>
  .pane-h { padding: 16px 18px 14px; border-bottom: 1px solid var(--line); }
  h2 { margin: 6px 0 4px; font-size: 16.5px; letter-spacing: -0.015em; }
  .now { font-size: 12.5px; color: var(--text-2); }
  .now.bad { color: var(--bad); } .now.warn { color: var(--warn); }
  .acts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
  .pane-b { padding: 10px 18px 18px; }
  h4 { margin: 18px 0 8px; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
  .stages { display: flex; flex-wrap: wrap; gap: 5px; }
  .fail { border: 1px solid color-mix(in srgb, var(--bad) 28%, var(--line)); background: color-mix(in srgb, var(--bad-soft) 50%, transparent);
    border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; display: grid; gap: 4px; animation: rise 0.3s var(--ease-out) both; }
  pre.log { margin: 8px 0 0; max-height: 300px; overflow: auto; font: 11.5px/1.5 var(--mono); background: var(--bg-2); border: 1px solid var(--line);
    border-radius: 8px; padding: 10px; white-space: pre-wrap; word-break: break-word; color: var(--text-2); }
  summary { cursor: pointer; color: var(--text-2); }
  .sk { display: grid; gap: 10px; margin-top: 16px; }
  .err { margin-top: 14px; color: var(--bad); font-size: 13px; }
</style>
