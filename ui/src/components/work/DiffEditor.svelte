<script lang="ts">
  // "Abrir alterações" (como no VS Code): o arquivo como está no índice/último commit × como está agora.
  //   · não preparado: índice × árvore de trabalho — o lado direito é o MESMO documento do editor (edita e salva com ⌘S);
  //   · preparado: último commit × índice (só leitura).
  // Lado a lado ou em linha, setas para a alteração anterior/seguinte, preparar/despreparar e abrir o arquivo.
  import { ArrowDown, ArrowUp, Columns2, FileText, Minus, Plus, Rows2, RotateCcw } from "@lucide/svelte";
  import type * as Monaco from "monaco-editor";
  import { get, post } from "../../lib/api";
  import { loadMonaco, monacoTheme, onThemeChange } from "../../lib/monaco";
  import { prefs } from "../../lib/prefs.svelte";
  import { scm } from "../../lib/scm.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { dirty, docs, keyOf, loadDoc, saveDoc } from "./Editor.svelte";
  import FileIcon from "./FileIcon.svelte";

  let { repoId, taskId = null, gitRepo, path, staged = false, onopen }:
    { repoId: string; taskId?: string | null; gitRepo: string; path: string; staged?: boolean; onopen?: (path: string) => void } = $props();
  let host: HTMLDivElement | undefined = $state();
  let diff: Monaco.editor.IStandaloneDiffEditor | null = null;
  let monaco: typeof Monaco | null = null;
  let inline = $state((() => { try { return localStorage.getItem("codeck.diff.inline") === "1"; } catch { return false; } })());
  let note = $state<string | null>(null);
  let stats = $state({ add: 0, del: 0, changes: 0 });
  const relP = $derived(path);
  const stagedP = $derived(staged);
  let seq = 0;

  async function show() {
    if (!diff || !monaco) return;
    const n = ++seq, rel = relP, isStaged = stagedP;
    note = null;
    try {
      const orig = await get<{ text: string; exists: boolean; binary?: boolean }>("ws/base", { repoId, taskId, path: rel, ref: isStaged ? "HEAD" : "INDEX" });
      let modified: Monaco.editor.ITextModel;
      if (isStaged) {
        const idx = await get<{ text: string; exists: boolean }>("ws/base", { repoId, taskId, path: rel, ref: "INDEX" });
        modified = monaco.editor.createModel(idx.text, undefined, monaco.Uri.parse(`cdidx:///${n}/${rel}`));
      } else {
        const d = await loadDoc(monaco, repoId, taskId, rel).catch(() => null);
        if (!d || "note" in d) {
          // apagado no disco: compara com vazio
          modified = monaco.editor.createModel("", undefined, monaco.Uri.parse(`cdgone:///${n}/${rel}`));
          if (d && "note" in d) note = d.note;
        } else modified = d.model;
      }
      if (orig.binary) note = "Arquivo binário — sem diff de texto.";
      if (n !== seq || !diff) return;
      const lang = modified.getLanguageId();
      const original = monaco.editor.createModel(orig.text, lang, monaco.Uri.parse(`cdbase:///${n}/${rel}`));
      const old = diff.getModel();
      diff.setModel({ original, modified });
      diff.getModifiedEditor().updateOptions({ readOnly: isStaged || modified.uri.scheme !== "file" });
      // libera os modelos temporários antigos (o documento do editor fica)
      old?.original.dispose();
      if (old && old.modified.uri.scheme !== "file") old.modified.dispose();
      setTimeout(() => { if (n === seq) diff?.revealFirstDiff(); }, 80);
    } catch (e: any) { note = e.message; }
  }
  function count() {
    const ch = diff?.getLineChanges() || [];
    let add = 0, del = 0;
    for (const c of ch) {
      if (c.modifiedEndLineNumber >= c.modifiedStartLineNumber && c.modifiedEndLineNumber > 0) add += c.modifiedEndLineNumber - c.modifiedStartLineNumber + 1;
      if (c.originalEndLineNumber >= c.originalStartLineNumber && c.originalEndLineNumber > 0) del += c.originalEndLineNumber - c.originalStartLineNumber + 1;
    }
    stats = { add, del, changes: ch.length };
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
      diff = m.editor.createDiffEditor(host, { automaticLayout: true, theme: monacoTheme(), renderSideBySide: !inline, originalEditable: false,
        renderMarginRevertIcon: true, ignoreTrimWhitespace: false, fontSize: fs, lineHeight: Math.round(fs * 1.54),
        fontFamily: (fam ? `"${fam.replace(/"/g, "")}", ` : "") + '"JetBrains Mono Variable", ui-monospace, Menlo, monospace', fontLigatures: !!prefs.get("editor.ligatures"),
        minimap: { enabled: false }, scrollBeyondLastLine: false, renderOverviewRuler: true, fixedOverflowWidgets: true, useInlineViewWhenSpaceIsLimited: true,
        hideUnchangedRegions: { enabled: true, contextLineCount: 4, minimumLineCount: 6 } });
      diff.getModifiedEditor().addCommand(m.KeyMod.CtrlCmd | m.KeyCode.KeyS, async () => {
        const d = docs.get(keyOf(repoId, taskId, relP));
        if (!d) return;
        try { await saveDoc(d); ui.toast(`${relP.split("/").pop()} salvo`); scm.touch(gitRepo); } catch (e) { ui.error(e); }
      });
      subs.push(diff.onDidUpdateDiff(count), onThemeChange(() => monaco?.editor.setTheme(monacoTheme())));
      show();
    });
    return () => {
      dead = true;
      for (const s of subs) s.dispose();
      const md = diff?.getModel();
      diff?.dispose(); diff = null;
      md?.original.dispose();
      if (md && md.modified.uri.scheme !== "file") md.modified.dispose();
    };
  });
  $effect(() => { void relP; void stagedP; if (diff) show(); });
  $effect(() => { const i = inline; diff?.updateOptions({ renderSideBySide: !i }); try { localStorage.setItem("codeck.diff.inline", i ? "1" : "0"); } catch { /* */ } });

  // relê o lado de base quando o Git muda (stage/commit) — o lado do arquivo já acompanha o disco pelo editor
  const sig = $derived(JSON.stringify(scm.status[gitRepo]?.staged || []) + (scm.status[gitRepo]?.head || ""));
  let lastSig = "";
  $effect(() => { const s = sig; if (lastSig && s !== lastSig) show(); lastSig = s; });

  const nav = (dir: 1 | -1) => (diff as any)?.goToDiff?.(dir > 0 ? "next" : "previous");
  async function stage(on: boolean) {
    try { await post("repo/" + (on ? "stage" : "unstage"), { id: gitRepo, paths: [relP] }); ui.toast(on ? "Preparado" : "Despreparado"); }
    catch (e) { ui.error(e); }
    scm.touch(gitRepo);
  }
  async function discard() {
    if (!(await ui.ask({ title: `Descartar as alterações em ${relP.split("/").pop()}?`, message: "Voltam ao último commit.", confirm: "Descartar", danger: true }))) return;
    try { await post("repo/discard", { id: gitRepo, paths: [relP] }); ui.toast("Alterações descartadas"); } catch (e) { ui.error(e); }
    scm.touch(gitRepo);
  }
  const k = $derived(keyOf(repoId, taskId, relP));
