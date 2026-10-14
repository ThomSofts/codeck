<script lang="ts">
  import type { Snippet } from "svelte";
  import type { Source } from "../lib/types";
  import SourceStatus from "./SourceStatus.svelte";
  // live: as fontes que a tela mostra — o cabeçalho diz se estão lendo ou quando atualizaram, e ↻ relê só elas
  let { title, sub = "", actions = undefined, children, icon = undefined, live = undefined }:
    { title: string; sub?: string; actions?: Snippet; children: Snippet; icon?: Snippet; live?: Source[] } = $props();
</script>

<section class="page">
  <header class="ph">
    {#if icon}<span class="pic">{@render icon()}</span>{/if}
    <div class="titles">
      <h1>{title}</h1>
      {#if sub}<p>{sub}</p>{/if}
    </div>
    <span class="spacer"></span>
    {#if live?.length}<SourceStatus sources={live} />{/if}
    {#if actions}<div class="acts">{@render actions()}</div>{/if}
  </header>
  <div class="pb">{@render children()}</div>
</section>

<style>
  .page { height: 100%; display: flex; flex-direction: column; min-height: 0; }
  .ph { display: flex; align-items: center; gap: 14px; padding: 18px 24px 14px; flex: none; min-height: 72px; }
  .pic { display: grid; place-items: center; }
  .titles { min-width: 0; }
  h1 { margin: 0; font-size: 21px; font-weight: 720; letter-spacing: -0.03em; line-height: 1.2; }
  p { margin: 2px 0 0; color: var(--muted); font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .acts { display: flex; align-items: center; gap: 8px; }
  .pb { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 0 24px 20px; }
  @media (max-width: 860px) { .ph, .pb { padding-left: 14px; padding-right: 14px; } }
</style>
