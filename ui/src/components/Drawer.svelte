<script lang="ts">
  // Gaveta lateral (editores, formulários): entra deslizando com o fundo desfocado; Esc ou clique fora fecha.
  // Com `resizeKey`, a borda esquerda se arrasta (duplo clique volta ao padrão) e a largura fica guardada.
  import { X } from "@lucide/svelte";
  import type { Snippet } from "svelte";
  import { untrack } from "svelte";
  import { clearSize, dragX, loadSize, saveSize } from "../lib/resize";

  // A gaveta vai para o fim do #app: dentro de um painel com animação de transform (o detalhe da PR ao lado da lista),
  // o position: fixed ficava preso ao painel — o diff abria espremido nele. Continua dentro da raiz do Svelte, então os
  // eventos delegados (onclick…) seguem funcionando.
  function portal(node: HTMLElement) {
    (document.getElementById("app") || document.body).appendChild(node);
    return { destroy() { node.remove(); } };
  }

  let { title, onclose, width = 620, children, footer = undefined, subtitle = "", resizeKey = null }:
    { title: string; onclose: () => void; width?: number; children: Snippet; footer?: Snippet; subtitle?: string; resizeKey?: string | null } = $props();
  let closing = $state(false);
  let w = $state(untrack(() => (resizeKey && loadSize(resizeKey)) || width));
  function start(e: PointerEvent) {
    dragX(e, x => (w = Math.round(Math.max(480, Math.min(window.innerWidth - 40, window.innerWidth - x)))), () => { if (resizeKey) saveSize(resizeKey, w); });
  }
  function reset() { w = width; if (resizeKey) clearSize(resizeKey); }

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

<div class="wrap" class:closing use:portal>
  <button class="scrim" aria-label="Fechar" onclick={close}></button>
  <aside class="drawer" style="width:min({w}px, 100%)" aria-label={title}>
    {#if resizeKey}<div class="edge" role="separator" aria-orientation="vertical" aria-label="Redimensionar" title="Arraste para redimensionar · duplo clique volta ao padrão"
      onpointerdown={start} ondblclick={reset}></div>{/if}
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
  .edge { position: absolute; z-index: 5; top: 0; bottom: 0; left: -5px; width: 10px; cursor: col-resize; }
  .edge::after { content: ""; position: absolute; top: 30%; bottom: 30%; left: 4px; width: 2px; border-radius: 2px; background: transparent; transition: background var(--t); }
  .edge:hover::after { background: var(--accent-line); }
  footer { display: flex; align-items: center; gap: 8px; padding: 14px 20px; border-top: 1px solid var(--line); }
</style>
