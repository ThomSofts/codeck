<script lang="ts">
  // Medidor circular de um limite (5 h, semanal, contexto…): o arco enche animado ao aparecer e quando o valor muda; a
  // cor segue o quanto falta (verde → amarelo ≥ 70% → vermelho ≥ 90%) e o trilho é a mesma cor, bem clara.
  import { Tween, prefersReducedMotion } from "svelte/motion";
  import { cubicOut } from "svelte/easing";
  import { tone } from "./limits.svelte";

  let { used, size = 64, stroke = 0, label = "", binding = false, title = "" }:
    { used: number | null | undefined; size?: number; stroke?: number; label?: string; binding?: boolean; title?: string } = $props();

  const sw = $derived(stroke || Math.max(3, Math.round(size / 11)));
  const r = $derived((size - sw) / 2);
  const C = $derived(2 * Math.PI * r);
  const p = $derived(used == null ? 0 : Math.min(100, Math.max(0, used)));
  const t = new Tween(0, { duration: 900, easing: cubicOut });
  $effect(() => { const v = p; t.set(v, { duration: prefersReducedMotion.current ? 0 : 900 }); });
  const k = $derived(tone(used));
  const mini = $derived(size < 44);
</script>

<div class="ring {k}" class:binding class:mini style="--s:{size}px" role="img" aria-label={title || `${label} ${used == null ? "sem leitura" : Math.round(p) + "%"}`} title={title || undefined}>
  <svg width={size} height={size} viewBox="0 0 {size} {size}">
    <circle class="track" cx={size / 2} cy={size / 2} {r} stroke-width={sw} />
    <circle class="arc" cx={size / 2} cy={size / 2} {r} stroke-width={sw} stroke-dasharray={C} stroke-dashoffset={C * (1 - t.current / 100)}
      style:opacity={t.current < 0.4 ? 0 : 1} transform="rotate(-90 {size / 2} {size / 2})" />
  </svg>
  <div class="c">
    <b>{used == null ? "—" : Math.round(t.current)}{#if used != null}<small>%</small>{/if}</b>
    {#if label && !mini}<span>{label}</span>{/if}
  </div>
</div>

<style>
  .ring { --c: var(--muted); position: relative; width: var(--s); height: var(--s); flex: none; }
  .good { --c: var(--good); } .warn { --c: var(--warn); } .bad { --c: var(--bad); }
  svg { display: block; overflow: visible; }
  .track { fill: none; stroke: color-mix(in srgb, var(--c) 16%, transparent); }
  .muted .track { stroke: var(--surface-3); }
  .arc { fill: none; stroke: var(--c); stroke-linecap: round; }
  .binding .arc { filter: drop-shadow(0 0 4px color-mix(in srgb, var(--c) 55%, transparent)); }
  .bad.binding svg { animation: alarm 2.4s var(--ease) infinite; }
  .c { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; line-height: 1; gap: 2px; }
  .c b { font-size: calc(var(--s) * 0.26); font-weight: 680; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; color: var(--text); }
  .c small { font-size: 0.55em; font-weight: 600; color: var(--text-2); margin-left: 1px; }
  .c span { font-size: max(9.5px, calc(var(--s) * 0.14)); color: var(--muted); font-weight: 550; }
  .mini .c b { font-size: calc(var(--s) * 0.3); font-weight: 650; }
  .mini .c small { display: none; }
  @keyframes alarm { 50% { filter: drop-shadow(0 0 6px color-mix(in srgb, var(--bad) 50%, transparent)); } }
  @media (prefers-reduced-motion: reduce) { .bad.binding svg { animation: none; } }
</style>
