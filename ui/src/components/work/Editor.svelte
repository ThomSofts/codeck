<script lang="ts" module>
  // Um editor Monaco por tela; cada arquivo aberto é um "model" (com o próprio desfazer e posição do cursor).
  // O agente edita os mesmos arquivos no disco: se o arquivo não tem alteração sua, ele é recarregado sozinho;
  // se tem, o salvar avisa que o disco mudou (nunca sobrescreve em silêncio).
  import type * as Monaco from "monaco-editor";
  type Doc = { model: Monaco.editor.ITextModel; mtime: number; saved: number; view: Monaco.editor.ICodeEditorViewState | null };
  export const docs = new Map<string, Doc>();
  export const dirty = $state<Record<string, boolean>>({});
  export const keyOf = (repoId: string, taskId: string | null | undefined, path: string) => `${repoId}:${taskId || ""}:${path}`;
  export function forget(key: string) { docs.get(key)?.model.dispose(); docs.delete(key); delete dirty[key]; mdModes.delete(key); }
  /** Markdown: como cada arquivo está sendo visto nesta sessão (pré-visualização, código ou lado a lado) */
  type MdMode = "preview" | "code" | "split";
  const mdModes = new Map<string, MdMode>();
</script>

<script lang="ts">
  import { get, post } from "../../lib/api";
  import { kbd } from "../../lib/keys";
  import { attach, gotoDefinition, openInApp } from "../../lib/lsp";
  import { loadMonaco, monacoTheme } from "../../lib/monaco";
  import { prefs } from "../../lib/prefs.svelte";
  import { ui } from "../../lib/ui.svelte";
  import MarkdownView from "./MarkdownView.svelte";
  import { scanTasks } from "./md/render";

  let { repoId, taskId = null, path, line = 0 }: { repoId: string; taskId?: string | null; path: string; line?: number } = $props();
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

  async function openDoc(k: string, rel: string): Promise<Doc | null> {
    if (docs.has(k)) return docs.get(k)!;
    const f = await get<any>("ws/file", { repoId, taskId, path: rel });
    if (f.binary || f.tooLarge) { note = f.binary ? "Arquivo binário — não dá para editar aqui." : `Arquivo grande demais (${Math.round(f.size / 1e6)} MB).`; return null; }
    const uri = monaco!.Uri.parse(`file:///${encodeURIComponent(repoId + "-" + (taskId || "main"))}/${rel}`);
    const model = monaco!.editor.getModel(uri) || monaco!.editor.createModel(f.text, undefined, uri);
    if (f.crlf) model.setEOL(monaco!.editor.EndOfLineSequence.CRLF);
    const d: Doc = { model, mtime: f.mtime, saved: model.getAlternativeVersionId(), view: null };
    model.onDidChangeContent(() => { dirty[k] = model.getAlternativeVersionId() !== d.saved; });
    docs.set(k, d);
    attach(monaco!, model, { repoId, taskId, root: f.root, rel }, s => { if (key === k) lsp = s; });
    return d;
  }

  async function save(quiet = false) {
    const k = key, d = docs.get(k);
    if (!d) return;
    try {
      const r = await post<{ mtime: number }>("ws/file", { repoId, taskId, path, text: d.model.getValue(), mtime: d.mtime });
      d.mtime = r.mtime;
      d.saved = d.model.getAlternativeVersionId();
      dirty[k] = false;
      if (!quiet) ui.toast(`${path.split("/").pop()} salvo`);
    } catch (e: any) {
      if (/mudou no disco/.test(e.message || "") && await ui.ask({ title: "O arquivo mudou no disco", message: "Alguém (provavelmente o agente) editou este arquivo depois que você abriu. Sobrescrever com a sua versão?", confirm: "Sobrescrever", danger: true })) {
        d.mtime = 0;
        const r = await post<{ mtime: number }>("ws/file", { repoId, taskId, path, text: d.model.getValue() });
        d.mtime = r.mtime; d.saved = d.model.getAlternativeVersionId(); dirty[k] = false;
      } else ui.error(e);
    }
  }

  // o arquivo aberto e sem alteração sua acompanha o disco (o agente editando aparece ao vivo)
  async function syncFromDisk() {
    const k = key, d = docs.get(k);
    if (!d || dirty[k] || document.hidden) return;
    try {
      const f = await get<any>("ws/file", { repoId, taskId, path });
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

  $effect(() => {
    if (!host) return;
    let disposed = false;
    loadMonaco().then(m => {
      if (disposed || !host) return;
      monaco = m;
      editor = m.editor.create(host, { automaticLayout: true, theme: monacoTheme(), fontFamily: '"JetBrains Mono Variable", ui-monospace, Menlo, monospace',
        smoothScrolling: true, cursorSmoothCaretAnimation: "on",
        bracketPairColorization: { enabled: true }, renderWhitespace: "selection", scrollBeyondLastLine: false,
        padding: { top: 8 }, fixedOverflowWidgets: true, ...editorPrefs() });
      editor.addCommand(m.KeyMod.CtrlCmd | m.KeyCode.KeyS, () => save());
      editor.addCommand(m.KeyMod.CtrlCmd | m.KeyMod.Shift | m.KeyCode.KeyV, () => { if (isMd) toggleMd(); });
      // ir para a definição pelo servidor de linguagem — inclusive em outro arquivo, que abre numa aba
      editor.addCommand(m.KeyCode.F12, () => { const pos = editor!.getPosition(); if (pos) gotoDefinition(editor!, pos); });
      editor.onMouseDown(e => {
        if ((e.event.metaKey || e.event.ctrlKey) && e.target.position) gotoDefinition(editor!, e.target.position);
      });
      loading = false;
    });
    const obs = new MutationObserver(() => monaco?.editor.setTheme(monacoTheme()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const t = setInterval(syncFromDisk, 3000);
    return () => { disposed = true; clearInterval(t); obs.disconnect(); mdSub?.dispose(); clearTimeout(mdTimer); editor?.dispose(); editor = null; };
  });

  // preferências do editor (Configurações → Editor): na criação e ao mudar
  function editorPrefs() {
    const fs = Number(prefs.get("editor.fontSize")) || 13;
    return { fontSize: fs, lineHeight: Math.round(fs * 1.54), minimap: { enabled: !!prefs.get("editor.minimap"), renderCharacters: false },
      wordWrap: (prefs.get("editor.wordWrap") ? "on" : "off") as "on" | "off", lineNumbers: (prefs.get("editor.lineNumbers") ? "on" : "off") as "on" | "off",
      stickyScroll: { enabled: !!prefs.get("editor.stickyScroll") } };
  }
  $effect(() => {
    const o = editorPrefs();
    if (loading || !editor) return;
    editor.updateOptions(o);
  });

  let shownKey = "";
  $effect(() => {
    const k = key, rel = relP, ln = lineP;
    if (loading || !editor) return;
    note = null;
    const prev = docs.get(shownKey);
    if (prev && shownKey !== k) prev.view = editor.saveViewState();
    openDoc(k, rel).then(d => {
      if (!d || !editor || key !== k) return;
      editor.setModel(d.model);
      watchMd(d);
      if (d.view) editor.restoreViewState(d.view);
      if (ln) { editor.revealLineInCenter(ln); editor.setPosition({ lineNumber: ln, column: 1 }); }
      shownKey = k;
      // só pega o foco se ninguém está digitando em outro lugar (o arquivo pode terminar de abrir depois que o
      // usuário já foi para um formulário — antes o editor roubava o foco no meio da digitação)
      const a = document.activeElement;
      if ((!isMd || mdMode !== "preview") && (!a || a === document.body || host?.contains(a))) editor.focus();
    }).catch(e => (note = e.message));
  });
</script>

<div class="ed" class:md={isMd && !note} class:split={isMd && mdMode === "split"}>
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
  {#if lsp}<div class="lsp" class:ok={lsp === "ativo"} title="Servidor de linguagem">{lsp === "ativo" ? "● servidor de linguagem ativo" : lsp}</div>{/if}
  {#if loading}<div class="loading"><span class="shim"></span><span class="shim"></span><span class="shim"></span></div>{/if}
</div>

<style>
  .ed { position: relative; width: 100%; height: 100%; min-height: 0; background: var(--surface); }
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
  .lsp { position: absolute; right: 18px; bottom: 6px; z-index: 3; font-size: 11px; color: var(--muted); background: var(--surface-2); padding: 2px 8px; border-radius: 99px; pointer-events: none; }
  .lsp.ok { color: var(--good); }
  .loading { position: absolute; inset: 16px; display: grid; gap: 10px; align-content: start; }
  .loading .shim { height: 12px; }
  .loading .shim:nth-child(2) { width: 70%; }
  .loading .shim:nth-child(3) { width: 45%; }
</style>
