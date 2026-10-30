// Atalhos de teclado como os do VS Code, personalizáveis (Configurações → Atalhos). Cada comando tem um id (o mesmo do
// VS Code quando existe), um nome, o atalho padrão (no Mac e no Windows) e quem o executa:
//   · comandos do app (abrir arquivo, painéis, abas…): quem sabe fazer registra o handler com kb.on(id, fn) — o mesmo
//     atalho pode servir a dois comandos (o primeiro que aceitar fica com ele, ex.: ⌘\ divide o editor na área de
//     trabalho e recolhe a barra lateral fora dela);
//   · comandos do editor (Monaco): o próprio Monaco executa; um atalho personalizado tira o padrão dele e põe o seu.
// Atalho em texto: "mod+shift+k" (mod = ⌘ no Mac, Ctrl no Windows), acorde com espaço: "mod+k mod+f".
// As personalizações ficam nas preferências ("keybindings": id → atalhos; lista vazia = sem atalho).
import type * as Monaco from "monaco-editor";
import { edState } from "./editorstate.svelte";
import { isMac, kbd } from "./keys";
import { prefs } from "./prefs.svelte";

export type Scope = "app" | "editor" | "explorer";
export type Command = { id: string; label: string; group: string; scope: Scope; mac: string[]; win: string[];
  /** comando nativo do Monaco (o editor executa) */
  monaco?: boolean };

const c = (id: string, label: string, group: string, scope: Scope, mac: string[] | string, win?: string[] | string, monaco = false): Command => {
  const m = Array.isArray(mac) ? mac : mac ? [mac] : [];
  const w = win === undefined ? m : Array.isArray(win) ? win : win ? [win] : [];
  return { id, label, group, scope, mac: m, win: w, monaco };
};
const ed = (id: string, label: string, mac: string[] | string, win?: string[] | string) => c(id, label, "Editor", "editor", mac, win, true);

