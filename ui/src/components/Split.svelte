<script lang="ts">
  // Lista + painel de detalhes lado a lado, cada um rolando por dentro. Em janela estreita o painel vira gaveta.
  // Com `resizeKey`, a divisória entre os dois se arrasta (duplo clique volta ao padrão) e a proporção fica guardada.
  import type { Snippet } from "svelte";
  import { untrack } from "svelte";
  import { clearSize, dragX, loadSize, saveSize } from "../lib/resize";
  import Drawer from "./Drawer.svelte";

  let { list, pane = undefined, paneKey = null, onclose = () => {}, paneWidth = "minmax(400px, 38%)", paneTitle = "Detalhes",
    resizeKey = null, defaultFrac = 0.5 }:
    { list: Snippet; pane?: Snippet; paneKey?: string | null; onclose?: () => void; paneWidth?: string; paneTitle?: string;
      resizeKey?: string | null; defaultFrac?: number } = $props();
  let w = $state(window.innerWidth);
  const wide = $derived(w >= 1180);
  const HANDLE = 14, MIN_LIST = 320, MIN_PANE = 380;
  let box: HTMLDivElement | undefined = $state();
  let cw = $state(0);
  // fração da largura que o painel ocupa (acompanha a janela quando ela muda de tamanho)
  let frac = $state(untrack(() => (resizeKey && loadSize(resizeKey)) || defaultFrac));
  const panepx = $derived(Math.round(Math.max(MIN_PANE, Math.min(cw - HANDLE - MIN_LIST, frac * cw))));
  let dragging = $state(false);

  function start(e: PointerEvent) {
    if (!box) return;
    const r = box.getBoundingClientRect();
    dragging = true;
    dragX(e, x => (frac = Math.max(0.15, Math.min(0.85, (r.right - x) / r.width))), () => { dragging = false; if (resizeKey) saveSize(resizeKey, frac); });
  }
  function reset() { frac = defaultFrac; if (resizeKey) clearSize(resizeKey); }
  const rs = $derived(!!resizeKey && wide && !!pane && !!paneKey);
</script>

<svelte:window bind:innerWidth={w} />

<div class="split" class:with={wide && pane && paneKey} class:rs bind:this={box} bind:clientWidth={cw} style="--pane:{paneWidth};--pw:{panepx}px">
  <div class="card scroll list-card">{@render list()}</div>
  {#if wide && pane && paneKey}
    {#if rs}<div class="handle" class:on={dragging} role="separator" aria-orientation="vertical" aria-label="Redimensionar o painel"
      title="Arraste para redimensionar · duplo clique volta ao padrão" onpointerdown={start} ondblclick={reset}></div>{/if}
    {#key paneKey}<aside class="card scroll pane">{@render pane()}</aside>{/key}
  {/if}
</div>
{#if !wide && pane && paneKey}
  <Drawer title={paneTitle} onclose={onclose} width={560}>{@render pane()}</Drawer>
{/if}

<style>
  .split { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; }
  .split.with { grid-template-columns: minmax(0, 1fr) var(--pane); }
  .split.with.rs { grid-template-columns: minmax(0, 1fr) 14px var(--pw); gap: 0; }
  .scroll { min-height: 0; overflow: auto; overscroll-behavior: contain; }
  .pane { animation: pane-in 0.32s var(--ease-out) both; }
  @keyframes pane-in { from { opacity: 0; transform: translateX(12px); } }
  .handle { position: relative; cursor: col-resize; }
  .handle::after { content: ""; position: absolute; top: 30%; bottom: 30%; left: 6px; width: 2px; border-radius: 2px; background: transparent;
    transition: background var(--t); }
  .handle:hover::after, .handle.on::after { background: var(--accent-line); }
</style>
