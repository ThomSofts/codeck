<script lang="ts">
  // Gerenciador de Soluções (como o do Visual Studio): a solução, as pastas de solução, os projetos (tipo, framework,
  // projeto de inicialização em negrito) e os arquivos de cada um — a mesma árvore do explorador (criar, renomear,
  // excluir, arrastar, recortar/copiar/colar, cores do Git). Clique direito no projeto: definir como inicialização,
  // compilar, recompilar, limpar, novo arquivo/pasta. No topo, o que esta máquina tem para compilar e rodar.
  import { AppWindow, Box, Check, ChevronRight, CircleAlert, ClipboardPaste, Copy, Eye, EyeOff, FilePlus2, FolderOpen, FolderPlus, Globe, Hammer, Library, Play, RefreshCw, Sparkles, SquareTerminal, TestTube2, Trash2, Wrench } from "@lucide/svelte";
  import { tick, untrack } from "svelte";
  import { post } from "../../lib/api";
  import { dotnet, KIND_LABEL, type DnProject } from "../../lib/dotnet.svelte";
  import { fileManagerName } from "../../lib/native";
  import { ui } from "../../lib/ui.svelte";
  import FileIcon from "./FileIcon.svelte";
  import FileTree, { type FsChange } from "./FileTree.svelte";

  let { repoId, taskId = null, gitRepo = null, root = "", active = null, onopen, onterm, ondiff, onfs, onterminal }:
    { repoId: string; taskId?: string | null; gitRepo?: string | null; root?: string; active?: string | null; onopen: (path: string, line?: number, o?: { preview?: boolean }) => void;
      onterm?: (id: string) => void; ondiff?: (path: string) => void; onfs?: (changes: FsChange[]) => void; onterminal?: (dir: string) => void } = $props();
  const k = $derived(dotnet.key(repoId, taskId));
  $effect(() => { const kk = k; untrack(() => { if (!dotnet.data[kk]) dotnet.load(repoId, taskId); }); });
  const d = $derived(dotnet.data[k] || null);
  const c = $derived(dotnet.choice(repoId));
  const sln = $derived(dotnet.solution(repoId, taskId));
  const OPEN = "codeck.sln.open";
  let open = $state<Record<string, boolean>>((() => { try { return JSON.parse(localStorage.getItem(OPEN) || "{}")[`${repoId}|${taskId || ""}`] || {}; } catch { return {}; } })());
  $effect(() => {
    const v = JSON.stringify(open);
    try { const all = JSON.parse(localStorage.getItem(OPEN) || "{}"); all[`${repoId}|${taskId || ""}`] = JSON.parse(v); localStorage.setItem(OPEN, JSON.stringify(all)); } catch { /* sem armazenamento */ }
  });
  // como o "Mostrar todos os arquivos" do Visual Studio: bin/ e obj/ ficam escondidos até ligar
  let showAll = $state(false);
  const trees = $state<Record<string, FileTree | undefined>>({});
  const baseOf = (p: DnProject) => (p.dir === "." ? "" : p.dir + "/");
  async function inProject(p: DnProject, fn: (t: FileTree) => void) {
    if (!open[p.path]) { open = { ...open, [p.path]: true }; await tick(); }
    const t = trees[p.path];
    if (t) fn(t);
  }
  const abs = (rel: string) => (root.replace(/[\\/]$/, "") + "/" + rel.replace(/\/$/, "")).replace(/\//g, root.includes("\\") ? "\\" : "/");
  async function copy(t: string) { try { await navigator.clipboard.writeText(t); ui.toast("Caminho copiado"); } catch (e) { ui.error(e); } }

  const ICON: Record<string, any> = { web: Globe, console: SquareTerminal, winexe: AppWindow, library: Library, test: TestTube2 };
  const folders = $derived.by(() => {
    const m = new Map<string, DnProject[]>();
    for (const p of sln?.projects || []) { const f = p.folder || ""; m.set(f, [...(m.get(f) || []), p]); }
    return [...m.entries()].sort((a, b) => (a[0] === "" ? 1 : b[0] === "" ? -1 : a[0].localeCompare(b[0])));
  });
  const isStart = (p: DnProject) => c.startup.includes(p.path);
  function projMenu(p: DnProject) {
    return [
      { label: isStart(p) ? "É o projeto de inicialização" : "Definir como projeto de inicialização", icon: Check, disabled: isStart(p) || p.kind === "library", onclick: () => dotnet.toggleStartup(repoId, p.path) },
      { label: isStart(p) ? "Tirar da inicialização múltipla" : "Adicionar à inicialização múltipla", icon: Play, disabled: p.kind === "library",
        onclick: () => dotnet.toggleStartup(repoId, p.path, true) },
      { separator: true },
      { label: "Compilar", icon: Hammer, onclick: () => dotnet.run(repoId, taskId, "Build", { target: p.path, onterm }) },
      { label: "Recompilar", icon: Wrench, onclick: () => dotnet.run(repoId, taskId, "Rebuild", { target: p.path, onterm }) },
      { label: "Limpar", icon: Trash2, onclick: () => dotnet.run(repoId, taskId, "Clean", { target: p.path, onterm }) },
      { label: "Restaurar pacotes NuGet", icon: RefreshCw, onclick: () => dotnet.run(repoId, taskId, "Restore", { target: p.path, onterm }) },
      { separator: true },
      { label: "Novo arquivo…", icon: FilePlus2, onclick: () => inProject(p, t => t.newIn("file")) },
      { label: "Nova pasta…", icon: FolderPlus, onclick: () => inProject(p, t => t.newIn("folder")) },
      { label: "Colar", icon: ClipboardPaste, disabled: !trees[p.path]?.canPaste(), onclick: () => inProject(p, t => t.pasteHere()) },
      { separator: true },
      { label: "Abrir o arquivo do projeto", icon: Box, onclick: () => onopen(p.path, undefined, { preview: false }) },
      { label: "Copiar caminho", icon: Copy, onclick: () => copy(abs(p.dir === "." ? "" : p.dir)) },
      { label: `Revelar no ${fileManagerName()}`, icon: FolderOpen, onclick: () => post("open", { path: abs(p.dir === "." ? "" : p.dir), target: "files" }).catch(ui.error) },
      ...(onterminal ? [{ label: "Abrir no terminal integrado", icon: SquareTerminal, onclick: () => onterminal!(p.dir === "." ? "" : p.dir) }] : []),
    ];
  }
  const tc = $derived(d?.toolchain);
  const needsMsbuild = $derived(!!sln?.projects.some(p => p.netfx && !p.sdk));
  const hasWebFx = $derived(!!sln?.projects.some(p => p.netfx && p.kind === "web"));
</script>

<div class="sv">
  <div class="top">
    <span class="ttl">Gerenciador de Soluções</span>
    <button class="ib" class:on={showAll} title={showAll ? "Esconder bin/ e obj/" : "Mostrar todos os arquivos (bin/, obj/)"} onclick={() => (showAll = !showAll)}>{#if showAll}<Eye size={14} />{:else}<EyeOff size={14} />{/if}</button>
    <button class="ib" title="Ler a solução de novo" onclick={() => dotnet.load(repoId, taskId, true)}><RefreshCw size={13} class={dotnet.loading[k] ? "spin" : ""} /></button>
  </div>
  {#if !d}
    <div class="none">{dotnet.loading[k] ? "Lendo a solução…" : "Não consegui ler a solução."}</div>
  {:else if !d.solutions.length}
    <div class="none">Nenhuma solução (.sln) ou projeto .NET neste projeto.</div>
  {:else}
    {#if d.solutions.length > 1}
      <select class="input sm pick" value={c.sln} onchange={(e) => dotnet.set(repoId, { sln: (e.target as HTMLSelectElement).value, startup: [] })}>
        {#each d.solutions as s (s.path)}<option value={s.path}>{s.name} — {s.path}</option>{/each}
      </select>
    {/if}
    {#if (needsMsbuild && !tc?.msbuild) || (hasWebFx && !tc?.iisexpress)}
      <div class="warn small"><CircleAlert size={14} /><span>
        {#if needsMsbuild && !tc?.msbuild}Projetos .NET Framework no formato antigo precisam do <b>MSBuild</b> — {d.platform === "windows" ? "instale o Visual Studio ou as Build Tools" : "no Mac, só com o Mono (ou compile no Windows)"}.{/if}
        {#if hasWebFx && !tc?.iisexpress} Sites .NET Framework rodam no <b>IIS Express</b>{d.platform === "windows" ? " (vem com o Visual Studio)" : " — só no Windows"}.{/if}
      </span></div>
    {/if}
    <div class="tools tiny">
      <span class:ok={tc?.msbuild}>MSBuild</span><span class:ok={tc?.dotnet}>dotnet</span>
      {#if d.platform === "windows"}<span class:ok={tc?.iisexpress}>IIS Express</span>{:else}<span class:ok={tc?.mono}>Mono</span>{/if}
      {#if tc?.vs}<span class="ok" title={tc.vs}>{tc.vs.replace(/^Visual Studio /, "VS ")}</span>{/if}
      {#if d.platform === "windows" && sln?.path}<button class="lnk" onclick={() => post("dotnet/open-vs", { repoId, taskId, target: sln!.path }).catch(ui.error)}>Abrir no Visual Studio</button>{/if}
    </div>
    <div class="list">
      {#if sln}
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="sol" ondblclick={() => sln?.path && onopen(sln.path, undefined, { preview: false })}
          oncontextmenu={(e) => sln?.path && ui.contextMenu(e, [{ label: "Abrir o arquivo da solução", icon: Box, onclick: () => onopen(sln!.path!, undefined, { preview: false }) }])}><Sparkles size={13} /><b class="ell">Solução “{sln.name}”</b><span class="tiny muted">{sln.projects.length} projeto{sln.projects.length === 1 ? "" : "s"}</span></div>
        {#each folders as [folder, projs] (folder)}
          {#if folder}<div class="fold" style="--d:1"><FileIcon name={folder} dir open size={14} /><span class="ell">{folder}</span></div>{/if}
          {#each projs as p (p.path)}
            {@const I = ICON[p.kind] || Box}
            {@const depth = folder ? 2 : 1}
            <button class="proj" class:start={isStart(p)} class:missing={p.missing} style="--d:{depth}" title={`${p.path}${p.framework ? " · " + p.framework : ""}`}
              onclick={() => (open = { ...open, [p.path]: !open[p.path] })} ondblclick={() => !p.missing && p.kind !== "library" && dotnet.toggleStartup(repoId, p.path)}
              oncontextmenu={(e) => ui.contextMenu(e, projMenu(p))}>
              <ChevronRight size={12} class="chev {open[p.path] ? 'rot' : ''}" />
              <span class="pi k-{p.kind}"><I size={13} /></span>
              <span class="pn ell">{p.name}</span>
              {#if isStart(p)}<span class="st" title="Projeto de inicialização"><Play size={9} fill="currentColor" /></span>{/if}
              <span class="fw tiny">{p.netfx ? (p.framework || "").replace(".NET Framework ", "fx ") : p.framework || ""}</span>
            </button>
            {#if open[p.path] && !p.missing}
              <div class="meta tiny muted" style="--d:{depth + 1}">{KIND_LABEL[p.kind]}{p.sdk ? " · SDK" : p.netfx ? " · formato clássico" : ""}{p.iisUrl ? " · " + p.iisUrl : ""}</div>
              <FileTree bind:this={trees[p.path]} {repoId} {taskId} {gitRepo} {onopen} {ondiff} {onfs} {onterminal} {active}
                base={baseOf(p)} embedded depth0={depth + 1} hide={showAll ? [] : ["bin/", "obj/"]} />
            {/if}
          {/each}
        {/each}
      {/if}
    </div>
  {/if}
</div>

<style>
  .sv { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .top { display: flex; align-items: center; gap: 2px; padding: 8px 8px 4px 12px; }
  .ttl { flex: 1; min-width: 0; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ib { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; }
  .ib:hover { background: var(--surface-3); color: var(--text); }
  .ib.on { color: var(--accent); }
  .none { padding: 12px; font-size: 12px; color: var(--muted); }
  .pick { margin: 2px 8px 6px; width: calc(100% - 16px); height: 28px; font-size: 12px; }
  .warn { display: flex; gap: 7px; margin: 2px 8px 6px; padding: 7px 9px; border-radius: 8px; background: var(--warn-soft); color: var(--text-2); }
  .warn :global(svg) { color: var(--warn); flex: none; margin-top: 2px; }
  .tools { display: flex; flex-wrap: wrap; gap: 4px; padding: 0 10px 6px; }
  .tools span { padding: 1px 7px; border-radius: 99px; border: 1px solid var(--line-2); color: var(--faint); text-decoration: line-through; }
  .tools span.ok { color: var(--good); border-color: color-mix(in srgb, var(--good) 35%, transparent); text-decoration: none; }
  .lnk { border: 0; background: none; color: var(--accent); font: 600 11px var(--font); cursor: pointer; padding: 1px 4px; }
  .list { flex: 1; overflow: auto; padding: 0 4px 12px; }
  .sol { display: flex; align-items: center; gap: 6px; padding: 4px 8px; font-size: 12.5px; color: var(--text); }
  .sol :global(svg) { color: #9b6bdf; flex: none; }
  .fold, .meta { --d: 0; display: flex; align-items: center; gap: 6px; height: 22px; padding-left: calc(8px + var(--d) * 12px); font-size: 12.5px; color: var(--text-2); }
  .meta { height: 20px; padding-left: calc(22px + var(--d) * 12px); }
  .proj { --d: 0; display: flex; align-items: center; gap: 5px; width: 100%; height: 23px; padding: 0 6px 0 calc(4px + var(--d) * 12px); border: 0; border-radius: 5px;
    background: none; color: var(--text-2); font: 12.5px var(--font); text-align: left; cursor: pointer; }
  .proj:hover { background: var(--surface-2); color: var(--text); }
  .proj :global(.chev) { color: var(--faint); flex: none; transition: transform var(--t) var(--ease); }
  .proj :global(.chev.rot) { transform: rotate(90deg); }
  .pi { display: grid; place-items: center; width: 18px; height: 18px; border-radius: 5px; flex: none; color: #fff; background: #6b5bd6; }
  .pi.k-web { background: #2f8cf0; } .pi.k-console { background: #3a7d5c; } .pi.k-winexe { background: #6b5bd6; } .pi.k-library { background: #5a6276; } .pi.k-test { background: #c27c0e; }
  .pn { flex: 1; min-width: 0; color: var(--text); }
  .proj.start .pn { font-weight: 700; }
  .proj.missing { opacity: 0.5; text-decoration: line-through; }
  .st { display: grid; place-items: center; width: 15px; height: 15px; border-radius: 50%; background: var(--good); color: #0b0d12; flex: none; }
  .fw { color: var(--muted); font-family: var(--mono); flex: none; }
</style>
