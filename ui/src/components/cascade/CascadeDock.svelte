<script lang="ts">
  // Doca dos acompanhamentos em cascata: um botão no canto (só com algo em andamento) que abre a lista das PRs
  // seguidas até o deploy, cada uma com a linha do tempo ao vivo. Uma PR integrada sai das listas de PRs, então é
  // aqui (e na barra lateral) que o merge, o build e o deploy dela continuam visíveis.
  import { ChevronDown, Radio } from "@lucide/svelte";
  import { cascade } from "../../lib/cascade.svelte";
  import { router } from "../../lib/router.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import CascadeTrack from "./CascadeTrack.svelte";

  const items = $derived(cascade.items);
  const active = $derived(cascade.active.length);
  const running = $derived(cascade.running.length);
  const waiting = $derived(cascade.waiting.length);
  const status = $derived([running ? `${running} em execução` : "", waiting ? `${waiting} aguardando merge` : ""].filter(Boolean).join(" · "));
  // dentro de um projeto o canto é do editor/terminal: o botão fechado só aparece nas outras telas (a barra lateral abre)
  const showPill = $derived(active > 0 && !["work", "solo", "repo"].includes(router.view));
  let expanded = $state<string | null>(null);
  $effect(() => { if (cascade.focus) expanded = cascade.focus; });
  $effect(() => { if (cascade.open && !items.length) cascade.open = false; });
  function onKey(e: KeyboardEvent) { if (e.key === "Escape" && cascade.open) cascade.open = false; }
</script>

<svelte:window onkeydown={onKey} />

{#if cascade.open && items.length}
  <div class="dock card" role="dialog" aria-label="Acompanhando até o deploy">
    <div class="dh">
      <Radio size={14} class={running ? "pulse" : ""} />
      <b>Até o deploy</b><span class="small muted">{status || "nada em andamento"}</span>
      <span class="spacer"></span>
      <button class="btn sm ghost icon" title="Fechar (Esc)" aria-label="Fechar" onclick={() => (cascade.open = false)}><ChevronDown size={15} /></button>
    </div>
    <div class="list">
      {#each items as it (it.key)}
        <div class="row-it" class:on={expanded === it.key} class:done={it.stage === "finished"}>
          <button class="head" onclick={() => (expanded = expanded === it.key ? null : it.key)}>
            <span class="small muted row" style="gap:5px"><ProviderIcon provider={it.provider} size={11} /><span class="ell">{it.org}/{it.repo} #{it.prId} → {it.target}</span></span>
            <span class="tt ell">{it.title}</span>
            {#if expanded !== it.key}<CascadeTrack item={it} compact />{/if}
          </button>
          {#if expanded === it.key}<CascadeTrack item={it} />{/if}
        </div>
      {/each}
    </div>
  </div>
{:else if showPill}
  <button class="pill-btn" onclick={() => cascade.show((cascade.running[0] || cascade.active[0])?.key)} title={`Acompanhando até o deploy — ${status}`}>
    {#if running}<Radio size={13} class="pulse" /> {running} em execução{#if waiting}<span class="wt">+{waiting}</span>{/if}
    {:else}<Radio size={13} /> {waiting} aguardando merge{/if}
  </button>
{/if}

<style>
  /* --corner-lift: o aviso de versão nova (UpdateBanner) ocupa o canto — a doca e o botão sobem acima dele */
  .dock { position: fixed; right: 16px; bottom: var(--corner-lift, 16px); z-index: 80; width: min(440px, calc(100vw - 32px)); max-height: min(72vh, 640px);
    display: flex; flex-direction: column; box-shadow: var(--shadow-3); animation: up 0.2s var(--ease-out); }
  @keyframes up { from { opacity: 0; transform: translateY(8px); } }
  .dh { display: flex; align-items: center; gap: 8px; padding: 10px 10px 10px 14px; border-bottom: 1px solid var(--line); font-size: 13px; }
  .dh :global(.pulse), .pill-btn :global(.pulse) { color: var(--accent); animation: breathe 1.4s var(--ease) infinite; }
  @keyframes breathe { 50% { opacity: 0.4; } }
  .list { overflow: auto; padding: 6px; display: grid; gap: 4px; }
  .row-it { border-radius: 9px; padding: 2px 4px 6px; }
  .row-it.on { background: var(--surface-2); padding-bottom: 10px; }
  .row-it.done:not(.on) { opacity: 0.7; }
  .head { display: grid; gap: 4px; width: 100%; padding: 6px 6px 2px; border: 0; background: none; text-align: left; color: var(--text); cursor: pointer; font: inherit; min-width: 0; }
  .tt { font-size: 13px; font-weight: 600; }
  .row-it :global(.track) { margin: 4px 6px 0; }
  .pill-btn { position: fixed; right: 16px; bottom: var(--corner-lift, 16px); z-index: 80; display: inline-flex; align-items: center; gap: 7px; height: 32px; padding: 0 13px;
    border-radius: 99px; border: 1px solid var(--line-2); background: var(--elevated); color: var(--text); font: 600 12.5px var(--font); cursor: pointer;
    box-shadow: var(--shadow-2, var(--shadow-3)); animation: up 0.2s var(--ease-out); }
  .pill-btn:hover { border-color: var(--accent); }
  .wt { font-weight: 500; color: var(--muted); margin-left: 2px; }
</style>
