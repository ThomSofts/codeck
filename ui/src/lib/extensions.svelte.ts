// Extensões do VS Code no Codeck: lista (as do VS Code/Cursor desta máquina, as embutidas do VS Code e as instaladas
// pelo Codeck via Open VSX), e o que dá para usar delas:
//   · tema de cores → o editor (Monaco), o terminal e, se ligado, o app inteiro (fundo, painéis, destaque, texto);
//   · tema de ícones → explorador, abas, ⌘P, controle de código-fonte;
//   · snippets → autocompletar no editor;
//   · linguagens → extensões de arquivo e comentários/colchetes de linguagens que o Monaco não conhece.
// Extensões que rodam código (depuradores, linters…) aparecem, mas marcadas como "precisa do VS Code".
import type * as Monaco from "monaco-editor";
import { ApiError, get, post } from "./api";
import { setExtTerminal } from "./exttheme";
import { icons, type IconSource } from "./fileicons.svelte";
import { loadMonaco, setEditorTheme } from "./monaco";
import { prefs } from "./prefs.svelte";
import { forceTheme } from "./theme";
import { ui } from "./ui.svelte";

export type ExtTheme = { label: string; id: string; uiTheme: string; path: string };
export type Ext = {
  id: string; key: string; source: string; builtin: boolean; removable: boolean; name: string; publisher: string; version: string;
  displayName: string; description: string; icon: string | null; categories: string[];
  themes: ExtTheme[]; iconThemes: { label: string; id: string; path: string }[]; snippets: { language: string; path: string }[];
  languages: { id: string; extensions: string[]; filenames: string[]; aliases: string[] }[]; grammars: number; code: boolean;
};
export type Market = { id: string; namespace: string; name: string; displayName: string; description: string; version: string; downloads: number;
  rating: number | null; icon: string | null; verified: boolean; installed: boolean; installedFrom: string | null };

const headers = () => ({ "X-Codeck-Token": window.CODECK_TOKEN || "" });
async function fetchBlob(key: string, path: string): Promise<Blob> {
  const r = await fetch(`/api/ext/file?${new URLSearchParams({ key, path })}`, { headers: headers() });
  if (!r.ok) throw new ApiError(`HTTP ${r.status}`, r.status);
  return r.blob();
}
/** junta caminhos relativos ("./icons/../a.svg") como o VS Code faz com os caminhos do tema */
function join(dir: string, rel: string) {
  const out: string[] = [];
  for (const p of (dir ? dir + "/" : "") .concat(rel).replace(/\\/g, "/").split("/")) {
    if (!p || p === ".") continue;
    if (p === "..") out.pop(); else out.push(p);
  }
  return out.join("/");
}

