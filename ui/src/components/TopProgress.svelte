<script lang="ts">
  // Fio de progresso no topo: só para o que VOCÊ pediu — uma ação sendo enviada ou o "Atualizar tudo". As leituras
  // automáticas de cada fonte (PRs, builds, deploys, issues) aparecem no próprio lugar (barra lateral e cabeçalho da tela).
  import { store } from "../lib/store.svelte";
  import { ui } from "../lib/ui.svelte";
  const on = $derived((store.refreshing && !store.offline) || ui.inflight > 0);
</script>

<div class="tp" class:on class:send={ui.inflight > 0} aria-hidden="true"><span></span></div>

<style>
  .tp { position: relative; height: 2px; flex: none; overflow: hidden; opacity: 0; transition: opacity 0.4s var(--ease); }
  .tp.on { opacity: 1; transition-duration: 0.15s; }
  .tp span { position: absolute; top: 0; bottom: 0; width: 38%; border-radius: 2px; background: linear-gradient(90deg, transparent, var(--accent), var(--accent-2), transparent);
    animation: travel 1.25s var(--ease) infinite; animation-play-state: paused; }
  .tp.on span { animation-play-state: running; }
  .tp.send span { background: linear-gradient(90deg, transparent, var(--good), var(--accent), transparent); }
  @keyframes travel { from { left: -40%; } to { left: 100%; } }
  @media (prefers-reduced-motion: reduce) { .tp span { animation: none; left: 0; width: 100%; opacity: 0.6; } }
</style>
