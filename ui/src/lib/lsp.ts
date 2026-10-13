// Cliente LSP mínimo para o Monaco: um servidor por (projeto/tarefa, linguagem), pela ponte /ws/lsp do backend.
// Faz: abrir/alterar/fechar documento, erros (publishDiagnostics → marcações), autocompletar, hover e ir para a definição.
import type * as Monaco from "monaco-editor";

type Pending = { resolve: (v: any) => void; reject: (e: any) => void };
const LANGS = new Set(["typescript", "javascript", "python", "csharp", "go", "rust", "java", "php", "html", "css", "json"]);

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
              completion: { completionItem: { snippetSupport: false, documentationFormat: ["markdown", "plaintext"] } }, definition: {}, publishDiagnostics: {} },
              workspace: { workspaceFolders: true, configuration: true } } });
          this.caps = r?.capabilities || {};
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
      if (m.id != null && m.method) {   // pedido do servidor (configuração, registro, progresso): responde algo neutro
        const result = m.method === "workspace/configuration" ? (m.params?.items || []).map(() => null) : null;
        this.ws.send(JSON.stringify({ jsonrpc: "2.0", id: m.id, result }));
      }
    };
    this.ws.onclose = () => { if (this.status === "ativo") { this.status = "desconectado"; onStatus("desconectado"); } };
  }
  request(method: string, params: any): Promise<any> {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error("tempo esgotado")); } }, 15000);
    });
  }
  notify(method: string, params: any) { if (this.ws.readyState === 1) this.ws.send(JSON.stringify({ jsonrpc: "2.0", method, params })); }
  diagnostics(p: { uri: string; diagnostics: any[] }) {
    const d = this.docs.get(norm(p.uri));
    if (!d) return;
    const S = this.monaco.MarkerSeverity;
    this.monaco.editor.setModelMarkers(d.model, "lsp", p.diagnostics.map(x => ({
      severity: [S.Error, S.Error, S.Warning, S.Info, S.Hint][x.severity || 1], message: x.message, source: x.source,
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
  const md = (c: any): string => (typeof c === "string" ? c : Array.isArray(c) ? c.map(md).join("\n\n") : c?.kind ? c.value : c?.language ? "```" + c.language + "\n" + c.value + "\n```" : c?.value || "");
  monaco.languages.registerHoverProvider(lang, {
    async provideHover(model, position) {
      const x = ctxOf(model); if (!x) return null;
      await x.client.ready;
      const r = await x.client.request("textDocument/hover", { textDocument: { uri: x.uri }, position: pos(position) }).catch(() => null);
      return r?.contents ? { contents: [{ value: md(r.contents) }] } : null;
    },
  });
  monaco.languages.registerCompletionItemProvider(lang, {
    triggerCharacters: [".", ":", "<", '"', "/", "@"],
    async provideCompletionItems(model, position) {
      const x = ctxOf(model); if (!x) return { suggestions: [] };
      await x.client.ready;
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
      const x = ctxOf(model); if (!x) return null;
      await x.client.ready;
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


/** Ir para a definição (F12 / ⌘-clique), tratado pelo app: no mesmo arquivo, move o cursor; em outro, abre a aba. */
export async function gotoDefinition(editor: Monaco.editor.ICodeEditor, position: Monaco.Position) {
  const model = editor.getModel();
  const x = model && byModel.get(model.uri.toString());
  if (!model || !x) return false;
  await x.client.ready;
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