export const COMMANDS: Command[] = [
  // ---- geral
  c("workbench.action.showCommands", "Paleta de comandos", "Geral", "app", ["mod+shift+p", "mod+k"]),
  c("workbench.action.quickOpen", "Abrir arquivo do projeto (Ir para arquivo)", "Geral", "app", "mod+p"),
  c("workbench.action.openSettings", "Configurações", "Geral", "app", "mod+,"),
  c("workbench.action.openGlobalKeybindings", "Atalhos de teclado", "Geral", "app", "mod+k mod+s"),
  c("codeck.askAi", "Abrir agente (escolher a conta de IA)", "Geral", "app", "mod+shift+i"),
  // ---- visões e painéis
  c("workbench.view.explorer", "Mostrar o Explorador", "Visões", "app", "mod+shift+e"),
  c("workbench.view.search", "Buscar no projeto", "Visões", "app", "mod+shift+f"),
  c("workbench.view.scm", "Mostrar o Controle de código-fonte", "Visões", "app", "ctrl+shift+g"),
  c("workbench.view.debug", "Mostrar Executar e depurar", "Visões", "app", "mod+shift+d"),
  c("workbench.view.extensions", "Mostrar as Extensões", "Visões", "app", "mod+shift+x"),
  c("codeck.view.solution", "Mostrar o Gerenciador de Soluções (.NET)", "Visões", "app", []),
  c("workbench.actions.view.problems", "Mostrar/esconder Problemas", "Visões", "app", "mod+shift+m"),
  c("workbench.action.toggleSidebarVisibility", "Mostrar/esconder a barra lateral do projeto", "Visões", "app", "mod+b"),
  c("workbench.action.togglePanel", "Mostrar/esconder o painel inferior", "Visões", "app", "mod+j"),
  // ---- terminal
  c("workbench.action.terminal.toggleTerminal", "Ir para o terminal (e voltar)", "Terminal", "app", "ctrl+`"),
  c("workbench.action.terminal.new", "Novo terminal", "Terminal", "app", ["ctrl+shift+`", "mod+t"]),
  // ---- abas e arquivos
  c("workbench.action.files.newUntitledFile", "Novo arquivo", "Abas e arquivos", "app", "mod+n"),
  c("workbench.action.files.save", "Salvar", "Abas e arquivos", "app", "mod+s"),
  c("workbench.action.files.saveAll", "Salvar tudo", "Abas e arquivos", "app", "mod+alt+s", "mod+k s"),
  c("workbench.action.closeActiveEditor", "Fechar a aba", "Abas e arquivos", "app", "mod+w", ["mod+w", "mod+f4"]),
  c("workbench.action.closeAllEditors", "Fechar todas as abas de arquivo", "Abas e arquivos", "app", "mod+k mod+w"),
  c("workbench.action.closeOtherEditors", "Fechar as outras abas", "Abas e arquivos", "app", "mod+alt+t", []),
  c("workbench.action.reopenClosedEditor", "Reabrir a aba fechada", "Abas e arquivos", "app", "mod+shift+t"),
  c("workbench.action.nextEditor", "Próxima aba", "Abas e arquivos", "app", ["mod+alt+right", "ctrl+tab"], ["ctrl+pagedown", "ctrl+tab"]),
  c("workbench.action.previousEditor", "Aba anterior", "Abas e arquivos", "app", ["mod+alt+left", "ctrl+shift+tab"], ["ctrl+pageup", "ctrl+shift+tab"]),
  ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map(n => c(`workbench.action.openEditorAtIndex${n}`, `Ir para a aba ${n}`, "Abas e arquivos", "app", `ctrl+${n}`, `alt+${n}`)),
  c("workbench.action.splitEditor", "Dividir o editor (lado a lado)", "Abas e arquivos", "app", "mod+\\"),
  c("workbench.files.action.showActiveFileInExplorer", "Revelar o arquivo no Explorador", "Abas e arquivos", "app", []),
  c("markdown.showPreviewToSide", "Markdown: alternar pré-visualização", "Abas e arquivos", "app", "mod+shift+v"),
  // ---- executar e depurar
  c("workbench.action.debug.start", "Iniciar a depuração / continuar", "Executar e depurar", "app", "f5"),
  c("workbench.action.debug.run", "Executar sem depurar", "Executar e depurar", "app", "ctrl+f5"),
  c("workbench.action.debug.stop", "Parar", "Executar e depurar", "app", "shift+f5"),
  c("workbench.action.debug.restart", "Reiniciar", "Executar e depurar", "app", "mod+shift+f5"),
  c("workbench.action.debug.pause", "Pausar", "Executar e depurar", "app", "f6"),
  c("workbench.action.debug.stepOver", "Passar por cima (step over)", "Executar e depurar", "app", "f10"),
  c("workbench.action.debug.stepInto", "Entrar (step into)", "Executar e depurar", "app", "f11"),
  c("workbench.action.debug.stepOut", "Sair (step out)", "Executar e depurar", "app", "shift+f11"),
  // ---- projetos
  ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map(n => c(`codeck.openProject${n}`, `Ir para o projeto ${n}`, "Projetos", "app", `mod+${n}`)),
  // ---- explorador (com o foco na árvore de arquivos)
  c("explorer.newFile", "Novo arquivo", "Explorador", "explorer", []),
  c("explorer.newFolder", "Nova pasta", "Explorador", "explorer", []),
  c("renameFile", "Renomear", "Explorador", "explorer", ["enter", "f2"], "f2"),
  c("deleteFile", "Excluir (vai para a Lixeira)", "Explorador", "explorer", ["mod+backspace", "delete"], "delete"),
  c("filesExplorer.copy", "Copiar", "Explorador", "explorer", "mod+c"),
  c("filesExplorer.cut", "Recortar", "Explorador", "explorer", "mod+x"),
  c("filesExplorer.paste", "Colar", "Explorador", "explorer", "mod+v"),
  c("explorer.duplicate", "Duplicar", "Explorador", "explorer", []),
  c("copyFilePath", "Copiar caminho", "Explorador", "explorer", "alt+mod+c", "shift+alt+c"),
  c("copyRelativeFilePath", "Copiar caminho relativo", "Explorador", "explorer", "alt+mod+shift+c", "mod+shift+alt+c"),
  // ---- editor: navegação (do app, pelo servidor de linguagem)
  c("codeck.gotoDefinition", "Ir para a definição", "Editor", "editor", "f12"),
  c("codeck.findAllReferences", "Localizar todas as referências", "Editor", "editor", "shift+alt+f12"),
  c("editor.action.toggleWordWrap", "Quebra de linha automática", "Editor", "editor", "alt+z"),
  c("editor.action.toggleMinimap", "Mostrar/esconder o minimapa", "Editor", "editor", []),
  // ---- editor (Monaco)
  ed("editor.action.commentLine", "Comentar/descomentar a linha", "mod+/"),
  ed("editor.action.blockComment", "Comentário em bloco", "shift+alt+a"),
  ed("editor.action.copyLinesDownAction", "Copiar a linha para baixo", "shift+alt+down"),
  ed("editor.action.copyLinesUpAction", "Copiar a linha para cima", "shift+alt+up"),
  ed("editor.action.moveLinesDownAction", "Mover a linha para baixo", "alt+down"),
  ed("editor.action.moveLinesUpAction", "Mover a linha para cima", "alt+up"),
  ed("editor.action.deleteLines", "Apagar a linha", "mod+shift+k"),
  ed("editor.action.insertLineAfter", "Nova linha abaixo", "mod+enter"),
  ed("editor.action.insertLineBefore", "Nova linha acima", "mod+shift+enter"),
  ed("editor.action.indentLines", "Indentar", "mod+]"),
  ed("editor.action.outdentLines", "Desindentar", "mod+["),
  ed("editor.action.joinLines", "Juntar as linhas", "ctrl+j", []),
  ed("editor.action.duplicateSelection", "Duplicar a seleção", []),
  ed("expandLineSelection", "Selecionar a linha", "mod+l"),
  ed("editor.action.addSelectionToNextFindMatch", "Selecionar a próxima ocorrência", "mod+d"),
  ed("editor.action.moveSelectionToNextFindMatch", "Pular para a próxima ocorrência", "mod+k mod+d"),
  ed("editor.action.selectHighlights", "Selecionar todas as ocorrências", "mod+shift+l"),
  ed("editor.action.changeAll", "Alterar todas as ocorrências", "mod+f2"),
  ed("editor.action.insertCursorAbove", "Cursor acima", "mod+alt+up", "ctrl+alt+up"),
  ed("editor.action.insertCursorBelow", "Cursor abaixo", "mod+alt+down", "ctrl+alt+down"),
  ed("editor.action.insertCursorAtEndOfEachLineSelected", "Cursor no fim de cada linha selecionada", "shift+alt+i"),
  ed("cursorUndo", "Desfazer o último cursor", "mod+u"),
  ed("editor.action.smartSelect.expand", "Expandir a seleção", "ctrl+shift+mod+right", "shift+alt+right"),
  ed("editor.action.smartSelect.shrink", "Reduzir a seleção", "ctrl+shift+mod+left", "shift+alt+left"),
  ed("editor.action.jumpToBracket", "Ir para o colchete correspondente", "mod+shift+\\"),
  ed("editor.action.formatDocument", "Formatar o documento", "shift+alt+f", "shift+alt+f"),
  ed("editor.action.formatSelection", "Formatar a seleção", "mod+k mod+f"),
  ed("editor.action.trimTrailingWhitespace", "Remover espaços no fim das linhas", "mod+k mod+x"),
  ed("editor.action.transformToUppercase", "Transformar em MAIÚSCULAS", []),
  ed("editor.action.transformToLowercase", "Transformar em minúsculas", []),
  ed("editor.action.sortLinesAscending", "Ordenar as linhas", []),
  ed("editor.action.rename", "Renomear o símbolo", "f2"),
  ed("editor.action.peekDefinition", "Espiar a definição", "alt+f12", "alt+f12"),
  ed("editor.action.goToReferences", "Ir para as referências", "shift+f12"),
  ed("editor.action.goToImplementation", "Ir para a implementação", "mod+f12"),
  ed("editor.action.goToTypeDefinition", "Ir para a definição de tipo", []),
  ed("editor.action.quickFix", "Correção rápida", "mod+."),
  ed("editor.action.triggerSuggest", "Sugestões (autocompletar)", "ctrl+space"),
  ed("editor.action.triggerParameterHints", "Dicas de parâmetros", "mod+shift+space"),
  ed("editor.action.showHover", "Mostrar a documentação (hover)", "mod+k mod+i"),
  ed("editor.action.quickOutline", "Ir para o símbolo no arquivo", "mod+shift+o"),
  ed("editor.action.gotoLine", "Ir para a linha", "ctrl+g"),
  ed("editor.action.marker.next", "Próximo problema", "f8"),
  ed("editor.action.marker.prev", "Problema anterior", "shift+f8"),
  ed("editor.fold", "Recolher o bloco", "mod+alt+["),
  ed("editor.unfold", "Expandir o bloco", "mod+alt+]"),
  ed("editor.toggleFold", "Recolher/expandir o bloco", "mod+k mod+l"),
  ed("editor.foldAll", "Recolher tudo", "mod+k mod+0"),
  ed("editor.unfoldAll", "Expandir tudo", "mod+k mod+j"),
  ed("actions.find", "Localizar", "mod+f"),
  ed("editor.action.startFindReplaceAction", "Substituir", "mod+alt+f", "ctrl+h"),
  ed("editor.action.nextMatchFindAction", "Localizar o próximo", ["mod+g", "f3"], "f3"),
  ed("editor.action.previousMatchFindAction", "Localizar o anterior", ["mod+shift+g", "shift+f3"], "shift+f3"),
  ed("editor.action.quickCommand", "Comandos do editor", "f1"),
  // por último: no mesmo atalho, o "dividir o editor" da área de trabalho tem a vez (fora dela, recolhe a barra)
  c("codeck.toggleNav", "Recolher/expandir a barra lateral do app", "Geral", "app", "mod+\\"),
];
const BY_ID = new Map(COMMANDS.map(x => [x.id, x]));
export const GROUPS = [...new Set(COMMANDS.map(x => x.group))];

