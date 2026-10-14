<script lang="ts">
  // A barra do Visual Studio: configuração (Debug|Any CPU…), projeto(s) de inicialização com ▶ Iniciar (F5: compila e
  // abre), parar (Shift+F5) e o menu Compilar (⌘/Ctrl+Shift+B), Recompilar, Limpar, Restaurar NuGet.
  import { ChevronDown, Hammer, Loader2, Play, RefreshCw, Square, Trash2, Wrench, Zap } from "@lucide/svelte";
  import { dotnet, KIND_LABEL } from "../../lib/dotnet.svelte";
  import { kbd } from "../../lib/keys";
  import type { TermInfo } from "../../lib/work.svelte";
  import { ui } from "../../lib/ui.svelte";

  let { repoId, taskId = null, terms = [], onterm }: { repoId: string; taskId?: string | null; terms?: TermInfo[]; onterm?: (id: string) => void } = $props();
  const k = $derived(dotnet.key(repoId, taskId));
  const sln = $derived(dotnet.solution(repoId, taskId));
  const c = $derived(dotnet.choice(repoId));
  const b = $derived(dotnet.build[k] || null);
  const building = $derived(!!b && !b.done);
  const running = $derived(terms.filter(t => t.alive && String(t.meta?.run || (t.meta as any)?.dotnet || "").startsWith("start:")));
  const startLabel = $derived.by(() => {
    if (!sln) return "Iniciar";
    if (c.startup.length > 1) return `${c.startup.length} projetos`;
    const p = sln.projects.find(x => x.path === c.startup[0]);
    return p ? p.name : "Iniciar";
  });
  const profiles = $derived(c.startup.length === 1 ? sln?.projects.find(p => p.path === c.startup[0])?.profiles || [] : []);
  const startItems = $derived([
    { heading: "Projeto de inicialização" },
    ...(sln?.projects.filter(p => p.kind !== "library" && !p.missing).map(p => ({
      label: `${c.startup.includes(p.path) ? "● " : "○ "}${p.name}  · ${KIND_LABEL[p.kind]}`, onclick: () => dotnet.toggleStartup(repoId, p.path) })) || []),
    ...(sln && sln.projects.some(p => p.kind !== "library") ? [{ separator: true }, { heading: "Vários projetos (clique para incluir/tirar)" },
      ...sln.projects.filter(p => p.kind !== "library" && !p.missing).map(p => ({ label: `${c.startup.includes(p.path) ? "☑ " : "☐ "}${p.name}`, onclick: () => dotnet.toggleStartup(repoId, p.path, true) }))] : []),
    ...(profiles.length ? [{ separator: true }, { heading: "Perfil (launchSettings)" }, { label: `${!c.profile ? "● " : "○ "}Padrão`, onclick: () => dotnet.set(repoId, { profile: null }) },
      ...profiles.map(pr => ({ label: `${c.profile === pr.name ? "● " : "○ "}${pr.name}`, onclick: () => dotnet.set(repoId, { profile: pr.name }) }))] : []),
    { separator: true },
    { label: "Iniciar sem compilar", icon: Zap, onclick: () => dotnet.start(repoId, taskId, onterm) },
  ]);
  const buildItems = $derived([
    { label: `Compilar a solução`, icon: Hammer, kbd: kbd("mod+shift+b"), onclick: () => dotnet.run(repoId, taskId, "Build", { onterm }) },
    { label: "Recompilar a solução", icon: Wrench, onclick: () => dotnet.run(repoId, taskId, "Rebuild", { onterm }) },
    { label: "Limpar a solução", icon: Trash2, onclick: () => dotnet.run(repoId, taskId, "Clean", { onterm }) },
    { label: "Restaurar pacotes NuGet", icon: RefreshCw, onclick: () => dotnet.run(repoId, taskId, "Restore", { onterm }) },
  ]);
  /** "Debug|Any CPU" aparece só "Debug" (como no Visual Studio, a plataforma fica no seletor dela) */
  const cfgLabel = (cf: string) => (/\|\s*any\s*cpu$/i.test(cf) ? cf.split("|")[0] : cf.replace("|", " · "));
  function startF5() { dotnet.run(repoId, taskId, "Build", { startAfter: true, onterm }); }
  async function stop() { await dotnet.stop(running); }
  function onKey(e: KeyboardEvent) {
    if (!sln) return;
    if (e.key === "F5" && !e.shiftKey && !e.metaKey && !e.ctrlKey) { e.preventDefault(); startF5(); }
    else if (e.key === "F5" && e.shiftKey) { e.preventDefault(); stop(); }
    else if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "b") { e.preventDefault(); dotnet.run(repoId, taskId, "Build", { onterm }); }
  }
