<script lang="ts">
  // Avatar da conta de IA: a marca da CLI dentro de um disco na cor da conta. Trabalhando = anel girando;
  // precisa de você = pulso quente; terminou = ponto verde.
  import AgentIcon from "../work/AgentIcon.svelte";
  import { accColor } from "./limits.svelte";

  let { a, state = null, size = 36 }: { a: { id: string; provider: string; color?: string | null }; state?: string | null; size?: number } = $props();
</script>

<span class="av {state || ''}" style="--ac:{accColor(a)};--s:{size}px">
  <AgentIcon provider={a.provider} size={Math.round(size * 0.5)} />
  {#if state === "done"}<i class="badge"></i>{/if}
</span>

<style>
  .av { position: relative; display: grid; place-items: center; width: var(--s); height: var(--s); border-radius: 50%; flex: none;
    background: radial-gradient(circle at 30% 25%, color-mix(in srgb, var(--ac) 30%, transparent), color-mix(in srgb, var(--ac) 10%, var(--surface-2)) 70%);
    box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--ac) 55%, transparent); }
  .av::before { content: ""; position: absolute; inset: -3px; border-radius: 50%; opacity: 0; pointer-events: none; }
  .working::before { opacity: 1; background: conic-gradient(from 0deg, transparent 0 55%, var(--accent) 85%, transparent 100%);
    -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2px));
    mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2px)); animation: spin 1.3s linear infinite; }
  .needs-you { animation: warm 1.6s var(--ease) infinite; }
  .badge { position: absolute; right: -1px; bottom: -1px; width: calc(var(--s) * 0.3); height: calc(var(--s) * 0.3); border-radius: 50%;
    background: var(--good); box-shadow: 0 0 0 2px var(--surface); animation: pop-in 0.4s var(--spring) both; }
  @keyframes warm { 0% { box-shadow: inset 0 0 0 1.5px var(--warn), 0 0 0 0 color-mix(in srgb, var(--warn) 55%, transparent); }
    70%, 100% { box-shadow: inset 0 0 0 1.5px var(--warn), 0 0 0 9px transparent; } }
  @keyframes pop-in { from { transform: scale(0); } }
  @media (prefers-reduced-motion: reduce) { .working::before, .needs-you { animation: none; } .needs-you { box-shadow: inset 0 0 0 2px var(--warn); } }
</style>
