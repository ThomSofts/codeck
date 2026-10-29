<script lang="ts">
  // Todos os projetos abertos num popover (para quando as abas não cabem): busca, estado dos agentes, cor do grupo,
  // trocar de projeto e fechar. ↑/↓ escolhe, Enter vai, Esc fecha.
  import { AppWindow, Search, X } from "@lucide/svelte";
  import { tick } from "svelte";
  import { go } from "../../lib/router.svelte";
  import { work } from "../../lib/work.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import { agentsByProject, noAgents, openOrdered, tone } from "./open";

  let btn: HTMLButtonElement | undefined = $state();
  let input: HTMLInputElement | undefined = $state();
  let open = $state(false);
  let q = $state("");
  let hi = $state(0);
  let pos = $state({ top: 0, left: 0 });

  const ordered = $derived(openOrdered());
  const ags = $derived(agentsByProject());
  const need = $derived([...ags.values()].reduce((n, a) => n + a.need, 0));
  const busy = $derived([...ags.values()].some(a => a.working));
  const list = $derived.by(() => {
    const parts = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return ordered.filter(p => { const h = `${p.name} ${p.slug || ""} ${work.groupOf(p.id)?.name || ""}`.toLowerCase(); return parts.every(t => h.includes(t)); });
  });

  async function toggle() {
    if (open) return (open = false);
    const r = btn!.getBoundingClientRect(), W = 340;
    pos = { top: r.bottom + 6, left: Math.max(8, Math.min(r.left, window.innerWidth - W - 8)) };
    q = ""; hi = Math.max(0, ordered.findIndex(p => p.id === work.active));
    open = true;
    await tick();
    input?.focus();
  }
  function pick(id: string) { open = false; go("/work/" + id, "soft"); }
  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") { e.preventDefault(); open = false; btn?.focus(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); hi = Math.min(list.length - 1, hi + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); hi = Math.max(0, hi - 1); }
    else if (e.key === "Enter" && list[hi]) { e.preventDefault(); pick(list[hi].id); }
  }
  $effect(() => { void q; hi = 0; });
  $effect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => { const t = e.target as Node; if (!btn?.contains(t) && !document.querySelector(".osw-pop")?.contains(t)) open = false; };
    const away = () => (open = false);
    window.addEventListener("pointerdown", down, true);
    window.addEventListener("resize", away);
    return () => { window.removeEventListener("pointerdown", down, true); window.removeEventListener("resize", away); };
  });
</script>

