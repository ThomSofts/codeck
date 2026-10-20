// Depuração dentro do editor (Monaco), como no Visual Studio: bolinha vermelha na margem (clique ou F9), breakpoint
// condicional / com contador / logpoint (clique direito na margem), oca enquanto o depurador não confirmou a linha,
// seta amarela + faixa na linha onde a execução parou, e o valor da variável ao passar o mouse (sessão parada).
import type * as Monaco from "monaco-editor";
import { debug, type Bp } from "./debug.svelte";
import { ui } from "./ui.svelte";

type Ctx = { repoId: string; taskId: string | null; path: string };
const ctxOf = new WeakMap<Monaco.editor.ITextModel, () => Ctx | null>();
let hoverRegistered = false;

export function attachDebug(monaco: typeof Monaco, editor: Monaco.editor.IStandaloneCodeEditor, getCtx: () => Ctx | null) {
  editor.updateOptions({ glyphMargin: true });
  const decos = editor.createDecorationsCollection([]);
  const hint = editor.createDecorationsCollection([]);
  const subs: Monaco.IDisposable[] = [];
  /** id da decoração → linha do breakpoint (para acompanhar as edições) */
  let bpIds: { line: number; bp: Bp }[] = [];

  const lineAt = (e: Monaco.editor.IEditorMouseEvent) => e.target.position?.lineNumber || (e.target.range?.startLineNumber ?? 0);
  const inGutter = (e: Monaco.editor.IEditorMouseEvent) => e.target.type === monaco.editor.MouseTargetType.GUTTER_GLYPH_MARGIN
    || e.target.type === monaco.editor.MouseTargetType.GUTTER_LINE_DECORATIONS;

  subs.push(editor.onMouseDown(e => {
    const c = getCtx();
    if (!c || !inGutter(e) || e.event.rightButton) return;
    const ln = lineAt(e);
    if (ln) debug.toggleBp(c.repoId, c.path, ln);
  }));
  subs.push(editor.onMouseMove(e => {
    const ln = inGutter(e) ? lineAt(e) : 0;
    const c = getCtx();
    if (!ln || !c || debug.fileBps(c.repoId, c.path).some(b => b.line === ln)) { hint.clear(); return; }
    hint.set([{ range: new monaco.Range(ln, 1, ln, 1), options: { glyphMarginClassName: "cd-bp-hint", glyphMarginHoverMessage: { value: "Clique para pôr um breakpoint (F9)" } } }]);
  }));
  subs.push(editor.onMouseLeave(() => hint.clear()));
  subs.push(editor.onContextMenu(e => {
    const c = getCtx();
    if (!c || !inGutter(e)) return;
    const ln = lineAt(e);
    if (!ln) return;
    e.event.preventDefault();
    const bp = debug.fileBps(c.repoId, c.path).find(b => b.line === ln);
    const ev = e.event.browserEvent as MouseEvent;
    ui.contextMenu(ev, bp ? [
      { label: "Remover breakpoint", onclick: () => debug.setBp(c.repoId, c.path, ln, null) },
      { label: bp.enabled === false ? "Ativar breakpoint" : "Desativar breakpoint", onclick: () => debug.setBp(c.repoId, c.path, ln, { enabled: bp.enabled === false }) },
      { separator: true },
      { label: "Editar condição…", onclick: () => askCond(c, ln, bp) },
      { label: "Editar contador de ocorrências…", onclick: () => askHit(c, ln, bp) },
      { label: "Editar mensagem (logpoint)…", onclick: () => askLog(c, ln, bp) },
    ] : [
      { label: "Adicionar breakpoint", kbd: "F9", onclick: () => debug.toggleBp(c.repoId, c.path, ln) },
      { label: "Adicionar breakpoint condicional…", onclick: () => askCond(c, ln) },
      { label: "Adicionar logpoint…", onclick: () => askLog(c, ln) },
    ]);
  }));
  editor.addCommand(monaco.KeyCode.F9, () => {
    const c = getCtx(), p = editor.getPosition();
    if (c && p) debug.toggleBp(c.repoId, c.path, p.lineNumber);
  });

  // os breakpoints andam junto com o texto (inseriu linhas acima): lê as decorações de volta e grava as linhas novas
  let moveT: ReturnType<typeof setTimeout> | undefined;
  subs.push(editor.onDidChangeModelContent(() => {
    clearTimeout(moveT);
    moveT = setTimeout(() => {
      const c = getCtx();
      const model = editor.getModel();
      if (!c || !model || !bpIds.length) return;
      const ranges = decos.getRanges();
      const bpRanges = ranges.slice(0, bpIds.length);
      let changed = false;
      const list = bpIds.map((x, i) => {
        const ln = bpRanges[i]?.startLineNumber || x.line;
        if (ln !== x.line) changed = true;
        return { ...x.bp, line: ln };
      });
      if (changed) debug.moveBps(c.repoId, c.path, Object.values(Object.fromEntries(list.map(b => [b.line, b]))));
    }, 700);
  }));

  function paint() {
    const c = getCtx();
    const model = editor.getModel();
    if (!c || !model) { decos.clear(); bpIds = []; return; }
    ctxOf.set(model, getCtx);
    const max = model.getLineCount();
    const list = debug.fileBps(c.repoId, c.path).filter(b => b.line >= 1 && b.line <= max);
    bpIds = list.map(b => ({ line: b.line, bp: b }));
    const items: Monaco.editor.IModelDeltaDecoration[] = list.map(b => {
      const st = debug.bpState(c.repoId, c.path, b.line);
      const kind = b.logMessage ? "log" : (b.condition || b.hitCondition) ? "cond" : "plain";
      const cls = ["cd-bp", `cd-bp-${kind}`, b.enabled === false ? "cd-bp-off" : st === "pending" ? "cd-bp-pending" : ""].join(" ");
      const msg = b.logMessage ? `Logpoint: ${b.logMessage}` : b.condition ? `Condição: ${b.condition}` : b.hitCondition ? `Quando o contador: ${b.hitCondition}` : "Breakpoint";
      return { range: new monaco.Range(b.line, 1, b.line, 1), options: { glyphMarginClassName: cls, stickiness: monaco.editor.TrackedRangeStickiness.NeverGrowsWhenTypingAtEdges,
        glyphMarginHoverMessage: { value: msg + (b.enabled === false ? " (desativado)" : st === "pending" ? " — ainda não confirmado pelo depurador" : "") },
        overviewRuler: { color: "#e51400", position: monaco.editor.OverviewRulerLane.Left } } };
    });
    const cur = debug.current;
    if (cur && cur.repoId === c.repoId && (cur.taskId || null) === (c.taskId || null) && cur.path === c.path && cur.line <= max) {
      const top = cur.sid === debug.focus.sid && debug.focus.frameId != null ? isTopFrame() : true;
      items.push({ range: new monaco.Range(cur.line, 1, cur.line, 1), options: { isWholeLine: true, className: top ? "cd-cur-line" : "cd-frame-line",
        glyphMarginClassName: top ? "cd-cur" : "cd-frame", stickiness: monaco.editor.TrackedRangeStickiness.NeverGrowsWhenTypingAtEdges,
        overviewRuler: { color: "#ffcc00", position: monaco.editor.OverviewRulerLane.Full } } });
    }
    decos.set(items);
  }
  function isTopFrame() {
    const s = debug.sessions.find(x => x.id === debug.focus.sid);
    const top = s?.stopped?.top;
    return !top || top.id === debug.focus.frameId;
  }

  if (!hoverRegistered) {
    hoverRegistered = true;
    monaco.languages.registerHoverProvider("*", {
      async provideHover(model, pos) {
        const get = ctxOf.get(model);
        const c = get?.();
        if (!c) return null;
        const s = debug.sessions.find(x => x.id === debug.focus.sid && x.status === "stopped" && x.repoId === c.repoId)
          || debug.sessions.find(x => x.status === "stopped" && x.repoId === c.repoId);
        if (!s) return null;
        const expr = exprAt(model, pos);
        if (!expr) return null;
        try {
          const r = await debug.evaluate(s.id, expr.text, s.id === debug.focus.sid ? debug.focus.frameId : s.stopped?.top?.id ?? null, "hover");
          if (r.result == null || r.result === "") return null;
          return { range: expr.range, contents: [{ value: "```\n" + `${expr.text} = ${String(r.result).slice(0, 2000)}` + (r.type ? `   (${r.type})` : "") + "\n```" }] };
        } catch { return null; }
      },
    });
  }
  function exprAt(model: Monaco.editor.ITextModel, pos: Monaco.Position) {
    const w = model.getWordAtPosition(pos);
    if (!w) return null;
    // pega a cadeia "a.b.c" até a palavra (como o VS Code): obj.Prop mostra o valor da propriedade
    const line = model.getLineContent(pos.lineNumber);
    let start = w.startColumn - 1;
    while (start > 0) {
      if (line[start - 1] === "." || line[start - 1] === "?") { start--; continue; }
      const m = /[\w$]+$/.exec(line.slice(0, start));
      if (m && (line[start] === "." || line[start] === "?")) { start -= m[0].length; continue; }
      break;
    }
    const text = line.slice(start, w.endColumn - 1).replace(/^\?*\.+/, "");
    if (!text || /^\d/.test(text)) return null;
    return { text, range: new monaco.Range(pos.lineNumber, start + 1, pos.lineNumber, w.endColumn) };
  }

  return { paint, dispose: () => { clearTimeout(moveT); for (const s of subs) s.dispose(); decos.clear(); hint.clear(); } };
}

