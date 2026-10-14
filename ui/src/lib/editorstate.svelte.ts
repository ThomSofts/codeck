// Estado do editor em foco, para a barra de status (como a do VS Code): linha/coluna, seleção, linguagem, fim de linha,
// indentação, servidor de linguagem e a contagem de problemas de todos os arquivos abertos.
import type * as Monaco from "monaco-editor";

export const edState = $state({
  path: "" as string,
  line: 0, col: 0, sel: 0, lines: 0,
  lang: "" as string,
  eol: "LF" as "LF" | "CRLF",
  indent: "" as string,
  lsp: "" as string,
  errors: 0, warnings: 0,
  /** o editor em foco (para "ir para linha", trocar linguagem, EOL…) */
  editor: null as Monaco.editor.ICodeEditor | null,
});

export type Problem = { scope?: string; path: string; line: number; col: number; message: string; severity: "error" | "warning" | "info"; source?: string; code?: string };
/** problemas do servidor de linguagem (marcações do Monaco) + os da última compilação (.NET/MSBuild) */
export const problems = $state<{ lsp: Problem[]; build: Problem[]; buildAt: string | null }>({ lsp: [], build: [], buildAt: null });

let monacoRef: typeof Monaco | null = null;
/** URI do modelo de um arquivo do projeto: file:///<repoId>-<tarefa|main>/<caminho> (ver Editor.svelte). */
export const modelUri = (repoId: string, taskId: string | null | undefined, rel: string) => `file:///${encodeURIComponent(repoId + "-" + (taskId || "main"))}/${rel}`;
export const scopeKey = (repoId: string, taskId: string | null | undefined) => repoId + "-" + (taskId || "main");
function relOf(uri: string): { scope: string; path: string } | null {
  const m = /^file:\/\/\/([^/]+)\/(.+)$/.exec(uri);
  if (!m) return null;
  try { return { scope: decodeURIComponent(m[1]), path: decodeURIComponent(m[2]) }; } catch { return null; }
}
/** Junta as marcações de todos os modelos abertos (chamado quando as marcações mudam). */
export function trackMarkers(monaco: typeof Monaco) {
  if (monacoRef) return;
  monacoRef = monaco;
  const sync = () => {
    const S = monaco.MarkerSeverity;
    const out: Problem[] = [];
    for (const m of monaco.editor.getModelMarkers({})) {
      if (m.severity < S.Warning) continue;
      const r = relOf(m.resource.toString());
      if (!r) continue;
      out.push({ scope: r.scope, path: r.path, line: m.startLineNumber, col: m.startColumn, message: m.message, severity: m.severity === S.Error ? "error" : "warning",
        source: m.source, code: typeof m.code === "string" ? m.code : (m.code as any)?.value });
    }
    problems.lsp = out;
    const all = [...out, ...problems.build];
    edState.errors = all.filter(p => p.severity === "error").length;
    edState.warnings = all.filter(p => p.severity === "warning").length;
  };
  let t: ReturnType<typeof setTimeout> | undefined;
  monaco.editor.onDidChangeMarkers(() => { clearTimeout(t); t = setTimeout(sync, 200); });
}
export function setBuildProblems(list: Problem[]) {
  problems.build = list;
  problems.buildAt = new Date().toISOString();
  const all = [...problems.lsp, ...list];
  edState.errors = all.filter(p => p.severity === "error").length;
  edState.warnings = all.filter(p => p.severity === "warning").length;
}
