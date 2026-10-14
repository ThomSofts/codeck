<script lang="ts">
  // Barra de status (como a do VS Code): à esquerda a branch, sincronizar (↓↑), problemas e compilação/execução; à
  // direita, quando há um arquivo à vista, linha e coluna, indentação, codificação, fim de linha e linguagem (clicáveis).
  import { ArrowDown, ArrowUp, CircleX, GitBranch, Hammer, Loader2, Play, RefreshCw, TriangleAlert } from "@lucide/svelte";
  import { post } from "../../lib/api";
  import { edState } from "../../lib/editorstate.svelte";
  import { loadMonaco } from "../../lib/monaco";
  import { scm } from "../../lib/scm.svelte";
  import { ui } from "../../lib/ui.svelte";

  let { gitRepo, fileShown = false, building = null, running = 0, onbranch, onproblems, onrunning }:
    { gitRepo: string; fileShown?: boolean; building?: { done: boolean; ok: boolean; errors: number; action: string } | null; running?: number;
      onbranch?: () => void; onproblems?: () => void; onrunning?: (e: MouseEvent) => void } = $props();
  const st = $derived(scm.status[gitRepo] || null);
  let syncing = $state(false);
  async function sync() {
    if (!st || syncing) return;
    syncing = true;
    try {
      if (st.behind) await post("repo/pull", { id: gitRepo });
      if (st.ahead || !st.upstream) await post("repo/push", { id: gitRepo });
      if (!st.ahead && !st.behind && st.upstream) await post("repo/fetch", { id: gitRepo });
    } catch (e) { ui.error(e); }
    syncing = false;
    scm.touch(gitRepo);
  }
  const LANGS: [string, string][] = [["plaintext", "Texto"], ["csharp", "C#"], ["typescript", "TypeScript"], ["javascript", "JavaScript"], ["json", "JSON"], ["html", "HTML"],
    ["css", "CSS"], ["scss", "SCSS"], ["xml", "XML"], ["markdown", "Markdown"], ["python", "Python"], ["sql", "SQL"], ["yaml", "YAML"], ["shell", "Shell"],
    ["powershell", "PowerShell"], ["razor", "Razor"], ["go", "Go"], ["rust", "Rust"], ["java", "Java"], ["php", "PHP"], ["dockerfile", "Dockerfile"], ["ini", "INI"]];
  const langName = (id: string) => LANGS.find(l => l[0] === id)?.[1] || id;
  async function setLang(id: string) {
    const m = edState.editor?.getModel();
    if (!m) return;
    loadMonaco().then(mo => { mo.editor.setModelLanguage(m, id); edState.lang = id; });
  }
  function setEol(crlf: boolean) {
    const m = edState.editor?.getModel();
    if (!m) return;
    m.pushEOL(crlf ? 1 : 0);   // 0 = LF, 1 = CRLF
    edState.eol = crlf ? "CRLF" : "LF";
  }
  function goLine() {
    ui.ask({ title: "Ir para a linha", input: { label: `Linha (1–${edState.lines})`, value: String(edState.line) }, confirm: "Ir" }).then((v: any) => {
      const n = parseInt(v);
      const e = edState.editor;
      if (!n || !e) return;
      e.revealLineInCenter(n); e.setPosition({ lineNumber: n, column: 1 }); e.focus();
    });
  }
</script>

<div class="sb" class:busy={building && !building.done}>
  <button class="it" title={st?.upstream ? `${st.branch} ↔ ${st.upstream}` : "Branch (abre o Git)"} onclick={onbranch}><GitBranch size={12} /> {st?.detached ? (st.head || "").slice(0, 8) : st?.branch || "…"}{st?.dirty ? "*" : ""}</button>
  {#if st}
    <button class="it" title={st.upstream ? `Sincronizar: ${st.behind} para baixar, ${st.ahead} para enviar` : "Publicar a branch"} onclick={sync}>
      <RefreshCw size={12} class={syncing ? "spin" : ""} />{#if st.behind}<ArrowDown size={11} />{st.behind}{/if}{#if st.ahead}<ArrowUp size={11} />{st.ahead}{/if}</button>
  {/if}
  <button class="it" title="Problemas" onclick={onproblems}><CircleX size={12} /> {edState.errors} <TriangleAlert size={12} /> {edState.warnings}</button>
  {#if building}
    <span class="it static" class:ok={building.done && building.ok} class:bad={building.done && !building.ok}>
      {#if !building.done}<Loader2 size={12} class="spin" /> {building.action === "Clean" ? "Limpando…" : building.action === "Restore" ? "Restaurando…" : "Compilando…"}
      {:else}<Hammer size={12} /> {building.ok ? "Compilação OK" : `Falhou · ${building.errors} erro(s)`}{/if}</span>
  {/if}
  {#if running}<button class="it run" title="Processos em execução: mostrar ou parar" onclick={(e) => onrunning?.(e)}><Play size={11} fill="currentColor" /> {running} em execução</button>{/if}
  <span class="grow"></span>
  {#if fileShown && edState.line}
    <button class="it" title="Ir para a linha" onclick={goLine}>Ln {edState.line}, Col {edState.col}{edState.sel ? ` (${edState.sel} selecionado${edState.sel === 1 ? "" : "s"})` : ""}</button>
    <button class="it" title="Indentação" onclick={(e) => ui.contextMenu(e, [2, 4, 8].flatMap(n => [
      { label: `Espaços: ${n}`, onclick: () => edState.editor?.getModel()?.updateOptions({ tabSize: n, insertSpaces: true }) },
      { label: `Tab: ${n}`, onclick: () => edState.editor?.getModel()?.updateOptions({ tabSize: n, insertSpaces: false }) }]))}>{edState.indent}</button>
    <span class="it static">UTF-8</span>
    <button class="it" title="Fim de linha" onclick={(e) => ui.contextMenu(e, [{ label: "LF (Mac/Linux)", onclick: () => setEol(false) }, { label: "CRLF (Windows)", onclick: () => setEol(true) }])}>{edState.eol}</button>
    <button class="it" title="Linguagem" onclick={(e) => ui.contextMenu(e, LANGS.map(([id, nm]) => ({ label: (edState.lang === id ? "● " : "") + nm, onclick: () => setLang(id) })))}>{langName(edState.lang)}</button>
    {#if edState.lsp}<span class="it static lsp" class:ok={edState.lsp === "ativo"} title="Servidor de linguagem">{edState.lsp === "ativo" ? "● LSP" : edState.lsp}</span>{/if}
  {/if}
</div>

<style>
  .sb { display: flex; align-items: center; gap: 1px; height: 24px; padding: 0 6px; flex: none; border-top: 1px solid var(--line); background: var(--bg-2);
    font: 500 11.5px var(--font); color: var(--text-2); overflow: hidden; white-space: nowrap; transition: background var(--t); }
  .sb.busy { background: color-mix(in srgb, var(--accent) 14%, var(--bg-2)); }
  .it { display: inline-flex; align-items: center; gap: 4px; height: 20px; padding: 0 7px; border: 0; border-radius: 4px; background: none; color: inherit; font: inherit; cursor: pointer; }
  .it:hover:not(.static) { background: var(--surface-3); color: var(--text); }
  .it.static { cursor: default; }
  .ok { color: var(--good); } .bad { color: var(--bad); } .run { color: var(--good); }
  .grow { flex: 1; }
</style>