async function askCond(c: Ctx, line: number, bp?: Bp) {
  const v = await ui.ask({ title: "Breakpoint condicional", message: "Para só quando a expressão for verdadeira (na linguagem do programa).",
    input: { label: "Condição", value: bp?.condition || "", placeholder: "ex.: id == 42" }, confirm: "Salvar" });
  if (v === null || v === false) return;
  debug.setBp(c.repoId, c.path, line, { condition: String(v).trim() || undefined, enabled: true });
}
async function askHit(c: Ctx, line: number, bp?: Bp) {
  const v = await ui.ask({ title: "Contador de ocorrências", message: "Para só a partir de N passagens (ex.: 10, >= 5, % 2).",
    input: { label: "Contador", value: bp?.hitCondition || "" }, confirm: "Salvar" });
  if (v === null || v === false) return;
  debug.setBp(c.repoId, c.path, line, { hitCondition: String(v).trim() || undefined, enabled: true });
}
async function askLog(c: Ctx, line: number, bp?: Bp) {
  const v = await ui.ask({ title: "Logpoint", message: "Escreve no console de depuração sem parar. Expressões entre chaves: Pedido {id} de {cliente.Nome}",
    input: { label: "Mensagem", value: bp?.logMessage || "" }, confirm: "Salvar" });
  if (v === null || v === false) return;
  debug.setBp(c.repoId, c.path, line, { logMessage: String(v).trim() || undefined, enabled: true });
}
