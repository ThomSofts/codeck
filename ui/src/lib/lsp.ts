// Cliente LSP mínimo para o Monaco: um servidor por (projeto/tarefa, linguagem), pela ponte /ws/lsp do backend.
// Faz: abrir/alterar/fechar documento, erros (publishDiagnostics → marcações), autocompletar, hover, definição,
// referências, renomear, símbolos, formatar, destaque semântico (cores pelo significado, como no VS Code), ocorrências
// do símbolo, dicas inline e correções rápidas (a lâmpada, ⌘.).
import type * as Monaco from "monaco-editor";
import { get as apiGet, post as apiPost } from "./api";
import { modelUri } from "./editorstate.svelte";
import { ui } from "./ui.svelte";

type Pending = { resolve: (v: any) => void; reject: (e: any) => void };
const LANGS = new Set(["typescript", "javascript", "python", "csharp", "go", "rust", "java", "php", "html", "css", "json"]);
// os tipos e modificadores de token semântico do LSP (o servidor devolve a lista dele no initialize)
const TOKEN_TYPES = ["namespace", "type", "class", "enum", "interface", "struct", "typeParameter", "parameter", "variable", "property", "enumMember",
  "event", "function", "method", "macro", "keyword", "modifier", "comment", "string", "number", "regexp", "operator", "decorator"];
const TOKEN_MODS = ["declaration", "definition", "readonly", "static", "deprecated", "abstract", "async", "modification", "documentation", "defaultLibrary"];
const legends = new Map<string, { tokenTypes: string[]; tokenModifiers: string[] }>();

