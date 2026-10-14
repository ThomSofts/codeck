<script lang="ts" module>
  // Um editor Monaco por tela; cada arquivo aberto é um "model" (com o próprio desfazer e posição do cursor).
  // O agente edita os mesmos arquivos no disco: se o arquivo não tem alteração sua, ele é recarregado sozinho;
  // se tem, o salvar avisa que o disco mudou (nunca sobrescreve em silêncio).
  // O mesmo modelo serve o editor e o diff ("Abrir alterações"): editar num aparece no outro.
  import type * as Monaco from "monaco-editor";
  import { get as apiGet, post as apiPost } from "../../lib/api";
  import { attach } from "../../lib/lsp";
  import { modelUri } from "../../lib/editorstate.svelte";
  export type Doc = { model: Monaco.editor.ITextModel; mtime: number; saved: number; view: Monaco.editor.ICodeEditorViewState | null; root: string;
    repoId: string; taskId: string | null; rel: string };
  export const docs = new Map<string, Doc>();
  export const dirty = $state<Record<string, boolean>>({});
  export const keyOf = (repoId: string, taskId: string | null | undefined, path: string) => `${repoId}:${taskId || ""}:${path}`;
  export function forget(key: string) { docs.get(key)?.model.dispose(); docs.delete(key); delete dirty[key]; mdModes.delete(key); }
  /** Markdown: como cada arquivo está sendo visto nesta sessão (pré-visualização, código ou lado a lado) */
  type MdMode = "preview" | "code" | "split";
  const mdModes = new Map<string, MdMode>();
  const lspStatus = new Map<string, (s: string) => void>();

  /** Abre (ou reaproveita) o documento de um arquivo do projeto. Binário/grande demais: devolve a explicação. */
  export async function loadDoc(monaco: typeof Monaco, repoId: string, taskId: string | null, rel: string): Promise<Doc | { note: string }> {
    const k = keyOf(repoId, taskId, rel);
    const ex = docs.get(k);
    if (ex) return ex;
    const f = await apiGet<any>("ws/file", { repoId, taskId, path: rel });
    if (f.binary || f.tooLarge) return { note: f.binary ? "Arquivo binário — não dá para editar aqui." : `Arquivo grande demais (${Math.round(f.size / 1e6)} MB).` };
    if (docs.has(k)) return docs.get(k)!;   // outro editor abriu enquanto este lia
    const uri = monaco.Uri.parse(modelUri(repoId, taskId, rel));
    const model = monaco.editor.getModel(uri) || monaco.editor.createModel(f.text, undefined, uri);
    if (f.crlf) model.setEOL(monaco.editor.EndOfLineSequence.CRLF);
    const d: Doc = { model, mtime: f.mtime, saved: model.getAlternativeVersionId(), view: null, root: f.root, repoId, taskId, rel };
    model.onDidChangeContent(() => { dirty[k] = model.getAlternativeVersionId() !== d.saved; });
    docs.set(k, d);
    attach(monaco, model, { repoId, taskId, root: f.root, rel }, s => lspStatus.get(k)?.(s));
    return d;
  }
  /** Grava o documento. `force` sobrescreve mesmo se o disco mudou (depois de perguntar). */
  export async function saveDoc(d: Doc, force = false) {
    const k = keyOf(d.repoId, d.taskId, d.rel);
    const r = await apiPost<{ mtime: number }>("ws/file", { repoId: d.repoId, taskId: d.taskId, path: d.rel, text: d.model.getValue(), mtime: force ? undefined : d.mtime });
    d.mtime = r.mtime;
    d.saved = d.model.getAlternativeVersionId();
    dirty[k] = false;
  }
</script>

