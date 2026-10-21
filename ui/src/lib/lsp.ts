// Cliente LSP mínimo para o Monaco: um servidor por (projeto/tarefa, linguagem), pela ponte /ws/lsp do backend.
// Faz: abrir/alterar/fechar documento, erros (publishDiagnostics → marcações), autocompletar, hover, definição,
// referências (com "N referências" em cima das declarações), implementação, definição de tipo, renomear, símbolos,
// formatar, destaque semântico (cores pelo significado, como no VS Code), ocorrências do símbolo, dicas inline e
// correções rápidas (a lâmpada, ⌘.). Navegar para outro arquivo (⌘-clique, F12, o peek das referências) abre a aba dele.
import type * as Monaco from "monaco-editor";
import { get as apiGet, post as apiPost } from "./api";
import { edState, modelUri, scopeKey } from "./editorstate.svelte";
import { ui } from "./ui.svelte";

type Pending = { resolve: (v: any) => void; reject: (e: any) => void };
const LANGS = new Set(["typescript", "javascript", "python", "csharp", "go", "rust", "java", "php", "html", "css", "json", "dart"]);
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
              completion: { completionItem: { snippetSupport: false, documentationFormat: ["markdown", "plaintext"] } }, definition: { linkSupport: true }, publishDiagnostics: {},
              rename: { prepareSupport: false }, references: {}, implementation: { linkSupport: true }, typeDefinition: { linkSupport: true }, documentSymbol: { hierarchicalDocumentSymbolSupport: true },
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
/** Caminho relativo ao projeto de uma URI do servidor (null se é de fora: biblioteca, SDK, node_modules). No Windows o
 *  disco não diferencia maiúsculas: "file:///c:/Projetos/App" e "file:///C:/projetos/app" são a mesma pasta. */
function relIn(root: string, uri: string) {
  const r = norm(toUri(root.replace(/[\\/]$/, ""))) + "/", u = norm(uri);
  const hit = /^file:\/\/\/[a-z]:/.test(r) ? u.toLowerCase().startsWith(r.toLowerCase()) : u.startsWith(r);
  return hit ? u.slice(r.length) : null;
}
const clients = new Map<string, Client>();
const byModel = new Map<string, { client: Client; uri: string; root: string; rel: string }>();
let opener: ((rel: string, line: number) => void) | null = null;
// modelos "de espiar": arquivos sem aba que o peek (referências, definição) e a prévia do ⌘-hover mostram — com o
// texto do disco. Viram o documento da aba quando ela abre (Editor.loadDoc reaproveita o modelo).
const peeked = new Set<string>();
const fetching = new Map<string, Promise<void>>();
export const isPeek = (m: Monaco.editor.ITextModel) => peeked.has(m.uri.toString());
const registered = new Set<string>();