</script>

<svelte:window onkeydown={onKey} />

{#if sln}
  <div class="vs" role="toolbar" aria-label="Visual Studio">
    <select class="cfg" value={c.config} title="Configuração da solução" onchange={(e) => dotnet.set(repoId, { config: (e.target as HTMLSelectElement).value })}>
      {#each sln.configs as cf (cf)}<option value={cf}>{cfgLabel(cf)}</option>{/each}
    </select>
    <div class="start">
      {#if running.length}
        <button class="stop" title={`Parar (${kbd("shift")}F5)`} onclick={stop}><Square size={11} fill="currentColor" /></button>
      {/if}
      <button class="go" disabled={building} title={`Compilar e iniciar (F5)${c.startup.length ? "" : " — escolha o projeto de inicialização"}`} onclick={startF5}>
        {#if building && b?.startAfter}<Loader2 size={13} class="spin" />{:else}<Play size={12} fill="currentColor" />{/if}<span class="ell">{startLabel}</span></button>
      <button class="caret" title="Projeto de inicialização" onclick={(e) => ui.contextMenu(e, startItems)}><ChevronDown size={12} /></button>
    </div>
    <button class="bld" class:busy={building} title={building ? "Compilando…" : `Compilar (${kbd("mod+shift+b")})`} onclick={(e) => ui.contextMenu(e, buildItems)}>
      {#if building}<Loader2 size={13} class="spin" />{:else}<Hammer size={13} />{/if}
      {#if b?.done}<span class="res" class:ok={b.ok} class:bad={!b.ok}>{b.ok ? (b.warnings ? `${b.warnings}⚠` : "✓") : `${b.errors}✕`}</span>{/if}
    </button>
  </div>
{/if}

<style>
  .vs { display: flex; align-items: center; gap: 4px; padding: 2px; border-radius: 9px; background: var(--bg-2); border: 1px solid var(--line); flex: none; }
  .cfg { height: 24px; max-width: 150px; border: 0; border-radius: 6px; background: none; color: var(--text-2); font: 600 11.5px var(--font); padding: 0 4px; cursor: pointer; }
  .cfg:hover { background: var(--surface-3); color: var(--text); }
  .start { display: flex; align-items: center; }
  .go { display: inline-flex; align-items: center; gap: 6px; height: 24px; max-width: 190px; padding: 0 9px; border: 0; border-radius: 6px 0 0 6px; cursor: pointer;
    background: color-mix(in srgb, var(--good) 16%, transparent); color: var(--good); font: 650 12px var(--font); transition: background var(--t-fast); }
  .go:hover:not(:disabled) { background: color-mix(in srgb, var(--good) 26%, transparent); }
  .go:disabled { opacity: 0.75; cursor: progress; }
  .caret { display: grid; place-items: center; width: 20px; height: 24px; border: 0; border-radius: 0 6px 6px 0; margin-left: 1px; cursor: pointer;
    background: color-mix(in srgb, var(--good) 16%, transparent); color: var(--good); }
  .caret:hover { background: color-mix(in srgb, var(--good) 26%, transparent); }
  .stop { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; margin-right: 3px; cursor: pointer; background: var(--bad-soft); color: var(--bad);
    animation: pulse-stop 1.6s var(--ease) infinite; }
  @keyframes pulse-stop { 50% { box-shadow: 0 0 0 3px color-mix(in srgb, var(--bad) 22%, transparent); } }
  .bld { display: inline-flex; align-items: center; gap: 5px; height: 24px; padding: 0 7px; border: 0; border-radius: 6px; background: none; color: var(--text-2); cursor: pointer; font: 650 11px var(--font); }
  .bld:hover { background: var(--surface-3); color: var(--text); }
  .bld.busy { color: var(--accent); }
  .res.ok { color: var(--good); } .res.bad { color: var(--bad); }
  @media (prefers-reduced-motion: reduce) { .stop { animation: none; } }
  @container (max-width: 980px) { .cfg { max-width: 96px; } .go { max-width: 130px; } }
  @container (max-width: 760px) { .cfg { max-width: 70px; } .go span { display: none; } }
</style>
