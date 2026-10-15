<script lang="ts">
  // Gaveta lateral (editores, formulários): entra deslizando com o fundo desfocado; Esc ou clique fora fecha.
  import { X } from "@lucide/svelte";
  import type { Snippet } from "svelte";

  let { title, onclose, width = 620, children, footer = undefined, subtitle = "" }:
    { title: string; onclose: () => void; width?: number; children: Snippet; footer?: Snippet; subtitle?: string } = $props();
  let closing = $state(false);

  function close() {
    closing = true;
    setTimeout(onclose, 190);
  }
  // Não segura a atualização automática: a gaveta pode ficar aberta (detalhe de build/PR em janela estreita) e o que
  // está por trás dela tem de continuar vivo. Os formulários guardam o rascunho no próprio estado.
  $effect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });
</script>

<div class="wrap" class:closing>
  <button class="scrim" aria-label="Fechar" onclick={close}></button>
  <aside class="drawer" style="width:min({width}px, 100%)" aria-label={title}>
    <header>
      <div class="grow"><h2>{title}</h2>{#if subtitle}<p>{subtitle}</p>{/if}</div>
      <button class="btn ghost icon" onclick={close} title="Fechar (Esc)"><X size={18} /></button>
    </header>
    <div class="body">{@render children()}</div>
    {#if footer}<footer>{@render footer()}</footer>{/if}
  </aside>
</div>

<style>
  .wrap { position: fixed; inset: 0; z-index: 50; }
  .scrim { position: absolute; inset: 0; border: 0; background: rgba(5, 7, 12, 0.55); backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px);
    animation: fade 0.22s var(--ease) both; cursor: default; }
  .drawer { position: absolute; top: 0; right: 0; bottom: 0; background: var(--surface); border-left: 1px solid var(--line-2); display: flex; flex-direction: column;
    box-shadow: var(--shadow-3); animation: drawer-in 0.38s var(--ease-out) both; }
  .closing .scrim { animation: fade-out 0.18s var(--ease) forwards; }
  .closing .drawer { animation: drawer-out 0.19s var(--ease) forwards; }
  @keyframes drawer-in { from { transform: translateX(48px); opacity: 0; } }
  @keyframes drawer-out { to { transform: translateX(48px); opacity: 0; } }
  header { display: flex; align-items: flex-start; gap: 10px; padding: 18px 20px 14px; border-bottom: 1px solid var(--line); }
  h2 { margin: 0; font-size: 17px; letter-spacing: -0.02em; }
  header p { margin: 3px 0 0; color: var(--muted); font-size: 12.5px; }
  .body { flex: 1; overflow: auto; padding: 4px 20px 24px; overscroll-behavior: contain; }
  footer { display: flex; align-items: center; gap: 8px; padding: 14px 20px; border-top: 1px solid var(--line); }
</style>
