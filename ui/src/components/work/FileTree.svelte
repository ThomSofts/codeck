<script lang="ts" module>
  /** O que mudou de lugar (to) ou foi excluído (to: null) — as abas abertas acompanham */
  export type FsChange = { from: string; to: string | null };
  import { get as apiGet } from "../../lib/api";
  type FilesResp = { files: string[]; root: string; dirs: string[]; ignored: string[]; lazy: string[]; truncated?: boolean };
  // várias árvores do mesmo escopo (explorador, um projeto por vez no Gerenciador de Soluções) leem a lista uma vez só;
  // depois de criar/mover/excluir, a que mexeu avisa as outras
  const inflight = new Map<string, Promise<FilesResp>>();
  const listeners = new Set<(scope: string, from: object) => void>();
  function fetchFiles(scope: string, repoId: string, taskId: string | null, fresh = false) {
    if (fresh) inflight.delete(scope);
    let p = inflight.get(scope);
    if (!p) {
      p = apiGet<FilesResp>("ws/files", { repoId, taskId });
      p.finally(() => setTimeout(() => { if (inflight.get(scope) === p) inflight.delete(scope); }, 1500)).catch(() => {});
      inflight.set(scope, p);
    }
    return p;
  }
  function filesChanged(scope: string, from: object) { for (const l of listeners) l(scope, from); }
</script>

