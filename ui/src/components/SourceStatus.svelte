<script lang="ts">
  // "Lendo…" / "atualizado há 20 s" de uma ou mais fontes (PRs, builds, deploys, issues), com ↻ para reler só elas.
  // Cada fonte tem o próprio ciclo no backend: a tela mostra o estado no lugar certo, sem acender nada no topo.
  import { Check, RefreshCw } from "@lucide/svelte";
  import { store } from "../lib/store.svelte";
  import type { Source } from "../lib/types";

  let { sources, compact = false }: { sources: Source[]; compact?: boolean } = $props();
  const NAMES: Record<Source, string> = { prs: "pull requests", builds: "builds", deploys: "deploys", issues: "issues" };
  let now = $state(Date.now());
  $effect(() => { const t = setInterval(() => (now = Date.now()), 5000); return () => clearInterval(t); });
  const loading = $derived(sources.filter(s => store.loadingOf(s)));
  const last = $derived(sources.map(s => store.updatedOf(s)).filter(Boolean).map(x => new Date(x!).getTime()));
  const oldest = $derived(last.length === sources.length ? Math.min(...last) : null);
  // terminou agora há pouco: um "✓ atualizado" rápido
  let flash = $state(false);
  let prevSig = "";
  $effect(() => {
    const sig = sources.map(s => store.updatedOf(s) || "").join("|");
    if (prevSig && sig !== prevSig && !loading.length) { flash = true; setTimeout(() => (flash = false), 1800); }
    prevSig = sig;
  });
  function ago(t: number) {
    const s = Math.max(0, Math.round((now - t) / 1000));
    return s < 10 ? "agora" : s < 60 ? `há ${s} s` : s < 3600 ? `há ${Math.round(s / 60)} min` : `há ${Math.round(s / 3600)} h`;
  }
  const title = $derived(sources.map(s => `${NAMES[s]}: ${store.loadingOf(s) ? "lendo…" : store.updatedOf(s) ? "lido " + ago(new Date(store.updatedOf(s)!).getTime()) : "ainda não lido"}`).join("\n"));
</script>

<button class="ss" class:loading={loading.length > 0} class:flash class:compact title={`${title}\nClique para ler agora`} disabled={store.offline}
  onclick={() => { for (const s of sources) store.refreshSource(s); }}>
  {#if loading.length}<RefreshCw size={12} class="spin" />{#if !compact}<span>lendo {loading.map(s => NAMES[s]).join(" e ")}…</span>{/if}
  {:else if flash}<Check size={12} />{#if !compact}<span>atualizado</span>{/if}
  {:else}<RefreshCw size={12} />{#if !compact}<span>{store.offline ? "sem conexão" : oldest ? `atualizado ${ago(oldest)}` : "aguardando a 1ª leitura"}</span>{/if}{/if}
</button>

<style>
  .ss { display: inline-flex; align-items: center; gap: 6px; height: 26px; padding: 0 10px; border-radius: 99px; border: 1px solid var(--line-2); background: var(--surface);
    color: var(--muted); font: 500 11.5px var(--font); cursor: pointer; white-space: nowrap; transition: color var(--t), border-color var(--t), background var(--t); }
  .ss:hover:not(:disabled) { color: var(--text); border-color: var(--line-3); }
  .ss.loading { color: var(--accent); border-color: var(--accent-line); background: var(--accent-soft); }
  .ss.flash { color: var(--good); border-color: color-mix(in srgb, var(--good) 40%, transparent); animation: pop-in 0.3s var(--spring); }
  .ss.compact { padding: 0; width: 26px; justify-content: center; }
  @keyframes pop-in { from { transform: scale(0.94); } }
</style>
