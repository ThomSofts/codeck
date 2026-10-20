<script lang="ts">
  // A parte de compilação da barra do Visual Studio: configuração (Debug|Any CPU…) e o menu Compilar (⌘/Ctrl+Shift+B),
  // Recompilar, Limpar, Restaurar NuGet. Iniciar/depurar (F5) fica no RunBar, que serve a todas as linguagens.
  import { Hammer, Loader2, RefreshCw, Trash2, Wrench } from "@lucide/svelte";
  import { dotnet } from "../../lib/dotnet.svelte";
  import { kbd } from "../../lib/keys";
  import { ui } from "../../lib/ui.svelte";

  let { repoId, taskId = null, onterm }: { repoId: string; taskId?: string | null; onterm?: (id: string) => void } = $props();
  const k = $derived(dotnet.key(repoId, taskId));
  const sln = $derived(dotnet.solution(repoId, taskId));
  const c = $derived(dotnet.choice(repoId));
  const b = $derived(dotnet.build[k] || null);
  const building = $derived(!!b && !b.done);
  const buildItems = $derived([
    { label: `Compilar a solução`, icon: Hammer, kbd: kbd("mod+shift+b"), onclick: () => dotnet.run(repoId, taskId, "Build", { onterm }) },
    { label: "Recompilar a solução", icon: Wrench, onclick: () => dotnet.run(repoId, taskId, "Rebuild", { onterm }) },
    { label: "Limpar a solução", icon: Trash2, onclick: () => dotnet.run(repoId, taskId, "Clean", { onterm }) },
    { label: "Restaurar pacotes NuGet", icon: RefreshCw, onclick: () => dotnet.run(repoId, taskId, "Restore", { onterm }) },
  ]);
  /** "Debug|Any CPU" aparece só "Debug" (como no Visual Studio, a plataforma fica no seletor dela) */
  const cfgLabel = (cf: string) => (/\|\s*any\s*cpu$/i.test(cf) ? cf.split("|")[0] : cf.replace("|", " · "));
  function onKey(e: KeyboardEvent) {
    if (!sln) return;
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "b") { e.preventDefault(); dotnet.run(repoId, taskId, "Build", { onterm }); }
  }
</script>

<svelte:window onkeydown={onKey} />

{#if sln}
  <div class="vs" role="toolbar" aria-label="Visual Studio">
    <select class="cfg" value={c.config} title="Configuração da solução" onchange={(e) => dotnet.set(repoId, { config: (e.target as HTMLSelectElement).value })}>
      {#each sln.configs as cf (cf)}<option value={cf}>{cfgLabel(cf)}</option>{/each}
    </select>
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
  .bld { display: inline-flex; align-items: center; gap: 5px; height: 24px; padding: 0 7px; border: 0; border-radius: 6px; background: none; color: var(--text-2); cursor: pointer; font: 650 11px var(--font); }
  .bld:hover { background: var(--surface-3); color: var(--text); }
  .bld.busy { color: var(--accent); }
  .res.ok { color: var(--good); } .res.bad { color: var(--bad); }
  @container (max-width: 980px) { .cfg { max-width: 96px; } }
  @container (max-width: 760px) { .cfg { max-width: 70px; } }
</style>