// ------------------------------------------------------------ tema VS Code → Monaco
const hex = (c?: string) => (typeof c === "string" && /^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(c.trim()) ? c.trim() : null);
function norm6(c: string) {
  let h = c.replace("#", "");
  if (h.length === 3 || h.length === 4) h = h.split("").map(x => x + x).join("");
  return h;
}
/** escopo TextMate → token do Monaco (os tokenizadores do Monaco usam nomes curtos: keyword, string, type…) */
function tokensFor(scope: string): string[] {
  const s = scope.trim();
  if (!s) return [];
  const m: [RegExp, string[]][] = [
    [/^comment/, ["comment"]],
    [/^string\.regexp/, ["regexp"]],
    [/^constant\.character\.escape/, ["string.escape"]],
    [/^support\.type\.property-name\.json|^meta\.object-literal\.key|^support\.type\.property-name/, ["string.key.json", "key", "attribute.name.css"]],
    [/^string/, ["string", "string.value.json", "attribute.value"]],
    [/^constant\.numeric/, ["number"]],
    [/^constant\.language/, ["keyword.json", "constant"]],
    [/^constant/, ["constant"]],
    [/^keyword\.operator/, ["operator"]],
    [/^keyword|^storage/, ["keyword"]],
    [/^entity\.name\.(type|class|struct|interface|enum)|^support\.(type|class)|^entity\.other\.inherited-class/, ["type", "type.identifier"]],
    [/^entity\.name\.namespace/, ["namespace"]],
    [/^entity\.name\.function|^support\.function|^meta\.function-call/, ["predefined", "function"]],
    [/^entity\.name\.tag/, ["tag"]],
    [/^entity\.other\.attribute-name/, ["attribute.name"]],
    [/^variable\.parameter/, ["variable.parameter"]],
    [/^variable\.language/, ["keyword.this", "variable.predefined"]],
    [/^variable/, ["variable"]],
    [/^meta\.annotation|^storage\.type\.annotation|^punctuation\.definition\.annotation/, ["annotation"]],
    [/^punctuation\.definition\.tag/, ["delimiter.html", "delimiter.xml"]],
    [/^punctuation/, ["delimiter"]],
    [/^markup\.heading/, ["keyword.md"]],
    [/^markup\.bold/, ["strong"]],
    [/^markup\.italic/, ["emphasis"]],
    [/^markup\.underline\.link/, ["string.link"]],
    [/^invalid/, ["invalid"]],
  ];
  for (const [re, toks] of m) if (re.test(s)) return toks;
  return [];
}
function toMonaco(t: { type: string; colors: Record<string, string>; tokenColors: any[] }): Monaco.editor.IStandaloneThemeData {
  const base = t.type === "light" ? "vs" : t.type === "hc" ? "hc-black" : "vs-dark";
  const fg = hex(t.colors["editor.foreground"] || t.colors["foreground"]);
  const bg = hex(t.colors["editor.background"]);
  const rules: Monaco.editor.ITokenThemeRule[] = [{ token: "", ...(fg ? { foreground: norm6(fg) } : {}), ...(bg ? { background: norm6(bg) } : {}) }];
  const seen = new Map<string, number>();
  for (const tc of t.tokenColors || []) {
    const st = tc?.settings || {};
    const f = hex(st.foreground);
    if (!f && !st.fontStyle) continue;
    if (!tc.scope) { if (f) rules[0] = { ...rules[0], foreground: norm6(f) }; continue; }
    const scopes: string[] = Array.isArray(tc.scope) ? tc.scope : String(tc.scope).split(",");
    for (const sc of scopes) {
      // escopo composto ("source.cs keyword"): o último pedaço manda
      const last = sc.trim().split(/\s+/).pop() || "";
      for (const tok of tokensFor(last)) {
        // a primeira regra que pega um token é a mais genérica; as seguintes (mais específicas) sobrescrevem
        const rule: Monaco.editor.ITokenThemeRule = { token: tok, ...(f ? { foreground: norm6(f) } : {}), ...(st.fontStyle !== undefined ? { fontStyle: String(st.fontStyle) } : {}) };
        const at = seen.get(tok);
        const specific = last.split(".").length;
        if (at === undefined) { seen.set(tok, rules.length); rules.push({ ...rule, _spec: specific } as any); }
        else if (specific <= ((rules[at] as any)._spec ?? 99)) rules[at] = { ...rule, _spec: specific } as any;
      }
    }
  }
  for (const r of rules) delete (r as any)._spec;
  const colors: Record<string, string> = {};
  for (const [k, v] of Object.entries(t.colors || {})) { const h = hex(v); if (h) colors[k] = h; }
  return { base, inherit: true, rules, colors };
}