<button class="osw" class:on={open} bind:this={btn} onclick={toggle} aria-haspopup="dialog" aria-expanded={open}
  title={`Projetos abertos (${work.projects.length})`} aria-label={`Projetos abertos: ${work.projects.length}`}>
  <AppWindow size={14} />
  <span class="n">{work.projects.length}</span>
  {#if need}<span class="need" title="agente(s) precisando de você">{need}</span>{:else if busy}<span class="live" title="agente trabalhando"></span>{/if}
</button>

{#if open}
  <div class="osw-pop" style="top:{pos.top}px;left:{pos.left}px" role="dialog" aria-label="Projetos abertos">
    <label class="q"><Search size={13} /><input bind:this={input} bind:value={q} onkeydown={onKey} placeholder="Buscar nos abertos…" /></label>
    <div class="items" role="listbox">
      {#each list as p, i (p.id)}
        {@const a = ags.get(p.id) || noAgents}
        {@const g = work.groupOf(p.id)}
        <div class="it" class:hi={i === hi} class:cur={p.id === work.active} role="option" aria-selected={i === hi} tabindex="-1"
          style={g ? `--g:${g.color}` : ""} onclick={() => pick(p.id)} onkeydown={() => {}} onmouseenter={() => (hi = i)}>
          <span class="gb"></span>
          <ProviderIcon provider={(p.provider as any) || null} size={13} />
          <span class="nm ell">{p.name}{#if g}<span class="gn">&nbsp;· {g.name}</span>{/if}</span>
          {#if a.need}<span class="badge" title="precisa de você">{a.need}</span>
          {:else}<span class="sd {tone(a)}" title={a.working ? "trabalhando" : a.done ? "terminou" : a.n ? "agente aberto" : "sem agente"}></span>{/if}
          <button class="x" title="Fechar projeto" onclick={(e) => { e.stopPropagation(); work.close(p.id); }}><X size={12} /></button>
        </div>
      {:else}
        <div class="none">{work.projects.length ? "Nada com essa busca." : "Nenhum projeto aberto."}</div>
      {/each}
    </div>
    <div class="ft"><span class="kbd">↑↓</span> escolher <span class="kbd">Enter</span> ir <span class="kbd">Esc</span> fechar</div>
  </div>
{/if}

<style>
  .osw { position: relative; display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 9px; border-radius: 8px; border: 1px solid var(--line-2);
    background: var(--surface); color: var(--text-2); font: 600 12.5px var(--font); cursor: pointer; flex: none;
    transition: background var(--t-fast), color var(--t-fast), border-color var(--t-fast); }
  .osw:hover, .osw.on { background: var(--surface-2); color: var(--text); border-color: var(--line-3); }
  .osw:focus-visible { outline: none; box-shadow: var(--ring); }
  .n { font-variant-numeric: tabular-nums; }
  .need { font: 650 10px/1 var(--font); padding: 2px 5px; border-radius: 99px; background: var(--warn-soft); color: var(--warn); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--warn) 35%, transparent); }
  .live { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); animation: osw-ping 1.2s var(--ease) infinite; }
  .osw-pop { position: fixed; z-index: 80; width: 340px; max-height: min(460px, 70vh); display: flex; flex-direction: column; border-radius: 12px;
    background: var(--elevated); border: 1px solid var(--line-2); box-shadow: var(--shadow-3); overflow: hidden; animation: osw-in 0.16s var(--ease-out); }
  .q { display: flex; align-items: center; gap: 7px; height: 38px; padding: 0 12px; border-bottom: 1px solid var(--line); color: var(--muted); flex: none; }
  .q input { flex: 1; min-width: 0; border: 0; outline: none; background: none; color: var(--text); font: 13px var(--font); }
  .items { overflow: auto; padding: 5px; }
  .it { position: relative; display: flex; align-items: center; gap: 8px; height: 32px; padding: 0 6px 0 12px; border-radius: 7px; color: var(--text-2);
    font: 13px var(--font); cursor: pointer; }
  .it.hi { background: var(--surface-3); color: var(--text); }
  .it.cur .nm { font-weight: 650; color: var(--text); }
  .gb { position: absolute; left: 3px; top: 8px; bottom: 8px; width: 3px; border-radius: 2px; background: var(--g, transparent); }
  .nm { flex: 1; }
  .gn { color: var(--muted); font-size: 11.5px; }
  .badge { font: 650 10px/1 var(--font); padding: 2px 6px; border-radius: 99px; background: var(--warn-soft); color: var(--warn); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--warn) 35%, transparent); }
  .sd { width: 7px; height: 7px; border-radius: 50%; flex: none; background: transparent; }
  .sd.accent { background: var(--accent); animation: osw-ping 1.2s var(--ease) infinite; } .sd.good { background: var(--good); } .sd.muted { background: var(--text-2); }
  .x { display: grid; place-items: center; width: 20px; height: 20px; border: 0; border-radius: 5px; background: none; color: var(--muted); cursor: pointer; opacity: 0; flex: none; }
  .it.hi .x, .it:hover .x { opacity: 1; }
  .x:hover { background: var(--surface-2); color: var(--text); }
  .none { padding: 14px; text-align: center; color: var(--muted); font-size: 12.5px; }
  .ft { display: flex; align-items: center; gap: 5px; padding: 7px 12px; border-top: 1px solid var(--line); font-size: 11px; color: var(--muted); flex: none; }
  .ft .kbd { margin-left: 4px; }
  .ft .kbd:first-child { margin-left: 0; }
  @keyframes osw-ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 6px transparent; } }
  @keyframes osw-in { from { opacity: 0; transform: translateY(-4px) scale(0.98); } }
  @media (prefers-reduced-motion: reduce) { .osw-pop, .live, .sd.accent { animation: none; } }
</style>
