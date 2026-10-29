<script lang="ts">
  // Os grupos de projetos como blocos: cada um com a cor, quantos projetos, quantos em andamento e se tem agente
  // trabalhando ou perguntando. Clique filtra a lista pelo grupo (de novo, tira o filtro); o ⋯ abre/renomeia/apaga.
  import { FolderPlus, Layers } from "@lucide/svelte";
  import type { Group } from "../../lib/work.svelte";
  import { work } from "../../lib/work.svelte";
  import Menu, { type MenuItem } from "../Menu.svelte";

  let { value = $bindable("any"), total, ungrouped, stats, menu }: {
    value?: string; total: number; ungrouped: number;
    stats: Map<string, { ongoing: number; open: number; need: number; working: number }>; menu: (g: Group) => MenuItem[];
  } = $props();
  const pick = (id: string) => (value = value === id ? "any" : id);
</script>

<div class="gt" role="tablist" aria-label="Grupos de projetos">
  <button class="tile all" class:on={value === "any"} role="tab" aria-selected={value === "any"} onclick={() => (value = "any")}>
    <span class="ico"><Layers size={14} /></span>
    <span class="nm"><b>Todos</b><span class="n">{total} projetos</span></span>
  </button>
  {#each work.groups as g (g.id)}
    {@const s = stats.get(g.id) || { ongoing: 0, open: 0, need: 0, working: 0 }}
    <div class="tile" class:on={value === g.id} style="--g:{g.color}" role="tab" tabindex="0" aria-selected={value === g.id}
      onclick={() => pick(g.id)} onkeydown={(e) => e.key === "Enter" && pick(g.id)} data-menu-row title={g.description || g.name}>
      <span class="sw"></span>
      <span class="nm">
        <b class="ell">{g.name}</b>
        <span class="n">{g.repoIds.length} projeto{g.repoIds.length === 1 ? "" : "s"}{#if s.ongoing} · <em>{s.ongoing} em andamento</em>{/if}</span>
      </span>
      {#if s.need}<span class="st warn" title="agente perguntando"></span>{:else if s.working}<span class="st live" title="agente trabalhando"></span>{/if}
      <Menu items={menu(g)} />
    </div>
  {/each}
  {#if ungrouped && work.groups.length}
    <button class="tile none" class:on={value === "none"} role="tab" aria-selected={value === "none"} onclick={() => pick("none")}>
      <span class="sw dashed"></span>
      <span class="nm"><b>Sem grupo</b><span class="n">{ungrouped} projetos</span></span>
    </button>
  {/if}
  <button class="tile add" onclick={() => work.newGroup([])} title="Criar um grupo (como os grupos de abas do navegador)">
    <FolderPlus size={14} /><span>{work.groups.length ? "Novo grupo" : "Agrupe seus projetos"}</span>
  </button>
</div>

<style>
  .gt { display: flex; flex: none; gap: 8px; overflow-x: auto; padding: 2px 1px 4px; scrollbar-width: thin; }
  .tile { position: relative; display: flex; align-items: center; gap: 10px; min-width: 150px; max-width: 250px; height: 48px; padding: 0 6px 0 12px; flex: none;
    border-radius: 12px; border: 1px solid var(--line); background: var(--surface); color: var(--text-2); font: 13px var(--font); text-align: left; cursor: pointer;
    transition: border-color var(--t), background var(--t), transform var(--t) var(--spring); }
  .tile:hover { border-color: var(--line-3); transform: translateY(-1px); }
  .tile:focus-visible { outline: none; box-shadow: var(--ring); }
  .tile.on { border-color: color-mix(in srgb, var(--g, var(--accent)) 60%, transparent);
    background: linear-gradient(135deg, color-mix(in srgb, var(--g, var(--accent)) 14%, var(--surface)), var(--surface) 75%); color: var(--text); }
  .ico { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 8px; background: var(--surface-2); color: var(--text-2); flex: none; }
  .sw { width: 10px; height: 26px; border-radius: 4px; background: var(--g); flex: none; box-shadow: 0 0 12px -2px color-mix(in srgb, var(--g) 70%, transparent); }
  .sw.dashed { background: none; border: 1.5px dashed var(--line-3); box-shadow: none; }
  .nm { display: grid; min-width: 0; flex: 1; gap: 1px; }
  .nm b { color: var(--text); font-weight: 620; font-size: 13px; }
  .n { font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .n em { font-style: normal; color: var(--text-2); }
  .st { width: 7px; height: 7px; border-radius: 50%; flex: none; }
  .st.warn { background: var(--warn); box-shadow: 0 0 0 3px var(--warn-soft); }
  .st.live { background: var(--accent); animation: gt-ping 1.4s var(--ease) infinite; }
  .tile :global(.btn.sm.icon) { opacity: 0; transition: opacity var(--t-fast); }
  .tile:hover :global(.btn.sm.icon), .tile.on :global(.btn.sm.icon) { opacity: 1; }
  .tile.add { min-width: 0; padding: 0 14px; gap: 7px; border-style: dashed; background: none; color: var(--muted); }
  .tile.add:hover { color: var(--text); }
  @keyframes gt-ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 5px transparent; } }
  @media (prefers-reduced-motion: reduce) { .st.live { animation: none; } .tile:hover { transform: none; } }
</style>