class Client {
  ws: WebSocket;
  seq = 0;
  pending = new Map<number, Pending>();
  ready: Promise<void>;
  status = "conectando…";
  caps: any = {};
  docs = new Map<string, { model: Monaco.editor.ITextModel; version: number }>();   // uri do LSP → modelo
  constructor(public monaco: typeof Monaco, public lang: string, public repoId: string, public taskId: string | null, public root: string, onStatus: (s: string) => void) {
    const qs = new URLSearchParams({ repoId, ...(taskId ? { taskId } : {}) });
    this.ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/lsp/${lang}?${qs}`, ["codeck." + (window.CODECK_TOKEN || "")]);
    this.ready = new Promise((resolve, reject) => {
      this.ws.onopen = async () => {
        try {
          const rootUri = toUri(root);
          const r = await this.request("initialize", { processId: null, rootUri, rootPath: root, workspaceFolders: [{ uri: rootUri, name: root.split(/[\\/]/).pop() }],
            capabilities: { textDocument: { synchronization: { didSave: true, dynamicRegistration: false }, hover: { contentFormat: ["markdown", "plaintext"] },
              completion: { completionItem: { snippetSupport: false, documentationFormat: ["markdown", "plaintext"] } }, definition: {}, publishDiagnostics: {},
              rename: { prepareSupport: false }, references: {}, implementation: {}, documentSymbol: { hierarchicalDocumentSymbolSupport: true },
              formatting: {}, rangeFormatting: {}, signatureHelp: { signatureInformation: { documentationFormat: ["markdown", "plaintext"] } },
              documentHighlight: {}, inlayHint: {},
              semanticTokens: { requests: { full: true, range: false }, tokenTypes: TOKEN_TYPES, tokenModifiers: TOKEN_MODS, formats: ["relative"] },
              codeAction: { resolveSupport: { properties: ["edit"] }, codeActionLiteralSupport: { codeActionKind: { valueSet: ["", "quickfix", "refactor",
                "refactor.extract", "refactor.inline", "refactor.rewrite", "source", "source.organizeImports", "source.fixAll"] } } } },
              workspace: { workspaceFolders: true, configuration: true, applyEdit: true, workspaceEdit: { documentChanges: true } } },
            // TypeScript: o servidor só manda as dicas inline se pedir (o editor mostra segurando ⌃⌥, como no VS Code)
            initializationOptions: { preferences: { includeInlayParameterNameHints: "literals", includeInlayFunctionLikeReturnTypeHints: true,
              includeInlayVariableTypeHints: true, includeInlayPropertyDeclarationTypeHints: true, includeInlayEnumMemberValueHints: true } } }, 90000);   // servidor frio (C#, Java) demora para subir
          this.caps = r?.capabilities || {};
          const lg = this.caps.semanticTokensProvider?.legend;
          if (lg) legends.set(lang, lg);
          this.notify("initialized", {});
          this.status = "ativo"; onStatus("ativo");
          resolve();
        } catch (e) { reject(e); }
      };
    });
    this.ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.codeck === "unavailable") { this.status = m.message; onStatus(m.message); return; }
      if (m.id != null && (m.result !== undefined || m.error) && this.pending.has(m.id)) {
        const p = this.pending.get(m.id)!; this.pending.delete(m.id);
        return m.error ? p.reject(m.error) : p.resolve(m.result);
      }
      if (m.method === "textDocument/publishDiagnostics") return this.diagnostics(m.params);
      if (m.id != null && m.method === "workspace/applyEdit") {   // a correção rápida/refatoração pediu para editar
        applyWorkspaceEdit(this, m.params?.edit).then(() => this.ws.send(JSON.stringify({ jsonrpc: "2.0", id: m.id, result: { applied: true } })),
          (err) => this.ws.send(JSON.stringify({ jsonrpc: "2.0", id: m.id, result: { applied: false, failureReason: String(err?.message || err) } })));
        return;
      }
      if (m.id != null && m.method) {   // pedido do servidor (configuração, registro, progresso): responde algo neutro
        const result = m.method === "workspace/configuration" ? (m.params?.items || []).map(() => null) : null;
        this.ws.send(JSON.stringify({ jsonrpc: "2.0", id: m.id, result }));
      }
    };
    this.ws.onclose = () => { if (this.status === "ativo") { this.status = "desconectado"; onStatus("desconectado"); } };
  }
  request(method: string, params: any, timeout = 15000): Promise<any> {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error("tempo esgotado")); } }, timeout);
    });
  }
  notify(method: string, params: any) { if (this.ws.readyState === 1) this.ws.send(JSON.stringify({ jsonrpc: "2.0", method, params })); }
  diagnostics(p: { uri: string; diagnostics: any[] }) {
    const d = this.docs.get(norm(p.uri));
    if (!d) return;
    const S = this.monaco.MarkerSeverity;
    this.monaco.editor.setModelMarkers(d.model, "lsp", p.diagnostics.map(x => ({
      severity: [S.Error, S.Error, S.Warning, S.Info, S.Hint][x.severity || 1], message: x.message, source: x.source,
      code: x.code != null ? String(x.code) : undefined, tags: x.tags,
      startLineNumber: x.range.start.line + 1, startColumn: x.range.start.character + 1, endLineNumber: x.range.end.line + 1, endColumn: x.range.end.character + 1,
    })));
  }
}

// Comparação de URIs: o servidor pode devolver "file:///d%3A/x" para "file:///D:/x" (Windows): decodifica e
// padroniza a letra do drive antes de comparar.
const norm = (u: string) => { let x = u; try { x = decodeURIComponent(u); } catch { /* já decodificada */ } return x.replace(/^file:\/\/\/([A-Za-z]):/, (_m, d) => `file:///${d.toLowerCase()}:`); };
const toUri = (p: string) => "file://" + (p.startsWith("/") ? "" : "/") + p.replace(/\\/g, "/").split("/").map(encodeURIComponent).join("/").replace(/%3A/g, ":");
const clients = new Map<string, Client>();
const byModel = new Map<string, { client: Client; uri: string; root: string; rel: string }>();
let opener: ((rel: string, line: number) => void) | null = null;
const registered = new Set<string>();

/** Liga um modelo do Monaco ao servidor de linguagem do projeto (se houver um instalado para a linguagem). */
export function attach(monaco: typeof Monaco, model: Monaco.editor.ITextModel, ctx: { repoId: string; taskId: string | null; root: string; rel: string },
  onStatus: (s: string) => void) {
  const lang = model.getLanguageId();
  if (!LANGS.has(lang) || !ctx.root) return onStatus("");
  const key = `${ctx.repoId}:${ctx.taskId || ""}:${lang}`;
  let c = clients.get(key);
  if (!c || c.ws.readyState > 1) { c = new Client(monaco, lang, ctx.repoId, ctx.taskId, ctx.root, onStatus); clients.set(key, c); }
  else onStatus(c.status);
  const uri = toUri(ctx.root.replace(/[\\/]$/, "") + "/" + ctx.rel);
  byModel.set(model.uri.toString(), { client: c, uri, root: ctx.root, rel: ctx.rel });
  register(monaco, lang);
  const client = c;
  client.ready.then(() => {
    if (client.docs.has(norm(uri))) return;
    client.docs.set(norm(uri), { model, version: 1 });
    client.notify("textDocument/didOpen", { textDocument: { uri, languageId: lang, version: 1, text: model.getValue() } });
    let t: ReturnType<typeof setTimeout> | undefined;
    model.onDidChangeContent(() => {
      clearTimeout(t);
      t = setTimeout(() => {
        const d = client.docs.get(norm(uri));
        if (!d) return;
        d.version++;
        client.notify("textDocument/didChange", { textDocument: { uri, version: d.version }, contentChanges: [{ text: model.getValue() }] });
      }, 250);
    });
    model.onWillDispose(() => { client.notify("textDocument/didClose", { textDocument: { uri } }); client.docs.delete(norm(uri)); byModel.delete(model.uri.toString()); });
  }).catch(() => onStatus("falhou ao iniciar o servidor"));
}

/** Para onde vai o "ir para a definição" em outro arquivo do projeto (a tela abre a aba). */
export function setOpener(fn: (rel: string, line: number) => void) { opener = fn; }
/** Abre outro arquivo do projeto numa aba (links relativos do Markdown usam o mesmo caminho). */
export function openInApp(rel: string, line = 1) { opener?.(rel, line); }

function register(monaco: typeof Monaco, lang: string) {
  if (registered.has(lang)) return;
  registered.add(lang);
  const pos = (p: Monaco.Position) => ({ line: p.lineNumber - 1, character: p.column - 1 });
  const ctxOf = (m: Monaco.editor.ITextModel) => byModel.get(m.uri.toString());
  // servidor que não subiu (ou demorou demais no initialize): os recursos só não aparecem — nada de erro na tela
  const up = (x: { client: Client }) => x.client.ready.then(() => true, () => false);
  const md = (c: any): string => (typeof c === "string" ? c : Array.isArray(c) ? c.map(md).join("\n\n") : c?.kind ? c.value : c?.language ? "```" + c.language + "\n" + c.value + "\n```" : c?.value || "");
  monaco.languages.registerHoverProvider(lang, {
    async provideHover(model, position) {
      const x = ctxOf(model); if (!x || !(await up(x))) return null;
      const r = await x.client.request("textDocument/hover", { textDocument: { uri: x.uri }, position: pos(position) }).catch(() => null);
      return r?.contents ? { contents: [{ value: md(r.contents) }] } : null;
    },
  });
  monaco.languages.registerCompletionItemProvider(lang, {
    triggerCharacters: [".", ":", "<", '"', "/", "@"],
    async provideCompletionItems(model, position) {
      const x = ctxOf(model); if (!x || !(await up(x))) return { suggestions: [] };
      const r = await x.client.request("textDocument/completion", { textDocument: { uri: x.uri }, position: pos(position) }).catch(() => null);
      const items: any[] = Array.isArray(r) ? r : r?.items || [];
      const word = model.getWordUntilPosition(position);
      const range = { startLineNumber: position.lineNumber, endLineNumber: position.lineNumber, startColumn: word.startColumn, endColumn: word.endColumn };
      return { suggestions: items.slice(0, 300).map(i => ({ label: i.label, kind: Math.max(0, (i.kind || 1) - 1), detail: i.detail,
        documentation: i.documentation ? { value: md(i.documentation) } : undefined, insertText: i.textEdit?.newText ?? i.insertText ?? i.label,
        sortText: i.sortText, filterText: i.filterText, range })) };
    },
  });
  monaco.languages.registerDefinitionProvider(lang, {
    async provideDefinition(model, position) {
      const x = ctxOf(model); if (!x || !(await up(x))) return null;
      const r = await x.client.request("textDocument/definition", { textDocument: { uri: x.uri }, position: pos(position) }).catch(() => null);
      const locs: any[] = (Array.isArray(r) ? r : r ? [r] : []).map(l => ({ uri: l.targetUri || l.uri, range: l.targetSelectionRange || l.range }));
      const rootUri = norm(toUri(x.root.replace(/[\\/]$/, ""))) + "/";
      return locs.filter(l => norm(l.uri).startsWith(rootUri)).map(l => {
        const rel = norm(l.uri).slice(rootUri.length);
        const same = rel === x.rel;
        const target = same ? model.uri : monaco.Uri.parse(`cdgoto:///${encodeURIComponent(rel)}`);
        // o editor só "abre" um arquivo que tenha modelo: um vazio basta — o opener abaixo troca pela aba de verdade
        if (!same && !monaco.editor.getModel(target)) monaco.editor.createModel("", undefined, target);
        return { uri: target, range: {
          startLineNumber: l.range.start.line + 1, startColumn: l.range.start.character + 1, endLineNumber: l.range.end.line + 1, endColumn: l.range.end.character + 1 } };
      });
    },
  });
  const range = (r: any) => ({ startLineNumber: r.start.line + 1, startColumn: r.start.character + 1, endLineNumber: r.end.line + 1, endColumn: r.end.character + 1 });
  const textEdits = (list: any[]) => (list || []).map(e => ({ range: range(e.range), text: e.newText }));
  const relOf = (x: { root: string }, uri: string) => { const rootUri = norm(toUri(x.root.replace(/[\\/]$/, ""))) + "/"; const u = norm(uri); return u.startsWith(rootUri) ? u.slice(rootUri.length) : null; };
  // referências e implementação: só as do projeto (cada uma vira um modelo vazio que a tela troca pela aba, como a definição)
  const locations = (model: Monaco.editor.ITextModel, x: { rel: string; root: string }, r: any) => (Array.isArray(r) ? r : r ? [r] : []).flatMap((l: any) => {
    const uri = l.targetUri || l.uri, rg = l.targetSelectionRange || l.range, rel = relOf(x, uri);
    if (rel === null) return [];
    const target = rel === x.rel ? model.uri : monaco.Uri.parse(`cdgoto:///${encodeURIComponent(rel)}`);
    if (rel !== x.rel && !monaco.editor.getModel(target)) monaco.editor.createModel("", undefined, target);
    return [{ uri: target, range: range(rg) }];
  });
  monaco.languages.registerReferenceProvider(lang, {
    async provideReferences(model, position, context) {
      const x = ctxOf(model); if (!x || !(await up(x))) return [];
      const r = await x.client.request("textDocument/references", { textDocument: { uri: x.uri }, position: pos(position), context }).catch(() => null);
      return locations(model, x, r);
    },
  });
  monaco.languages.registerImplementationProvider(lang, {
    async provideImplementation(model, position) {
      const x = ctxOf(model); if (!x || !(await up(x))) return [];
      const r = await x.client.request("textDocument/implementation", { textDocument: { uri: x.uri }, position: pos(position) }).catch(() => null);
      return locations(model, x, r);
    },
  });
  monaco.languages.registerDocumentSymbolProvider(lang, {
    async provideDocumentSymbols(model) {
      const x = ctxOf(model); if (!x || !(await up(x))) return [];
      const r: any[] = (await x.client.request("textDocument/documentSymbol", { textDocument: { uri: x.uri } }).catch(() => null)) || [];
      const conv = (s: any): Monaco.languages.DocumentSymbol => ({ name: s.name, detail: s.detail || "", kind: Math.max(0, (s.kind || 1) - 1), tags: [],
        range: range(s.range || s.location.range), selectionRange: range(s.selectionRange || s.range || s.location.range), children: (s.children || []).map(conv) });
      return r.map(conv);
    },
  });
  monaco.languages.registerDocumentFormattingEditProvider(lang, {
    async provideDocumentFormattingEdits(model, options) {
      const x = ctxOf(model); if (!x || !(await up(x))) return [];
      return textEdits(await x.client.request("textDocument/formatting", { textDocument: { uri: x.uri }, options }).catch(() => null));
    },
  });
  monaco.languages.registerDocumentRangeFormattingEditProvider(lang, {
    async provideDocumentRangeFormattingEdits(model, rg, options) {
      const x = ctxOf(model); if (!x || !(await up(x))) return [];
      const r = { start: { line: rg.startLineNumber - 1, character: rg.startColumn - 1 }, end: { line: rg.endLineNumber - 1, character: rg.endColumn - 1 } };
      return textEdits(await x.client.request("textDocument/rangeFormatting", { textDocument: { uri: x.uri }, range: r, options }).catch(() => null));
    },
  });
  monaco.languages.registerSignatureHelpProvider(lang, {
    signatureHelpTriggerCharacters: ["(", ","],
    async provideSignatureHelp(model, position) {
      const x = ctxOf(model); if (!x || !(await up(x))) return null;
      const r = await x.client.request("textDocument/signatureHelp", { textDocument: { uri: x.uri }, position: pos(position) }).catch(() => null);
      if (!r?.signatures?.length) return null;
      return { value: { activeSignature: r.activeSignature || 0, activeParameter: r.activeParameter || 0,
        signatures: r.signatures.map((g: any) => ({ label: g.label, documentation: g.documentation ? { value: md(g.documentation) } : undefined,
          parameters: (g.parameters || []).map((p: any) => ({ label: p.label, documentation: p.documentation ? { value: md(p.documentation) } : undefined })) })) },
        dispose() {} };
    },
  });
  // cores pelo significado (função, tipo, parâmetro, propriedade…): o tema pinta pelos tipos da legenda do servidor
  monaco.languages.registerDocumentSemanticTokensProvider(lang, {
    getLegend: () => legends.get(lang) || { tokenTypes: [], tokenModifiers: [] },
    async provideDocumentSemanticTokens(model) {
      const x = ctxOf(model); if (!x || !(await up(x)) || !x.client.caps.semanticTokensProvider) return null;
      const r = await x.client.request("textDocument/semanticTokens/full", { textDocument: { uri: x.uri } }).catch(() => null);
      return r?.data ? { data: new Uint32Array(r.data), resultId: r.resultId } : null;
    },
    releaseDocumentSemanticTokens() {},
  });
  // as outras ocorrências do símbolo sob o cursor (leitura/escrita), como no VS Code
  monaco.languages.registerDocumentHighlightProvider(lang, {
    async provideDocumentHighlights(model, position) {
      const x = ctxOf(model); if (!x || !(await up(x)) || !x.client.caps.documentHighlightProvider) return null;
      const r: any[] = (await x.client.request("textDocument/documentHighlight", { textDocument: { uri: x.uri }, position: pos(position) }).catch(() => null)) || [];
      return r.map(h => ({ range: range(h.range), kind: Math.max(0, (h.kind || 1) - 1) }));
    },
  });
  // dicas inline (nome do parâmetro, tipo inferido): aparecem segurando ⌃⌥ (Configurações → Editor muda)
  monaco.languages.registerInlayHintsProvider(lang, {
    async provideInlayHints(model, rg) {
      const x = ctxOf(model); if (!x || !(await up(x)) || !x.client.caps.inlayHintProvider) return { hints: [], dispose() {} };
      const r: any[] = (await x.client.request("textDocument/inlayHint", { textDocument: { uri: x.uri },
        range: { start: { line: rg.startLineNumber - 1, character: 0 }, end: { line: rg.endLineNumber, character: 0 } } }).catch(() => null)) || [];
      return { hints: r.map(h => ({ position: { lineNumber: h.position.line + 1, column: h.position.character + 1 },
        label: typeof h.label === "string" ? h.label : (h.label || []).map((p: any) => p.value).join(""), kind: h.kind === 1 ? 1 : 2,
        paddingLeft: h.paddingLeft, paddingRight: h.paddingRight })), dispose() {} };
    },
  });
  // correções rápidas e refatorações (a lâmpada, ⌘.): a ação escolhida aplica as edições e/ou executa o comando no servidor
  monaco.languages.registerCodeActionProvider(lang, {
    async provideCodeActions(model, rg, context) {
      const x = ctxOf(model); if (!x || !(await up(x)) || !x.client.caps.codeActionProvider) return { actions: [], dispose() {} };
      const S = monaco.MarkerSeverity;
      const diagnostics = context.markers.map(m => ({
        range: { start: { line: m.startLineNumber - 1, character: m.startColumn - 1 }, end: { line: m.endLineNumber - 1, character: m.endColumn - 1 } },
        severity: m.severity === S.Error ? 1 : m.severity === S.Warning ? 2 : m.severity === S.Info ? 3 : 4, message: m.message, source: m.source,
        ...(m.code ? { code: typeof m.code === "string" ? m.code : m.code.value } : {}) }));
      const r: any[] = (await x.client.request("textDocument/codeAction", { textDocument: { uri: x.uri },
        range: { start: { line: rg.startLineNumber - 1, character: rg.startColumn - 1 }, end: { line: rg.endLineNumber - 1, character: rg.endColumn - 1 } },
        context: { diagnostics, ...(context.only ? { only: [context.only] } : {}), triggerKind: context.trigger === 1 ? 1 : 2 } }).catch(() => null)) || [];
      // sem "kind" (o TypeScript manda as correções como comando): é correção rápida — senão a lâmpada a esconderia
      return { actions: r.filter(a => !a.disabled).map(a => ({ title: a.title, kind: a.kind || "quickfix", isPreferred: a.isPreferred,
        diagnostics: [], command: { id: "codeck.lsp.codeAction", title: a.title, arguments: [x.client, a] } })), dispose() {} };
    },
  }, { providedCodeActionKinds: ["quickfix", "refactor", "source"] });
  if (!actionCmd) {
    actionCmd = true;
    monaco.editor.registerCommand("codeck.lsp.codeAction", async (_acc, client: Client, a: any) => {
      try {
        if (!a.command && !a.edit && client.caps.codeActionProvider?.resolveProvider) a = await client.request("codeAction/resolve", a);
        if (a.edit) await applyWorkspaceEdit(client, a.edit);
        const cmd = typeof a.command === "string" ? a : a.command;
        if (cmd?.command) await client.request("workspace/executeCommand", { command: cmd.command, arguments: cmd.arguments }, 60000);
      } catch (e) { ui.error(e); }
    });
  }
  // renomear o símbolo (F2): o servidor devolve as edições de todos os arquivos. As dos arquivos abertos entram no
  // editor (desfazíveis, ficam por salvar); as dos fechados são gravadas no disco direto.
  monaco.languages.registerRenameProvider(lang, {
    async provideRenameEdits(model, position, newName) {
      const x = ctxOf(model); if (!x || !(await up(x))) return { edits: [] };
      const r = await x.client.request("textDocument/rename", { textDocument: { uri: x.uri }, position: pos(position), newName });
      const byUri = new Map<string, any[]>();
      for (const [u, list] of Object.entries(r?.changes || {})) byUri.set(u, list as any[]);
      for (const dc of r?.documentChanges || []) if (dc.textDocument && dc.edits) byUri.set(dc.textDocument.uri, [...(byUri.get(dc.textDocument.uri) || []), ...dc.edits]);
      const edits: Monaco.languages.IWorkspaceTextEdit[] = [];
      let onDisk = 0;
      for (const [u, list] of byUri) {
        const rel = relOf(x, u);
        if (rel === null) continue;
        const m = rel === x.rel ? model : monaco.editor.getModel(monaco.Uri.parse(modelUri(x.client.repoId, x.client.taskId, rel)));
        if (m) { for (const e of list) edits.push({ resource: m.uri, textEdit: { range: range(e.range), text: e.newText }, versionId: undefined }); continue; }
        const f = await apiGet<any>("ws/file", { repoId: x.client.repoId, taskId: x.client.taskId, path: rel });
        if (typeof f.text !== "string") continue;
        await apiPost("ws/file", { repoId: x.client.repoId, taskId: x.client.taskId, path: rel, text: applyEdits(f.text, list), mtime: f.mtime });
        onDisk++;
      }
      if (onDisk) ui.toast(`Renomeado também em ${onDisk} arquivo${onDisk === 1 ? "" : "s"} fechado${onDisk === 1 ? "" : "s"} (já gravado${onDisk === 1 ? "" : "s"} no disco)`);
      return { edits };
    },
  });
  // definição em outro arquivo: em vez de abrir um modelo solto, a tela abre a aba do arquivo
  monaco.editor.registerEditorOpener({
    openCodeEditor(_src, resource, sel) {
      if (resource.scheme !== "cdgoto" || !opener) return false;
      const line = sel && "startLineNumber" in sel ? sel.startLineNumber : (sel as any)?.lineNumber || 1;
      opener(decodeURIComponent(resource.path.replace(/^\//, "")), line);
      return true;
    },
  });
}


let actionCmd = false;

/** Com servidor de TypeScript/JavaScript instalado, o TypeScript embutido do Monaco sai do caminho: ele registra os
 *  recursos dele depois dos nossos (carrega o módulo sob demanda) e passava na frente — o F2 dele só renomeava os
 *  arquivos abertos, o hover e o autocompletar vinham em dobro. Só vale antes do 1º arquivo TS abrir (o Monaco lê a
 *  configuração uma vez): monaco.ts chama ao carregar. Sem servidor, o embutido continua valendo. */
export function builtinOff(monaco: typeof Monaco, lang: string) {
  const d = lang === "typescript" ? monaco.languages.typescript.typescriptDefaults : monaco.languages.typescript.javascriptDefaults;
  d.setModeConfiguration({ completionItems: false, hovers: false, documentSymbols: false, definitions: false, references: false, documentHighlights: false,
    rename: false, diagnostics: false, documentRangeFormattingEdits: false, signatureHelp: false, onTypeFormattingEdits: false, codeActions: false, inlayHints: false });
}

/** Aplica um WorkspaceEdit do servidor: arquivo aberto edita no editor (desfazível, fica por salvar); fechado é gravado. */
async function applyWorkspaceEdit(client: Client, edit: any) {
  if (!edit) return;
  const m = client.monaco;
  const byUri = new Map<string, any[]>();
  for (const [u, list] of Object.entries(edit.changes || {})) byUri.set(u, list as any[]);
  for (const dc of edit.documentChanges || []) if (dc.textDocument && dc.edits) byUri.set(dc.textDocument.uri, [...(byUri.get(dc.textDocument.uri) || []), ...dc.edits]);
  const rootUri = norm(toUri(client.root.replace(/[\\/]$/, ""))) + "/";
  for (const [u, list] of byUri) {
    const nu = norm(u);
    if (!nu.startsWith(rootUri)) continue;
    const rel = nu.slice(rootUri.length);
    const model = m.editor.getModel(m.Uri.parse(modelUri(client.repoId, client.taskId, rel)));
    if (model) {
      model.pushEditOperations([], list.map(e => ({ range: new m.Range(e.range.start.line + 1, e.range.start.character + 1, e.range.end.line + 1, e.range.end.character + 1), text: e.newText })), () => null);
      continue;
    }
    const f = await apiGet<any>("ws/file", { repoId: client.repoId, taskId: client.taskId, path: rel });
    if (typeof f.text === "string") await apiPost("ws/file", { repoId: client.repoId, taskId: client.taskId, path: rel, text: applyEdits(f.text, list), mtime: f.mtime });
  }
}

/** Os símbolos do arquivo (classe › método…) para os breadcrumbs. Vazio se não há servidor de linguagem. */
export type Sym = { name: string; kind: number; range: { s: number; e: number }; sel: { line: number; col: number }; children: Sym[] };
const symCache = new Map<string, { v: number; syms: Promise<Sym[]> }>();
export function documentSymbols(model: Monaco.editor.ITextModel): Promise<Sym[]> {
  const x = byModel.get(model.uri.toString());
  if (!x) return Promise.resolve([]);
  const k = model.uri.toString(), v = model.getVersionId(), hit = symCache.get(k);
  if (hit && hit.v === v) return hit.syms;
  const syms = x.client.ready.then(async () => {
    if (!x.client.caps.documentSymbolProvider) return [];
    const r: any[] = (await x.client.request("textDocument/documentSymbol", { textDocument: { uri: x.uri } }).catch(() => null)) || [];
    const conv = (s: any): Sym => { const rg = s.range || s.location?.range, sr = s.selectionRange || rg;
      return { name: s.name, kind: s.kind || 1, range: { s: rg.start.line + 1, e: rg.end.line + 1 }, sel: { line: sr.start.line + 1, col: sr.start.character + 1 }, children: (s.children || []).map(conv) }; };
    const out = r.map(conv);
    // lista "plana" (SymbolInformation, sem filhos): monta a árvore pela contenção das linhas
    if (out.length && !r.some(s => s.children)) {
      out.sort((a, b) => a.range.s - b.range.s || b.range.e - a.range.e);
      const roots: Sym[] = [], stack: Sym[] = [];
      for (const s of out) {
        while (stack.length && stack[stack.length - 1].range.e < s.range.s) stack.pop();
        (stack.length ? stack[stack.length - 1].children : roots).push(s);
        stack.push(s);
      }
      return roots;
    }
    return out;
  }, () => []);
  symCache.set(k, { v, syms });
  return syms;
}

/** Aplica edições do LSP (linha/caractere) num texto — do fim para o começo, para as posições não mudarem. */
function applyEdits(text: string, edits: any[]) {
  const starts = [0];
  for (let i = 0; i < text.length; i++) if (text[i] === "\n") starts.push(i + 1);
  const off = (p: { line: number; character: number }) => Math.min(text.length, (starts[p.line] ?? text.length) + p.character);
  const sorted = [...edits].sort((a, b) => off(b.range.start) - off(a.range.start));
  let out = text;
  for (const e of sorted) out = out.slice(0, off(e.range.start)) + e.newText + out.slice(off(e.range.end));
  return out;
}

/** Ir para a definição (F12 / ⌘-clique), tratado pelo app: no mesmo arquivo, move o cursor; em outro, abre a aba. */
export async function gotoDefinition(editor: Monaco.editor.ICodeEditor, position: Monaco.Position) {
  const model = editor.getModel();
  const x = model && byModel.get(model.uri.toString());
  if (!model || !x) return false;
  if (!(await x.client.ready.then(() => true, () => false))) return false;
  const r = await x.client.request("textDocument/definition", { textDocument: { uri: x.uri }, position: { line: position.lineNumber - 1, character: position.column - 1 } }).catch(() => null);
  const l = (Array.isArray(r) ? r : r ? [r] : []).map((y: any) => ({ uri: y.targetUri || y.uri, range: y.targetSelectionRange || y.range }))[0];
  if (!l) return false;
  const rootUri = norm(toUri(x.root.replace(/[\\/]$/, ""))) + "/";
  if (!norm(l.uri).startsWith(rootUri)) return false;   // fora do projeto (biblioteca, node_modules): não abre
  const rel = norm(l.uri).slice(rootUri.length), line = l.range.start.line + 1;
  if (rel === x.rel) {
    editor.setPosition({ lineNumber: line, column: l.range.start.character + 1 });
    editor.revealLineInCenter(line);
  } else opener?.(rel, line);
  return true;
}
