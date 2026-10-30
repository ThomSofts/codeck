<script lang="ts" module>
  import type * as Monaco from "monaco-editor";
  import type { Engine } from "../../lib/db.svelte";

  // Autocompletar: um provedor por linguagem, registrado uma vez; ele pergunta ao editor em foco (tabelas do catálogo e
  // colunas das tabelas citadas na consulta).
  export interface SqlSource {
    tables: () => { schema: string; name: string; kind: string }[];
    columns: (schema: string, name: string) => Promise<{ name: string; type: string }[]>;
    engine: Engine;
  }
  // só os editores de banco recebem estas sugestões (o Monaco é o mesmo do editor de código do projeto)
  const sources = new Map<string, SqlSource>();
  const registered = new Set<string>();
  const KEYWORDS = ["SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "NULL", "IS NULL", "IS NOT NULL", "IN", "LIKE", "BETWEEN", "ORDER BY", "GROUP BY",
    "HAVING", "JOIN", "LEFT JOIN", "INNER JOIN", "ON", "AS", "DISTINCT", "COUNT(*)", "INSERT INTO", "VALUES", "UPDATE", "SET", "DELETE FROM",
    "LIMIT", "TOP", "OFFSET", "CASE", "WHEN", "THEN", "ELSE", "END", "UNION ALL", "EXISTS", "WITH", "DESC", "ASC"];

  export const languageFor = (e: Engine) => (e === "postgres" ? "pgsql" : e === "mysql" ? "mysql" : e === "mongodb" || e === "firebase" ? "javascript"
    : e === "redis" ? "redis" : "sql");
  const REDIS = ["GET", "SET", "DEL", "EXISTS", "TTL", "EXPIRE", "TYPE", "SCAN 0 MATCH  COUNT 500", "HGETALL", "HGET", "HSET", "LRANGE  0 -1", "LPUSH",
    "RPUSH", "SMEMBERS", "SADD", "ZRANGE  0 -1 WITHSCORES", "ZADD", "INCR", "INFO", "DBSIZE"];
  const MONGO = ["find({})", "findOne({})", "aggregate([])", "countDocuments({})", "distinct('campo')", "insertOne({})", "insertMany([])",
    "updateOne({}, {$set: {}})", "updateMany({}, {$set: {}})", "deleteOne({})", "deleteMany({})", "createIndex({})", "getIndexes()"];
  const FIRE = ["where('campo', '==', valor)", "orderBy('campo')", "limit(50)", "get()", "add({})", "update({})", "set({})", "delete()",
    "orderByChild('campo')", "equalTo(valor)", "limitToFirst(50)", "push({})", "remove()", "listCollections()"];

  function docSuggestions(m: typeof Monaco, model: Monaco.editor.ITextModel, pos: Monaco.Position, src: SqlSource) {
    const word = model.getWordUntilPosition(pos);
    const range = { startLineNumber: pos.lineNumber, endLineNumber: pos.lineNumber, startColumn: word.startColumn, endColumn: word.endColumn };
    const before = model.getValueInRange({ startLineNumber: pos.lineNumber, startColumn: 1, endLineNumber: pos.lineNumber, endColumn: word.startColumn });
    const K = m.languages.CompletionItemKind;
    const S = m.languages.CompletionItemInsertTextRule.InsertAsSnippet;
    if (/\bdb\.$/.test(before) || /(collection|collectionGroup|ref|getCollection)\(\s*['"]$/.test(before))
      return src.tables().map(t => ({ label: t.name, kind: K.Struct, insertText: t.name, range }));
    if (/\.$/.test(before))
      return (src.engine === "mongodb" ? MONGO : FIRE).map(x => ({ label: x, kind: K.Method, insertText: x, range, insertTextRules: S }));
    return src.engine === "mongodb" ? [{ label: "db.", kind: K.Keyword, insertText: "db.", range }, { label: "show collections", kind: K.Keyword, insertText: "show collections", range }]
      : ["collection('')", "collectionGroup('')", "doc('')", "ref('')"].map(x => ({ label: x, kind: K.Function, insertText: x, range }));
  }

  function register(m: typeof Monaco, lang: string) {
    if (registered.has(lang)) return;
    registered.add(lang);
    m.languages.registerCompletionItemProvider(lang, {
      triggerCharacters: [".", " ", "'", '"'],
      async provideCompletionItems(model, pos) {
        const src = sources.get(model.uri.toString());
        if (!src) return { suggestions: [] };
        if (lang === "javascript") return { suggestions: docSuggestions(m, model, pos, src) };
        if (lang === "redis") {
          const w = model.getWordUntilPosition(pos);
          const range = { startLineNumber: pos.lineNumber, endLineNumber: pos.lineNumber, startColumn: w.startColumn, endColumn: w.endColumn };
          const lineStart = model.getValueInRange({ startLineNumber: pos.lineNumber, startColumn: 1, endLineNumber: pos.lineNumber, endColumn: w.startColumn }).trim() === "";
          return { suggestions: lineStart ? REDIS.map(x => ({ label: x.trim(), kind: m.languages.CompletionItemKind.Keyword, insertText: x.replace(/ {2}/, " "), range }))
            : src.tables().map(t => ({ label: t.name.replace(/\*$/, ""), kind: m.languages.CompletionItemKind.Struct, insertText: t.name.replace(/\*$/, ""), range })) };
        }
        const word = model.getWordUntilPosition(pos);
        const range = { startLineNumber: pos.lineNumber, endLineNumber: pos.lineNumber, startColumn: word.startColumn, endColumn: word.endColumn };
        const before = model.getValueInRange({ startLineNumber: pos.lineNumber, startColumn: 1, endLineNumber: pos.lineNumber, endColumn: word.startColumn });
        const text = model.getValue();
        const tables = src.tables();
        const out: Monaco.languages.CompletionItem[] = [];
        const K = m.languages.CompletionItemKind;
        // "apelido." ou "tabela.": colunas daquela tabela
        const dot = /([\w$#]+)\.$/.exec(before);
        const aliasOf = (a: string) => {
          const re = new RegExp(`(?:from|join|update|into)\\s+((?:[\\w$#\\[\\]"\`]+\\.)?[\\w$#\\[\\]"\`]+)(?:\\s+(?:as\\s+)?([\\w$#]+))?`, "gi");
          for (const mm of text.matchAll(re)) {
            const full = mm[1].replace(/[\[\]"`]/g, "");
            const name = full.split(".").pop()!;
            if (a.toLowerCase() === (mm[2] || "").toLowerCase() || a.toLowerCase() === name.toLowerCase()) return full;
          }
          return null;
        };
        const find = (full: string) => {
          const [a, b] = full.includes(".") ? full.split(".") : [null, full];
          return tables.find(t => t.name.toLowerCase() === b!.toLowerCase() && (!a || t.schema.toLowerCase() === a.toLowerCase()));
        };
        if (dot) {
          const full = aliasOf(dot[1]);
          const t = full ? find(full) : null;
          if (t) for (const c of await src.columns(t.schema, t.name)) out.push({ label: c.name, kind: K.Field, detail: c.type, insertText: c.name, range });
          else for (const t2 of tables.filter(x => x.schema.toLowerCase() === dot[1].toLowerCase()))
            out.push({ label: t2.name, kind: t2.kind === "view" ? K.Interface : K.Struct, detail: t2.kind, insertText: t2.name, range });
          return { suggestions: out };
        }
        for (const t of tables) {
          const full = src.engine === "sqlite" || src.engine === "mysql" ? t.name : `${t.schema}.${t.name}`;
          out.push({ label: full, kind: t.kind === "view" ? K.Interface : t.kind === "table" ? K.Struct : K.Function, detail: t.kind, insertText: full, range, sortText: "1" + full });
        }
        // colunas das tabelas já citadas na consulta
        const seen = new Set<string>();
        for (const mm of text.matchAll(/(?:from|join|update|into)\s+((?:[\w$#\[\]"`]+\.)?[\w$#\[\]"`]+)/gi)) {
          const t = find(mm[1].replace(/[\[\]"`]/g, ""));
          if (!t || seen.has(t.schema + "." + t.name)) continue;
          seen.add(t.schema + "." + t.name);
          for (const c of await src.columns(t.schema, t.name))
            out.push({ label: c.name, kind: K.Field, detail: `${t.name} · ${c.type}`, insertText: c.name, range, sortText: "0" + c.name });
        }
        for (const k of KEYWORDS) out.push({ label: k, kind: K.Keyword, insertText: k, range, sortText: "2" + k });
        return { suggestions: out };
      },
    });
  }
</script>

<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { loadMonaco, monacoTheme, onThemeChange } from "../../lib/monaco";

  let { value, engine, source, onchange, onrun, onsave = undefined, errorAt = null }:
    { value: string; engine: Engine; source: SqlSource; onchange: (v: string) => void;
      onrun: (sql: string, base: number, all: boolean) => void; onsave?: () => void; errorAt?: number | null } = $props();

  let host: HTMLDivElement | undefined = $state();
  let editor: Monaco.editor.IStandaloneCodeEditor | null = null;
  let monaco: typeof Monaco | null = null;
  const subs: { dispose(): void }[] = [];

  /** O comando onde está o cursor: entre ";" (fora de texto) e linhas em branco — o T-SQL quase nunca usa ";". */
  function statementAt(text: string, at: number): { sql: string; base: number } {
    const cuts: number[] = [0];
    let q: string | null = null;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) { if (c === q) q = null; continue; }
      if (c === "'" || c === '"' || c === "`") { q = c; continue; }
      if (c === "-" && text[i + 1] === "-") { const e = text.indexOf("\n", i); i = e < 0 ? text.length : e; continue; }
      if (c === ";") cuts.push(i + 1);
      else if (c === "\n" && /^[ \t]*\n/.test(text.slice(i + 1))) cuts.push(i + 1);
    }
    cuts.push(text.length);
    for (let k = 0; k < cuts.length - 1; k++) {
      const a = cuts[k], b = cuts[k + 1];
      if (at >= a && at <= b && text.slice(a, b).trim()) {
        const raw = text.slice(a, b);
        const lead = raw.length - raw.trimStart().length;
        return { sql: raw.trim(), base: a + lead };
      }
    }
    // cursor numa linha em branco: o comando logo acima
    for (let k = cuts.length - 2; k >= 0; k--) {
      if (cuts[k] <= at && text.slice(cuts[k], cuts[k + 1]).trim()) {
        const raw = text.slice(cuts[k], cuts[k + 1]);
        return { sql: raw.trim(), base: cuts[k] + raw.length - raw.trimStart().length };
      }
    }
    return { sql: text.trim(), base: text.length - text.trimStart().length };
  }

  export function run(all = false) {
    if (!editor) return;
    editor.trigger("codeck", "hideSuggestWidget", null);
    const model = editor.getModel()!;
    const sel = editor.getSelection();
    const text = model.getValue();
    if (all) return onrun(text, 0, true);
    if (sel && !sel.isEmpty()) {
      const base = model.getOffsetAt(sel.getStartPosition());
      return onrun(model.getValueInRange(sel), base, false);
    }
    const at = model.getOffsetAt(editor.getPosition()!);
    const st = statementAt(text, at);
    onrun(st.sql, st.base, false);
  }
  export function focus() { editor?.focus(); }
  export function insert(text: string) {
    if (!editor) return;
    const sel = editor.getSelection()!;
    editor.executeEdits("codeck", [{ range: sel, text, forceMoveMarkers: true }]);
    editor.focus();
  }

  onMount(() => {
    let disposed = false;
    loadMonaco().then(m => {
      if (disposed || !host) return;
      monaco = m;
      const lang = languageFor(engine);
      register(m, lang);
      editor = m.editor.create(host, {
        value, language: lang, automaticLayout: true, theme: monacoTheme(), minimap: { enabled: false }, scrollBeyondLastLine: false,
        fontSize: 13, lineNumbersMinChars: 3, padding: { top: 8 }, fixedOverflowWidgets: true, renderLineHighlight: "all", wordWrap: "on",
        suggest: { showStatusBar: true }, quickSuggestions: { other: true, comments: false, strings: false }, tabSize: 2,
        scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
      });
      subs.push(editor.onDidChangeModelContent(() => onchange(editor!.getValue())));
      const uri = editor.getModel()!.uri.toString();
      sources.set(uri, source);
      subs.push({ dispose: () => sources.delete(uri) });
      subs.push(onThemeChange(() => monaco?.editor.setTheme(monacoTheme())));
      editor.addCommand(m.KeyMod.CtrlCmd | m.KeyCode.Enter, () => run(false));
      editor.addCommand(m.KeyMod.CtrlCmd | m.KeyMod.Shift | m.KeyCode.Enter, () => run(true));
      editor.addCommand(m.KeyCode.F5, () => run(true));
      editor.addCommand(m.KeyMod.CtrlCmd | m.KeyCode.KeyS, () => onsave?.());
      editor.focus();
    });
    return () => { disposed = true; };
  });
  onDestroy(() => { for (const s of subs) s.dispose(); editor?.getModel()?.dispose(); editor?.dispose(); });

  // texto trocado de fora (outra aba, tabela aberta): atualiza sem perder o desfazer quando é a mesma aba
  $effect(() => { const v = value; if (editor && editor.getValue() !== v) editor.setValue(v); });
  // erro numa posição: marca a linha
  $effect(() => {
    const at = errorAt;
    if (!editor || !monaco) return;
    const model = editor.getModel()!;
    if (at == null || at < 0) { monaco.editor.setModelMarkers(model, "db", []); return; }
    const p = model.getPositionAt(at);
    monaco.editor.setModelMarkers(model, "db", [{ startLineNumber: p.lineNumber, endLineNumber: p.lineNumber, startColumn: 1,
      endColumn: model.getLineMaxColumn(p.lineNumber), message: "Erro neste comando", severity: monaco.MarkerSeverity.Error }]);
    editor.revealLineInCenterIfOutsideViewport(p.lineNumber);
  });
</script>

<div class="sqled" bind:this={host}></div>

<style>
  .sqled { width: 100%; height: 100%; min-height: 60px; }
</style>
