// Monaco (o editor do VS Code), carregado sob demanda: só baixa quando o primeiro arquivo é aberto.
import type * as Monaco from "monaco-editor";

let loading: Promise<typeof Monaco> | null = null;

export function loadMonaco(): Promise<typeof Monaco> {
  if (loading) return loading;
  loading = (async () => {
    const [monaco, editorW, jsonW, cssW, htmlW, tsW] = await Promise.all([
      import("monaco-editor"),
      import("monaco-editor/esm/vs/editor/editor.worker?worker"),
      import("monaco-editor/esm/vs/language/json/json.worker?worker"),
      import("monaco-editor/esm/vs/language/css/css.worker?worker"),
      import("monaco-editor/esm/vs/language/html/html.worker?worker"),
      import("monaco-editor/esm/vs/language/typescript/ts.worker?worker"),
    ]);
    (self as any).MonacoEnvironment = {
      getWorker(_: string, label: string) {
        if (label === "json") return new jsonW.default();
        if (["css", "scss", "less"].includes(label)) return new cssW.default();
        if (["html", "handlebars", "razor"].includes(label)) return new htmlW.default();
        if (["typescript", "javascript"].includes(label)) return new tsW.default();
        return new editorW.default();
      },
    };
    // o Monaco cancela buscas em andamento quando o arquivo troca (rejeita com "Canceled"): é esperado, não é erro
    // (idem "no diff result available": o diff foi fechado no meio do cálculo)
    window.addEventListener("unhandledrejection", e => {
      const m = e.reason?.message || "";
      if (e.reason?.name === "Canceled" || m === "Canceled" || m === "no diff result available") e.preventDefault();
    });
    // o TypeScript embutido não conhece o projeto (sem node_modules): sem erros falsos de import
    monaco.languages.typescript.typescriptDefaults.setDiagnosticsOptions({ noSemanticValidation: true, noSyntaxValidation: false });
    monaco.languages.typescript.javascriptDefaults.setDiagnosticsOptions({ noSemanticValidation: true, noSyntaxValidation: false });
    if ((window as any).__CD_SELFTEST) (window as any).__cdMonaco = monaco;   // autoteste: marcações e modelos
    monaco.editor.defineTheme("codeck-dark", {
      base: "vs-dark", inherit: true, rules: [
        { token: "comment", foreground: "6e778c", fontStyle: "italic" }, { token: "keyword", foreground: "b07cff" },
        { token: "string", foreground: "3ccf91" }, { token: "number", foreground: "f5b84f" }, { token: "type", foreground: "4fc3f7" },
      ],
      colors: { "editor.background": "#12151c", "editor.lineHighlightBackground": "#171b24", "editorLineNumber.foreground": "#4a5163",
        "editorLineNumber.activeForeground": "#a7aec0", "editor.selectionBackground": "#6f8cff40", "editorCursor.foreground": "#8ba3ff",
        "editorIndentGuide.background1": "#1d222d", "editorWidget.background": "#1a1f29", "editorGutter.background": "#12151c",
        "minimap.background": "#12151c", "scrollbarSlider.background": "#ffffff14",
        "diffEditor.insertedLineBackground": "#3ccf9112", "diffEditor.insertedTextBackground": "#3ccf912e", "diffEditor.removedLineBackground": "#ff6b7d12",
        "diffEditor.removedTextBackground": "#ff6b7d33", "diffEditorGutter.insertedLineBackground": "#3ccf9126", "diffEditorGutter.removedLineBackground": "#ff6b7d26",
        "diffEditor.unchangedRegionBackground": "#0e1117" },
    });
    monaco.editor.defineTheme("codeck-light", { base: "vs", inherit: true, rules: [], colors: { "editor.background": "#ffffff",
      "diffEditor.insertedLineBackground": "#0f9f6612", "diffEditor.insertedTextBackground": "#0f9f662b", "diffEditor.removedLineBackground": "#e0384f10",
      "diffEditor.removedTextBackground": "#e0384f2b" } });
    loaded = monaco;
    if (ext) monaco.editor.defineTheme("cd-ext", ext.data);
    return monaco;
  })();
  return loading;
}

// ------------------------------------------------------------ tema de cores (o do Codeck ou o de uma extensão do VS Code)
let loaded: typeof Monaco | null = null;
let ext: { id: string; data: Monaco.editor.IStandaloneThemeData } | null = null;
const listeners = new Set<() => void>();
let observer: MutationObserver | null = null;
const fire = () => { for (const l of listeners) l(); };

/** Tema de uma extensão (já convertido para o formato do Monaco) — null volta ao do Codeck. */
export function setEditorTheme(t: { id: string; data: Monaco.editor.IStandaloneThemeData } | null) {
  ext = t;
  if (loaded && t) loaded.editor.defineTheme("cd-ext", t.data);
  if (loaded) loaded.editor.setTheme(monacoTheme());
  fire();
}
export const monacoTheme = () => (ext ? "cd-ext" : document.documentElement.dataset.theme === "light" ? "codeck-light" : "codeck-dark");
/** Avisa quando o tema muda (claro/escuro do app ou tema de extensão). */
export function onThemeChange(cb: () => void): { dispose(): void } {
  listeners.add(cb);
  if (!observer) {
    observer = new MutationObserver(fire);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }
  return { dispose: () => listeners.delete(cb) };
}
