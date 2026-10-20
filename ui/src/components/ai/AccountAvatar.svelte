<script lang="ts">
  // Avatar da conta de IA: as iniciais do apelido num disco na cor da conta, com a marca da CLI no canto — várias
  // contas do Claude ficam distinguíveis de relance. Trabalhando = anel girando; precisa de você = pulso quente;
  // terminou = ponto verde.
  import AgentIcon from "../work/AgentIcon.svelte";
  import { accColor, initials } from "./limits.svelte";

  let { a, state = null, size = 36 }: { a: { id: string; provider: string; name?: string; color?: string | null }; state?: string | null; size?: number } = $props();
  const badge = $derived(Math.max(12, Math.round(size * 0.42)));
</script>

<span class="av {state || ''}" style="--ac:{accColor(a)};--s:{size}px;--b:{badge}px" title={a.name}>
  <span class="ini">{initials(a.name || a.provider)}</span>
  <span class="pv"><AgentIcon provider={a.provider} size={Math.round(badge * 0.66)} /></span>
  {#if state === "done"}<i class="badge"></i>{/if}
</span>

<style>
  .av { position: relative; display: grid; place-items: center; width: var(--s); height: var(--s); border-radius: 50%; flex: none;
    background: color-mix(in srgb, var(--ac) 22%, var(--surface-2)); box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--ac) 60%, transparent); }
  .ini { font: 700 calc(var(--s) * 0.36)/1 var(--font); letter-spacing: -0.02em; color: color-mix(in srgb, var(--ac) 55%, var(--text)); }
  .pv { position: absolute; right: calc(var(--b) * -0.28); bottom: calc(var(--b) * -0.22); display: grid; place-items: center; width: var(--b); height: var(--b);
    border-radius: 50%; background: var(--surface); box-shadow: 0 0 0 1.5px var(--surface), inset 0 0 0 1px var(--line-2); }
  .av::before { content: ""; position: absolute; inset: -3px; border-radius: 50%; opacity: 0; pointer-events: none; }
  .working::before { opacity: 1; background: conic-gradient(from 0deg, transparent 0 55%, var(--accent) 85%, transparent 100%);
    -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2px));
    mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2px)); animation: spin 1.3s linear infinite; }
  .needs-you { animation: warm 1.6s var(--ease) infinite; }
  .badge { position: absolute; left: -1px; top: -1px; width: calc(var(--s) * 0.28); height: calc(var(--s) * 0.28); border-radius: 50%;
    background: var(--good); box-shadow: 0 0 0 2px var(--surface); animation: pop-in 0.4s var(--ease-out) both; }
  @keyframes warm { 0% { box-shadow: inset 0 0 0 1.5px var(--warn), 0 0 0 0 color-mix(in srgb, var(--warn) 55%, transparent); }
    70%, 100% { box-shadow: inset 0 0 0 1.5px var(--warn), 0 0 0 9px transparent; } }
  @keyframes pop-in { from { transform: scale(0); } }
  @media (prefers-reduced-motion: reduce) { .working::before, .needs-you { animation: none; } .needs-you { box-shadow: inset 0 0 0 2px var(--warn); } }
</style>
