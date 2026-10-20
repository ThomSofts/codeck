// Monaco (o editor do VS Code), carregado sob demanda: só baixa quando o primeiro arquivo é aberto.
import type * as Monaco from "monaco-editor";
import { kb } from "./keybindings.svelte";
import { get } from "./api";
import { builtinOff } from "./lsp";

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
    // cores de sintaxe do VS Code (Dark Modern / Light Modern), com o fundo do Codeck. As regras sem ponto ("function",
    // "parameter"…) são os tokens semânticos do servidor de linguagem — é o que dá cor a função, tipo, parâmetro e
    // propriedade, como no VS Code (a gramática sozinha só conhece palavra-chave, texto e número).
    const dark: Record<string, string> = {
      comment: "6A9955", keyword: "569CD6", "keyword.flow": "C586C0", "keyword.control": "C586C0", string: "CE9178", "string.escape": "D7BA7D",
      "string.key.json": "9CDCFE", "string.value.json": "CE9178", number: "B5CEA8", regexp: "D16969", type: "4EC9B0", "type.identifier": "4EC9B0",
      identifier: "9CDCFE", variable: "9CDCFE", "variable.predefined": "4FC1FF", constant: "4FC1FF", delimiter: "D4D4D4", operator: "D4D4D4",
      tag: "569CD6", "metatag": "569CD6", "attribute.name": "9CDCFE", "attribute.value": "CE9178", annotation: "DCDCAA", key: "9CDCFE",
      namespace: "4EC9B0", class: "4EC9B0", enum: "4EC9B0", interface: "4EC9B0", struct: "4EC9B0", typeParameter: "4EC9B0",
      parameter: "9CDCFE", property: "9CDCFE", enumMember: "4FC1FF", event: "9CDCFE", function: "DCDCAA", method: "DCDCAA", member: "DCDCAA", macro: "569CD6",
      decorator: "DCDCAA", "variable.readonly": "4FC1FF", "property.readonly": "4FC1FF", "variable.defaultLibrary": "4EC9B0", "class.defaultLibrary": "4EC9B0",
    };
    const light: Record<string, string> = {
      comment: "008000", keyword: "0000FF", "keyword.flow": "AF00DB", "keyword.control": "AF00DB", string: "A31515", "string.escape": "EE0000",
      "string.key.json": "0451A5", "string.value.json": "A31515", number: "098658", regexp: "811F3F", type: "267F99", "type.identifier": "267F99",
      identifier: "001080", variable: "001080", "variable.predefined": "0070C1", constant: "0070C1", delimiter: "000000", operator: "000000",
      tag: "800000", metatag: "800000", "attribute.name": "E50000", "attribute.value": "0000FF", annotation: "795E26", key: "0451A5",
      namespace: "267F99", class: "267F99", enum: "267F99", interface: "267F99", struct: "267F99", typeParameter: "267F99",
      parameter: "001080", property: "001080", enumMember: "0070C1", event: "001080", function: "795E26", method: "795E26", member: "795E26", macro: "0000FF",
      decorator: "795E26", "variable.readonly": "0070C1", "property.readonly": "0070C1", "variable.defaultLibrary": "267F99", "class.defaultLibrary": "267F99",
    };
    const rules = (m: Record<string, string>) => [...Object.entries(m).map(([token, foreground]) => ({ token, foreground })),
      { token: "comment.doc", foreground: m.comment }, { token: "deprecated", fontStyle: "strikethrough" }];
    monaco.editor.defineTheme("codeck-dark", {
      base: "vs-dark", inherit: true, rules: rules(dark),
      colors: { "editor.background": "#12151c", "editor.foreground": "#d4d4d4", "editor.lineHighlightBackground": "#1a1f2a", "editor.lineHighlightBorder": "#00000000",
        "editorLineNumber.foreground": "#4a5163", "editorLineNumber.activeForeground": "#c6cbd6", "editor.selectionBackground": "#264f78",
        "editor.inactiveSelectionBackground": "#3a3d4166", "editor.selectionHighlightBackground": "#add6ff26", "editor.wordHighlightBackground": "#575757b8",
        "editor.wordHighlightStrongBackground": "#004972b8", "editor.findMatchHighlightBackground": "#ea5c0055", "editorCursor.foreground": "#aeafad",
        "editorIndentGuide.background1": "#262b36", "editorIndentGuide.activeBackground1": "#4b5263", "editorBracketMatch.background": "#0064001a",
        "editorBracketMatch.border": "#888888", "editorWidget.background": "#1a1f29", "editorWidget.border": "#2b3140", "editorSuggestWidget.selectedBackground": "#04395e",
        "editorHoverWidget.background": "#1a1f29", "editorHoverWidget.border": "#2b3140", "editorGutter.background": "#12151c", "editorInlayHint.foreground": "#969696",
        "editorInlayHint.background": "#ffffff0f", "editorLightBulb.foreground": "#ffcc00", "editorStickyScroll.background": "#12151c",
        "editorStickyScrollHover.background": "#1f2430", "minimap.background": "#12151c", "scrollbarSlider.background": "#79797933",
        "scrollbarSlider.hoverBackground": "#64646459", "editorOverviewRuler.border": "#00000000",
        "diffEditor.insertedLineBackground": "#3ccf9112", "diffEditor.insertedTextBackground": "#3ccf912e", "diffEditor.removedLineBackground": "#ff6b7d12",
        "diffEditor.removedTextBackground": "#ff6b7d33", "diffEditorGutter.insertedLineBackground": "#3ccf9126", "diffEditorGutter.removedLineBackground": "#ff6b7d26",
        "diffEditor.unchangedRegionBackground": "#0e1117" },
    });
    monaco.editor.defineTheme("codeck-light", { base: "vs", inherit: true, rules: rules(light), colors: { "editor.background": "#ffffff",
      "editor.lineHighlightBackground": "#f3f5f9", "editor.lineHighlightBorder": "#00000000", "editorInlayHint.foreground": "#868686", "editorInlayHint.background": "#0000000a",
      "diffEditor.insertedLineBackground": "#0f9f6612", "diffEditor.insertedTextBackground": "#0f9f662b", "diffEditor.removedLineBackground": "#e0384f10",
      "diffEditor.removedTextBackground": "#e0384f2b" } });
    try {
      const r = await get<{ servers: Record<string, string> }>("lsp");
      for (const l of ["typescript", "javascript"]) if (r.servers[l]) builtinOff(monaco, l);
    } catch { /* sem a lista: fica o embutido */ }
    loaded = monaco;
    kb.attachMonaco(monaco);   // atalhos do VS Code (e os personalizados) também dentro do editor
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
