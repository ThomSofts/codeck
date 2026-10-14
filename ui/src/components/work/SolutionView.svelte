<script lang="ts">
  // Gerenciador de Soluções (como o do Visual Studio): a solução, as pastas de solução, os projetos (tipo, framework,
  // projeto de inicialização em negrito) e os arquivos de cada um. Clique direito no projeto: definir como
  // inicialização, compilar, recompilar, limpar, iniciar. No topo, o que esta máquina tem para compilar e rodar.
  import { AppWindow, Box, Check, ChevronRight, CircleAlert, Globe, Hammer, Library, Play, RefreshCw, Sparkles, SquareTerminal, TestTube2, Trash2, Wrench } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { get, post } from "../../lib/api";
  import { dotnet, KIND_LABEL, type DnProject } from "../../lib/dotnet.svelte";
  import { ui } from "../../lib/ui.svelte";
  import FileIcon from "./FileIcon.svelte";

  let { repoId, taskId = null, active = null, onopen, onterm }:
    { repoId: string; taskId?: string | null; active?: string | null; onopen: (path: string, line?: number, o?: { preview?: boolean }) => void; onterm?: (id: string) => void } = $props();
  const k = $derived(dotnet.key(repoId, taskId));
  $effect(() => { const kk = k; untrack(() => { if (!dotnet.data[kk]) dotnet.load(repoId, taskId); }); });
  const d = $derived(dotnet.data[k] || null);
  const c = $derived(dotnet.choice(repoId));
  const sln = $derived(dotnet.solution(repoId, taskId));
  let files = $state<string[]>([]);
  let open = $state<Record<string, boolean>>({});
  $effect(() => { void k; get<{ files: string[] }>("ws/files", { repoId, taskId }).then(r => (files = r.files)).catch(() => {}); });

  const ICON: Record<string, any> = { web: Globe, console: SquareTerminal, winexe: AppWindow, library: Library, test: TestTube2 };
  const folders = $derived.by(() => {
    const m = new Map<string, DnProject[]>();
    for (const p of sln?.projects || []) { const f = p.folder || ""; m.set(f, [...(m.get(f) || []), p]); }
    return [...m.entries()].sort((a, b) => (a[0] === "" ? 1 : b[0] === "" ? -1 : a[0].localeCompare(b[0])));
  });
  function filesOf(p: DnProject, prefix: string) {
    const base = (p.dir === "." ? "" : p.dir + "/") + prefix;
    const dirs = new Set<string>(), fl: string[] = [];
    for (const f of files) {
      if (!f.startsWith(base)) continue;
      const rest = f.slice(base.length), i = rest.indexOf("/");
      if (/^(bin|obj)\//i.test(rest) && !prefix) continue;
      if (i >= 0) dirs.add(rest.slice(0, i)); else fl.push(f);
    }
    return { dirs: [...dirs].sort((a, b) => a.localeCompare(b)), files: fl.sort((a, b) => a.localeCompare(b)) };
  }
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
      { label: "Abrir o arquivo do projeto", icon: Box, onclick: () => onopen(p.path, undefined, { preview: false }) },
    ];
  }
  const tc = $derived(d?.toolchain);
  const needsMsbuild = $derived(!!sln?.projects.some(p => p.netfx && !p.sdk));
  const hasWebFx = $derived(!!sln?.projects.some(p => p.netfx && p.kind === "web"));
</script>

{#snippet ftree(p: DnProject, prefix: string, depth: number)}
  {@const t = filesOf(p, prefix)}
  {#each t.dirs as dname (dname)}
    {@const key = p.path + ":" + prefix + dname}
    <button class="n" style="--d:{depth}" onclick={() => (open = { ...open, [key]: !open[key] })}>
      <ChevronRight size={12} class="chev {open[key] ? 'rot' : ''}" /><FileIcon name={dname} dir open={!!open[key]} size={15} /><span class="ell">{dname}</span></button>
    {#if open[key]}{@render ftree(p, prefix + dname + "/", depth + 1)}{/if}
  {/each}
  {#each t.files as f (f)}
    <button class="n" class:on={active === f} style="--d:{depth}" onclick={() => onopen(f, undefined, { preview: true })} ondblclick={() => onopen(f, undefined, { preview: false })}>
      <span class="sp"></span><FileIcon name={f.split("/").pop() || f} size={15} /><span class="ell">{f.split("/").pop()}</span></button>
  {/each}
{/snippet}

<div class="sv">
  <div class="top">
    <span class="ttl">Gerenciador de Soluções</span>
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
        <div class="sol"><Sparkles size={13} /><b class="ell">Solução “{sln.name}”</b><span class="tiny muted">{sln.projects.length} projeto{sln.projects.length === 1 ? "" : "s"}</span></div>
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
              {@render ftree(p, "", depth + 1)}
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
  .proj, .n { --d: 0; display: flex; align-items: center; gap: 5px; width: 100%; height: 23px; padding: 0 6px 0 calc(4px + var(--d) * 12px); border: 0; border-radius: 5px;
    background: none; color: var(--text-2); font: 12.5px var(--font); text-align: left; cursor: pointer; }
  .proj:hover, .n:hover { background: var(--surface-2); color: var(--text); }
  .n.on { background: var(--accent-soft); color: var(--text); }
  .proj :global(.chev), .n :global(.chev) { color: var(--faint); flex: none; transition: transform var(--t) var(--ease); }
  .proj :global(.chev.rot), .n :global(.chev.rot) { transform: rotate(90deg); }
  .sp { width: 12px; flex: none; }
  .pi { display: grid; place-items: center; width: 18px; height: 18px; border-radius: 5px; flex: none; color: #fff; background: #6b5bd6; }
  .pi.k-web { background: #2f8cf0; } .pi.k-console { background: #3a7d5c; } .pi.k-winexe { background: #6b5bd6; } .pi.k-library { background: #5a6276; } .pi.k-test { background: #c27c0e; }
  .pn { flex: 1; min-width: 0; color: var(--text); }
  .proj.start .pn { font-weight: 700; }
  .proj.missing { opacity: 0.5; text-decoration: line-through; }
  .st { display: grid; place-items: center; width: 15px; height: 15px; border-radius: 50%; background: var(--good); color: #0b0d12; flex: none; }
  .fw { color: var(--muted); font-family: var(--mono); flex: none; }
</style>
