<script lang="ts">
  // Indicador numérico: conta até o valor ao aparecer e anima a troca quando ele muda (formatado por `fmt`).
  import { Tween, prefersReducedMotion } from "svelte/motion";
  import { cubicOut } from "svelte/easing";
  import type { Component } from "svelte";

  let { label, value, fmt = (n: number) => String(Math.round(n)), sub = "", tone = "", index = 0, icon = undefined, onclick = undefined }:
    { label: string; value: number; fmt?: (n: number) => string; sub?: string; tone?: string; index?: number; icon?: Component<any>; onclick?: () => void } = $props();
  const t = new Tween(0, { duration: 800, easing: cubicOut });
  $effect(() => { const v = value; t.set(v, { duration: prefersReducedMotion.current ? 0 : 800 }); });
  const Icon = $derived(icon);
</script>

<svelte:element this={onclick ? "button" : "div"} class="stat {tone}" class:click={!!onclick} style="--i:{index}" {onclick} role={onclick ? "button" : undefined}>
  <div class="l">{#if Icon}<span class="ic"><Icon size={13} /></span>{/if}{label}</div>
  <div class="v">{fmt(t.current)}</div>
  {#if sub}<div class="s">{sub}</div>{/if}
</svelte:element>

<style>
  .stat { --c: var(--accent); position: relative; display: grid; gap: 2px; min-width: 0; padding: 11px 14px 12px; border-radius: var(--r); text-align: left;
    font: inherit; color: inherit; background: var(--surface); border: 1px solid var(--line); box-shadow: var(--shadow-1); overflow: hidden;
    animation: rise 0.45s var(--ease-out) both; animation-delay: calc(var(--i) * 40ms); transition: border-color var(--t), transform var(--t) var(--ease); }
  .stat::after { content: ""; position: absolute; left: 0; right: 0; top: 0; height: 2px; background: linear-gradient(90deg, var(--c), transparent 70%); opacity: 0.6; }
  .stat:hover { border-color: var(--line-2); transform: translateY(-1px); }
  .click { cursor: pointer; }
  .good { --c: var(--good); } .warn { --c: var(--warn); } .bad { --c: var(--bad); } .muted { --c: var(--line-3); }
  .l { display: flex; align-items: center; gap: 6px; font-size: 11.5px; font-weight: 500; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ic { display: grid; place-items: center; width: 20px; height: 20px; border-radius: 6px; background: color-mix(in srgb, var(--c) 14%, transparent); color: var(--c); flex: none; }
  .v { font-size: 22px; font-weight: 680; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; line-height: 1.3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .s { font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  @media (prefers-reduced-motion: reduce) { .stat { animation: none; } }
</style>
