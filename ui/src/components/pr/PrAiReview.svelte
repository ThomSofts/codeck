<script lang="ts">
  // Revisão da IA desta PR (regra "Revisar com IA"): situação, resumo e os pontos — cada ponto com arquivo abre o diff
  // naquela linha. "Revisar de novo" relê a versão atual.
  import { Bot, RefreshCw } from "@lucide/svelte";
  import { post } from "../../lib/api";
  import { store } from "../../lib/store.svelte";
  import type { AiFinding, PR } from "../../lib/types";
  import { ui } from "../../lib/ui.svelte";
  import Ago from "../Ago.svelte";
  import { VOTES } from "./votes";

  let { pr, onjump }: { pr: PR; onjump: (f: AiFinding) => void } = $props();
  const r = $derived(store.s?.aiReviews?.[pr.key]);
  const SEV: Record<string, [string, string]> = { alta: ["Alta", "bad"], media: ["Média", "warn"], baixa: ["Baixa", "neutral"] };
  const old = $derived(r?.status === "done" && !!r.commit && !!pr.commit && r.commit !== pr.commit);
  let busy = $state(false);
  async function again() {
    busy = true;
    try { await post("pr/ai-review", { key: pr.key }); ui.toast("Revisão da IA na fila"); store.refreshSoon(300); }
    catch (e) { ui.error(e); }
    finally { busy = false; }
  }
</script>

{#if r}
  <section class="air">
    <div class="h">
      <Bot size={14} /><b>Revisão da IA</b>
      {#if r.status === "queued"}<span class="pill neutral">na fila</span>
      {:else if r.status === "running"}<span class="pill accent run">revisando…</span>
      {:else if r.status === "error"}<span class="pill bad">falhou</span>
      {:else if r.verdict === "approve"}<span class="pill good">tudo certo</span>
      {:else}<span class="pill warn">pediu ajustes</span>{/if}
      {#if r.status === "done" && r.vote != null && VOTES[r.vote]}<span class="pill {VOTES[r.vote][1]}">votou {VOTES[r.vote][0]}</span>
      {:else if r.status === "done" && r.mine}<span class="pill neutral">só comentou</span>{/if}
      <span class="spacer"></span>
      <span class="tiny muted">{r.accountName || ""}{#if r.finished && r.status !== "running" && r.status !== "queued"} · <Ago iso={r.finished} />{/if}</span>
      {#if r.status !== "queued" && r.status !== "running"}
        <button class="btn sm ghost icon" title="Revisar de novo (a versão atual)" aria-label="Revisar de novo" disabled={busy} onclick={again}><RefreshCw size={13} /></button>{/if}
    </div>
    {#if r.status === "error"}<p class="small err">{r.error}</p>{/if}
    {#if old}<p class="tiny muted">Revisou o commit {r.commit?.slice(0, 8)} — a PR já recebeu commit novo, a próxima leitura revisa de novo.</p>{/if}
    {#if r.summary && r.status === "done"}<p class="sum">{r.summary}</p>{/if}
    {#if r.status === "done"}
      {#each r.findings || [] as f, i (i)}
        <button class="f" disabled={!f.file} title={f.file ? "Abrir no diff" : undefined} onclick={() => onjump(f)}>
          <span class="tags"><span class="pill {SEV[f.severity]?.[1] || 'warn'}">{SEV[f.severity]?.[0] || f.severity}</span>
            {#if f.blocking}<span class="pill bad">bloqueia</span>{/if}
            {#if f.file}<code class="ell">{f.file}{f.line ? `:${f.line}` : ""}</code>{/if}</span>
          <span class="txt">{f.text}</span>
        </button>
      {/each}
    {/if}
  </section>
{/if}

<style>
  .air { margin-top: 14px; border: 1px solid var(--line); border-radius: 10px; background: var(--bg-2); padding: 10px 12px; display: grid; gap: 8px; }
  .h { display: flex; align-items: center; gap: 7px; font-size: 13px; flex-wrap: wrap; }
  .spacer { flex: 1; }
  .run { animation: pulse 1.4s var(--ease) infinite; }
  @keyframes pulse { 50% { opacity: 0.55; } }
  .sum { margin: 0; font-size: 13px; color: var(--text-2); white-space: pre-wrap; }
  .err { margin: 0; color: var(--bad); }
  .f { display: grid; gap: 5px; text-align: left; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface);
    color: var(--text); font: 12.5px/1.45 var(--font); cursor: pointer; transition: border-color var(--t-fast), background var(--t-fast); }
  .f:hover:not(:disabled) { border-color: var(--accent-line); background: var(--surface-2); }
  .f:disabled { cursor: default; }
  .tags { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .tags code { color: var(--text-2); min-width: 0; }
  .txt { white-space: pre-wrap; color: var(--text-2); }
</style>