// ------------------------------------------------------------ texto ↔ tecla
const MODS = ["ctrl", "mod", "alt", "shift"];
const CODE: Record<string, string> = { Backquote: "`", Minus: "-", Equal: "=", BracketLeft: "[", BracketRight: "]", Backslash: "\\", IntlBackslash: "\\",
  Semicolon: ";", Quote: "'", Comma: ",", Period: ".", Slash: "/", IntlRo: "/", Space: "space", Enter: "enter", NumpadEnter: "enter", Escape: "esc",
  Backspace: "backspace", Delete: "delete", Tab: "tab", ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", Home: "home",
  End: "end", PageUp: "pageup", PageDown: "pagedown", Insert: "insert", NumpadAdd: "=", NumpadSubtract: "-" };

/** Uma tecla em forma canônica: modificadores em ordem fixa; no Windows, Ctrl é o "mod". */
function canon(stroke: string) {
  const parts = stroke.toLowerCase().split("+").map(p => p.trim()).filter(Boolean);
  const key = parts.pop() || "";
  const mods = new Set(parts.map(p => (p === "cmd" || p === "meta" ? "mod" : p === "option" ? "alt" : p === "ctrl" && !isMac() ? "mod" : p)));
  return [...MODS.filter(m => mods.has(m)), key === "escape" ? "esc" : key].join("+");
}
export const canonical = (combo: string) => combo.trim().split(/\s+/).map(canon).join(" ");