<script lang="ts">
  // Explorador (como o do VS Code): todos os arquivos do projeto/tarefa, inclusive os ignorados pelo .gitignore (apagados)
  // e os repositórios dentro dele, em árvore — pasta ignorada inteira (bin/, obj/, node_modules/) é lida ao abrir —, com as cores do Git (M alterado, U novo, D apagado, A adicionado, ! conflito — a pasta herda a
  // cor), ícones do tema de ícones, menu de contexto (novo, recortar/copiar/colar, duplicar, renomear, excluir, caminho,
  // abrir alterações) e teclado (↑↓ ←→ Enter F2 ⌘X ⌘C ⌘V ⌘⌫ — Ctrl no Windows). Seleção múltipla com ⌘/⇧-clique.
  // Arrastar move (com ⌥/Ctrl copia) para outra pasta; arrastar do Finder/Explorer copia para dentro do projeto.
  // Clique abre em "visualização" (a aba é reaproveitada); duplo clique fixa. Também a busca no conteúdo.
  // Pastas abrem sob demanda e a árvore é indexada uma vez por leitura — projeto com dezenas de milhares de arquivos continua leve.
  import { CaseSensitive, ChevronRight, ChevronsDownUp, ClipboardPaste, Copy, CopyPlus, FilePlus2, FolderOpen, FolderPlus, GitCompareArrows, Pencil, Regex, RefreshCw, Scissors, Search, SquareTerminal, Trash2, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { get, post } from "../../lib/api";
  import { isMac, matches as isKey } from "../../lib/keys";
  import { kb } from "../../lib/keybindings.svelte";
  import { fileManagerName } from "../../lib/native";
  import { folderDecor, scm } from "../../lib/scm.svelte";
  import { icons } from "../../lib/fileicons.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { dirty, docs, keyOf, saveDoc } from "./Editor.svelte";
  import FileIcon from "./FileIcon.svelte";

  type OpenOpts = { preview?: boolean };
  // base/embedded: só a pasta `base` (com a barra no fim), sem barra de filtro nem rolagem própria — o Gerenciador de
  // Soluções mostra cada projeto assim, abaixo do nó dele (depth0 = recuo); `hide` esconde pastas logo abaixo da base
  let { repoId, taskId = null, gitRepo = null, mode = "files", onopen, ondiff, onterminal, onfs, active = null, base: baseDir = "", embedded = false, depth0 = 0, hide = [] }:
    { repoId: string; taskId?: string | null; gitRepo?: string | null; mode?: "files" | "search"; onopen: (path: string, line?: number, o?: OpenOpts) => void;
      ondiff?: (path: string) => void; onterminal?: (dir: string) => void; onfs?: (changes: FsChange[]) => void; active?: string | null;
      base?: string; embedded?: boolean; depth0?: number; hide?: string[] } = $props();
  let all = $state<string[]>([]);
  // ignorados pelo .gitignore (pasta com a barra no fim vale para tudo dentro) e pastas lidas só ao abrir
  let ignored = $state<Set<string>>(new Set());
  let lazy = $state<string[]>([]);
  let lazyKids = $state<Record<string, { files: string[]; lazy: string[] }>>({});
  let lazyBusy = $state<Record<string, boolean>>({});
  // pastas vazias: as que o backend achou e as criadas aqui (pasta vazia dentro de pasta nova o git não mostra)
  let emptyDirs = $state<string[]>([]);
  let ghosts = $state<string[]>([]);
  let root = $state("");
  let open = $state<Record<string, boolean>>({});
  let q = $state("");
  let loading = $state(true);
  let sq = $state("");
  let sCase = $state(false);
  let sRegex = $state(false);
  let results = $state<{ path: string; line: number; col: number; text: string }[]>([]);
  let truncated = $state(false);
  let searching = $state(false);
  let sTimer: ReturnType<typeof setTimeout> | undefined;
  let cursor = $state<string | null>(null);
  let listEl: HTMLDivElement | undefined = $state();
  // criação/renomeação em linha: { at: pasta-mãe ("" = raiz), kind, path?: o que está sendo renomeado }
  let edit = $state<{ at: string; kind: "file" | "folder" | "rename"; path?: string; value: string } | null>(null);
  // seleção (⌘/Ctrl-clique alterna, ⇧-clique estende a partir da âncora) e a área de transferência do explorador
  let sel = $state<string[]>([]);
  let anchor: string | null = null;
  let clip = $state<{ cut: boolean; paths: string[] } | null>(null);

  // As props chegam como getters que releem o projeto a cada leitura do /api/ws (2,5 s). O efeito depende só desta
  // chave: antes ele rodava a cada leitura e zerava as pastas abertas ("a árvore fechava sozinha").
  const scope = $derived(`${repoId}|${taskId || ""}`);
  const OPEN_KEY = "codeck.tree.open";
  function readOpen(k: string): Record<string, boolean> {
    try { return JSON.parse(localStorage.getItem(OPEN_KEY) || "{}")[k] || {}; } catch { return {}; }
  }
  function saveOpen() {
    try {
      const s = JSON.parse(localStorage.getItem(OPEN_KEY) || "{}");
      // só a parte desta árvore (base): as outras do mesmo escopo (um projeto cada, na solução) gravam a delas
      const others = Object.entries(s[scope] || {}).filter(([k]) => !k.startsWith(baseDir));
      s[scope] = Object.fromEntries([...others, ...Object.entries(open).filter(([k, v]) => v && k.startsWith(baseDir))]);
      const keys = Object.keys(s);
      for (const k of keys.slice(0, Math.max(0, keys.length - 40))) delete s[k];   // guarda as últimas 40 árvores
      localStorage.setItem(OPEN_KEY, JSON.stringify(s));
    } catch { /* sem armazenamento */ }
  }
  function toggleDir(path: string, force?: boolean) {
    open = { ...open, [path]: force ?? !open[path] };
    saveOpen();
    if (open[path]) loadLazy();
  }
  /** Pasta "sob demanda" que está aberta e ainda não foi lida (ou `again`: relê as abertas) */
  async function loadLazy(again = false) {
    const known = new Set([...lazy, ...Object.values(lazyKids).flatMap(k => k.lazy)]);
    const want = Object.keys(open).filter(d => open[d] && known.has(d) && (again ? lazyKids[d] : !lazyKids[d]) && !lazyBusy[d]);
    for (const d of want) {
      lazyBusy = { ...lazyBusy, [d]: true };
      try {
        const r = await get<FilesResp>("ws/files", { repoId, taskId, under: d });
        lazyKids = { ...lazyKids, [d]: { files: r.files, lazy: r.lazy } };
      } catch (e) { if (!again) ui.error(e); }
      lazyBusy = { ...lazyBusy, [d]: false };
    }
  }
  const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);

  async function load(silent = false, fresh = false) {
    if (!silent) loading = true;
    const k = scope;
    try {
      const r = await fetchFiles(k, repoId, taskId, fresh);
      if (k !== scope) return;
      const files = [...r.files].sort((a, b) => a.localeCompare(b));
      if (!sameList(files, all)) all = files;
      const dirs = [...(r.dirs || [])].sort();
      if (!sameList(dirs, emptyDirs)) emptyDirs = dirs;
      if (!sameList(r.lazy || [], lazy)) lazy = r.lazy || [];
      const ign = [...(r.ignored || [])].sort();
      if (!sameList(ign, [...ignored].sort())) ignored = new Set(ign);
      root = r.root;
      await loadLazy(silent);
    }
    catch (e) { if (!silent) ui.error(e); }
    loading = false;
  }
  /** Depois de mexer nos arquivos: relê já (sem o cache) e avisa as outras árvores do mesmo escopo */
  const self = {};
  async function reload() { await load(true, true); filesChanged(scope, self); }
  $effect(() => {
    const l = (s: string, from: object) => { if (s === scope && from !== self) load(true); };
    listeners.add(l);
    return () => { listeners.delete(l); };
  });
  $effect(() => { const k = scope; untrack(() => { open = readOpen(k); lazyKids = {}; load(); }); });
  // o git status do escopo: cores e letras (o explorador relê junto)
  $effect(() => { const g = gitRepo; if (!g) return; return scm.watch(g); });
  const decor = $derived(scm.map(gitRepo));
  const fdecor = $derived(folderDecor(decor));
  // arquivo novo/apagado no status que a lista ainda não tem: relê a lista (o agente criou algo)
  $effect(() => {
    const d = decor;
    if (untrack(() => [...d.keys()].some(p => d.get(p)!.tone === "add" && !index.files.has(p) && within(p, strip(baseDir) || p)))) untrack(() => load(true, true));
  });

  // o arquivo ativo (aberto por ⌘P, busca ou definição) fica visível: abre as pastas dele — uma vez por arquivo, para
  // não reabrir a cada leitura a pasta que você recolheu
  let revealed = "";
  $effect(() => {
    const f = active;
    if (!f || f === revealed) return;
    revealed = f;
    untrack(() => {
      cursor = f;
      if (!f.startsWith(baseDir)) return;
      const parts = f.split("/").slice(0, -1);
      let acc = "", changed = false;
      const next = { ...open };
      for (const p of parts) { acc += p + "/"; if (!next[acc]) { next[acc] = true; changed = true; } }
      if (changed) { open = next; saveOpen(); }
      requestAnimationFrame(() => listEl?.querySelector(`[data-p="${CSS.escape(f)}"]`)?.scrollIntoView({ block: "nearest" }));
    });
  });
  // arquivos novos (o agente cria, você cria no terminal) aparecem sem recarregar à mão
  $effect(() => {
    void scope;
    const t = setInterval(() => { if (document.visibilityState === "visible" && mode === "files") untrack(() => load(true)); }, 15000);
    return () => clearInterval(t);
  });

  // ------------------------------------------------------------ índice da árvore (uma vez por lista)
  type Dir = { dirs: string[]; files: string[] };
  const index = $derived.by(() => {
    const dirs = new Map<string, Dir>([["", { dirs: [], files: [] }]]);
    const files = new Set<string>();
    const ensure = (p: string) => { let d = dirs.get(p); if (!d) { d = { dirs: [], files: [] }; dirs.set(p, d); } return d; };
    const kids = Object.values(lazyKids);
    for (const f of kids.length ? [...all, ...kids.flatMap(k => k.files)] : all) {
      if (files.has(f)) continue;
      files.add(f);
      const parts = f.split("/");
      let acc = "";
      for (let i = 0; i < parts.length - 1; i++) {
        const parent = acc;
        acc += parts[i] + "/";
        if (!dirs.has(acc)) { ensure(parent).dirs.push(acc); ensure(acc); }
      }
      ensure(acc).files.push(f);
    }
    for (const g of new Set([...emptyDirs, ...ghosts, ...lazy, ...kids.flatMap(k => k.lazy)])) {
      let acc = "";
      for (const part of g.split("/").filter(Boolean)) { const parent = acc; acc += part + "/"; if (!dirs.has(acc)) { ensure(parent).dirs.push(acc); ensure(acc); } }
    }
    const cmp = (a: string, b: string) => a.localeCompare(b, undefined, { sensitivity: "base", numeric: true });
    for (const d of dirs.values()) { d.dirs.sort(cmp); d.files.sort((a, b) => cmp(a.split("/").pop()!, b.split("/").pop()!)); }
    return { dirs, files };
  });
  // pastas com uma única subpasta e nada mais aparecem juntas ("src/main/java"), como no VS Code
  function compact(p: string): { path: string; label: string } {
    let cur = p, label = p.slice(0, -1).split("/").pop()!;
    for (;;) {
      const d = index.dirs.get(cur);
      if (!d || d.files.length || d.dirs.length !== 1) break;
      cur = d.dirs[0];
      label += "/" + cur.slice(0, -1).split("/").pop();
    }
    return { path: cur, label };
  }
  type Row = { path: string; name: string; dir: boolean; depth: number; deleted?: boolean };
  const rows = $derived.by<Row[]>(() => {
    const out: Row[] = [];
    const walk = (prefix: string, depth: number) => {
      const d = index.dirs.get(prefix);
      if (!d) return;
      for (const sub of d.dirs) {
        if (prefix === baseDir && hide.includes(sub.slice(prefix.length))) continue;
        const c = compact(sub);
        out.push({ path: c.path, name: c.label, dir: true, depth });
        if (open[c.path]) walk(c.path, depth + 1);
      }
      for (const f of d.files) out.push({ path: f, name: f.slice(prefix.length), dir: false, depth });
    };
    walk(baseDir, depth0);
    return out;
  });
  const matches = $derived.by(() => {
    const t = q.trim().toLowerCase();
    if (!t) return [];
    const parts = t.split(/\s+/);
    const score = (f: string) => { const n = f.split("/").pop()!.toLowerCase(); return n.startsWith(parts[0]) ? 0 : n.includes(parts[0]) ? 1 : 2; };
    return all.filter(f => { const l = f.toLowerCase(); return f.startsWith(baseDir) && parts.every(p => l.includes(p)); })
      .sort((a, b) => score(a) - score(b) || a.length - b.length).slice(0, 300);
  });
  const visible = $derived<Row[]>(q.trim() ? matches.map(f => ({ path: f, name: f.split("/").pop()!, dir: false, depth: 0 })) : rows);
  const rowBy = $derived(new Map(visible.map(r => [r.path, r])));
  function isIgnored(p: string) {
    if (!ignored.size) return false;
    if (ignored.has(p)) return true;
    const parts = p.replace(/\/$/, "").split("/");
    let acc = "";
    for (let i = 0; i < parts.length - 1; i++) { acc += parts[i] + "/"; if (ignored.has(acc)) return true; }
    return false;
  }

  // ------------------------------------------------------------ seleção e teclado
  const scrollTo = (path: string) => listEl?.querySelector(`[data-p="${CSS.escape(path)}"]`)?.scrollIntoView({ block: "nearest" });
  function range(a: string, b: string) {
    const i = visible.findIndex(r => r.path === a), j = visible.findIndex(r => r.path === b);
    if (i < 0 || j < 0) return [b];
    return visible.slice(Math.min(i, j), Math.max(i, j) + 1).map(r => r.path);
  }
  function pick(path: string, e?: { shiftKey: boolean; metaKey: boolean; ctrlKey: boolean }) {
    const add = e && (isMac() ? e.metaKey : e.ctrlKey);
    if (e?.shiftKey && anchor) sel = range(anchor, path);
    else if (add) { sel = sel.includes(path) ? sel.filter(x => x !== path) : [...sel, path]; anchor = path; }
    else { sel = [path]; anchor = path; }
    cursor = path;
  }
  /** Alvo de uma ação na linha: a seleção inteira se a linha faz parte dela; senão só a linha. Sem item dentro de pasta
   *  que também foi escolhida (mover a pasta já leva ele). */
  function targets(path: string | null): string[] {
    const list = path && !(sel.length > 1 && sel.includes(path)) ? [path] : sel.length ? sel : path ? [path] : [];
    return list.filter(p => !list.some(q => q !== p && q.endsWith("/") && p.startsWith(q)));
  }
  function onKey(e: KeyboardEvent) {
    if (edit || (e.target as HTMLElement).closest("input")) return;
    const i = visible.findIndex(r => r.path === cursor);
    const r = visible[i];
    const move = (j: number) => {
      const n = visible[Math.max(0, Math.min(visible.length - 1, j))];
      if (!n) return;
      if (e.shiftKey && anchor) { sel = range(anchor, n.path); cursor = n.path; } else pick(n.path);
      scrollTo(n.path);
    };
    const done = () => { e.preventDefault(); e.stopPropagation(); };
    if (e.key === "ArrowDown") { e.preventDefault(); move(i + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(i - 1); }
    else if (e.key === "ArrowRight" && r?.dir) { e.preventDefault(); if (!open[r.path]) toggleDir(r.path, true); else move(i + 1); }
    else if (e.key === "ArrowLeft" && r) {
      e.preventDefault();
      if (r.dir && open[r.path]) toggleDir(r.path, false);
      else { const parent = r.path.replace(/[^/]+\/?$/, ""); const pi = visible.findIndex(x => x.dir && x.path === parent); if (pi >= 0) move(pi); }
    }
    else if (e.key === "Enter" && r) { e.preventDefault(); if (r.dir) toggleDir(r.path); else onopen(r.path, undefined, { preview: false }); }
    else if (e.key === " " && r && !r.dir) { e.preventDefault(); onopen(r.path, undefined, { preview: true }); }
    else if (kb.is(e, "renameFile") && r) { done(); startRename(r.path); }
    else if (kb.is(e, "deleteFile") && (r || sel.length)) { done(); remove(targets(cursor)); }
    else if (kb.is(e, "filesExplorer.copy") && (r || sel.length)) { done(); toClip(targets(cursor), false); }
    else if (kb.is(e, "filesExplorer.cut") && (r || sel.length)) { done(); toClip(targets(cursor), true); }
    else if (kb.is(e, "filesExplorer.paste") && clip) { done(); paste(cursor ? dirOf(cursor, cursor.endsWith("/")) : baseDir); }
    else if (kb.is(e, "explorer.newFile")) { done(); startNew("file", cursor ? dirOf(cursor, cursor.endsWith("/")) : baseDir); }
    else if (kb.is(e, "explorer.newFolder")) { done(); startNew("folder", cursor ? dirOf(cursor, cursor.endsWith("/")) : baseDir); }
    else if (kb.is(e, "explorer.duplicate") && (r || sel.length)) { done(); duplicate(targets(cursor)); }
    else if (kb.is(e, "copyFilePath") && (r || sel.length)) { done(); copy(targets(cursor).map(abs).join("\n"), "Caminho copiado"); }
    else if (kb.is(e, "copyRelativeFilePath") && (r || sel.length)) { done(); copy(targets(cursor).map(strip).join("\n"), "Caminho relativo copiado"); }
    else if (isKey(e, "mod+a")) { done(); sel = visible.map(x => x.path); }
    else if (e.key === "Escape" && (clip?.cut || sel.length > 1)) { done(); if (clip?.cut) clip = null; else if (cursor) sel = [cursor]; }
  }

  // ------------------------------------------------------------ arquivos: criar, renomear, mover, copiar, excluir
  const dirOf = (p: string, dir: boolean) => (dir ? p : p.replace(/[^/]+$/, ""));
  const strip = (p: string) => p.replace(/\/$/, "");
  const base = (p: string) => strip(p).split("/").pop()!;
  const parentOf = (p: string) => strip(p).replace(/[^/]+$/, "");
  /** p é a própria `of` (sem a barra final) ou está dentro dela */
  const within = (p: string, of: string) => p === of || p.startsWith(of + "/");
  function touched() { if (gitRepo) scm.touch(gitRepo); }
  /** Depois de criar/colar/mover: relê, abre as pastas de destino e seleciona o que chegou */
  async function landed(paths: string[], dirs: Set<string> = new Set()) {
    await reload();
    touched();
    const next = { ...open };
    for (const p of paths) { let acc = ""; for (const part of p.split("/").slice(0, -1)) { acc += part + "/"; next[acc] = true; } }
    open = next; saveOpen();
    const rowsOf = paths.map(p => (dirs.has(p) || index.dirs.has(p + "/") ? p + "/" : p));
    if (rowsOf.length) { sel = rowsOf; anchor = cursor = rowsOf[0]; requestAnimationFrame(() => scrollTo(rowsOf[0])); }
  }
  /** Pastas vazias criadas aqui acompanham o que foi movido/excluído */
  function remapGhosts(changes: FsChange[]) {
    let g = ghosts;
    for (const c of changes) g = g.flatMap(x => (within(strip(x), c.from) ? (c.to === null ? [] : [c.to + strip(x).slice(c.from.length) + "/"]) : [x]));
    ghosts = g;
  }
  function changed(changes: FsChange[]) {
    if (!changes.length) return;
    remapGhosts(changes);
    if (clip) clip = { ...clip, paths: clip.paths.flatMap(p => { const c = changes.find(c => within(strip(p), c.from)); return !c ? [p] : c.to === null ? [] : [c.to + p.slice(c.from.length)]; }) };
    onfs?.(changes);
  }
  /** Arquivos abertos com alteração não salva dentro de `paths` */
  function dirtyIn(paths: string[]) {
    const roots = paths.map(strip);
    return [...docs.entries()].filter(([k, d]) => dirty[k] && d.repoId === repoId && (d.taskId || null) === (taskId || null) && roots.some(r => within(d.rel, r)))
      .map(([, d]) => d);
  }
  /** Mover/renomear arquivo com alteração não salva: salva antes (com a sua confirmação) — senão a aba perderia a edição */
  async function saveBefore(paths: string[]) {
    const ds = dirtyIn(paths);
    if (!ds.length) return true;
    const names = ds.map(d => d.rel.split("/").pop()).join(", ");
    if (!(await ui.ask({ title: `${names} ${ds.length === 1 ? "tem" : "têm"} alterações não salvas`, message: "Salvar antes de mover?", confirm: "Salvar e mover" }))) return false;
    try { for (const d of ds) await saveDoc(d); return true; } catch (e) { ui.error(e); return false; }
  }

  function startNew(kind: "file" | "folder", at: string) {
    if (at) toggleDir(at, true);
    edit = { at, kind, value: "" };
    q = "";
  }
  /** Campo de nome: pega o foco (o `autofocus` do Svelte não tira o foco da lista, então o F2 não deixava digitar) e
   *  seleciona o nome sem a extensão, como no VS Code */
  function grab(i: HTMLInputElement) {
    requestAnimationFrame(() => { i.focus(); const dot = i.value.lastIndexOf("."); i.setSelectionRange(0, dot > 0 ? dot : i.value.length); });
  }
  function startRename(path: string) {
    edit = { at: dirOf(strip(path), false), kind: "rename", path, value: base(path) };
  }
  async function commitEdit() {
    const e = edit;
    if (!e) return;
    edit = null;
    const v = e.value.trim();
    if (!v) return;
    try {
      if (e.kind === "rename") {
        const from = strip(e.path!), to = e.at + v;
        if (to === from) return;
        if (!(await saveBefore([from]))) return;
        await post("ws/fs/rename", { repoId, taskId, from, to });
        changed([{ from, to }]);
        await landed([to], new Set(e.path!.endsWith("/") ? [to] : []));
      } else {
        const path = strip(e.at + v);
        await post("ws/fs/create", { repoId, taskId, path, folder: e.kind === "folder" });
        if (e.kind === "folder") ghosts = [...ghosts, path + "/"];
        await landed([path], new Set(e.kind === "folder" ? [path] : []));
        if (e.kind === "file") onopen(path, undefined, { preview: false });
      }
    } catch (err) { ui.error(err); }
  }
  async function remove(paths: string[]) {
    if (!paths.length) return;
    const one = paths.length === 1, dir = paths[0].endsWith("/");
    const unsaved = dirtyIn(paths).length;
    if (!(await ui.ask({ title: one ? `Excluir ${base(paths[0])}${dir ? " e tudo dentro dela" : ""}?` : `Excluir ${paths.length} itens?`,
      message: "Vai para a Lixeira — dá para recuperar de lá." + (unsaved ? ` ${unsaved === 1 ? "Um arquivo aberto tem" : `${unsaved} arquivos abertos têm`} alterações não salvas, que serão perdidas.` : ""),
      detail: one ? undefined : paths.slice(0, 12).map(strip), confirm: "Mover para a Lixeira", danger: true }))) return;
    try {
      const r = await post<{ paths: string[] }>("ws/fs/delete", { repoId, taskId, paths: paths.map(strip) });
      changed(r.paths.map(p => ({ from: p, to: null })));
      sel = [];
      await reload(); touched();
      ui.toast(one ? "Movido para a Lixeira" : `${r.paths.length} itens movidos para a Lixeira`);
    } catch (e) { ui.error(e); await reload(); }
  }
  function toClip(paths: string[], cut: boolean) {
    if (!paths.length) return;
    clip = { cut, paths };
    ui.toast(`${paths.length === 1 ? base(paths[0]) : paths.length + " itens"} ${cut ? "recortado" : "copiado"}${paths.length === 1 ? "" : "s"} — cole com ${kb.label("filesExplorer.paste")}`, "info");
  }
  async function paste(at: string) {
    const c = clip;
    if (!c?.paths.length) return;
    if (c.cut) { if (await moveTo(c.paths, at)) clip = null; return; }
    await copyTo(c.paths, at);
  }
  /** Copia para a pasta `at` ("" = raiz). Nome repetido vira "nome copy.ext", como no VS Code. */
  async function copyTo(paths: string[], at: string) {
    try {
      const r = await post<{ copied: { from: string; to: string }[] }>("ws/fs/copy", { repoId, taskId, paths: paths.map(strip), dest: strip(at) });
      await landed(r.copied.map(x => x.to), new Set(r.copied.filter((x, i) => paths[i]?.endsWith("/")).map(x => x.to)));
      return true;
    } catch (e) { ui.error(e); await reload(); return false; }
  }
  async function duplicate(paths: string[]) {
    const out: string[] = [], dirs = new Set<string>();
    try {
      for (const p of paths) {
        const r = await post<{ copied: { to: string }[] }>("ws/fs/copy", { repoId, taskId, paths: [strip(p)], dest: strip(parentOf(p)) });
        for (const x of r.copied) { out.push(x.to); if (p.endsWith("/")) dirs.add(x.to); }
      }
    } catch (e) { ui.error(e); }
    await landed(out, dirs);
  }
  /** Move para a pasta `at`. Nome que já existe lá: pergunta antes de substituir (o que estava vai para a Lixeira). */
  async function moveTo(paths: string[], at: string) {
    const dest = strip(at);
    const bad = paths.find(p => p.endsWith("/") && within(dest, strip(p)));
    if (bad) { ui.toast(`Não dá para mover ${base(bad)} para dentro dela mesma`, "error"); return false; }
    paths = paths.filter(p => parentOf(p) !== (dest ? dest + "/" : ""));
    if (!paths.length) return true;
    if (!(await saveBefore(paths))) return false;
    try {
      const body = { repoId, taskId, paths: paths.map(strip), dest };
      let r = await post<{ moved: { from: string; to: string }[]; conflicts: string[] }>("ws/fs/move", body);
      if (r.conflicts.length) {
        const one = r.conflicts.length === 1;
        if (!(await ui.ask({ title: one ? `Já existe ${base(r.conflicts[0])} em ${dest ? base(dest) : "raiz do projeto"}` : `${r.conflicts.length} itens já existem em ${dest ? base(dest) : "raiz do projeto"}`,
          message: "Substituir? O que está lá vai para a Lixeira.", detail: one ? undefined : r.conflicts.slice(0, 12), confirm: "Substituir", danger: true }))) return false;
        r = await post("ws/fs/move", { ...body, overwrite: true });
      }
      changed(r.moved.map(m => ({ from: m.from, to: m.to })));
      await landed(r.moved.map(m => m.to), new Set(r.moved.filter(m => index.dirs.has(m.from + "/") || ghosts.includes(m.to + "/")).map(m => m.to)));
      return true;
    } catch (e) { ui.error(e); await reload(); return false; }
  }

  // ------------------------------------------------------------ arrastar e soltar
  // De dentro da árvore: move para a pasta sob o cursor (⌥ no Mac / Ctrl no Windows copia). De fora (Finder/Explorer): a
  // WebView entrega só o conteúdo (File), sem caminho — as pastas são percorridas aqui e enviadas em pedaços ao backend.
  const DRAG = "application/x-codeck-paths";
  const MAX_DROP = 200 * 1024 * 1024, MAX_ITEMS = 5000, CHUNK = 2 * 1024 * 1024;
  let dragging = $state<string[] | null>(null);
  let dropAt = $state<string | null>(null);   // pasta de destino em destaque ("" = raiz)
  let hoverDir: string | null = null;
  let hoverTimer: ReturnType<typeof setTimeout> | undefined;
  let leaveTimer: ReturnType<typeof setTimeout> | undefined;
  const isCopy = (e: DragEvent) => (isMac() ? e.altKey : e.ctrlKey);
  function dragStart(e: DragEvent, r: Row) {
    if (edit) return e.preventDefault();
    if (!sel.includes(r.path)) pick(r.path);
    const paths = targets(r.path);
    dragging = paths;
    e.dataTransfer?.setData(DRAG, JSON.stringify(paths));
    e.dataTransfer?.setData("text/plain", paths.map(abs).join("\n"));   // soltar no terminal/editor escreve o caminho
    if (e.dataTransfer) e.dataTransfer.effectAllowed = "copyMove";
  }
  function dragEnd() { dragging = null; dropAt = null; clearTimeout(hoverTimer); hoverDir = null; }
  /** Pasta onde a soltura cai: a própria linha se for pasta; senão a pasta do arquivo; fora das linhas, a raiz */
  function dropDir(e: DragEvent) {
    const el = (e.target as HTMLElement).closest<HTMLElement>("[data-p]");
    const r = el ? rowBy.get(el.dataset.p!) : null;
    return { r, at: r ? dirOf(r.path, r.dir) : baseDir };
  }
  function dragOver(e: DragEvent) {
    const dt = e.dataTransfer;
    if (!dt || q.trim()) return;
    const external = !dragging && [...dt.types].includes("Files");
    if (!dragging && !external) return;
    const { r, at } = dropDir(e);
    // pasta para dentro dela mesma, ou mover para onde já está: não aceita a soltura
    if (dragging && (dragging.some(p => p.endsWith("/") && within(strip(at), strip(p))) || (!isCopy(e) && dragging.every(p => parentOf(p) === at)))) {
      dt.dropEffect = "none"; dropAt = null; return;
    }
    e.preventDefault();
    clearTimeout(leaveTimer);
    dt.dropEffect = external || isCopy(e) ? "copy" : "move";
    dropAt = at;
    // pasta fechada sob o cursor abre depois de um instante, como no VS Code
    const hd = r?.dir && !open[r.path] ? r.path : null;
    if (hd !== hoverDir) { clearTimeout(hoverTimer); hoverDir = hd; if (hd) hoverTimer = setTimeout(() => { if (hoverDir === hd) toggleDir(hd, true); }, 600); }
  }
  function dragLeave() {
    // o dragleave dispara a cada filho cruzado (e sem relatedTarget no WebKit): só some se o dragover não voltar logo
    clearTimeout(leaveTimer);
    leaveTimer = setTimeout(() => { dropAt = null; clearTimeout(hoverTimer); hoverDir = null; }, 120);
  }
  async function onDrop(e: DragEvent) {
    const dt = e.dataTransfer;
    if (!dt || dropAt === null) return;
    e.preventDefault();
    const at = dropAt, copy = isCopy(e);
    let inner: string[] | null = dragging;
    try { inner ??= dt.getData(DRAG) ? JSON.parse(dt.getData(DRAG)) : null; } catch { inner = null; }
    // as entradas do Finder/Explorer só valem durante o evento: pega já, percorre depois
    const entries = inner ? [] : [...dt.items].filter(i => i.kind === "file").map(i => (i as any).webkitGetAsEntry?.() as FileSystemEntry | null);
    const files = inner ? [] : [...dt.files];
    dragEnd();
    if (inner) { if (copy) await copyTo(inner, at); else await moveTo(inner, at); }
    else await importExternal(entries.every(Boolean) && entries.length ? entries as FileSystemEntry[] : null, files, at);
  }

  type Incoming = { rel: string; file?: File; dir?: boolean };
  const SKIP = new Set([".DS_Store", "Thumbs.db", "desktop.ini"]);   // lixo do sistema não vem junto
  async function walk(entry: FileSystemEntry, rel: string, out: Incoming[]) {
    if (out.length > MAX_ITEMS) throw new Error(`Mais de ${MAX_ITEMS} itens — copie pelo Finder/Explorer`);
    if (entry.isFile) {
      if (SKIP.has(entry.name)) return;
      out.push({ rel, file: await new Promise<File>((ok, fail) => (entry as FileSystemFileEntry).file(ok, fail)) });
    } else if (entry.isDirectory) {
      out.push({ rel, dir: true });
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((ok, fail) => reader.readEntries(ok, fail));   // vem em lotes (~100)
        if (!batch.length) break;
        for (const c of batch) await walk(c, rel + "/" + c.name, out);
      }
    }
  }
  function b64(buf: ArrayBuffer) {
    const u = new Uint8Array(buf);
    let s = "";
    for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000));
    return btoa(s);
  }
  async function importExternal(entries: FileSystemEntry[] | null, files: File[], at: string) {
    const dest = strip(at);
    const prog = ui.progress("Lendo o que foi solto…");
    try {
      // cada item solto ganha um nome livre na pasta de destino ("nome copy.ext" se já existe) — nunca sobrescreve
      const tops: { name: string; items: Incoming[] }[] = [];
      if (entries) for (const en of entries) { const items: Incoming[] = []; await walk(en, en.name, items); tops.push({ name: en.name, items }); }
      else for (const f of files) tops.push({ name: f.name, items: [{ rel: f.name, file: f }] });
      const items = tops.flatMap(t => t.items);
      const total = items.reduce((n, x) => n + (x.file?.size || 0), 0);
      if (!items.length) return prog.done("Nada para copiar");
      if (total > MAX_DROP) throw new Error(`Grande demais para soltar aqui (${Math.round(total / 1048576)} MB, o limite é ${MAX_DROP / 1048576} MB) — copie pelo ${fileManagerName()}`);
      const nFiles = items.filter(x => x.file).length;
      let sent = 0;
      const landedPaths: string[] = [], dirs = new Set<string>();
      for (const t of tops) {
        const { path: top } = await post<{ path: string }>("ws/fs/free", { repoId, taskId, dest, name: t.name }, { quiet: true });
        landedPaths.push(top);
        for (const it of t.items) {
          const rel = top + it.rel.slice(t.name.length);
          if (it.dir) { if (rel === top) dirs.add(top); await post("ws/fs/upload", { repoId, taskId, path: rel, folder: true }, { quiet: true }); ghosts = [...ghosts, rel + "/"]; continue; }
          const f = it.file!;
          let off = 0;
          do {
            const data = b64(await f.slice(off, off + CHUNK).arrayBuffer());
            await post("ws/fs/upload", { repoId, taskId, path: rel, data, offset: off }, { quiet: true });
            off += CHUNK; sent += Math.min(CHUNK, f.size - (off - CHUNK));
            prog.update(`Copiando ${nFiles} arquivo${nFiles === 1 ? "" : "s"}… ${total ? Math.round((sent / total) * 100) : 100}%`);
          } while (off < f.size);
        }
      }
      await landed(landedPaths, dirs);
      prog.done(`${nFiles} arquivo${nFiles === 1 ? "" : "s"} copiado${nFiles === 1 ? "" : "s"} para ${dest ? base(dest) : "a raiz do projeto"}`);
    } catch (e) { prog.fail(e); await reload(); }
  }
  // soltar arquivo fora da árvore não pode abrir o arquivo no lugar do app (a WebView navegaria para ele)
  $effect(() => {
    const guard = (e: DragEvent) => { if (!e.defaultPrevented && e.dataTransfer && [...e.dataTransfer.types].includes("Files")) { e.preventDefault(); if (e.type === "dragover") e.dataTransfer.dropEffect = "none"; } };
    window.addEventListener("dragover", guard);
    window.addEventListener("drop", guard);
    return () => { window.removeEventListener("dragover", guard); window.removeEventListener("drop", guard); };
  });

  const abs = (p: string) => (root.replace(/[\\/]$/, "") + "/" + p.replace(/\/$/, "")).replace(/\//g, root.includes("\\") ? "\\" : "/");
  async function copy(t: string, msg: string) { try { await navigator.clipboard.writeText(t); ui.toast(msg); } catch (e) { ui.error(e); } }
  function rowMenu(r: Row) {
    if (!sel.includes(r.path)) pick(r.path);
    const at = dirOf(r.path, r.dir), d = decor.get(r.path), ts = targets(r.path), many = ts.length > 1;
    return [
      ...(!r.dir && !many ? [{ label: "Abrir", onclick: () => onopen(r.path, undefined, { preview: false }) }] : []),
      ...(!r.dir && !many && d && ondiff ? [{ label: "Abrir alterações", icon: GitCompareArrows, onclick: () => ondiff!(r.path) }] : []),
      { separator: true },
      { label: "Novo arquivo…", icon: FilePlus2, kbd: kb.label("explorer.newFile"), onclick: () => startNew("file", at) },
      { label: "Nova pasta…", icon: FolderPlus, kbd: kb.label("explorer.newFolder"), onclick: () => startNew("folder", at) },
      { separator: true },
      { label: "Recortar", icon: Scissors, kbd: kb.label("filesExplorer.cut"), onclick: () => toClip(ts, true) },
      { label: "Copiar", icon: Copy, kbd: kb.label("filesExplorer.copy"), onclick: () => toClip(ts, false) },
      { label: clip && clip.paths.length > 1 ? `Colar ${clip.paths.length} itens` : "Colar", icon: ClipboardPaste, kbd: kb.label("filesExplorer.paste"), disabled: !clip?.paths.length, onclick: () => paste(at) },
      { label: "Duplicar", icon: CopyPlus, kbd: kb.label("explorer.duplicate"), onclick: () => duplicate(ts) },
      { separator: true },
      ...(!many ? [{ label: "Renomear…", icon: Pencil, kbd: kb.label("renameFile"), onclick: () => startRename(r.path) }] : []),
      { label: many ? `Excluir ${ts.length} itens` : "Excluir", icon: Trash2, kbd: kb.label("deleteFile"), danger: true, onclick: () => remove(ts) },
      { separator: true },
      { label: many ? "Copiar caminhos" : "Copiar caminho", icon: Copy, kbd: kb.label("copyFilePath"), onclick: () => copy(ts.map(abs).join("\n"), many ? "Caminhos copiados" : "Caminho copiado") },
      { label: many ? "Copiar caminhos relativos" : "Copiar caminho relativo", icon: Copy, kbd: kb.label("copyRelativeFilePath"), onclick: () => copy(ts.map(strip).join("\n"), "Caminho relativo copiado") },
      { label: `Revelar no ${fileManagerName()}`, icon: FolderOpen, onclick: () => post("open", { path: abs(r.path), target: "files" }).catch(ui.error) },
      ...(onterminal ? [{ label: "Abrir no terminal integrado", icon: SquareTerminal, onclick: () => onterminal!(strip(at)) }] : []),
    ];
  }
  /** Clique direito no vazio da lista: ações na raiz do projeto */
  function rootMenu(e: MouseEvent) {
    if ((e.target as HTMLElement).closest("[data-p], input")) return;
    e.stopPropagation();
    ui.contextMenu(e, [
      { label: "Novo arquivo…", icon: FilePlus2, onclick: () => startNew("file", baseDir) },
      { label: "Nova pasta…", icon: FolderPlus, onclick: () => startNew("folder", baseDir) },
      { separator: true },
      { label: "Colar", icon: ClipboardPaste, kbd: kb.label("filesExplorer.paste"), disabled: !clip?.paths.length, onclick: () => paste(baseDir) },
      { separator: true },
      { label: `Revelar no ${fileManagerName()}`, icon: FolderOpen, onclick: () => post("open", { path: baseDir ? abs(baseDir) : root, target: "files" }).catch(ui.error) },
    ]);
  }
  /** Ações na pasta-base (o Gerenciador de Soluções chama pelo nó do projeto) */
  export function newIn(kind: "file" | "folder") { startNew(kind, baseDir); }
  export function pasteHere() { paste(baseDir); }
  export const canPaste = () => !!clip?.paths.length;

  // ------------------------------------------------------------ busca no conteúdo
  function runSearch() {
    clearTimeout(sTimer);
    sTimer = setTimeout(async () => {
      if (!sq.trim()) { results = []; truncated = false; return; }
      searching = true;
      try { const r = await get<any>("ws/search", { repoId, taskId, q: sq, regex: sRegex ? 1 : 0, case: sCase ? 1 : 0 }); results = r.results; truncated = !!r.truncated; } catch (e) { ui.error(e); }
      searching = false;
    }, 250);
  }
  const grouped = $derived.by(() => {
    const m = new Map<string, typeof results>();
    for (const r of results) m.set(r.path, [...(m.get(r.path) || []), r]);
    return [...m.entries()];
  });
  let shut = $state<Record<string, boolean>>({});
  function hl(text: string, query: string) {
    const t = text.replace(/^\s+/, "");
    if (!query) return [{ s: t, m: false }];
    let re: RegExp;
    try { re = new RegExp(sRegex ? query : query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), sCase ? "g" : "gi"); } catch { return [{ s: t, m: false }]; }
    const out: { s: string; m: boolean }[] = [];
    let last = 0;
    for (const m of t.matchAll(re)) { if (!m[0]) break; out.push({ s: t.slice(last, m.index), m: false }, { s: m[0], m: true }); last = m.index! + m[0].length; }
    out.push({ s: t.slice(last), m: false });
    return out;
  }
