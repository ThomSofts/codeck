<script lang="ts">
  // O fôlego de uma conta: uma barra fina por janela (5 h e semanal), quanto já foi usado e a contagem para o reset
  // andando. A barra que segura a conta (a mais gasta) fica mais forte; as outras, mais apagadas.
  import type { AiAccount } from "../../lib/work.svelte";
  import { binding, clock, countdown, effUsed, expired, tone, winShort } from "./limits.svelte";

  let { a, compact = false }: { a: AiAccount; compact?: boolean } = $props();
  const now = $derived(clock.now);
  const span = (w: string) => (/semanal/i.test(w) ? 1e6 : parseFloat(w) || 1e5);
  const ws = $derived([...(a.usage?.rateLimits || [])].sort((x, y) => span(x.window) - span(y.window)));
  const bind = $derived(binding(ws, now));
  const pct = (n: number) => `${n > 0 && n < 10 ? n.toFixed(1).replace(".0", "") : Math.round(n)}%`;
</script>

{#if ws.length}
  <div class="fuel" class:compact>
    {#each ws as w (w.window)}
      {@const used = effUsed(w, now)}
      {@const cd = countdown(w.resetsAt, now)}
      <div class="w {tone(w.used == null ? null : used)}" class:lead={ws.length > 1 && bind?.window === w.window && used > 0}
        title={`${winShort(w)}: ${pct(used)} usado${cd ? cd === "resetou" ? " · resetou" : ` · reseta em ${cd}` : ""}`}>
        <span class="l">{winShort(w)}</span>
        <span class="t"><i style="transform:scaleX({Math.min(100, used) / 100})"></i></span>
        <b>{w.used == null ? "—" : pct(used)}</b>
        {#if !compact}<span class="cd" class:fresh={expired(w, now)}>{cd === "resetou" ? "resetou" : cd ? `↺ ${cd}` : ""}</span>{/if}
      </div>
    {/each}
  </div>
{/if}

<style>
  .fuel { display: grid; gap: 5px; min-width: 0; }
  .w { --c: var(--good); display: grid; grid-template-columns: 52px minmax(40px, 1fr) 38px 58px; align-items: center; gap: 8px; font-size: 11.5px; opacity: 0.72;
    transition: opacity var(--t); }
  .compact .w { grid-template-columns: 46px minmax(30px, 1fr) 34px; gap: 6px; }
  .w.lead, .fuel:not(:has(.lead)) .w { opacity: 1; }
  .w.warn { --c: var(--warn); } .w.bad { --c: var(--bad); } .w.muted { --c: var(--muted); }
  .l { color: var(--text-2); white-space: nowrap; }
  .t { position: relative; height: 6px; border-radius: 99px; background: var(--surface-3); overflow: hidden; }
  .t i { position: absolute; inset: 0; border-radius: inherit; background: var(--c); transform-origin: left; transition: transform 0.6s var(--ease-out), background var(--t); }
  b { text-align: right; font-weight: 650; font-variant-numeric: tabular-nums; color: var(--text); }
  .bad b, .warn b { color: var(--c); }
  .cd { color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .cd.fresh { color: var(--good); font-weight: 600; }
  @media (prefers-reduced-motion: reduce) { .t i { transition: none; } }
</style>