<script lang="ts">
  import { ChevronRight } from "@lucide/svelte";
  import { kbd } from "../../lib/keys";
  import { gotoDefinition, openInApp } from "../../lib/lsp";
  import { loadMonaco, monacoTheme, onThemeChange } from "../../lib/monaco";
  import { lineHunks } from "../../lib/linediff";
  import { edState, trackMarkers } from "../../lib/editorstate.svelte";
  import { prefs } from "../../lib/prefs.svelte";
  import { scm } from "../../lib/scm.svelte";
  import { ui } from "../../lib/ui.svelte";
  import FileIcon from "./FileIcon.svelte";
  import MarkdownView from "./MarkdownView.svelte";
  import { scanTasks } from "./md/render";

  let { repoId, taskId = null, gitRepo = null, path, line = 0, onreveal, onpin }:
    { repoId: string; taskId?: string | null; gitRepo?: string | null; path: string; line?: number; onreveal?: (dir: string) => void; onpin?: () => void } = $props();
  let host: HTMLDivElement | undefined = $state();
  let editor: Monaco.editor.IStandaloneCodeEditor | null = null;
  let monaco: typeof Monaco | null = null;
  let note = $state<string | null>(null);
  let loading = $state(true);
  let lsp = $state("");
  const key = $derived(keyOf(repoId, taskId, path));
  // props são lidas de novo a cada leitura do /api/ws (2,5 s): os efeitos dependem destes valores primitivos, que só
  // avisam quando mudam de fato — senão o editor reabria o arquivo, voltava para a linha e roubava o foco a cada ciclo
  const relP = $derived(path);
  const lineP = $derived(line || 0);

  // ------------------------------------------------------------ Markdown: pré-visualização com tarefas clicáveis
  const isMd = $derived(/\.(md|markdown|mdx)$/i.test(relP));
  let mdMode = $state<MdMode>("preview");
  let lastView: MdMode = "preview";
  $effect(() => {
    const k = key;
    if (!isMd) return;
    mdMode = mdModes.get(k) || (prefs.get("md.mode") as MdMode) || "preview";
    if (mdMode !== "code") lastView = mdMode;
  });
  function setMd(m: MdMode) {
    if (m !== "code") lastView = m;
    mdMode = m;
    mdModes.set(key, m);
    if (m !== "preview") requestAnimationFrame(() => { editor?.layout(); editor?.focus(); });
  }
  const toggleMd = () => setMd(mdMode === "code" ? lastView : "code");
  let mdText = $state("");
  let mdTimer: ReturnType<typeof setTimeout> | undefined;
  let mdSub: Monaco.IDisposable | null = null;
  function watchMd(d: Doc | null) {
    mdSub?.dispose();
    mdSub = null;
    clearTimeout(mdTimer);
    if (!d || !isMd) return;
    mdText = d.model.getValue();
    mdSub = d.model.onDidChangeContent(() => { clearTimeout(mdTimer); mdTimer = setTimeout(() => (mdText = d.model.getValue()), 150); });
  }
  /** Marcou/desmarcou a N-ésima tarefa: troca o [ ]/[x] na linha certa (desfazível) e salva se não havia edição sua. */
  async function toggleTask(i: number, done: boolean) {
    const d = docs.get(key);
    if (!d || !monaco) return;
    const t = scanTasks(d.model.getValue())[i];
    if (!t) return;
    const wasDirty = !!dirty[key];
    d.model.pushEditOperations([], [{ range: new monaco.Range(t.line, t.col, t.line, t.col + 1), text: done ? "x" : " " }], () => null);
    mdText = d.model.getValue();
    if (!wasDirty) await save(true);
  }

  async function save(quiet = false) {
    const d = docs.get(key);
    if (!d || !editor) return;
    try {
      if (prefs.get("editor.formatOnSave") && !quiet) await editor.getAction("editor.action.formatDocument")?.run().catch(() => {});
      await saveDoc(d);
      if (!quiet) ui.toast(`${relP.split("/").pop()} salvo`);
      scm.touch(gitRepo);
    } catch (e: any) {
      if (/mudou no disco/.test(e.message || "") && await ui.ask({ title: "O arquivo mudou no disco", message: "Alguém (provavelmente o agente) editou este arquivo depois que você abriu. Sobrescrever com a sua versão?", confirm: "Sobrescrever", danger: true })) {
        await saveDoc(d, true).catch(ui.error);
        scm.touch(gitRepo);
      } else ui.error(e);
    }
  }

  // o arquivo aberto e sem alteração sua acompanha o disco (o agente editando aparece ao vivo)
  async function syncFromDisk() {
    const k = key, d = docs.get(k);
    if (!d || dirty[k] || document.hidden) return;
    try {
      const f = await apiGet<any>("ws/file", { repoId, taskId, path: relP });
      if (f.text !== undefined && f.mtime !== d.mtime && f.text !== d.model.getValue()) {
        const view = editor?.saveViewState();
        d.model.pushEditOperations([], [{ range: d.model.getFullModelRange(), text: f.text }], () => null);
        d.saved = d.model.getAlternativeVersionId();
        dirty[k] = false;
        if (view) editor?.restoreViewState(view);
      }
      d.mtime = f.mtime ?? d.mtime;
    } catch { /* arquivo apagado ou fora do ar: deixa como está */ }
  }

  // ------------------------------------------------------------ marcas do Git na margem (como o VS Code)
  let base: { key: string; text: string; exists: boolean } | null = null;
  let gutter: Monaco.editor.IEditorDecorationsCollection | null = null;
  let gutTimer: ReturnType<typeof setTimeout> | undefined;
  async function loadBase() {
    const k = key;
    if (!prefs.get("editor.gitGutter")) { base = null; paintGutter(); return; }
    try {
      const r = await apiGet<{ text: string; exists: boolean; binary?: boolean; tooLarge?: boolean }>("ws/base", { repoId, taskId, path: relP, ref: "INDEX" });
      if (k !== key) return;
      base = r.binary || r.tooLarge ? null : { key: k, text: r.text, exists: r.exists };
    } catch { base = null; }
    paintGutter();
  }
  function paintGutter() {
    if (!editor || !monaco) return;
    const model = editor.getModel();
    if (!model || !base || base.key !== key || !prefs.get("editor.gitGutter")) { gutter?.clear(); return; }
    const hunks = base.exists ? lineHunks(base.text, model.getValue()) : [{ kind: "add" as const, start: 1, end: model.getLineCount() }];
    const C = { add: "#3ccf91", mod: "#4f9cf7", del: "#ff6b7d" };
    const decos = hunks.map(h => ({
      range: new monaco!.Range(h.start, 1, h.kind === "del" ? h.start : h.end, 1),
      options: { isWholeLine: true, linesDecorationsClassName: `cd-gut cd-gut-${h.kind}`,
        overviewRuler: { color: C[h.kind], position: monaco!.editor.OverviewRulerLane.Left },
        minimap: { color: C[h.kind], position: monaco!.editor.MinimapPosition.Gutter } },
    }));
    if (!gutter) gutter = editor.createDecorationsCollection(decos);
    else gutter.set(decos);
  }
  // commit/stage mudam a base: relê quando o status do Git do escopo muda
  const statusSig = $derived(gitRepo ? JSON.stringify(scm.status[gitRepo]?.staged || []) + (scm.status[gitRepo]?.head || "") : "");
  $effect(() => { void statusSig; void key; if (!loading) loadBase(); });

  // ------------------------------------------------------------ barra de status
  function publish() {
    if (!editor) return;
    const m = editor.getModel(), p = editor.getPosition(), s = editor.getSelection();
    if (!m || !p) return;
    const o = m.getOptions();
    edState.path = relP;
    edState.line = p.lineNumber; edState.col = p.column;
    edState.sel = s && !s.isEmpty() ? m.getValueInRange(s).length : 0;
    edState.lines = m.getLineCount();
    edState.lang = m.getLanguageId();
    edState.eol = m.getEOL() === "\r\n" ? "CRLF" : "LF";
    edState.indent = o.insertSpaces ? `Espaços: ${o.tabSize}` : `Tab: ${o.tabSize}`;
    edState.lsp = lsp;
    edState.editor = editor;
  }
  $effect(() => { if (edState.path === relP) edState.lsp = lsp; });

  $effect(() => {
    if (!host) return;
    let disposed = false;
    const subs: Monaco.IDisposable[] = [];
    loadMonaco().then(m => {
      if (disposed || !host) return;
      monaco = m;
      trackMarkers(m);
      editor = m.editor.create(host, { automaticLayout: true, theme: monacoTheme(),
        smoothScrolling: true, mouseWheelZoom: true, guides: { bracketPairs: "active", indentation: true },
        scrollBeyondLastLine: false, padding: { top: 6 }, fixedOverflowWidgets: true, ...editorPrefs() });
      editor.addCommand(m.KeyMod.CtrlCmd | m.KeyCode.KeyS, () => save());
      editor.addCommand(m.KeyMod.CtrlCmd | m.KeyMod.Shift | m.KeyCode.KeyV, () => { if (isMd) toggleMd(); });
      // ir para a definição pelo servidor de linguagem — inclusive em outro arquivo, que abre numa aba
      editor.addCommand(m.KeyCode.F12, () => { const pos = editor!.getPosition(); if (pos) gotoDefinition(editor!, pos); });
      editor.onMouseDown(e => {
        if ((e.event.metaKey || e.event.ctrlKey) && e.target.position) gotoDefinition(editor!, e.target.position);
      });
      subs.push(editor.onDidChangeCursorPosition(publish), editor.onDidChangeCursorSelection(publish), editor.onDidFocusEditorText(publish),
        editor.onDidChangeModel(publish), editor.onDidChangeModelLanguage(publish), editor.onDidChangeModelOptions(publish));
      // editar fixa a aba de visualização e atualiza as marcas do Git; salvar automático (se ligado)
      let autoT: ReturnType<typeof setTimeout> | undefined;
      subs.push(editor.onDidChangeModelContent(() => {
        clearTimeout(gutTimer); gutTimer = setTimeout(paintGutter, 250);
        if (!editor?.hasTextFocus()) return;   // o agente editou no disco (recarregou): não conta como edição sua
        onpin?.();
        if (prefs.get("editor.autoSave") === "afterDelay") { clearTimeout(autoT); autoT = setTimeout(() => { if (dirty[key]) save(true); }, 1000); }
      }));
      subs.push(editor.onDidBlurEditorText(() => { if (prefs.get("editor.autoSave") === "onFocusChange" && dirty[key]) save(true); }));
      subs.push(onThemeChange(() => monaco?.editor.setTheme(monacoTheme())));
      loading = false;
    });
    const t = setInterval(syncFromDisk, 3000);
    return () => {
      disposed = true; clearInterval(t); for (const s of subs) s.dispose(); mdSub?.dispose(); clearTimeout(mdTimer); clearTimeout(gutTimer);
      lspStatus.delete(key);
      if (edState.editor === editor) edState.editor = null;
      editor?.dispose(); editor = null;
    };
  });

  // preferências do editor (Configurações → Editor): na criação e ao mudar
  function editorPrefs(): Monaco.editor.IEditorOptions {
    const fs = Number(prefs.get("editor.fontSize")) || 13;
    const fam = String(prefs.get("editor.fontFamily") || "").trim();
    const tab = Number(prefs.get("editor.tabSize")) || 0;
    return { fontSize: fs, lineHeight: Math.round(fs * 1.54),
      fontFamily: (fam ? `"${fam.replace(/"/g, "")}", ` : "") + '"JetBrains Mono Variable", ui-monospace, Menlo, Consolas, monospace',
      fontLigatures: !!prefs.get("editor.ligatures"),
      minimap: { enabled: !!prefs.get("editor.minimap"), renderCharacters: false, showSlider: "mouseover" },
      wordWrap: (prefs.get("editor.wordWrap") ? "on" : "off") as "on" | "off", lineNumbers: (prefs.get("editor.lineNumbers") ? "on" : "off") as "on" | "off",
      stickyScroll: { enabled: !!prefs.get("editor.stickyScroll") }, renderWhitespace: prefs.get("editor.renderWhitespace"),
      cursorStyle: prefs.get("editor.cursorStyle"), cursorBlinking: prefs.get("editor.cursorBlinking"), cursorSmoothCaretAnimation: "on",
      bracketPairColorization: { enabled: !!prefs.get("editor.bracketPairs") },
      ...(tab ? { tabSize: tab, detectIndentation: false } : { detectIndentation: true }) };
  }
  $effect(() => {
    const o = editorPrefs();
    void prefs.get("editor.gitGutter");
    if (loading || !editor) return;
    editor.updateOptions(o);
    paintGutter();
  });

  let shownKey = "";
  $effect(() => {
    const k = key, rel = relP, ln = lineP;
    if (loading || !editor || !monaco) return;
    note = null;
    const prev = docs.get(shownKey);
    if (prev && shownKey !== k) prev.view = editor.saveViewState();
    lspStatus.set(k, s => { lsp = s; if (edState.path === rel) edState.lsp = s; });
    loadDoc(monaco, repoId, taskId, rel).then(d => {
      if (!editor || key !== k) return;
      if ("note" in d) { note = d.note; return; }
      editor.setModel(d.model);
      watchMd(d);
      if (d.view) editor.restoreViewState(d.view);
      if (ln) { editor.revealLineInCenter(ln); editor.setPosition({ lineNumber: ln, column: 1 }); }
      shownKey = k;
      publish();
      loadBase();
      // só pega o foco se ninguém está digitando em outro lugar (o arquivo pode terminar de abrir depois que o
      // usuário já foi para um formulário — antes o editor roubava o foco no meio da digitação)
      const a = document.activeElement;
      if ((!isMd || mdMode !== "preview") && (!a || a === document.body || host?.contains(a))) editor.focus();
    }).catch(e => (note = e.message));
  });
  const crumbs = $derived(relP.split("/"));