// ------------------------------------------------------------ tema VS Code → cores do app
/** texto legível sobre a cor de destaque (amarelo do Ayu pede texto escuro; azul do Dark+, branco) */
function inkFor(c: string) {
  const h = norm6(c).slice(0, 6);
  const [r, g, b] = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255).map(v => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.4 ? "#14161c" : "#ffffff";
}
function appCss(t: { type: string; colors: Record<string, string> }) {
  const c = (k: string) => hex(t.colors[k]);
  const ed = c("editor.background") || (t.type === "light" ? "#ffffff" : "#1e1e1e");
  const fg = c("foreground") || c("editor.foreground") || (t.type === "light" ? "#1f2328" : "#cccccc");
  const side = c("sideBar.background") || c("activityBar.background") || ed;
  const panel = c("panel.background") || c("editorGroupHeader.tabsBackground") || side;
  const accent = c("focusBorder") || c("button.background") || c("activityBarBadge.background") || c("textLink.foreground") || "#6f8cff";
  const mix = (a: string, b: string, p: number) => `color-mix(in srgb, ${a} ${p}%, ${b})`;
  const line = c("sideBar.border") || c("panel.border") || c("editorGroup.border");
  const v: Record<string, string> = {
    "--bg": c("titleBar.activeBackground") || mix(side, "#000", 92),
    "--bg-2": side,
    "--surface": ed,
    "--surface-2": mix(fg, ed, 5),
    "--surface-3": mix(fg, ed, 9),
    "--elevated": c("editorWidget.background") || c("menu.background") || mix(fg, ed, 6),
    "--line": line ? mix(line, "transparent", 70) : mix(fg, "transparent", 8),
    "--line-2": mix(fg, "transparent", 13),
    "--line-3": mix(fg, "transparent", 20),
    "--text": fg,
    "--text-2": mix(fg, ed, 78),
    "--muted": c("descriptionForeground") || mix(fg, ed, 58),
    "--faint": mix(fg, ed, 40),
    "--accent": accent,
    "--accent-ink": inkFor(accent),
    "--accent-soft": mix(accent, "transparent", 14),
    "--accent-line": mix(accent, "transparent", 40),
    "--ed-bg": ed,
    "--panel-bg": panel,
  };
  const good = c("gitDecoration.addedResourceForeground") || c("terminal.ansiGreen");
  const bad = c("errorForeground") || c("editorError.foreground") || c("terminal.ansiRed");
  const warn = c("editorWarning.foreground") || c("terminal.ansiYellow");
  if (good) Object.assign(v, { "--good": good, "--good-soft": mix(good, "transparent", 13) });
  if (bad) Object.assign(v, { "--bad": bad, "--bad-soft": mix(bad, "transparent", 13) });
  if (warn) Object.assign(v, { "--warn": warn, "--warn-soft": mix(warn, "transparent", 13) });
  return `:root[data-ext-theme] {\n${Object.entries(v).map(([k, x]) => `  ${k}: ${x};`).join("\n")}\n}`;
}
function terminalColors(t: { type: string; colors: Record<string, string> }) {
  const c = (k: string) => hex(t.colors[k]) || undefined;
  const ed = c("terminal.background") || c("panel.background") || c("editor.background");
  if (!ed) return null;
  const names = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"];
  const out: Record<string, string> = { background: ed, foreground: c("terminal.foreground") || c("editor.foreground") || "#cccccc",
    cursor: c("terminalCursor.foreground") || c("editorCursor.foreground") || "#aeafad", selectionBackground: c("terminal.selectionBackground") || c("editor.selectionBackground") || "#264f78" };
  for (const n of names) {
    const cap = n[0].toUpperCase() + n.slice(1);
    const a = c("terminal.ansi" + cap), b = c("terminal.ansiBright" + cap);
    if (a) out[n] = a;
    if (b) out["bright" + cap] = b;
  }
  return out;
}

// ------------------------------------------------------------ estado
class Extensions {
  list = $state<Ext[]>([]);
  vscodeSettings = $state<{ app: string; settings: Record<string, any> }[]>([]);
  loaded = $state(false);
  loading = $state(false);
  activeTheme = $state<{ ext: string; id: string; label: string; type: string } | null>(null);
  activeIcons = $state<{ ext: string; id: string; label: string } | null>(null);
  private snippetSubs: Monaco.IDisposable[] = [];
  private restored = false;

