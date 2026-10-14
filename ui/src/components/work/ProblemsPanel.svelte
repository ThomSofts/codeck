<script lang="ts">
  // Problemas (como no VS Code / Lista de Erros do Visual Studio): erros e avisos do servidor de linguagem dos arquivos
  // abertos e da última compilação, agrupados por arquivo. Clique abre o arquivo na linha.
  import { ChevronRight, CircleAlert, CircleX, TriangleAlert, X } from "@lucide/svelte";
  import { problems, type Problem } from "../../lib/editorstate.svelte";
  import FileIcon from "./FileIcon.svelte";

  let { lspScope, buildScope, onopen, onclose }: { lspScope: string; buildScope: string; onopen: (path: string, line: number) => void; onclose: () => void } = $props();
  let q = $state("");
  let showErr = $state(true);
  let showWarn = $state(true);
  let shut = $state<Record<string, boolean>>({});
  const list = $derived([...problems.lsp.filter(p => p.scope === lspScope), ...problems.build.filter(p => p.scope === buildScope)]
    .filter(p => (p.severity === "error" ? showErr : showWarn) && (!q || `${p.message} ${p.path} ${p.code || ""}`.toLowerCase().includes(q.toLowerCase()))));
  const groups = $derived.by(() => {
    const m = new Map<string, Problem[]>();
    for (const p of list) m.set(p.path || "(sem arquivo)", [...(m.get(p.path || "(sem arquivo)") || []), p]);
    return [...m.entries()].sort((a, b) => (b[1].some(x => x.severity === "error") ? 1 : 0) - (a[1].some(x => x.severity === "error") ? 1 : 0) || a[0].localeCompare(b[0]));
  });
  const nErr = $derived(list.filter(p => p.severity === "error").length);
  const nWarn = $derived(list.filter(p => p.severity === "warning").length);
</script>

<div class="pp">
  <div class="hd">
    <b>Problemas</b>
    <button class="tg" class:on={showErr} onclick={() => (showErr = !showErr)} title="Erros"><CircleX size={13} /> {nErr}</button>
    <button class="tg w" class:on={showWarn} onclick={() => (showWarn = !showWarn)} title="Avisos"><TriangleAlert size={13} /> {nWarn}</button>
    <input class="flt" bind:value={q} placeholder="Filtrar (texto, arquivo, código CS…)" />
    {#if problems.buildAt && problems.build.some(p => p.scope === buildScope)}<span class="tiny muted">compilação de {new Date(problems.buildAt).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span>{/if}
    <span class="grow"></span>
    <button class="ib" title="Fechar o painel" onclick={onclose}><X size={14} /></button>
  </div>
  <div class="body">
    {#each groups as [path, items] (path)}
      <button class="g" onclick={() => (shut = { ...shut, [path]: !shut[path] })}>
        <ChevronRight size={12} class="chev {shut[path] ? '' : 'rot'}" /><FileIcon name={path.split("/").pop() || path} size={14} />
        <b>{path.split("/").pop()}</b><span class="tiny muted ell">{path.split("/").slice(0, -1).join("/")}</span><span class="cnt">{items.length}</span>
      </button>
      {#if !shut[path]}
        {#each items as p, i (i)}
          <button class="p" onclick={() => p.path && onopen(p.path, p.line)}>
            {#if p.severity === "error"}<CircleX size={13} class="e" />{:else}<TriangleAlert size={13} class="w" />{/if}
            <span class="msg">{p.message}</span>
            <span class="src tiny">{p.source || ""}{p.code ? `(${p.code})` : ""}</span>
            <span class="pos tiny">[Ln {p.line}, Col {p.col}]</span>
          </button>
        {/each}
      {/if}
    {:else}
      <div class="none"><CircleAlert size={14} /> Nenhum problema {q ? "com esse filtro" : "encontrado"} — erros do servidor de linguagem e da compilação aparecem aqui.</div>
    {/each}
  </div>
</div>

<style>
  .pp { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--surface); }
  .hd { display: flex; align-items: center; gap: 6px; height: 32px; padding: 0 8px 0 12px; border-bottom: 1px solid var(--line); flex: none; font-size: 12px; }
  .hd b { font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-2); margin-right: 4px; }
  .tg { display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 7px; border: 1px solid var(--line-2); border-radius: 6px; background: none;
    color: var(--muted); font: 600 11.5px var(--font); cursor: pointer; opacity: 0.6; }
  .tg.on { opacity: 1; color: var(--bad); }
  .tg.w.on { color: var(--warn); }
  .flt { width: 220px; height: 22px; border: 1px solid var(--line-2); border-radius: 6px; background: var(--bg-2); color: var(--text); font: 12px var(--font); padding: 0 8px; outline: none; }
  .flt:focus { border-color: var(--accent); }
  .grow { flex: 1; }
  .ib { display: grid; place-items: center; width: 24px; height: 22px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; }
  .ib:hover { background: var(--surface-3); color: var(--text); }
  .body { flex: 1; overflow: auto; padding: 4px 6px 8px; }
  .g { display: flex; align-items: center; gap: 6px; width: 100%; height: 22px; padding: 0 6px; border: 0; border-radius: 5px; background: none; color: var(--text); font: 12.5px var(--font); cursor: pointer; text-align: left; }
  .g:hover { background: var(--surface-2); }
  .g :global(.chev) { color: var(--faint); transition: transform var(--t) var(--ease); flex: none; }
  .g :global(.chev.rot) { transform: rotate(90deg); }
  .g .ell { flex: 1; min-width: 0; }
  .cnt { font: 650 10.5px/1 var(--font); padding: 2px 6px; border-radius: 99px; background: var(--surface-3); color: var(--text-2); }
  .p { display: flex; align-items: flex-start; gap: 7px; width: 100%; padding: 3px 6px 3px 30px; border: 0; border-radius: 5px; background: none; color: var(--text-2);
    font: 12.5px/1.4 var(--font); text-align: left; cursor: pointer; }
  .p:hover { background: var(--surface-2); color: var(--text); }
  .p :global(.e) { color: var(--bad); flex: none; margin-top: 2px; } .p :global(.w) { color: var(--warn); flex: none; margin-top: 2px; }
  .msg { flex: 1; min-width: 0; }
  .src, .pos { color: var(--muted); white-space: nowrap; flex: none; }
  .none { display: flex; align-items: center; gap: 7px; padding: 12px; font-size: 12.5px; color: var(--muted); }
</style>
