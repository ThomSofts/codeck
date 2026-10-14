<script lang="ts">
  // Explorador (como o do VS Code): arquivos do projeto/tarefa (git ls-files: versionados + novos não ignorados) em
  // árvore, com as cores do Git (M alterado, U novo, D apagado, A adicionado, ! conflito — a pasta herda a cor), ícones do
  // tema de ícones, menu de contexto (novo, renomear, excluir, copiar caminho, abrir alterações) e teclado (↑↓ ←→ Enter F2).
  // Clique abre em "visualização" (a aba é reaproveitada); duplo clique fixa. Também a busca no conteúdo.
  // Pastas abrem sob demanda e a árvore é indexada uma vez por leitura — projeto com dezenas de milhares de arquivos continua leve.
  import { CaseSensitive, ChevronRight, ChevronsDownUp, Copy, FilePlus2, FolderOpen, FolderPlus, GitCompareArrows, Pencil, Regex, RefreshCw, Search, SquareTerminal, Trash2, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { get, post } from "../../lib/api";
  import { fileManagerName } from "../../lib/native";
  import { folderDecor, scm } from "../../lib/scm.svelte";
  import { icons } from "../../lib/fileicons.svelte";
  import { ui } from "../../lib/ui.svelte";
  import FileIcon from "./FileIcon.svelte";

  type OpenOpts = { preview?: boolean };
  let { repoId, taskId = null, gitRepo = null, mode = "files", onopen, ondiff, onterminal, active = null }:
    { repoId: string; taskId?: string | null; gitRepo?: string | null; mode?: "files" | "search"; onopen: (path: string, line?: number, o?: OpenOpts) => void;
      ondiff?: (path: string) => void; onterminal?: (dir: string) => void; active?: string | null } = $props();
  let all = $state<string[]>([]);
  let root = $state("");
  let open = $state<Record<string, boolean>>({});
  let q = $state("");
  let loading = $state(true);
  let sq = $state("");
  let sCase = $state(false);
  let sRegex = $state(false);
  let results = $state<{ path: string; line: number; col: number; text: string }[]>([]);
  let truncated = $state(false);
  let searching = $state(false);
  let sTimer: ReturnType<typeof setTimeout> | undefined;
  let cursor = $state<string | null>(null);
  let listEl: HTMLDivElement | undefined = $state();
  // criação/renomeação em linha: { at: pasta-mãe ("" = raiz), kind, path?: o que está sendo renomeado }
  let edit = $state<{ at: string; kind: "file" | "folder" | "rename"; path?: string; value: string } | null>(null);

  // As props chegam como getters que releem o projeto a cada leitura do /api/ws (2,5 s). O efeito depende só desta
  // chave: antes ele rodava a cada leitura e zerava as pastas abertas ("a árvore fechava sozinha").
  const scope = $derived(`${repoId}|${taskId || ""}`);
  const OPEN_KEY = "codeck.tree.open";
  function readOpen(k: string): Record<string, boolean> {
    try { return JSON.parse(localStorage.getItem(OPEN_KEY) || "{}")[k] || {}; } catch { return {}; }
  }
  function saveOpen() {
    try {
      const s = JSON.parse(localStorage.getItem(OPEN_KEY) || "{}");
      s[scope] = Object.fromEntries(Object.entries(open).filter(([, v]) => v));
      const keys = Object.keys(s);
      for (const k of keys.slice(0, Math.max(0, keys.length - 40))) delete s[k];   // guarda as últimas 40 árvores
      localStorage.setItem(OPEN_KEY, JSON.stringify(s));
    } catch { /* sem armazenamento */ }
  }
  function toggleDir(path: string, force?: boolean) {
    open = { ...open, [path]: force ?? !open[path] };
    saveOpen();
  }

  async function load(silent = false) {
    if (!silent) loading = true;
    const k = scope;
    try {
      const r = await get<{ files: string[]; root: string }>("ws/files", { repoId, taskId });
      if (k !== scope) return;
      const files = r.files.sort((a, b) => a.localeCompare(b));
      if (files.length !== all.length || files.some((f, i) => f !== all[i])) all = files;
      root = r.root;
    }
    catch (e) { if (!silent) ui.error(e); }
    loading = false;
  }
  $effect(() => { const k = scope; untrack(() => { open = readOpen(k); load(); }); });
  // o git status do escopo: cores e letras (o explorador relê junto)
  $effect(() => { const g = gitRepo; if (!g) return; return scm.watch(g); });
  const decor = $derived(scm.map(gitRepo));
  const fdecor = $derived(folderDecor(decor));
  // arquivo novo/apagado no status que a lista ainda não tem: relê a lista (o agente criou algo)
  $effect(() => {
    const d = decor;
    if (untrack(() => [...d.keys()].some(p => d.get(p)!.tone === "add" && !index.files.has(p)))) untrack(() => load(true));
  });

  // o arquivo ativo (aberto por ⌘P, busca ou definição) fica visível: abre as pastas dele — uma vez por arquivo, para
  // não reabrir a cada leitura a pasta que você recolheu
  let revealed = "";
  $effect(() => {
    const f = active;
    if (!f || f === revealed) return;
    revealed = f;
    untrack(() => {
      cursor = f;
      const parts = f.split("/").slice(0, -1);
      let acc = "", changed = false;
      const next = { ...open };
      for (const p of parts) { acc += p + "/"; if (!next[acc]) { next[acc] = true; changed = true; } }
      if (changed) { open = next; saveOpen(); }
      requestAnimationFrame(() => listEl?.querySelector(`[data-p="${CSS.escape(f)}"]`)?.scrollIntoView({ block: "nearest" }));
    });
  });
  // arquivos novos (o agente cria, você cria no terminal) aparecem sem recarregar à mão
  $effect(() => {
    void scope;
    const t = setInterval(() => { if (document.visibilityState === "visible" && mode === "files") untrack(() => load(true)); }, 15000);
    return () => clearInterval(t);
  });

  // ------------------------------------------------------------ índice da árvore (uma vez por lista)
  type Dir = { dirs: string[]; files: string[] };
  const index = $derived.by(() => {
    const dirs = new Map<string, Dir>([["", { dirs: [], files: [] }]]);
    const files = new Set<string>();
    const ensure = (p: string) => { let d = dirs.get(p); if (!d) { d = { dirs: [], files: [] }; dirs.set(p, d); } return d; };
    for (const f of all) {
      files.add(f);
      const parts = f.split("/");
      let acc = "";
      for (let i = 0; i < parts.length - 1; i++) {
        const parent = acc;
        acc += parts[i] + "/";
        if (!dirs.has(acc)) { ensure(parent).dirs.push(acc); ensure(acc); }
      }
      ensure(acc).files.push(f);
    }
    const cmp = (a: string, b: string) => a.localeCompare(b, undefined, { sensitivity: "base", numeric: true });
    for (const d of dirs.values()) { d.dirs.sort(cmp); d.files.sort((a, b) => cmp(a.split("/").pop()!, b.split("/").pop()!)); }
    return { dirs, files };
  });
  // pastas com uma única subpasta e nada mais aparecem juntas ("src/main/java"), como no VS Code
  function compact(p: string): { path: string; label: string } {
    let cur = p, label = p.slice(0, -1).split("/").pop()!;
    for (;;) {
      const d = index.dirs.get(cur);
      if (!d || d.files.length || d.dirs.length !== 1) break;
      cur = d.dirs[0];
      label += "/" + cur.slice(0, -1).split("/").pop();
    }
    return { path: cur, label };
  }
  type Row = { path: string; name: string; dir: boolean; depth: number; deleted?: boolean };
  const rows = $derived.by<Row[]>(() => {
    const out: Row[] = [];
    const walk = (prefix: string, depth: number) => {
      const d = index.dirs.get(prefix);
      if (!d) return;
      for (const sub of d.dirs) {
        const c = compact(sub);
        out.push({ path: c.path, name: c.label, dir: true, depth });
        if (open[c.path]) walk(c.path, depth + 1);
      }
      for (const f of d.files) out.push({ path: f, name: f.slice(prefix.length), dir: false, depth });
    };
    walk("", 0);
    return out;
  });
  const matches = $derived.by(() => {
    const t = q.trim().toLowerCase();
    if (!t) return [];
    const parts = t.split(/\s+/);
    const score = (f: string) => { const n = f.split("/").pop()!.toLowerCase(); return n.startsWith(parts[0]) ? 0 : n.includes(parts[0]) ? 1 : 2; };
    return all.filter(f => { const l = f.toLowerCase(); return parts.every(p => l.includes(p)); })
      .sort((a, b) => score(a) - score(b) || a.length - b.length).slice(0, 300);
  });
  const visible = $derived<Row[]>(q.trim() ? matches.map(f => ({ path: f, name: f.split("/").pop()!, dir: false, depth: 0 })) : rows);

  // ------------------------------------------------------------ teclado
  function onKey(e: KeyboardEvent) {
    if (edit || (e.target as HTMLElement).closest("input")) return;
    const i = visible.findIndex(r => r.path === cursor);
    const r = visible[i];
    const move = (j: number) => { const n = visible[Math.max(0, Math.min(visible.length - 1, j))]; if (n) { cursor = n.path; listEl?.querySelector(`[data-p="${CSS.escape(n.path)}"]`)?.scrollIntoView({ block: "nearest" }); } };
    if (e.key === "ArrowDown") { e.preventDefault(); move(i + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(i - 1); }
    else if (e.key === "ArrowRight" && r?.dir) { e.preventDefault(); if (!open[r.path]) toggleDir(r.path, true); else move(i + 1); }
    else if (e.key === "ArrowLeft" && r) {
      e.preventDefault();
      if (r.dir && open[r.path]) toggleDir(r.path, false);
      else { const parent = r.path.replace(/[^/]+\/?$/, ""); const pi = visible.findIndex(x => x.dir && x.path === parent); if (pi >= 0) move(pi); }
    }
    else if (e.key === "Enter" && r) { e.preventDefault(); if (r.dir) toggleDir(r.path); else onopen(r.path, undefined, { preview: false }); }
    else if (e.key === " " && r && !r.dir) { e.preventDefault(); onopen(r.path, undefined, { preview: true }); }
    else if (e.key === "F2" && r) { e.preventDefault(); startRename(r.path, r.dir); }
    else if ((e.key === "Delete" || (e.key === "Backspace" && (e.metaKey || e.ctrlKey))) && r) { e.preventDefault(); remove(r.path, r.dir); }
  }

  // ------------------------------------------------------------ arquivos: criar, renomear, excluir
  const dirOf = (p: string, dir: boolean) => (dir ? p : p.replace(/[^/]+$/, ""));
  function startNew(kind: "file" | "folder", at: string) {
    if (at) toggleDir(at, true);
    edit = { at, kind, value: "" };
    q = "";
  }
  function startRename(path: string, dir: boolean) {
    const name = path.replace(/\/$/, "").split("/").pop()!;
    edit = { at: dirOf(path.replace(/\/$/, ""), false), kind: "rename", path: dir ? path : path, value: name };
  }
  async function commitEdit() {
    const e = edit;
    if (!e) return;
    edit = null;
    const v = e.value.trim();
    if (!v) return;
    try {
      if (e.kind === "rename") {
        const from = e.path!.replace(/\/$/, ""), to = e.at + v;
        if (to === from) return;
        await post("ws/fs/rename", { repoId, taskId, from, to });
        await load(true);
        ui.toast("Renomeado");
      } else {
        const path = e.at + v;
        await post("ws/fs/create", { repoId, taskId, path, folder: e.kind === "folder" });
        await load(true);
        if (e.kind === "file") onopen(path, undefined, { preview: false });
        else toggleDir(path.replace(/\/?$/, "/"), true);
      }
      if (gitRepo) scm.touch(gitRepo);
    } catch (err) { ui.error(err); }
  }
  async function remove(path: string, dir: boolean) {
    const name = path.replace(/\/$/, "");
    if (!(await ui.ask({ title: `Excluir ${name.split("/").pop()}${dir ? " e tudo dentro dela" : ""}?`, message: "Vai para a Lixeira — dá para recuperar de lá.", confirm: "Mover para a Lixeira", danger: true }))) return;
    try { await post("ws/fs/delete", { repoId, taskId, path: name }); await load(true); if (gitRepo) scm.touch(gitRepo); ui.toast("Movido para a Lixeira"); }
    catch (e) { ui.error(e); }
  }
  const abs = (p: string) => (root.replace(/[\\/]$/, "") + "/" + p.replace(/\/$/, "")).replace(/\//g, root.includes("\\") ? "\\" : "/");
  async function copy(t: string, msg: string) { try { await navigator.clipboard.writeText(t); ui.toast(msg); } catch (e) { ui.error(e); } }
  function rowMenu(r: Row) {
    const at = dirOf(r.path, r.dir), d = decor.get(r.path);
    return [
      ...(!r.dir ? [{ label: "Abrir", onclick: () => onopen(r.path, undefined, { preview: false }) }] : []),
      ...(!r.dir && d && ondiff ? [{ label: "Abrir alterações", icon: GitCompareArrows, onclick: () => ondiff!(r.path) }] : []),
      { separator: true },
      { label: "Novo arquivo…", icon: FilePlus2, onclick: () => startNew("file", at) },
      { label: "Nova pasta…", icon: FolderPlus, onclick: () => startNew("folder", at) },
      { separator: true },
      { label: "Renomear…", icon: Pencil, kbd: "F2", onclick: () => startRename(r.path, r.dir) },
      { label: "Excluir", icon: Trash2, danger: true, onclick: () => remove(r.path, r.dir) },
      { separator: true },
      { label: "Copiar caminho", icon: Copy, onclick: () => copy(abs(r.path), "Caminho copiado") },
      { label: "Copiar caminho relativo", icon: Copy, onclick: () => copy(r.path.replace(/\/$/, ""), "Caminho relativo copiado") },
      { label: `Revelar no ${fileManagerName()}`, icon: FolderOpen, onclick: () => post("open", { path: abs(r.path), target: "files" }).catch(ui.error) },
      ...(onterminal ? [{ label: "Abrir no terminal integrado", icon: SquareTerminal, onclick: () => onterminal!(at.replace(/\/$/, "")) }] : []),
    ];
  }

  // ------------------------------------------------------------ busca no conteúdo
  function runSearch() {
    clearTimeout(sTimer);
    sTimer = setTimeout(async () => {
      if (!sq.trim()) { results = []; truncated = false; return; }
      searching = true;
      try { const r = await get<any>("ws/search", { repoId, taskId, q: sq, regex: sRegex ? 1 : 0, case: sCase ? 1 : 0 }); results = r.results; truncated = !!r.truncated; } catch (e) { ui.error(e); }
      searching = false;
    }, 250);
  }
  const grouped = $derived.by(() => {
    const m = new Map<string, typeof results>();
    for (const r of results) m.set(r.path, [...(m.get(r.path) || []), r]);
    return [...m.entries()];
  });
  let shut = $state<Record<string, boolean>>({});
  function hl(text: string, query: string) {
    const t = text.replace(/^\s+/, "");
    if (!query) return [{ s: t, m: false }];
    let re: RegExp;
    try { re = new RegExp(sRegex ? query : query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), sCase ? "g" : "gi"); } catch { return [{ s: t, m: false }]; }
    const out: { s: string; m: boolean }[] = [];
    let last = 0;
    for (const m of t.matchAll(re)) { if (!m[0]) break; out.push({ s: t.slice(last, m.index), m: false }, { s: m[0], m: true }); last = m.index! + m[0].length; }
    out.push({ s: t.slice(last), m: false });
    return out;
  }
</script>

{#snippet editor(depth: number)}
  <div class="n editing" style="--d:{depth}">
    <span class="sp"></span>
    <FileIcon name={edit?.kind === "folder" ? "pasta" : edit?.value || "arquivo"} dir={edit?.kind === "folder"} size={15} />
    <!-- svelte-ignore a11y_autofocus -->
    <input class="ren" autofocus bind:value={edit!.value} placeholder={edit?.kind === "folder" ? "nome da pasta" : edit?.kind === "file" ? "nome do arquivo (pode ter pastas/)" : ""}
      onkeydown={(e) => { if (e.key === "Enter") commitEdit(); else if (e.key === "Escape") edit = null; e.stopPropagation(); }} onblur={commitEdit}
      onfocus={(e) => { const i = (e.currentTarget as HTMLInputElement); const dot = i.value.lastIndexOf("."); i.setSelectionRange(0, dot > 0 ? dot : i.value.length); }} />
  </div>
{/snippet}

<div class="ft">
  {#if mode === "files"}
    <div class="bar">
      <label class="flt"><Search size={13} /><input bind:value={q} placeholder="Filtrar arquivos…" />{#if q}<button class="x" onclick={() => (q = "")}><X size={11} /></button>{/if}</label>
      <button class="ib" title="Novo arquivo" onclick={() => startNew("file", cursor ? dirOf(cursor, cursor.endsWith("/")) : "")}><FilePlus2 size={14} /></button>
      <button class="ib" title="Nova pasta" onclick={() => startNew("folder", cursor ? dirOf(cursor, cursor.endsWith("/")) : "")}><FolderPlus size={14} /></button>
      <button class="ib" title="Recarregar" onclick={() => { load(); if (gitRepo) scm.touch(gitRepo); }}><RefreshCw size={13} class={loading ? "spin" : ""} /></button>
      <button class="ib" title="Recolher todas as pastas" onclick={() => { open = {}; saveOpen(); }}><ChevronsDownUp size={14} /></button>
    </div>
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div class="list" bind:this={listEl} tabindex="0" role="tree" aria-label="Arquivos" onkeydown={onKey}>
      {#if edit && edit.at === "" && edit.kind !== "rename"}{@render editor(0)}{/if}
      {#if loading && !all.length}<div class="none">Carregando…</div>
      {:else if q.trim() && !matches.length}<div class="none">Nenhum arquivo com “{q}”.</div>
      {:else}
        {#each visible as r (r.path)}
          {@const d = r.dir ? null : decor.get(r.path)}
          {@const ft = r.dir ? fdecor.get(r.path) : null}
          {#if edit?.kind === "rename" && edit.path === r.path}{@render editor(r.depth)}
          {:else}
            <button class="n {d?.tone || ''} {ft ? 'f-' + ft : ''}" class:file={!r.dir} class:on={!r.dir && active === r.path} class:cur={cursor === r.path} class:del={d?.tone === "del"}
              style="--d:{r.depth}" data-p={r.path} role="treeitem" aria-selected={active === r.path} aria-expanded={r.dir ? !!open[r.path] : undefined}
              title={r.dir ? r.path : `${r.path}${d ? " · " + d.label : ""}`}
              onclick={() => { cursor = r.path; if (r.dir) toggleDir(r.path); else onopen(r.path, undefined, { preview: true }); }}
              ondblclick={() => { if (!r.dir) onopen(r.path, undefined, { preview: false }); }}
              oncontextmenu={(e) => { cursor = r.path; ui.contextMenu(e, rowMenu(r)); }}>
              {#if r.dir && !icons.hidesArrows}<ChevronRight size={12} class="chev {open[r.path] ? 'rot' : ''}" />{:else}<span class="sp"></span>{/if}
              <FileIcon name={r.dir ? r.path.slice(0, -1).split("/").pop() || r.name : r.name} dir={r.dir} open={!!open[r.path]} size={15} />
              <span class="nm ell">{#if q.trim()}<b>{r.name}</b> <span class="muted tiny">{r.path.split("/").slice(0, -1).join("/")}</span>{:else}{r.name}{/if}</span>
              {#if d}<span class="gl" title={d.label}>{d.letter}</span>{:else if ft}<span class="gd"></span>{/if}
            </button>
            {#if r.dir && open[r.path] && edit && edit.at === r.path && edit.kind !== "rename"}{@render editor(r.depth + 1)}{/if}
          {/if}
        {/each}
      {/if}
    </div>
  {:else}
    <div class="bar search">
      <label class="flt"><Search size={13} /><input bind:value={sq} oninput={runSearch} placeholder="Buscar no projeto…" />
        <button class="tg" class:on={sCase} title="Diferenciar maiúsculas" onclick={() => { sCase = !sCase; runSearch(); }}><CaseSensitive size={14} /></button>
        <button class="tg" class:on={sRegex} title="Expressão regular" onclick={() => { sRegex = !sRegex; runSearch(); }}><Regex size={13} /></button>
        {#if searching}<RefreshCw size={12} class="spin" />{/if}</label>
    </div>
    {#if results.length}<div class="sum tiny muted">{results.length}{truncated ? "+" : ""} resultado{results.length === 1 ? "" : "s"} em {grouped.length} arquivo{grouped.length === 1 ? "" : "s"}</div>{/if}
    <div class="list">
      {#each grouped as [path, hits] (path)}
        {@const d = decor.get(path)}
        <button class="grp {d?.tone || ''}" onclick={() => (shut = { ...shut, [path]: !shut[path] })}>
          <ChevronRight size={12} class="chev {shut[path] ? '' : 'rot'}" />
          <FileIcon name={path.split("/").pop() || path} size={14} />
          <span class="ell"><b>{path.split("/").pop()}</b> <span class="muted tiny">{path.split("/").slice(0, -1).join("/")}</span></span><span class="cnt">{hits.length}</span>
        </button>
        {#if !shut[path]}
          {#each hits as h (h.line + ":" + h.col)}
            <button class="hit" onclick={() => onopen(h.path, h.line, { preview: true })} ondblclick={() => onopen(h.path, h.line, { preview: false })}>
              <span class="ln">{h.line}</span><span class="ell mono">{#each hl(h.text, sq) as part, i (i)}{#if part.m}<mark>{part.s}</mark>{:else}{part.s}{/if}{/each}</span></button>
          {/each}
        {/if}
      {:else}<div class="none">{sq ? (searching ? "Buscando…" : "Nada encontrado.") : "Digite para buscar no conteúdo dos arquivos."}</div>{/each}
    </div>
  {/if}
</div>

<style>
  .ft { display: flex; flex-direction: column; min-height: 0; height: 100%; }
  .bar { display: flex; align-items: center; gap: 2px; padding: 6px 8px; }
  .flt { flex: 1; display: flex; align-items: center; gap: 6px; height: 27px; padding: 0 6px 0 8px; border-radius: 7px; border: 1px solid var(--line-2);
    background: var(--bg-2); color: var(--muted); min-width: 0; margin-right: 2px; }
  .flt:focus-within { border-color: var(--accent); }
  .flt input { flex: 1; min-width: 0; border: 0; outline: none; background: none; color: var(--text); font: 12.5px var(--font); }
  .x { display: grid; place-items: center; width: 16px; height: 16px; border: 0; border-radius: 50%; background: var(--surface-3); color: var(--text-2); cursor: pointer; }
  .ib { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; flex: none; }
  .ib:hover { background: var(--surface-3); color: var(--text); }
  .tg { display: grid; place-items: center; width: 22px; height: 20px; border: 1px solid transparent; border-radius: 5px; background: none; color: var(--muted); cursor: pointer; flex: none; }
  .tg:hover { color: var(--text); }
  .tg.on { color: var(--accent); background: var(--accent-soft); border-color: var(--accent-line); }
  .list { flex: 1; overflow: auto; padding: 0 4px 10px; outline: none; }
  .list:focus-visible .n.cur { box-shadow: inset 0 0 0 1px var(--accent); }
  .n { --d: 0; position: relative; display: flex; align-items: center; gap: 5px; width: 100%; height: 22px; padding: 0 6px 0 calc(4px + var(--d) * 12px); border: 0; border-radius: 5px;
    background: none; color: var(--text-2); font: 12.5px var(--font); text-align: left; cursor: pointer; }
  /* guias de indentação, como no VS Code */
  .n::before { content: ""; position: absolute; top: 0; bottom: 0; left: 10px; width: calc(var(--d) * 12px);
    background: repeating-linear-gradient(90deg, var(--line) 0 1px, transparent 1px 12px); pointer-events: none; }
  .n:hover { background: var(--surface-2); color: var(--text); }
  .n.cur { background: var(--surface-2); }
  .n.on { background: var(--accent-soft); color: var(--text); }
  .n :global(.chev) { color: var(--faint); flex: none; transition: transform var(--t) var(--ease); }
  .n :global(.chev.rot) { transform: rotate(90deg); }
  .nm { flex: 1; min-width: 0; }
  .sp { width: 12px; flex: none; }
  .gl { font: 650 10.5px/1 var(--mono); flex: none; width: 12px; text-align: center; }
  .gd { width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: 0.8; flex: none; margin-right: 3px; }
  /* cores do Git (iguais às do VS Code escuro/claro) */
  .n.mod, .grp.mod, .n.f-mod { color: #e2c08d; } .n.add, .grp.add, .n.f-add { color: #73c991; } .n.del, .grp.del { color: #e5717d; }
  .n.ren, .n.f-ren { color: #73c991; } .n.conf, .n.f-conf { color: #e5717d; }
  :global([data-theme="light"]) .n.mod, :global([data-theme="light"]) .n.f-mod, :global([data-theme="light"]) .grp.mod { color: #a26a00; }
  :global([data-theme="light"]) .n.add, :global([data-theme="light"]) .n.f-add, :global([data-theme="light"]) .n.ren, :global([data-theme="light"]) .grp.add { color: #2f8a4a; }
  :global([data-theme="light"]) .n.del, :global([data-theme="light"]) .n.conf, :global([data-theme="light"]) .grp.del { color: #c4314b; }
  .n.del .nm { text-decoration: line-through; opacity: 0.85; }
  .n.f-mod .gd, .n.f-add .gd, .n.f-conf .gd { opacity: 0.7; }
  .editing { cursor: default; background: var(--surface-2); }
  .ren { flex: 1; min-width: 0; height: 20px; border: 1px solid var(--accent); border-radius: 4px; outline: none; background: var(--bg-2); color: var(--text);
    font: 12.5px var(--font); padding: 0 5px; }
  .none { padding: 10px; font-size: 12px; color: var(--muted); }
  .sum { padding: 0 12px 4px; }
  .grp { display: flex; align-items: center; gap: 5px; width: 100%; padding: 4px 6px 2px; border: 0; background: none; font: 12.5px var(--font); color: var(--text-2);
    cursor: pointer; text-align: left; border-radius: 5px; }
  .grp:hover { background: var(--surface-2); }
  .grp :global(.chev) { color: var(--faint); flex: none; transition: transform var(--t) var(--ease); }
  .grp :global(.chev.rot) { transform: rotate(90deg); }
  .grp .ell { flex: 1; min-width: 0; }
  .cnt { font: 600 10.5px/1 var(--font); color: var(--text-2); background: var(--surface-3); padding: 2px 6px; border-radius: 99px; }
  .hit { display: flex; gap: 8px; width: 100%; padding: 2px 6px 2px 30px; border: 0; border-radius: 5px; background: none; color: var(--text-2);
    font: 12px var(--font); text-align: left; cursor: pointer; }
  .hit:hover { background: var(--surface-2); color: var(--text); }
  .hit mark { background: rgba(234, 179, 8, 0.28); color: var(--text); border-radius: 2px; outline: 1px solid rgba(234, 179, 8, 0.45); }
  .ln { color: var(--faint); font: 11px var(--mono); min-width: 26px; text-align: right; flex: none; }
</style>