  async load(refresh = false) {
    this.loading = true;
    try {
      const r = await get<{ extensions: Ext[]; vscodeSettings: any[] }>("ext/list", refresh ? { refresh: 1 } : undefined);
      this.list = r.extensions; this.vscodeSettings = r.vscodeSettings; this.loaded = true;
    } catch (e) { ui.error(e); }
    this.loading = false;
  }
  get themes() { return this.list.flatMap(e => e.themes.map(t => ({ ext: e, theme: t }))); }
  get iconThemes() { return this.list.flatMap(e => e.iconThemes.map(t => ({ ext: e, theme: t }))); }
  enabled(e: Ext) { return !prefs.get("ext.disabled").includes(e.id); }

  /** Tema de cores. null volta ao do Codeck. */
  async applyTheme(e: Ext | null, t?: ExtTheme, save = true) {
    if (!e || !t) {
      setEditorTheme(null); setExtTerminal(null); this.paintApp(null); forceTheme(null);
      this.activeTheme = null;
      if (save) prefs.set("workbench.colorTheme", "");
      return;
    }
    try {
      const th = await get<{ name: string; type: string; colors: Record<string, string>; tokenColors: any[] }>("ext/theme", { key: e.key, path: t.path });
      setEditorTheme({ id: `${e.id}|${t.id}`, data: toMonaco(th) });
      const appOn = prefs.get("workbench.themeApp");
      setExtTerminal(terminalColors(th));
      this.paintApp(appOn ? appCss(th) : null);
      forceTheme(appOn ? (th.type === "light" ? "light" : "dark") : null);
      document.documentElement.dataset.extTheme = String(Date.now());   // terminal e afins repintam
      if (!appOn) delete document.documentElement.dataset.extTheme;
      this.activeTheme = { ext: e.id, id: t.id, label: t.label, type: th.type };
      if (save) prefs.set("workbench.colorTheme", `${e.id}|${t.id}`);
    } catch (err) { ui.error(err); }
  }
  private paintApp(css: string | null) {
    let el = document.getElementById("cd-ext-theme") as HTMLStyleElement | null;
    if (!css) { el?.remove(); delete document.documentElement.dataset.extTheme; return; }
    if (!el) { el = document.createElement("style"); el.id = "cd-ext-theme"; document.head.appendChild(el); }
    el.textContent = css;
  }