</script>

<div class="dv">
  <div class="bar">
    <FileIcon name={relP.split("/").pop() || relP} size={14} />
    <span class="ttl ell"><b>{relP.split("/").pop()}</b> <span class="muted">{stagedP ? "(preparado)" : "(árvore de trabalho)"}</span>
      <span class="tiny muted">{relP.split("/").slice(0, -1).join("/")}</span></span>
    {#if dirty[k]}<span class="pill warn tiny">não salvo</span>{/if}
    <span class="st"><b class="a">+{stats.add}</b> <b class="d">−{stats.del}</b></span>
    <button class="ib" title="Alteração anterior" onclick={() => nav(-1)}><ArrowUp size={14} /></button>
    <button class="ib" title="Próxima alteração" onclick={() => nav(1)}><ArrowDown size={14} /></button>
    <button class="ib" title={inline ? "Lado a lado" : "Em linha"} onclick={() => (inline = !inline)}>{#if inline}<Columns2 size={14} />{:else}<Rows2 size={14} />{/if}</button>
    <span class="sepv"></span>
    {#if stagedP}<button class="ib" title="Despreparar" onclick={() => stage(false)}><Minus size={14} /></button>
    {:else}<button class="ib" title="Descartar alterações" onclick={discard}><RotateCcw size={13} /></button>
      <button class="ib" title="Preparar (stage)" onclick={() => stage(true)}><Plus size={14} /></button>{/if}
    {#if onopen}<button class="ib" title="Abrir arquivo" onclick={() => onopen!(relP)}><FileText size={14} /></button>{/if}
  </div>
  <div class="body">
    {#if note}<div class="note">{note}</div>{/if}
    <div class="host" bind:this={host}></div>
  </div>
</div>

<style>
  .dv { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--ed-bg, var(--surface)); }
  .bar { display: flex; align-items: center; gap: 4px; height: 30px; padding: 0 8px 0 12px; border-bottom: 1px solid var(--line); flex: none; font-size: 12.5px; }
  .ttl { flex: 1; min-width: 0; display: flex; align-items: baseline; gap: 6px; }
  .st { font: 600 11.5px var(--mono); margin-right: 4px; }
  .st .a { color: var(--good); } .st .d { color: var(--bad); }
  .ib { display: grid; place-items: center; width: 26px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; }
  .ib:hover { background: var(--surface-3); color: var(--text); }
  .sepv { width: 1px; height: 16px; background: var(--line-2); margin: 0 3px; }
  .body { position: relative; flex: 1; min-height: 0; }
  .host { position: absolute; inset: 0; }
  .note { position: absolute; z-index: 3; top: 8px; left: 50%; transform: translateX(-50%); padding: 6px 12px; border-radius: 8px; background: var(--surface-3); color: var(--text-2); font-size: 12.5px; }
</style>