/** A tecla do evento como texto ("mod+shift+k"); null se é só um modificador. */
export function strokeOf(e: KeyboardEvent): string | null {
  const c = e.code || "";
  let key: string | null = null;
  if (/^Key[A-Z]$/.test(c)) key = c.slice(3).toLowerCase();
  else if (/^Digit\d$/.test(c)) key = c.slice(5);
  else if (/^Numpad\d$/.test(c)) key = c.slice(6);
  else if (/^F\d{1,2}$/.test(c)) key = c.toLowerCase();
  else if (CODE[c]) key = CODE[c];
  else if (!["Shift", "Control", "Alt", "Meta", "CapsLock", "Fn", "Dead"].includes(e.key)) key = e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase();
  if (!key) return null;
  const mods = [e.ctrlKey && isMac() ? "ctrl" : "", (isMac() ? e.metaKey : e.ctrlKey) ? "mod" : "", e.altKey ? "alt" : "", e.shiftKey ? "shift" : ""].filter(Boolean);
  return [...mods, key].join("+");
}

/** "mod+k mod+f" → "⌘K ⌘F" / "Ctrl+K Ctrl+F" */
export const showKey = (combo: string) => combo.split(/\s+/).filter(Boolean).map(s => kbd(s === "space" ? "space" : s)).join(" ");

// ------------------------------------------------------------ registro
type Handler = () => boolean | void;

class Keybindings {
  private handlers = new Map<string, Handler[]>();
  private pending: { first: string; at: number; single?: string[]; timer?: ReturnType<typeof setTimeout> } | null = null;
  /** gravando um atalho na tela de Configurações: o despacho fica parado */
  recording = $state(false);