/** Liga um modelo do Monaco ao servidor de linguagem do projeto (se houver um instalado para a linguagem). */
export function attach(monaco: typeof Monaco, model: Monaco.editor.ITextModel, ctx: { repoId: string; taskId: string | null; root: string; rel: string },
  onStatus: (s: string) => void) {
  peeked.delete(model.uri.toString());   // virou aba de verdade
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
  const range = (r: any) => ({ startLineNumber: r.start.line + 1, startColumn: r.start.character + 1, endLineNumber: r.end.line + 1, endColumn: r.end.character + 1 });
  const textEdits = (list: any[]) => (list || []).map(e => ({ range: range(e.range), text: e.newText }));
  const relOf = (x: { root: string }, uri: string) => relIn(x.root, uri);
  // definição, referências, implementação e tipo: só as do projeto. Cada arquivo vira um modelo com o texto dele (o
  // peek mostra o trecho; abrir — ⌘-clique, duplo clique na lista — passa pelo opener abaixo, que abre a aba)
  const locations = async (model: Monaco.editor.ITextModel, x: { rel: string; root: string; client: Client }, r: any) => {
    const list = (Array.isArray(r) ? r : r ? [r] : []).map((l: any) => ({ uri: l.targetUri || l.uri, rg: l.targetSelectionRange || l.range }));
    const out = await Promise.all(list.map(async (l: any) => {
      const rel = relOf(x, l.uri);
      if (rel === null || !l.rg) return null;
      const target = rel === x.rel ? model.uri : await peekModel(monaco, x.client, rel);
      return target && monaco.editor.getModel(target) ? { uri: target, range: range(l.rg) } : null;
    }));
    return out.filter(Boolean) as Monaco.languages.Location[];
  };
  const nav = (method: string, cap: string) => async (model: Monaco.editor.ITextModel, position: Monaco.Position) => {
    const x = ctxOf(model); if (!x || !(await up(x)) || x.client.caps[cap] === false) return [];
    return locations(model, x, await x.client.request(method, { textDocument: { uri: x.uri }, position: pos(position) }).catch(() => null));
  };
  monaco.languages.registerDefinitionProvider(lang, { provideDefinition: nav("textDocument/definition", "definitionProvider") });
  monaco.languages.registerImplementationProvider(lang, { provideImplementation: nav("textDocument/implementation", "implementationProvider") });
  monaco.languages.registerTypeDefinitionProvider(lang, { provideTypeDefinition: nav("textDocument/typeDefinition", "typeDefinitionProvider") });
  monaco.languages.registerReferenceProvider(lang, {
    async provideReferences(model, position, context) {
      const x = ctxOf(model); if (!x || !(await up(x))) return [];
      const r = await x.client.request("textDocument/references", { textDocument: { uri: x.uri }, position: pos(position), context }, 60000).catch(() => null);
      return locations(model, x, r);
    },
  });
  // "N referências" em cima de classes, funções e métodos (como o VS Code no TypeScript): a contagem só é pedida ao
  // servidor para as que aparecem na tela; clicar abre o peek com a lista
  const LENS_KINDS = new Set([5, 6, 10, 11, 12, 23]);   // classe, método, enum, interface, função, struct
  monaco.languages.registerCodeLensProvider(lang, {
    async provideCodeLenses(model) {
      const x = ctxOf(model); if (!x || !(await up(x)) || !x.client.caps.referencesProvider) return { lenses: [], dispose() {} };
      const syms = await documentSymbols(model);
      const lenses: Monaco.languages.CodeLens[] = [];
      const walk = (l: Sym[]) => { for (const s of l) { if (LENS_KINDS.has(s.kind)) lenses.push({ range: { startLineNumber: s.sel.line, startColumn: s.sel.col, endLineNumber: s.sel.line, endColumn: s.sel.col }, id: `${s.sel.line}:${s.sel.col}` }); walk(s.children); } };
      walk(syms);
      return { lenses: lenses.slice(0, 300), dispose() {} };
    },
    async resolveCodeLens(model, lens) {
      const x = ctxOf(model); if (!x || !(await up(x))) return lens;
      const p = { lineNumber: lens.range.startLineNumber, column: lens.range.startColumn };
      const r: any[] = (await x.client.request("textDocument/references", { textDocument: { uri: x.uri }, position: { line: p.lineNumber - 1, character: p.column - 1 },
        context: { includeDeclaration: false } }, 60000).catch(() => null)) || [];
      const n = r.length;
      return { ...lens, command: { id: n ? "codeck.lsp.showRefs" : "", title: `${n} referência${n === 1 ? "" : "s"}`, arguments: [model.uri.toString(), p] } };
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
        const m = rel === x.rel ? model : openModel(monaco, x.client, rel);
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
  if (!navOnce) {
    navOnce = true;
    // outro arquivo do projeto (⌘-clique, F12, duplo clique no peek): a tela abre a aba dele e o cursor vai para a
    // linha/coluna. O mesmo arquivo do editor fica com o Monaco (move o cursor ali mesmo).
    monaco.editor.registerEditorOpener({
      openCodeEditor(src, resource, sel) {
        if (!opener || resource.toString() === src.getModel()?.uri.toString()) return false;
        const parts = resource.path.replace(/^\//, "").split("/");
        const scope = parts.shift() || "", rel = parts.join("/");
        if (resource.scheme !== "file" || !rel || ![...clients.values()].some(c => scopeKey(c.repoId, c.taskId) === scope)) return false;
        const line = sel && "startLineNumber" in sel ? sel.startLineNumber : (sel as any)?.lineNumber || 1;
        const col = sel && "startColumn" in sel ? sel.startColumn : (sel as any)?.column || 1;
        // o peek das referências reabriria no editor de origem: fecha (a aba nova assume)
        setTimeout(() => (src.getContribution("editor.contrib.referencesController") as any)?.closeWidget?.(false), 0);
        opener(rel, line);
        reveal(monaco, resource.toString(), line, col);
        return true;
      },
    });
    // "N referências": posiciona o cursor na declaração e abre o peek com a lista
    monaco.editor.registerCommand("codeck.lsp.showRefs", (_acc, uri: string, p: Monaco.IPosition) => {
      const ed = [edState.editor, ...monaco.editor.getEditors()].find(e => e?.getModel()?.uri.toString() === uri);
      if (!ed) return;
      ed.setPosition(p);
      ed.focus();
      ed.getAction("editor.action.referenceSearch.trigger")?.run();
    });
  }
}
let navOnce = false;

/** O modelo de um arquivo aberto numa aba (o de espiar não conta: editar nele não iria para o disco). */
function openModel(monaco: typeof Monaco, client: Client, rel: string) {
  const m = monaco.editor.getModel(monaco.Uri.parse(modelUri(client.repoId, client.taskId, rel)));
  return m && !peeked.has(m.uri.toString()) ? m : null;
}

/** Garante um modelo com o texto do arquivo (o da aba, se aberto; senão um de espiar, lido do disco). */
async function peekModel(monaco: typeof Monaco, client: Client, rel: string): Promise<Monaco.Uri | null> {
  const uri = monaco.Uri.parse(modelUri(client.repoId, client.taskId, rel)), k = uri.toString();
  const m = monaco.editor.getModel(uri);
  if (m && !peeked.has(k)) return uri;   // aberto numa aba: vale o texto do editor (inclusive o que está por salvar)
  let p = fetching.get(k);
  if (!p) {
    p = apiGet<any>("ws/file", { repoId: client.repoId, taskId: client.taskId, path: rel }).then(f => {
      if (typeof f.text !== "string" || f.binary || f.tooLarge) return;
      const cur = monaco.editor.getModel(uri);
      if (cur) { if (peeked.has(k) && cur.getValue() !== f.text) cur.setValue(f.text); return; }   // o disco mudou desde a última espiada
      monaco.editor.createModel(f.text, undefined, uri);
      peeked.add(k);
      // sem acumular: os de espiar mais antigos (que nenhum editor mostra) saem
      if (peeked.size > 150) for (const old of [...peeked].slice(0, peeked.size - 150)) {
        const om = monaco.editor.getModel(monaco.Uri.parse(old));
        if (om && monaco.editor.getEditors().some(e => e.getModel() === om)) continue;
        peeked.delete(old); om?.dispose();
      }
    }).catch(() => {}).finally(() => fetching.delete(k));
    fetching.set(k, p);
  }
  await p;
  return monaco.editor.getModel(uri) ? uri : null;
}

/** Depois de a tela abrir a aba: põe o cursor na linha/coluna certas (a aba só sabe a linha) e centraliza. */
function reveal(monaco: typeof Monaco, uri: string, line: number, col: number) {
  let n = 0;
  const tick = () => {
    const ed = [edState.editor, ...monaco.editor.getEditors()].find(e => e?.getModel()?.uri.toString() === uri && !!e.getContainerDomNode().offsetParent);
    if (ed) { ed.setPosition({ lineNumber: line, column: col }); ed.revealPositionInCenterIfOutsideViewport({ lineNumber: line, column: col }); ed.focus(); return; }
    if (++n < 80) setTimeout(tick, 50);   // a aba ainda está lendo o arquivo
  };
  setTimeout(tick, 0);
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
  for (const [u, list] of byUri) {
    const rel = relIn(client.root, u);
    if (rel === null) continue;
    const model = openModel(m, client, rel);
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
