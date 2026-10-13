<script lang="ts">
  // Revisão da tarefa: o que mudou desde a base, arquivo por arquivo, num diff do Monaco (antes × agora).
  //   · o lado "agora" é editável; a seta na margem desfaz um trecho; ⌘S/Ctrl+S salva;
  //   · selecione linhas e "Comentar" — os comentários viram UM prompt para o agente da tarefa (arquivo:linha + pedido).
  import { MessageSquarePlus, RefreshCw, Send, Trash2 } from "@lucide/svelte";
  import type * as Monaco from "monaco-editor";
  import { untrack } from "svelte";
  import { get, post } from "../../lib/api";
  import { loadMonaco, monacoTheme } from "../../lib/monaco";
  import { ui } from "../../lib/ui.svelte";
  import { kbd } from "../../lib/keys";
  import type { Project, Task } from "../../lib/work.svelte";
  import { work } from "../../lib/work.svelte";
  import { typeInto } from "./Terminal.svelte";

  let { project, task, onagent }: { project: Project; task: Task; onagent?: (termId: string) => void } = $props();
  type F = { path: string; add: number | null; del: number | null; status: string };
  let files = $state<F[]>([]);
  let sel = $state<string | null>(null);
  let loading = $state(true);
  let host: HTMLDivElement | undefined = $state();
  let diff: Monaco.editor.IStandaloneDiffEditor | null = null;
  let monaco: typeof Monaco | null = null;
  let mtime = 0;
  let shown = 0;
  let changed = $state(false);
  type C = { path: string; from: number; to: number; text: string; quote: string };
  let comments = $state<C[]>(readComments());
  function readComments(): C[] { try { return JSON.parse(localStorage.getItem("codeck.review." + task.id) || "[]"); } catch { return []; } }
  $effect(() => { const c = JSON.stringify(comments); try { localStorage.setItem("codeck.review." + task.id, c); } catch { /* sem armazenamento */ } });

  async function loadFiles() {
    loading = true;
    try {
      files = (await get<{ files: F[] }>("ws/task/changes", { repoId: project.id, taskId: task.id })).files;
      if (!sel || !files.some(f => f.path === sel)) sel = files[0]?.path || null;
    } catch (e) { ui.error(e); }
    loading = false;
  }
  const taskId = $derived(task.id);   // a prop troca de objeto a cada leitura (2,5 s): só a troca de tarefa recarrega
  $effect(() => { void taskId; untrack(loadFiles); });

  $effect(() => {
    if (!host) return;
    let dead = false;
    loadMonaco().then(m => {
      if (dead || !host) return;
      monaco = m;
      diff = m.editor.createDiffEditor(host, { automaticLayout: true, theme: monacoTheme(), renderSideBySide: true, originalEditable: false,
        renderMarginRevertIcon: true, ignoreTrimWhitespace: false, fontFamily: '"JetBrains Mono Variable", ui-monospace, Menlo, monospace', fontSize: 13,
        minimap: { enabled: false }, scrollBeyondLastLine: false, renderOverviewRuler: true, fixedOverflowWidgets: true });
      diff.getModifiedEditor().addCommand(m.KeyMod.CtrlCmd | m.KeyCode.KeyS, () => save());
      diff.getModifiedEditor().addCommand(m.KeyMod.CtrlCmd | m.KeyMod.Shift | m.KeyCode.KeyC, () => comment());
      if (sel) show(sel).catch(() => {});
    });
    return () => { dead = true; const m = diff?.getModel(); diff?.dispose(); diff = null; m?.original.dispose(); m?.modified.dispose(); };
  });
  // a tarefa pode ter sido removida enquanto o diff carregava: a resposta (404) é ignorada, não vira erro solto
  $effect(() => { const s = sel; if (s && diff) show(s).catch(() => {}); });

  async function show(path: string) {
    if (!diff || !monaco) return;
    const [base, cur] = await Promise.all([
      get<any>("ws/task/base-file", { repoId: project.id, taskId: task.id, path }),
      get<any>("ws/file", { repoId: project.id, taskId: task.id, path }).catch(() => ({ text: "" })),
    ]);
    if (sel !== path || !diff) return;
    const old = diff.getModel();
    const n = ++shown;   // URIs únicas por exibição: o modelo antigo só é liberado DEPOIS que o diff solta ele
    const uriO = monaco.Uri.parse(`review-base:///${task.id}/${n}/${path}`), uriM = monaco.Uri.parse(`review:///${task.id}/${n}/${path}`);
    const original = monaco.editor.createModel(base.text || "", undefined, uriO);
    const modified = monaco.editor.createModel(cur.text ?? "", undefined, uriM);
    mtime = cur.mtime || 0;
    changed = false;
    modified.onDidChangeContent(() => (changed = true));
    diff.setModel({ original, modified });
    old?.original.dispose(); old?.modified.dispose();
    setTimeout(() => diff?.revealFirstDiff(), 60);
  }

  async function save() {
    const m = diff?.getModel()?.modified;
    if (!m || !sel) return;
    try {
      const r = await post<{ mtime: number }>("ws/file", { repoId: project.id, taskId: task.id, path: sel, text: m.getValue(), mtime });
      mtime = r.mtime; changed = false;
      ui.toast(`${sel.split("/").pop()} salvo`);
      loadFiles();
    } catch (e) { ui.error(e); }
  }

  async function comment() {
    const ed = diff?.getModifiedEditor();
    const range = ed?.getSelection();
    if (!ed || !range || !sel) return;
    const from = range.startLineNumber, to = range.endLineNumber;
    const quote = ed.getModel()!.getValueInRange({ startLineNumber: from, startColumn: 1, endLineNumber: to, endColumn: ed.getModel()!.getLineMaxColumn(to) });
    const text = await ui.ask({ title: `Comentário em ${sel.split("/").pop()}:${from}${to > from ? "-" + to : ""}`, input: { label: "O que o agente deve fazer aqui?", multiline: true, required: true }, confirm: "Adicionar" });
    if (text) comments = [...comments, { path: sel, from, to, text, quote: quote.slice(0, 600) }];
  }

  const agentTerm = $derived(task.terms.find(t => t.kind === "agent" && t.alive) || null);
  async function sendToAgent() {
    if (!comments.length) return;
    const prompt = "Revisão das suas alterações — ajuste os pontos abaixo:\n\n" + comments.map((c, i) =>
      `${i + 1}. ${c.path}:${c.from}${c.to > c.from ? "-" + c.to : ""}\n   Trecho: ${c.quote.split("\n")[0].trim().slice(0, 120)}\n   Pedido: ${c.text}`).join("\n\n");
    if (agentTerm) {
      // texto colado de uma vez: o agente recebe como um bloco (bracketed paste) e só envia no Enter
      typeInto(agentTerm.id, "\x1b[200~" + prompt + "\x1b[201~\r");
      onagent?.(agentTerm.id);
    } else {
      const acc = work.defaultAccount(project);
      if (!acc) return ui.toast("Nenhuma conta de IA configurada", "info");
      const t = await post<any>("ws/agent", { repoId: project.id, taskId: task.id, accountId: acc, prompt });
      await work.load();
      onagent?.(t.id);
    }
    comments = [];
    ui.toast("Revisão enviada ao agente");
  }
  const tone = (s: string) => (s === "A" ? "good" : s === "D" ? "bad" : "warn");