  custom(): Record<string, string[]> { return (prefs.get("keybindings") as Record<string, string[]>) || {}; }
  defaults(id: string): string[] { const x = BY_ID.get(id); return x ? (isMac() ? x.mac : x.win) : []; }
  /** Os atalhos do comando agora (personalizados ou os padrão) */
  keys(id: string): string[] { const cu = this.custom()[id]; return cu ? cu : this.defaults(id); }
  isCustom(id: string) { return id in this.custom(); }
  /** O 1º atalho, para mostrar em menus e dicas ("⌘P") */
  label(id: string) { const k = this.keys(id)[0]; return k ? showKey(k) : ""; }
  set(id: string, keys: string[]) {
    const next = { ...this.custom() };
    const clean = [...new Set(keys.map(canonical).filter(Boolean))];
    if (JSON.stringify(clean) === JSON.stringify(this.defaults(id).map(canonical))) delete next[id]; else next[id] = clean;
    prefs.set("keybindings", next);
  }
  reset(id: string) { const next = { ...this.custom() }; delete next[id]; prefs.set("keybindings", next); }
  resetAll() { prefs.set("keybindings", {}); }
  /** Comandos que usam este atalho (para avisar de conflito) */
  usedBy(combo: string, except?: string) {
    const k = canonical(combo);
    return COMMANDS.filter(x => x.id !== except && this.keys(x.id).some(y => canonical(y) === k));
  }

  /** O evento é este comando? (só atalho de uma tecla — para quem trata o teclado dentro do próprio componente) */
  is(e: KeyboardEvent, id: string) {
    const s = strokeOf(e);
    return !!s && this.keys(id).some(k => canonical(k) === s);
  }

  /** Quem sabe executar o comando registra aqui. O handler devolve false quando não se aplica agora (outro tenta). */
  on(id: string, fn: Handler) {
    const list = this.handlers.get(id) || [];
    this.handlers.set(id, [fn, ...list]);
    return () => { const l = this.handlers.get(id) || []; this.handlers.set(id, l.filter(x => x !== fn)); };
  }
  /** Executa (pela paleta, por menu ou pelo atalho). Comando do Monaco roda no editor em foco. */
  run(id: string): boolean {
    for (const fn of this.handlers.get(id) || []) { if (fn() !== false) return true; }
    const cmd = BY_ID.get(id);
    if (cmd?.monaco && edState.editor) { edState.editor.focus(); edState.editor.trigger("keyboard", id, null); return true; }
    return false;
  }
  has(id: string) { return !!this.handlers.get(id)?.length || (!!BY_ID.get(id)?.monaco && !!edState.editor); }

  /** Despacho global (keydown da janela): comandos do app, com acordes ("⌘K ⌘W"). */
  dispatch(e: KeyboardEvent) {
    if (this.recording || e.defaultPrevented) return;
    const s = strokeOf(e);
    if (!s) return;
    const app = COMMANDS.filter(x => x.scope === "app");
    const p = this.pending;
    if (p) {
      clearTimeout(p.timer);
      this.pending = null;
      if (Date.now() - p.at < 2000) {
        const full = p.first + " " + s;
        const hit = app.filter(x => this.keys(x.id).some(k => canonical(k) === full));
        if (hit.some(x => this.run(x.id))) { e.preventDefault(); e.stopPropagation(); return; }
        // não formou acorde: vale o comando de uma tecla só que o 1º toque tinha (ex.: ⌘K = paleta)
        if (p.single?.some(id => this.run(id))) { /* e segue: a 2ª tecla é tratada normalmente */ }
      }
    }
    const single = app.filter(x => this.keys(x.id).some(k => canonical(k) === s));
    const chord = app.some(x => this.keys(x.id).some(k => canonical(k).startsWith(s + " ")));
    if (chord) {
      e.preventDefault(); e.stopPropagation();
      const ids = single.filter(x => this.has(x.id)).map(x => x.id);
      // acorde começa com uma tecla que também é um comando: espera a 2ª tecla um instante; sem ela, roda o comando
      this.pending = { first: s, at: Date.now(), single: ids, timer: ids.length ? setTimeout(() => { if (this.pending?.first === s) { this.pending = null; ids.some(id => this.run(id)); } }, 700) : undefined };
      return;
    }
    if (single.some(x => this.run(x.id))) { e.preventDefault(); e.stopPropagation(); }
  }