  /** Tema de ícones. null volta ao embutido. */
  async applyIcons(e: Ext | null, t?: { id: string; label: string; path: string }, save = true) {
    if (!e || !t) { await icons.use(null); this.activeIcons = null; if (save) prefs.set("workbench.iconTheme", ""); return; }
    try {
      const json = await get<any>("ext/json", { key: e.key, path: t.path });
      const dir = t.path.replace(/\\/g, "/").replace(/^\.\//, "").split("/").slice(0, -1).join("/");
      const src: IconSource = { id: `${e.id}-${t.id}`, label: t.label, blob: (rel) => fetchBlob(e.key, join(dir, rel)) };
      await icons.use(src, json);
      this.activeIcons = { ext: e.id, id: t.id, label: t.label };
      if (save) prefs.set("workbench.iconTheme", `${e.id}|${t.id}`);
    } catch (err) { ui.error(err); }
  }

  /** Snippets e linguagens das extensões ligadas → autocompletar e configurações no Monaco. */
  async applyContributions() {
    for (const s of this.snippetSubs) s.dispose();
    this.snippetSubs = [];
    const exts = this.list.filter(e => this.enabled(e) && (e.snippets.length || e.languages.length) && !e.builtin);
    if (!exts.length) return;
    const monaco = await loadMonaco();
    const known = new Set(monaco.languages.getLanguages().map(l => l.id));
    const LANG: Record<string, string> = { typescriptreact: "typescript", javascriptreact: "javascript", shellscript: "shell", jsonc: "json", aspnetcorerazor: "razor" };
    const byLang = new Map<string, { label: string; insert: string; doc: string; ext: string }[]>();
    for (const e of exts) {
      for (const l of e.languages) {
        if (known.has(l.id)) continue;
        monaco.languages.register({ id: l.id, extensions: l.extensions, filenames: l.filenames, aliases: l.aliases });
        known.add(l.id);
        get<{ languages: { id: string; configuration: any }[] }>("ext/languages", { key: e.key }).then(r => {
          const cfg = r.languages.find(x => x.id === l.id)?.configuration;
          if (!cfg) return;
          try {
            monaco.languages.setLanguageConfiguration(l.id, { comments: cfg.comments, brackets: cfg.brackets,
              autoClosingPairs: (cfg.autoClosingPairs || []).map((p: any) => (Array.isArray(p) ? { open: p[0], close: p[1] } : p)),
              surroundingPairs: (cfg.surroundingPairs || []).map((p: any) => (Array.isArray(p) ? { open: p[0], close: p[1] } : p)) });
          } catch { /* configuração com regex que o Monaco não aceita: fica sem */ }
        }).catch(() => {});
      }
      if (!e.snippets.length) continue;
      try {
        const r = await get<{ snippets: { language: string; prefix: string; body: string; description: string; name: string }[] }>("ext/snippets", { key: e.key });
        for (const s of r.snippets) {
          const lang = LANG[s.language] || s.language;
          const arr = byLang.get(lang) || [];
          arr.push({ label: s.prefix, insert: s.body, doc: s.description || s.name, ext: e.displayName });
          byLang.set(lang, arr);
        }
      } catch { /* extensão sem snippets legíveis */ }
    }
    for (const [lang, items] of byLang) {
      this.snippetSubs.push(monaco.languages.registerCompletionItemProvider(lang, {
        provideCompletionItems(model, position) {
          const w = model.getWordUntilPosition(position);
          const range = { startLineNumber: position.lineNumber, endLineNumber: position.lineNumber, startColumn: w.startColumn, endColumn: w.endColumn };
          return { suggestions: items.map(i => ({ label: { label: i.label, description: i.ext }, kind: monaco.languages.CompletionItemKind.Snippet,
            insertText: i.insert, insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, documentation: i.doc, range, sortText: "~" + i.label })) };
        },
      }));
    }
  }

  /** Na abertura do app: volta o tema de cores, de ícones e os snippets escolhidos. */
  async restore() {
    if (this.restored) return;
    this.restored = true;
    const ct = prefs.get("workbench.colorTheme"), it = prefs.get("workbench.iconTheme");
    if (!this.loaded) await this.load();
    if (ct) { const [eid, tid] = ct.split("|"); const e = this.list.find(x => x.id === eid); const t = e?.themes.find(x => x.id === tid || x.label === tid); if (e && t) await this.applyTheme(e, t, false); }
    if (it) { const [eid, tid] = it.split("|"); const e = this.list.find(x => x.id === eid); const t = e?.iconThemes.find(x => x.id === tid); if (e && t) await this.applyIcons(e, t, false); }
    this.applyContributions().catch(() => {});
  }

  /** "Usar a aparência do VS Code": tema, ícones, fonte e ajustes do editor das configurações dele. */
  async importVscode(s: Record<string, any>) {
    const found: string[] = [];
    if (s["workbench.colorTheme"]) {
      const want = String(s["workbench.colorTheme"]).toLowerCase();
      const hit = this.themes.find(x => x.theme.id?.toLowerCase() === want || x.theme.label?.toLowerCase() === want);
      if (hit) { await this.applyTheme(hit.ext, hit.theme); found.push(`tema ${hit.theme.label}`); }
    }
    if (s["workbench.iconTheme"]) {
      const want = String(s["workbench.iconTheme"]).toLowerCase();
      const hit = this.iconThemes.find(x => x.theme.id?.toLowerCase() === want);
      if (hit) { await this.applyIcons(hit.ext, hit.theme); found.push(`ícones ${hit.theme.label}`); }
    }
    const fam = s["editor.fontFamily"];
    if (typeof fam === "string" && fam.trim()) { prefs.set("editor.fontFamily", fam.split(",")[0].replace(/['"]/g, "").trim()); found.push("fonte"); }
    if (typeof s["editor.fontSize"] === "number") prefs.set("editor.fontSize", s["editor.fontSize"]);
    if (s["editor.fontLigatures"] !== undefined) prefs.set("editor.ligatures", !!s["editor.fontLigatures"]);
    if (typeof s["editor.tabSize"] === "number") prefs.set("editor.tabSize", s["editor.tabSize"]);
    if (s["editor.minimap.enabled"] !== undefined) prefs.set("editor.minimap", !!s["editor.minimap.enabled"]);
    if (s["editor.wordWrap"] !== undefined) prefs.set("editor.wordWrap", s["editor.wordWrap"] === "on");
    if (s["editor.stickyScroll.enabled"] !== undefined) prefs.set("editor.stickyScroll", !!s["editor.stickyScroll.enabled"]);
    if (s["editor.formatOnSave"] !== undefined) prefs.set("editor.formatOnSave", !!s["editor.formatOnSave"]);
    if (typeof s["editor.renderWhitespace"] === "string") prefs.set("editor.renderWhitespace", s["editor.renderWhitespace"] as any);
    if (typeof s["editor.cursorStyle"] === "string" && ["line", "block", "underline"].includes(s["editor.cursorStyle"])) prefs.set("editor.cursorStyle", s["editor.cursorStyle"] as any);
    if (s["files.autoSave"] === "afterDelay" || s["files.autoSave"] === "onFocusChange" || s["files.autoSave"] === "off") prefs.set("editor.autoSave", s["files.autoSave"]);
    if (typeof s["terminal.integrated.fontSize"] === "number") prefs.set("terminal.fontSize", s["terminal.integrated.fontSize"]);
    ui.toast(found.length ? `Aparência do VS Code aplicada: ${found.join(", ")}` : "Ajustes do editor aplicados (o tema dele não está entre as extensões encontradas)", "ok");
  }

  // ------------------------------------------------------------ Open VSX
  async search(q: string, category?: string) { return get<{ results: Market[]; total: number }>("ext/search", { q, category }); }
  async install(m: { namespace: string; name: string; displayName?: string }) {
    const prog = ui.progress(`Instalando ${m.displayName || m.name}…`);
    try {
      const r = await post<{ extension: Ext }>("ext/install", { namespace: m.namespace, name: m.name });
      await this.load(true);
      await this.applyContributions();
      prog.done(`${m.displayName || m.name} instalada`);
      return r.extension;
    } catch (e) { prog.fail(e); return null; }
  }
  async uninstall(e: Ext) {
    if (!(await ui.ask({ title: `Desinstalar ${e.displayName}?`, message: "Ela sai do Codeck (as do VS Code/Cursor ficam onde estão).", confirm: "Desinstalar", danger: true }))) return;
    try {
      if (this.activeTheme?.ext === e.id) await this.applyTheme(null);
      if (this.activeIcons?.ext === e.id) await this.applyIcons(null);
      await post("ext/uninstall", { key: e.key });
      await this.load(true);
      await this.applyContributions();
      ui.toast("Extensão desinstalada");
    } catch (err) { ui.error(err); }
  }
  toggle(e: Ext) {
    const d = prefs.get("ext.disabled");
    prefs.set("ext.disabled", d.includes(e.id) ? d.filter(x => x !== e.id) : [...d, e.id]);
    this.applyContributions().catch(() => {});
  }
}

export const extensions = new Extensions();
export { fetchBlob };
