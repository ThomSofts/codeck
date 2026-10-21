<script lang="ts" module>
  export type PrFile = { path: string; oldPath?: string | null; status: string; add: number | null; del: number | null; binary?: boolean };
  export type PrFileList = { files: PrFile[]; base: string | null; head: string | null; total: number; additions?: number; deletions?: number };
</script>

<script lang="ts">
  // Diff de um arquivo da PR (Monaco, só leitura): a base do merge à esquerda, a cabeça da PR à direita. A lista dos
  // arquivos fica ao lado; ↑/↓ (ou J/K) troca de arquivo, as setas da barra pulam entre as alterações.
  import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Columns2, Rows2 } from "@lucide/svelte";
  import type * as Monaco from "monaco-editor";
  import { get } from "../../lib/api";
  import { loadMonaco, monacoTheme, onThemeChange } from "../../lib/monaco";
  import { prefs } from "../../lib/prefs.svelte";
  import type { PR } from "../../lib/types";
  import Drawer from "../Drawer.svelte";
  import FileIcon from "../work/FileIcon.svelte";

  let { pr, files, base, head, index = $bindable(0), onclose, oncount }:
    { pr: PR; files: PrFile[]; base: string | null; head: string | null; index?: number; onclose: () => void;
      oncount?: (path: string, c: { add: number; del: number }) => void } = $props();

  type Pair = { original: string; modified: string; binary: boolean; tooBig: boolean; existsBefore: boolean; existsAfter: boolean };
  const cache = new Map<string, Promise<Pair>>();
  const fetchPair = (f: PrFile) => {
    const k = f.path;
    if (!cache.has(k)) {
      const p = get<Pair>("pr/file", { key: pr.key, path: f.path, oldPath: f.oldPath || undefined, base, head });
      p.catch(() => cache.delete(k));
      cache.set(k, p);
    }
    return cache.get(k)!;
  };

  let host: HTMLDivElement | undefined = $state();
  let diff: Monaco.editor.IStandaloneDiffEditor | null = null;
  let monaco: typeof Monaco | null = null;
  let inline = $state((() => { try { return localStorage.getItem("codeck.diff.inline") === "1"; } catch { return false; } })());
  let note = $state<string | null>(null);
  let loading = $state(true);
  let stats = $state({ add: 0, del: 0 });
  const cur = $derived(files[index]);
  let seq = 0;

  async function show() {
    if (!diff || !monaco || !cur) return;
    const n = ++seq, f = cur;
    loading = true;
    note = null;
    try {
      const r = await fetchPair(f);
      if (n !== seq || !diff || !monaco) return;
      if (r.binary) note = "Arquivo binário — sem diff de texto.";
      else if (r.tooBig) note = "Arquivo grande demais para mostrar aqui — abra a PR no navegador.";
      const original = monaco.editor.createModel(r.original, undefined, monaco.Uri.parse(`cdprbase:///${n}/${f.oldPath || f.path}`));
      const modified = monaco.editor.createModel(r.modified, original.getLanguageId(), monaco.Uri.parse(`cdprhead:///${n}/${f.path}`));
      const old = diff.getModel();
      diff.setModel({ original, modified });
      old?.original.dispose();
      old?.modified.dispose();
      // abre já no primeiro trecho alterado (os modelos podem demorar um instante para calcular)
      setTimeout(() => { if (n === seq) diff?.revealFirstDiff(); }, 120);
      // Azure não informa +/- e prefetch do próximo: navegar fica instantâneo
      const nx = files[index + 1];
      if (nx) fetchPair(nx).catch(() => {});
    } catch (e: any) { if (n === seq) note = e.message || String(e); }
    if (n === seq) loading = false;
  }
  function count() {
    const ch = diff?.getLineChanges() || [];
    let add = 0, del = 0;
    for (const c of ch) {
      if (c.modifiedEndLineNumber >= c.modifiedStartLineNumber && c.modifiedEndLineNumber > 0) add += c.modifiedEndLineNumber - c.modifiedStartLineNumber + 1;
      if (c.originalEndLineNumber >= c.originalStartLineNumber && c.originalEndLineNumber > 0) del += c.originalEndLineNumber - c.originalStartLineNumber + 1;
    }
    stats = { add, del };
    if (cur && cur.add == null && !loading) oncount?.(cur.path, stats);
  }

  $effect(() => {
    if (!host) return;
    let dead = false;
    const subs: Monaco.IDisposable[] = [];
    loadMonaco().then(m => {
      if (dead || !host) return;
      monaco = m;
      const fs = Number(prefs.get("editor.fontSize")) || 13;
      const fam = String(prefs.get("editor.fontFamily") || "").trim();
      diff = m.editor.createDiffEditor(host, { automaticLayout: true, theme: monacoTheme(), renderSideBySide: !inline, readOnly: true, originalEditable: false,
        ignoreTrimWhitespace: false, fontSize: fs, lineHeight: Math.round(fs * 1.54), renderMarginRevertIcon: false,
        fontFamily: (fam ? `"${fam.replace(/"/g, "")}", ` : "") + '"JetBrains Mono Variable", ui-monospace, Menlo, monospace', fontLigatures: !!prefs.get("editor.ligatures"),
        minimap: { enabled: false }, scrollBeyondLastLine: false, renderOverviewRuler: true, fixedOverflowWidgets: true, useInlineViewWhenSpaceIsLimited: true,
        hideUnchangedRegions: { enabled: true, contextLineCount: 4, minimumLineCount: 6 } });
      subs.push(diff.onDidUpdateDiff(count), onThemeChange(() => monaco?.editor.setTheme(monacoTheme())));
      show();
    });
    return () => {
      dead = true;
      for (const s of subs) s.dispose();
      const md = diff?.getModel();
      diff?.dispose(); diff = null;
      md?.original.dispose(); md?.modified.dispose();
    };
  });
  $effect(() => { void cur; if (diff) show(); });
  $effect(() => { const i = inline; diff?.updateOptions({ renderSideBySide: !i }); try { localStorage.setItem("codeck.diff.inline", i ? "1" : "0"); } catch { /* */ } });

  const nav = (dir: 1 | -1) => (diff as any)?.goToDiff?.(dir > 0 ? "next" : "previous");
  const step = (d: number) => { const i = Math.max(0, Math.min(files.length - 1, index + d)); if (i !== index) index = i; };
  function onKey(e: KeyboardEvent) {
    if ((e.target as HTMLElement)?.closest?.("input, textarea, .monaco-editor")) return;
    if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); step(-1); }
  }
  let listEl: HTMLDivElement | undefined = $state();
  $effect(() => { void index; listEl?.querySelector(".sel")?.scrollIntoView({ block: "nearest" }); });
  const CODE: Record<string, string> = { A: "good", D: "bad", M: "warn", R: "info", C: "info" };