  // ------------------------------------------------------------ Monaco
  private monaco: typeof Monaco | null = null;
  private rules: Monaco.IDisposable | null = null;
  private registered = new Set<string>();
  /** Liga os atalhos ao Monaco (chamado ao carregar o editor e quando um atalho muda). Dentro do editor o Monaco
   *  recebe as teclas primeiro: os comandos do app também entram nele (senão um acorde ⌘K… do app nunca chegaria). */
  attachMonaco(m: typeof Monaco) {
    this.monaco = m;
    this.rules?.dispose();
    const rules: Monaco.editor.IKeybindingRule[] = [];
    // primeiras teclas dos acordes nativos do editor (⌘K…): um comando do app de uma tecla só nelas mataria os acordes
    const prefixes = new Set(COMMANDS.filter(x => x.monaco).flatMap(x => this.keys(x.id)).map(canonical).filter(k => k.includes(" ")).map(k => k.split(" ")[0]));
    for (const cmd of COMMANDS) {
      if (cmd.scope === "explorer") continue;
      if (cmd.monaco) {
        if (!this.isCustom(cmd.id)) continue;   // padrão do próprio Monaco
        rules.push({ keybinding: 0, command: "-" + cmd.id });
        for (const k of this.keys(cmd.id)) { const n = toMonaco(m, k); if (n) rules.push({ keybinding: n, command: cmd.id, when: "editorTextFocus" }); }
        continue;
      }
      const run = "codeck:" + cmd.id;
      if (!this.registered.has(run)) { m.editor.registerCommand(run, () => { this.run(cmd.id); }); this.registered.add(run); }
      for (const k of this.keys(cmd.id)) {
        const ck = canonical(k);
        if (!ck.includes(" ") && prefixes.has(ck)) continue;
        const n = toMonaco(m, k);
        if (n) rules.push({ keybinding: n, command: run });
      }
    }
    this.rules = m.editor.addKeybindingRules(rules);
  }
  refreshMonaco() { if (this.monaco) this.attachMonaco(this.monaco); }
}

function monacoKey(m: typeof Monaco, key: string): number | null {
  const K = m.KeyCode;
  if (/^[a-z]$/.test(key)) return (K as any)["Key" + key.toUpperCase()];
  if (/^[0-9]$/.test(key)) return (K as any)["Digit" + key];
  if (/^f\d{1,2}$/.test(key)) return (K as any)["F" + key.slice(1)] ?? null;
  const map: Record<string, number> = { "`": K.Backquote, "-": K.Minus, "=": K.Equal, "[": K.BracketLeft, "]": K.BracketRight, "\\": K.Backslash,
    ";": K.Semicolon, "'": K.Quote, ",": K.Comma, ".": K.Period, "/": K.Slash, space: K.Space, enter: K.Enter, esc: K.Escape, backspace: K.Backspace,
    delete: K.Delete, tab: K.Tab, up: K.UpArrow, down: K.DownArrow, left: K.LeftArrow, right: K.RightArrow, home: K.Home, end: K.End,
    pageup: K.PageUp, pagedown: K.PageDown, insert: K.Insert };
  return map[key] ?? null;
}
function toMonaco(m: typeof Monaco, combo: string): number | null {
  const strokes = canonical(combo).split(" ").map(s => {
    const parts = s.split("+"), key = parts.pop()!;
    const code = monacoKey(m, key);
    if (code == null) return null;
    let n = code;
    for (const p of parts) n |= p === "mod" ? m.KeyMod.CtrlCmd : p === "ctrl" ? m.KeyMod.WinCtrl : p === "alt" ? m.KeyMod.Alt : p === "shift" ? m.KeyMod.Shift : 0;
    return n;
  });
  if (strokes.some(x => x == null) || !strokes.length) return null;
  return strokes.length === 1 ? strokes[0]! : m.KeyMod.chord(strokes[0]!, strokes[1]!);
}

export const kb = new Keybindings();
// mudou um atalho (aqui ou em outra janela, pelo /api/state): o Monaco recebe as regras novas
let lastSig = "";
prefs.onChange(k => { if (k === "keybindings") { lastSig = JSON.stringify(kb.custom()); kb.refreshMonaco(); } });
export function syncKeybindings() { const s = JSON.stringify(kb.custom()); if (s !== lastSig) { lastSig = s; kb.refreshMonaco(); } }
