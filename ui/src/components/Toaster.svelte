<script lang="ts">
  import { CheckCircle2, Info, LoaderCircle, XCircle } from "@lucide/svelte";
  import { ui } from "../lib/ui.svelte";
  const icons = { ok: CheckCircle2, error: XCircle, info: Info, loading: LoaderCircle };
</script>

<div class="toasts" aria-live="polite">
  {#each ui.toasts as t (t.id)}
    {@const Icon = icons[t.kind]}
    <div class="toast {t.kind}">
      {#key t.kind}<span class="ico"><Icon size={16} class={t.kind === "loading" ? "spin" : ""} /></span>{/key}
      <span class="txt">{t.text}</span>
      {#if t.action}<button class="btn sm ghost" onclick={() => t.action?.run()}>{t.action.label}</button>{/if}
    </div>
  {/each}
</div>

<style>
  /* canto superior direito: no centro de baixo cobriam a barra de lote, o aviso de versão e a doca do "Acompanhar" */
  .toasts { position: fixed; top: 14px; right: 18px; z-index: 90; display: grid; gap: 8px; justify-items: end; pointer-events: none; }
  .toast { pointer-events: auto; display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-radius: 12px; background: var(--elevated);
    border: 1px solid var(--line-2); box-shadow: var(--shadow-3); font-size: 13px; max-width: min(560px, 92vw); animation: toast-in 0.34s var(--spring) both; }
  @keyframes toast-in { from { opacity: 0; transform: translateX(18px) scale(0.97); } }
  .toast { transition: border-color 0.3s var(--ease), background 0.3s var(--ease); }
  .ico { display: grid; place-items: center; animation: pop 0.4s var(--spring); }
  .loading .ico { animation: none; }
  .loading :global(svg) { color: var(--accent); flex-shrink: 0; }
  .ok { border-color: color-mix(in srgb, var(--good) 30%, transparent); }
  .ok :global(svg) { color: var(--good); flex-shrink: 0; }
  .error :global(svg) { color: var(--bad); flex-shrink: 0; }
  .info :global(svg) { color: var(--info); flex-shrink: 0; }
  .error { border-color: color-mix(in srgb, var(--bad) 40%, transparent); }
</style>