</script>

<svelte:window onkeydown={onKey} />

<Drawer title={`#${pr.prId} · ${pr.title}`} subtitle={`${pr.source} → ${pr.target} · ${files.length} arquivo${files.length === 1 ? "" : "s"}`} {onclose} width={1360}>
  <div class="pd">
    <div class="side" bind:this={listEl}>
      {#each files as f, i (f.path)}
        <button class="f" class:sel={i === index} onclick={() => (index = i)} title={f.path}>
          <FileIcon name={f.path.split("/").pop() || f.path} size={13} />
          <span class="ell grow">{f.path.split("/").pop()}<span class="dir"> {f.path.split("/").slice(0, -1).join("/")}</span></span>
          <span class="code {CODE[f.status] || 'warn'}">{f.status}</span>
        </button>
      {/each}
    </div>
    <div class="main">
      <div class="bar">
        {#if cur}<FileIcon name={cur.path.split("/").pop() || cur.path} size={14} />
          <span class="ttl ell"><b>{cur.path.split("/").pop()}</b>
            <span class="tiny muted">{cur.oldPath && cur.oldPath !== cur.path ? `${cur.oldPath} → ` : ""}{cur.path.split("/").slice(0, -1).join("/")}</span></span>{/if}
        {#if loading}<span class="shim ld"></span>{/if}
        <span class="st"><b class="a">+{stats.add}</b> <b class="d">−{stats.del}</b></span>
        <button class="ib" title="Alteração anterior" onclick={() => nav(-1)}><ArrowUp size={14} /></button>
        <button class="ib" title="Próxima alteração" onclick={() => nav(1)}><ArrowDown size={14} /></button>
        <button class="ib" title={inline ? "Lado a lado" : "Em linha"} onclick={() => (inline = !inline)}>{#if inline}<Columns2 size={14} />{:else}<Rows2 size={14} />{/if}</button>
        <span class="sepv"></span>
        <button class="ib" title="Arquivo anterior (↑ / K)" disabled={index <= 0} onclick={() => step(-1)}><ChevronLeft size={15} /></button>
        <span class="tiny muted pos">{index + 1}/{files.length}</span>
        <button class="ib" title="Próximo arquivo (↓ / J)" disabled={index >= files.length - 1} onclick={() => step(1)}><ChevronRight size={15} /></button>
      </div>
      <div class="body" class:dim={loading}>
        {#if note}<div class="note">{note}</div>{/if}
        <div class="host" bind:this={host}></div>
      </div>
    </div>
  </div>
</Drawer>

<style>
  .pd { display: grid; grid-template-columns: 260px minmax(0, 1fr); height: calc(100vh - 110px); margin: 0 -20px -24px; border-top: 1px solid var(--line); }
  @media (max-width: 900px) { .pd { grid-template-columns: minmax(0, 1fr); } .side { display: none; } }
  .side { overflow: auto; border-right: 1px solid var(--line); padding: 4px 0; overscroll-behavior: contain; }
  .f { display: flex; align-items: center; gap: 7px; width: 100%; padding: 5px 10px; border: 0; background: none; color: var(--text-2); font: 12.5px var(--font);
    text-align: left; cursor: pointer; transition: background var(--t-fast), color var(--t-fast); }
  .f:hover { background: var(--surface-2); color: var(--text); }
  .f.sel { background: var(--accent-soft); color: var(--text); }
  .dir { color: var(--muted); font-size: 11px; }
  .code { font: 700 10.5px var(--mono); }
  .code.good { color: var(--good); } .code.bad { color: var(--bad); } .code.warn { color: var(--warn); } .code.info { color: var(--info); }
  .main { display: flex; flex-direction: column; min-width: 0; min-height: 0; background: var(--ed-bg, var(--surface)); }
  .bar { display: flex; align-items: center; gap: 4px; height: 32px; padding: 0 8px 0 12px; border-bottom: 1px solid var(--line); flex: none; font-size: 12.5px; }
  .ttl { flex: 1; min-width: 0; display: flex; align-items: baseline; gap: 6px; }
  .ld { width: 60px; height: 6px; border-radius: 3px; }
  .st { font: 600 11.5px var(--mono); margin: 0 4px; }
  .st .a { color: var(--good); } .st .d { color: var(--bad); }
  .ib { display: grid; place-items: center; width: 26px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; }
  .ib:hover:not(:disabled) { background: var(--surface-3); color: var(--text); }
  .ib:disabled { opacity: 0.35; cursor: default; }
  .pos { font-variant-numeric: tabular-nums; min-width: 36px; text-align: center; }
  .sepv { width: 1px; height: 16px; background: var(--line-2); margin: 0 3px; }
  .body { position: relative; flex: 1; min-height: 0; transition: opacity var(--t-fast); }
  .body.dim { opacity: 0.55; }
  .host { position: absolute; inset: 0; }
  .note { position: absolute; z-index: 3; top: 8px; left: 50%; transform: translateX(-50%); padding: 6px 12px; border-radius: 8px; background: var(--surface-3); color: var(--text-2);
    font-size: 12.5px; animation: fade 0.2s var(--ease); }
</style>