</script>

{#snippet editor(depth: number)}
  <div class="n editing" style="--d:{depth}">
    <span class="sp"></span>
    <FileIcon name={edit?.kind === "folder" ? "pasta" : edit?.value || "arquivo"} dir={edit?.kind === "folder"} size={15} />
    <input class="ren" use:grab bind:value={edit!.value} placeholder={edit?.kind === "folder" ? "nome da pasta" : edit?.kind === "file" ? "nome do arquivo (pode ter pastas/)" : ""}
      onkeydown={(e) => { if (e.key === "Enter" || e.key === "Escape") { if (e.key === "Enter") commitEdit(); else edit = null; listEl?.focus({ preventScroll: true }); } e.stopPropagation(); }}
      onblur={commitEdit} />
  </div>
{/snippet}

<div class="ft" class:emb={embedded}>
  {#if mode === "files"}
    {#if !embedded}
    <div class="bar">
      <label class="flt"><Search size={13} /><input bind:value={q} placeholder="Filtrar arquivos…" />{#if q}<button class="x" onclick={() => (q = "")}><X size={11} /></button>{/if}</label>
      <button class="ib" title="Novo arquivo" onclick={() => startNew("file", cursor ? dirOf(cursor, cursor.endsWith("/")) : baseDir)}><FilePlus2 size={14} /></button>
      <button class="ib" title="Nova pasta" onclick={() => startNew("folder", cursor ? dirOf(cursor, cursor.endsWith("/")) : baseDir)}><FolderPlus size={14} /></button>
      <button class="ib" title="Recarregar" onclick={() => { load(false, true); if (gitRepo) scm.touch(gitRepo); }}><RefreshCw size={13} class={loading ? "spin" : ""} /></button>
      <button class="ib" title="Recolher todas as pastas" onclick={() => { open = {}; saveOpen(); }}><ChevronsDownUp size={14} /></button>
    </div>
    {/if}
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div class="list" class:dz={dropAt === baseDir} bind:this={listEl} tabindex="0" role="tree" aria-label="Arquivos" aria-multiselectable="true" onkeydown={onKey}
      oncontextmenu={rootMenu} ondragover={dragOver} ondragleave={dragLeave} ondrop={onDrop}>
      {#if edit && edit.at === baseDir && edit.kind !== "rename"}{@render editor(depth0)}{/if}
      {#if loading && !all.length}<div class="none" style="--d:{depth0}">Carregando…</div>
      {:else if q.trim() && !matches.length}<div class="none">Nenhum arquivo com “{q}”.</div>
      {:else}
        {#each visible as r (r.path)}
          {@const d = r.dir ? null : decor.get(r.path)}
          {@const ft = r.dir ? fdecor.get(r.path) : null}
          {#if edit?.kind === "rename" && edit.path === r.path}{@render editor(r.depth)}
          {:else}
            <!-- linha é div (não button): o WebKit não arrasta <button>, e o foco fica na lista, que tem o teclado -->
            <!-- svelte-ignore a11y_click_events_have_key_events, a11y_interactive_supports_focus -->
            <div class="n {d?.tone || ''} {ft ? 'f-' + ft : ''}" class:file={!r.dir} class:on={!r.dir && active === r.path} class:cur={cursor === r.path} class:del={d?.tone === "del"}
              class:sel={sel.length > 1 && sel.includes(r.path)} class:cutting={clip?.cut && clip.paths.includes(r.path)} class:dz={!!dropAt && r.path.startsWith(dropAt)}
              class:dragged={dragging?.includes(r.path)} class:ign={isIgnored(r.path)}
              style="--d:{r.depth}" data-p={r.path} role="treeitem" aria-selected={sel.includes(r.path) || active === r.path} aria-expanded={r.dir ? !!open[r.path] : undefined}
              title={r.dir ? r.path : `${r.path}${d ? " · " + d.label : ""}`} draggable={!edit}
              ondragstart={(e) => dragStart(e, r)} ondragend={dragEnd}
              onclick={(e) => {
                listEl?.focus({ preventScroll: true });
                if (e.shiftKey || (isMac() ? e.metaKey : e.ctrlKey)) { pick(r.path, e); return; }
                pick(r.path);
                if (r.dir) toggleDir(r.path); else onopen(r.path, undefined, { preview: true });
              }}
              ondblclick={() => { if (!r.dir) onopen(r.path, undefined, { preview: false }); }}
              oncontextmenu={(e) => ui.contextMenu(e, rowMenu(r))}>
              {#if r.dir && !icons.hidesArrows}<ChevronRight size={12} class="chev {open[r.path] ? 'rot' : ''}" />{:else}<span class="sp"></span>{/if}
              <FileIcon name={r.dir ? r.path.slice(0, -1).split("/").pop() || r.name : r.name} dir={r.dir} open={!!open[r.path]} size={15} />
              <span class="nm ell">{#if q.trim()}<b>{r.name}</b> <span class="muted tiny">{r.path.split("/").slice(0, -1).join("/")}</span>{:else}{r.name}{/if}</span>
              {#if d}<span class="gl" title={d.label}>{d.letter}</span>{:else if ft}<span class="gd"></span>{/if}
            </div>
            {#if r.dir && open[r.path] && edit && edit.at === r.path && edit.kind !== "rename"}{@render editor(r.depth + 1)}{/if}
            {#if r.dir && open[r.path] && lazyBusy[r.path] && !lazyKids[r.path]}<div class="n wait" style="--d:{r.depth + 1}"><span class="sp"></span><RefreshCw size={11} class="spin" /><span class="tiny muted">lendo…</span></div>{/if}
          {/if}
        {/each}
      {/if}
    </div>
  {:else}
    <div class="bar search">
      <label class="flt"><Search size={13} /><input bind:value={sq} oninput={runSearch} placeholder="Buscar no projeto…" />
        <button class="tg" class:on={sCase} title="Diferenciar maiúsculas" onclick={() => { sCase = !sCase; runSearch(); }}><CaseSensitive size={14} /></button>
        <button class="tg" class:on={sRegex} title="Expressão regular" onclick={() => { sRegex = !sRegex; runSearch(); }}><Regex size={13} /></button>
        {#if searching}<RefreshCw size={12} class="spin" />{/if}</label>
    </div>
    {#if results.length}<div class="sum tiny muted">{results.length}{truncated ? "+" : ""} resultado{results.length === 1 ? "" : "s"} em {grouped.length} arquivo{grouped.length === 1 ? "" : "s"}</div>{/if}
    <div class="list">
      {#each grouped as [path, hits] (path)}
        {@const d = decor.get(path)}
        <button class="grp {d?.tone || ''}" onclick={() => (shut = { ...shut, [path]: !shut[path] })}>
          <ChevronRight size={12} class="chev {shut[path] ? '' : 'rot'}" />
          <FileIcon name={path.split("/").pop() || path} size={14} />
          <span class="ell"><b>{path.split("/").pop()}</b> <span class="muted tiny">{path.split("/").slice(0, -1).join("/")}</span></span><span class="cnt">{hits.length}</span>
        </button>
        {#if !shut[path]}
          {#each hits as h (h.line + ":" + h.col)}
            <button class="hit" onclick={() => onopen(h.path, h.line, { preview: true })} ondblclick={() => onopen(h.path, h.line, { preview: false })}>
              <span class="ln">{h.line}</span><span class="ell mono">{#each hl(h.text, sq) as part, i (i)}{#if part.m}<mark>{part.s}</mark>{:else}{part.s}{/if}{/each}</span></button>
          {/each}
        {/if}
      {:else}<div class="none">{sq ? (searching ? "Buscando…" : "Nada encontrado.") : "Digite para buscar no conteúdo dos arquivos."}</div>{/each}
    </div>
  {/if}
</div>

<style>
  .ft { display: flex; flex-direction: column; min-height: 0; height: 100%; }
  .bar { display: flex; align-items: center; gap: 2px; padding: 6px 8px; }
  .flt { flex: 1; display: flex; align-items: center; gap: 6px; height: 27px; padding: 0 6px 0 8px; border-radius: 7px; border: 1px solid var(--line-2);
    background: var(--bg-2); color: var(--muted); min-width: 0; margin-right: 2px; }
  .flt:focus-within { border-color: var(--accent); }
  .flt input { flex: 1; min-width: 0; border: 0; outline: none; background: none; color: var(--text); font: 12.5px var(--font); }
  .x { display: grid; place-items: center; width: 16px; height: 16px; border: 0; border-radius: 50%; background: var(--surface-3); color: var(--text-2); cursor: pointer; }
  .ib { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; flex: none; }
  .ib:hover { background: var(--surface-3); color: var(--text); }
  .tg { display: grid; place-items: center; width: 22px; height: 20px; border: 1px solid transparent; border-radius: 5px; background: none; color: var(--muted); cursor: pointer; flex: none; }
  .tg:hover { color: var(--text); }
  .tg.on { color: var(--accent); background: var(--accent-soft); border-color: var(--accent-line); }
  .list { flex: 1; overflow: auto; padding: 0 4px 10px; outline: none; }
  .emb, .emb .list { height: auto; flex: none; overflow: visible; padding: 0; }
  .emb .none { padding: 3px 0 3px calc(22px + var(--d, 0) * 12px); }
  /* ignorado pelo .gitignore: apagado, como no VS Code */
  .n.ign { opacity: 0.55; }
  .n.wait { cursor: default; gap: 6px; }
  .list:focus-visible .n.cur { box-shadow: inset 0 0 0 1px var(--accent); }
  .n { --d: 0; position: relative; display: flex; align-items: center; gap: 5px; width: 100%; height: 22px; padding: 0 6px 0 calc(4px + var(--d) * 12px); border: 0; border-radius: 5px;
    background: none; color: var(--text-2); font: 12.5px var(--font); text-align: left; cursor: pointer; user-select: none; -webkit-user-select: none; outline: none; }
  /* guias de indentação, como no VS Code */
  .n::before { content: ""; position: absolute; top: 0; bottom: 0; left: 10px; width: calc(var(--d) * 12px);
    background: repeating-linear-gradient(90deg, var(--line) 0 1px, transparent 1px 12px); pointer-events: none; }
  .n:hover { background: var(--surface-2); color: var(--text); }
  .n.cur { background: var(--surface-2); }
  .n.sel { background: var(--surface-3); color: var(--text); }
  .n.on { background: var(--accent-soft); color: var(--text); }
  .n.cutting, .n.dragged { opacity: 0.5; }
  /* destino de arrastar: a pasta e o que está dentro dela ficam marcados, como no VS Code */
  .n.dz, .list.dz { background: var(--accent-soft); }
  .n.dz { border-radius: 0; }
  .list.dz { box-shadow: inset 0 0 0 1px var(--accent-line); }
  .n :global(.chev) { color: var(--faint); flex: none; transition: transform var(--t) var(--ease); }
  .n :global(.chev.rot) { transform: rotate(90deg); }
  .nm { flex: 1; min-width: 0; }
  .sp { width: 12px; flex: none; }
  .gl { font: 650 10.5px/1 var(--mono); flex: none; width: 12px; text-align: center; }
  .gd { width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: 0.8; flex: none; margin-right: 3px; }
  /* cores do Git (iguais às do VS Code escuro/claro) */
  .n.mod, .grp.mod, .n.f-mod { color: #e2c08d; } .n.add, .grp.add, .n.f-add { color: #73c991; } .n.del, .grp.del { color: #e5717d; }
  .n.ren, .n.f-ren { color: #73c991; } .n.conf, .n.f-conf { color: #e5717d; }
  :global([data-theme="light"]) .n.mod, :global([data-theme="light"]) .n.f-mod, :global([data-theme="light"]) .grp.mod { color: #a26a00; }
  :global([data-theme="light"]) .n.add, :global([data-theme="light"]) .n.f-add, :global([data-theme="light"]) .n.ren, :global([data-theme="light"]) .grp.add { color: #2f8a4a; }
  :global([data-theme="light"]) .n.del, :global([data-theme="light"]) .n.conf, :global([data-theme="light"]) .grp.del { color: #c4314b; }
  .n.del .nm { text-decoration: line-through; opacity: 0.85; }
  .n.f-mod .gd, .n.f-add .gd, .n.f-conf .gd { opacity: 0.7; }
  .editing { cursor: default; background: var(--surface-2); }
  .ren { flex: 1; min-width: 0; height: 20px; border: 1px solid var(--accent); border-radius: 4px; outline: none; background: var(--bg-2); color: var(--text);
    font: 12.5px var(--font); padding: 0 5px; }
  .none { padding: 10px; font-size: 12px; color: var(--muted); }
  .sum { padding: 0 12px 4px; }
  .grp { display: flex; align-items: center; gap: 5px; width: 100%; padding: 4px 6px 2px; border: 0; background: none; font: 12.5px var(--font); color: var(--text-2);
    cursor: pointer; text-align: left; border-radius: 5px; }
  .grp:hover { background: var(--surface-2); }
  .grp :global(.chev) { color: var(--faint); flex: none; transition: transform var(--t) var(--ease); }
  .grp :global(.chev.rot) { transform: rotate(90deg); }
  .grp .ell { flex: 1; min-width: 0; }
  .cnt { font: 600 10.5px/1 var(--font); color: var(--text-2); background: var(--surface-3); padding: 2px 6px; border-radius: 99px; }
  .hit { display: flex; gap: 8px; width: 100%; padding: 2px 6px 2px 30px; border: 0; border-radius: 5px; background: none; color: var(--text-2);
    font: 12px var(--font); text-align: left; cursor: pointer; }
  .hit:hover { background: var(--surface-2); color: var(--text); }
  .hit mark { background: rgba(234, 179, 8, 0.28); color: var(--text); border-radius: 2px; outline: 1px solid rgba(234, 179, 8, 0.45); }
  .ln { color: var(--faint); font: 11px var(--mono); min-width: 26px; text-align: right; flex: none; }
</style>
