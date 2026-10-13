<script lang="ts">
  // Arquivos do projeto/tarefa (git ls-files: versionados + novos não ignorados) em árvore, e a busca no conteúdo.
  // Pastas abrem sob demanda — projeto com dezenas de milhares de arquivos continua leve.
  import { ChevronRight, ChevronsDownUp, File, FileCode2, FileJson, FileText, Folder, FolderOpen, RefreshCw, Search, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { get } from "../../lib/api";
  import { ui } from "../../lib/ui.svelte";

  let { repoId, taskId = null, mode = "files", onopen, active = null }:
    { repoId: string; taskId?: string | null; mode?: "files" | "search"; onopen: (path: string, line?: number) => void; active?: string | null } = $props();
  let all = $state<string[]>([]);
  let open = $state<Record<string, boolean>>({});
  let q = $state("");
  let loading = $state(true);
  let sq = $state("");
  let results = $state<{ path: string; line: number; col: number; text: string }[]>([]);
  let searching = $state(false);
  let sTimer: ReturnType<typeof setTimeout> | undefined;

  // As props chegam como getters que releem o projeto a cada leitura do /api/ws (2,5 s). O efeito depende só desta
  // chave: antes ele rodava a cada leitura e zerava as pastas abertas ("a árvore fechava sozinha").
  const scope = $derived(`${repoId}|${taskId || ""}`);
  const OPEN_KEY = "codeck.tree.open";
  function readOpen(k: string): Record<string, boolean> {
    try { return JSON.parse(localStorage.getItem(OPEN_KEY) || "{}")[k] || {}; } catch { return {}; }
  }
  function saveOpen() {
    try {
      const all = JSON.parse(localStorage.getItem(OPEN_KEY) || "{}");
      all[scope] = Object.fromEntries(Object.entries(open).filter(([, v]) => v));
      // guarda as últimas 40 árvores (projetos e tarefas)
      const keys = Object.keys(all);
      for (const k of keys.slice(0, Math.max(0, keys.length - 40))) delete all[k];
      localStorage.setItem(OPEN_KEY, JSON.stringify(all));
    } catch { /* sem armazenamento */ }
  }
  function toggleDir(path: string) {
    open = { ...open, [path]: !open[path] };
    saveOpen();
  }

  async function load(silent = false) {
    if (!silent) loading = true;
    const k = scope;
    try {
      const files = (await get<{ files: string[] }>("ws/files", { repoId, taskId })).files.sort((a, b) => a.localeCompare(b));
      if (k === scope) all = files;
    }
    catch (e) { if (!silent) ui.error(e); }
    loading = false;
  }
  $effect(() => { const k = scope; untrack(() => { open = readOpen(k); load(); }); });
  // o arquivo ativo (aberto por ⌘P, busca ou definição) fica visível: abre as pastas dele — uma vez por arquivo, para
  // não reabrir a cada leitura a pasta que você recolheu
  let revealed = "";
  $effect(() => {
    const f = active;
    if (!f || f === revealed) return;
    revealed = f;
    untrack(() => {
      const parts = f.split("/").slice(0, -1);
      let acc = "", changed = false;
      const next = { ...open };
      for (const p of parts) { acc += p + "/"; if (!next[acc]) { next[acc] = true; changed = true; } }
      if (changed) { open = next; saveOpen(); }
    });
  });
  // arquivos novos (o agente cria, você cria no terminal) aparecem sem recarregar à mão
  $effect(() => {
    void scope;
    const t = setInterval(() => { if (document.visibilityState === "visible" && mode === "files") untrack(() => load(true)); }, 15000);
    return () => clearInterval(t);
  });

  type Node = { name: string; path: string; dir: boolean };
  function children(prefix: string): Node[] {
    const dirs = new Set<string>(), files: Node[] = [];
    for (const f of all) {
      if (!f.startsWith(prefix)) continue;
      const rest = f.slice(prefix.length), i = rest.indexOf("/");
      if (i >= 0) dirs.add(rest.slice(0, i));
      else files.push({ name: rest, path: f, dir: false });
    }
    return [...[...dirs].sort((a, b) => a.localeCompare(b)).map(d => ({ name: d, path: prefix + d + "/", dir: true })), ...files];
  }
  const matches = $derived.by(() => {
    const t = q.trim().toLowerCase();
    if (!t) return [];
    const parts = t.split(/\s+/);
    return all.filter(f => parts.every(p => f.toLowerCase().includes(p))).sort((a, b) => a.length - b.length).slice(0, 200);
  });
  const icon = (n: string) => (/\.(json|jsonc)$/.test(n) ? FileJson : /\.(md|txt)$/.test(n) ? FileText : /\.\w+$/.test(n) ? FileCode2 : File);

  function runSearch() {
    clearTimeout(sTimer);
    sTimer = setTimeout(async () => {
      if (!sq.trim()) { results = []; return; }
      searching = true;
      try { results = (await get<any>("ws/search", { repoId, taskId, q: sq })).results; } catch (e) { ui.error(e); }
      searching = false;
    }, 250);
  }
  const grouped = $derived.by(() => {
    const m = new Map<string, typeof results>();
    for (const r of results) m.set(r.path, [...(m.get(r.path) || []), r]);
    return [...m.entries()];
  });
</script>

{#snippet tree(prefix: string, depth: number)}
  {#each children(prefix) as n (n.path)}
    {#if n.dir}
      <button class="n" style="--d:{depth}" onclick={() => toggleDir(n.path)}>
        <ChevronRight size={12} class="chev {open[n.path] ? 'rot' : ''}" />
        {#if open[n.path]}<FolderOpen size={14} class="fi" />{:else}<Folder size={14} class="fi" />{/if}<span class="ell">{n.name}</span>
      </button>
      {#if open[n.path]}{@render tree(n.path, depth + 1)}{/if}
    {:else}
      {@const I = icon(n.name)}
      <button class="n file" class:on={active === n.path} style="--d:{depth}" onclick={() => onopen(n.path)} title={n.path}>
        <span class="sp"></span><I size={14} class="fi" /><span class="ell">{n.name}</span>
      </button>
    {/if}
  {/each}
{/snippet}

<div class="ft">
  {#if mode === "files"}
    <div class="bar">
      <label class="flt"><Search size={13} /><input bind:value={q} placeholder="Filtrar arquivos…" />{#if q}<button class="x" onclick={() => (q = "")}><X size={11} /></button>{/if}</label>
      <button class="btn sm ghost icon" title="Recolher todas as pastas" onclick={() => { open = {}; saveOpen(); }}><ChevronsDownUp size={13} /></button>
      <button class="btn sm ghost icon" title="Recarregar" onclick={() => load()}><RefreshCw size={13} class={loading ? "spin" : ""} /></button>
    </div>
    <div class="list">
      {#if q.trim()}
        {#each matches as f (f)}
          {@const I = icon(f)}
          <button class="n file" class:on={active === f} style="--d:0" onclick={() => onopen(f)} title={f}><I size={14} class="fi" /><span class="ell"><b>{f.split("/").pop()}</b> <span class="muted tiny">{f.split("/").slice(0, -1).join("/")}</span></span></button>
        {:else}<div class="none">Nenhum arquivo com “{q}”.</div>{/each}
      {:else if loading && !all.length}<div class="none">Carregando…</div>
      {:else}{@render tree("", 0)}{/if}
    </div>
  {:else}
    <div class="bar"><label class="flt"><Search size={13} /><input bind:value={sq} oninput={runSearch} placeholder="Buscar no projeto…" />{#if searching}<RefreshCw size={12} class="spin" />{/if}</label></div>
    <div class="list">
      {#each grouped as [path, hits] (path)}
        <div class="grp"><span class="ell"><b>{path.split("/").pop()}</b> <span class="muted tiny">{path.split("/").slice(0, -1).join("/")}</span></span><span class="cnt">{hits.length}</span></div>
        {#each hits as h (h.line + ":" + h.col)}
          <button class="hit" onclick={() => onopen(h.path, h.line)}><span class="ln">{h.line}</span><span class="ell mono">{h.text.trim()}</span></button>
        {/each}
      {:else}<div class="none">{sq ? (searching ? "Buscando…" : "Nada encontrado.") : "Digite para buscar no conteúdo dos arquivos."}</div>{/each}
    </div>
  {/if}
</div>

<style>
  .ft { display: flex; flex-direction: column; min-height: 0; height: 100%; }
  .bar { display: flex; gap: 4px; padding: 8px; }
  .flt { flex: 1; display: flex; align-items: center; gap: 6px; height: 28px; padding: 0 8px; border-radius: 8px; border: 1px solid var(--line-2);
    background: var(--bg-2); color: var(--muted); }
  .flt:focus-within { border-color: var(--accent); }
  .flt input { flex: 1; min-width: 0; border: 0; outline: none; background: none; color: var(--text); font: 12.5px var(--font); }
  .x { display: grid; place-items: center; width: 16px; height: 16px; border: 0; border-radius: 50%; background: var(--surface-3); color: var(--text-2); cursor: pointer; }
  .list { flex: 1; overflow: auto; padding: 0 4px 10px; }
  .n { --d: 0; display: flex; align-items: center; gap: 5px; width: 100%; height: 24px; padding: 0 6px 0 calc(6px + var(--d) * 12px); border: 0; border-radius: 6px;
    background: none; color: var(--text-2); font: 12.5px var(--font); text-align: left; cursor: pointer; }
  .n:hover { background: var(--surface-2); color: var(--text); }
  .n.on { background: var(--accent-soft); color: var(--text); }
  .n :global(.fi) { color: var(--muted); flex: none; }
  .n :global(.chev) { color: var(--faint); flex: none; transition: transform var(--t) var(--ease); }
  .n :global(.chev.rot) { transform: rotate(90deg); }
  .sp { width: 12px; flex: none; }
  .ell { min-width: 0; }
  .none { padding: 10px; font-size: 12px; color: var(--muted); }
  .grp { display: flex; align-items: center; gap: 6px; padding: 8px 6px 3px; font-size: 12.5px; color: var(--text-2); }
  .grp .ell { flex: 1; }
  .cnt { font-size: 10.5px; color: var(--faint); }
  .hit { display: flex; gap: 8px; width: 100%; padding: 3px 6px 3px 14px; border: 0; border-radius: 6px; background: none; color: var(--text-2);
    font: 12px var(--font); text-align: left; cursor: pointer; }
  .hit:hover { background: var(--surface-2); color: var(--text); }
  .ln { color: var(--faint); font: 11px var(--mono); min-width: 28px; text-align: right; flex: none; }
</style>