</script>

<div class="rv">
  <aside class="files">
    <div class="fh"><b>{files.length} arquivo(s)</b><span class="tiny muted">desde {task.base}</span>
      <button class="btn sm ghost icon" title="Recarregar" onclick={loadFiles}><RefreshCw size={13} class={loading ? "spin" : ""} /></button></div>
    <div class="fl">
      {#each files as f (f.path)}
        <button class="f" class:on={sel === f.path} onclick={() => (sel = f.path)} title={f.path}>
          <span class="st {tone(f.status)}">{f.status}</span>
          <span class="ell"><b>{f.path.split("/").pop()}</b> <span class="tiny muted">{f.path.split("/").slice(0, -1).join("/")}</span></span>
          {#if f.add != null}<span class="tiny add">+{f.add}</span><span class="tiny del">−{f.del}</span>{/if}
          {#if comments.some(c => c.path === f.path)}<span class="cm">{comments.filter(c => c.path === f.path).length}</span>{/if}
        </button>
      {:else}<div class="none">{loading ? "Lendo…" : "Nada mudou ainda nesta tarefa."}</div>{/each}
    </div>
    {#if comments.length}
      <div class="cl">
        <div class="fh"><b>Comentários ({comments.length})</b></div>
        {#each comments as c, i (i)}
          <div class="c"><span class="tiny mono">{c.path.split("/").pop()}:{c.from}</span><span class="small">{c.text}</span>
            <button class="btn sm ghost icon" onclick={() => (comments = comments.filter((_, j) => j !== i))}><Trash2 size={12} /></button></div>
        {/each}
        <button class="btn sm primary" onclick={sendToAgent}><Send size={13} /> {agentTerm ? "Enviar ao agente" : "Abrir agente com a revisão"}</button>
      </div>
    {/if}
  </aside>
  <div class="main">
    <div class="bar">
      <span class="mono small ell">{sel || ""}</span>
      <span class="grow"></span>
      {#if changed}<span class="pill warn">não salvo</span>{/if}
      <button class="btn sm" disabled={!sel} onclick={comment} title={`Selecione linhas no lado direito (${kbd("mod+shift+c")})`}><MessageSquarePlus size={13} /> Comentar</button>
      <button class="btn sm" disabled={!changed} onclick={save}>Salvar <span class="kbd">{kbd("mod+s")}</span></button>
    </div>
    <div class="host" bind:this={host}></div>
  </div>
</div>

<style>
  .rv { height: 100%; display: grid; grid-template-columns: 260px minmax(0, 1fr); min-height: 0; }
  .files { display: flex; flex-direction: column; border-right: 1px solid var(--line); min-height: 0; }
  .fh { display: flex; align-items: center; gap: 8px; padding: 10px 10px 6px; font-size: 12.5px; }
  .fh .tiny { flex: 1; }
  .fl { flex: 1; overflow: auto; padding: 0 6px 8px; }
  .f { display: flex; align-items: center; gap: 7px; width: 100%; padding: 5px 6px; border: 0; border-radius: 7px; background: none; color: var(--text-2);
    font: 12.5px var(--font); text-align: left; cursor: pointer; }
  .f:hover { background: var(--surface-2); }
  .f.on { background: var(--accent-soft); color: var(--text); }
  .f .ell { flex: 1; min-width: 0; }
  .st { font: 700 10px/1 var(--mono); width: 16px; height: 16px; display: grid; place-items: center; border-radius: 4px; flex: none; }
  .st.good { background: var(--good-soft); color: var(--good); } .st.bad { background: var(--bad-soft); color: var(--bad); } .st.warn { background: var(--warn-soft); color: var(--warn); }
  .add { color: var(--good); } .del { color: var(--bad); }
  .cm { font: 650 10px/1 var(--font); padding: 3px 5px; border-radius: 99px; background: var(--accent); color: #fff; }
  .none { padding: 12px; font-size: 12px; color: var(--muted); }
  .cl { border-top: 1px solid var(--line); padding: 0 8px 10px; display: grid; gap: 6px; max-height: 45%; overflow: auto; }
  .c { display: grid; grid-template-columns: 1fr auto; gap: 2px 6px; padding: 6px 8px; border-radius: 8px; background: var(--surface-2); }
  .c .small { grid-column: 1; }
  .c button { grid-row: 1 / span 2; grid-column: 2; }
  .main { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
  .bar { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border-bottom: 1px solid var(--line); }
  .grow { flex: 1; }
  .host { flex: 1; min-height: 0; }
</style>