</script>

<div class="ed" class:md={isMd && !note} class:split={isMd && mdMode === "split"}>
  <div class="crumbs" aria-label="Caminho do arquivo">
    {#each crumbs as c, i (i)}
      {#if i}<ChevronRight size={11} class="sep" />{/if}
      {#if i === crumbs.length - 1}<span class="cur"><FileIcon name={c} size={13} />{c}</span>
      {:else}<button onclick={() => onreveal?.(crumbs.slice(0, i + 1).join("/") + "/")}>{c}</button>{/if}
    {/each}
  </div>
  <div class="body">
    {#if note}<div class="note">{note}</div>{/if}
    <div class="host" class:hidden={!!note || (isMd && mdMode === "preview")} bind:this={host}></div>
    {#if isMd && !note && !loading}
      {#if mdMode !== "code"}
        <div class="mdpane"><MarkdownView text={mdText} path={relP} ontoggle={toggleTask} onopen={(rel) => openInApp(rel)} onkey={toggleMd} /></div>
      {/if}
      <div class="mdbar" role="tablist" aria-label="Como ver o Markdown">
        <button role="tab" class:on={mdMode === "preview"} aria-selected={mdMode === "preview"} title={`Ver renderizado (${kbd("mod+shift+v")})`} onclick={() => setMd("preview")}>Visualizar</button>
        <button role="tab" class:on={mdMode === "code"} aria-selected={mdMode === "code"} title={`Ver o código (${kbd("mod+shift+v")})`} onclick={() => setMd("code")}>Código</button>
        <button role="tab" class:on={mdMode === "split"} aria-selected={mdMode === "split"} title="Código e renderizado lado a lado" onclick={() => setMd("split")}>Lado a lado</button>
      </div>
    {/if}
    {#if loading}<div class="loading"><span class="shim"></span><span class="shim"></span><span class="shim"></span></div>{/if}
  </div>
</div>

<style>
  .ed { position: relative; width: 100%; height: 100%; min-height: 0; background: var(--ed-bg, var(--surface)); display: flex; flex-direction: column; }
  .crumbs { display: flex; align-items: center; gap: 2px; height: 24px; padding: 0 12px; flex: none; overflow: hidden; white-space: nowrap;
    font: 12px var(--font); color: var(--muted); border-bottom: 1px solid var(--line); }
  .crumbs button { border: 0; background: none; padding: 1px 3px; border-radius: 4px; color: var(--muted); font: inherit; cursor: pointer; }
  .crumbs button:hover { color: var(--text); background: var(--surface-2); }
  .crumbs :global(.sep) { color: var(--faint); flex: none; }
  .crumbs .cur { display: inline-flex; align-items: center; gap: 5px; color: var(--text-2); padding: 0 3px; }
  .body { position: relative; flex: 1; min-height: 0; }
  .host { position: absolute; inset: 0; }
  .host.hidden { visibility: hidden; }
  .split .host { right: 50%; }
  .mdpane { position: absolute; inset: 0; z-index: 2; }
  .split .mdpane { left: 50%; border-left: 1px solid var(--line); }
  .mdbar { position: absolute; top: 8px; right: 22px; z-index: 4; display: flex; gap: 2px; padding: 2px; border-radius: 9px; background: var(--bg-2);
    border: 1px solid var(--line); box-shadow: var(--shadow-1); }
  .mdbar button { height: 24px; padding: 0 10px; border: 0; border-radius: 7px; background: none; color: var(--muted); font: 600 11.5px var(--font); cursor: pointer;
    transition: background var(--t-fast), color var(--t-fast); }
  .mdbar button:hover { color: var(--text); }
  .mdbar button.on { background: var(--surface-3); color: var(--text); box-shadow: var(--shadow-1); }
  .note { position: absolute; inset: 0; display: grid; place-items: center; color: var(--muted); font-size: 13px; }
  .loading { position: absolute; inset: 16px; display: grid; gap: 10px; align-content: start; }
  .loading .shim { height: 12px; }
  .loading .shim:nth-child(2) { width: 70%; }
  .loading .shim:nth-child(3) { width: 45%; }
  /* marcas do Git na margem */
  :global(.cd-gut) { margin-left: 3px; width: 3px !important; }
  :global(.cd-gut-add) { background: #3ccf91; }
  :global(.cd-gut-mod) { background: #4f9cf7; }
  :global(.cd-gut-del) { background: none; }
  :global(.cd-gut-del::before) { content: ""; position: absolute; top: -4px; left: 0; border: 4px solid transparent; border-left-color: #ff6b7d; }
</style>
