<script lang="ts">
  // ⌘K / Ctrl+K: ir para qualquer tela, repositório, catálogo ou PR, e disparar ações.
  import { untrack } from "svelte";
  import { ArrowRight, FolderGit2, GitPullRequest, Hammer, Keyboard, Layers, Plus, RefreshCw, Search, Sparkles, Zap, KanbanSquare, Code2 } from "@lucide/svelte";
  import { COMMANDS, kb } from "../lib/keybindings.svelte";
  import { work } from "../lib/work.svelte";
  import { post } from "../lib/api";
  import { repos } from "../lib/repos.svelte";
  import { go } from "../lib/router.svelte";
  import { store } from "../lib/store.svelte";
  import { ui } from "../lib/ui.svelte";
  import ProviderIcon from "./ProviderIcon.svelte";

  let q = $state("");
  let idx = $state(0);
  let input: HTMLInputElement | undefined = $state();
  // os comandos que dá para executar agora (o que tem quem execute depende da tela): lidos ao abrir
  let opened = $state(0);
  $effect(() => kb.on("workbench.action.showCommands", () => { ui.palette = !ui.palette; }));

  interface Item { group: string; label: string; sub?: string; icon?: any; provider?: string; run: () => void }
  const items = $derived.by<Item[]>(() => {
    void opened;
    const s = store.s;
    // "> texto" (como no VS Code): só os comandos
    const cmds: Item[] = COMMANDS.filter(c => c.id !== "workbench.action.showCommands" && kb.has(c.id))
      .map(c => ({ group: "Comandos", label: `${c.group}: ${c.label}`, sub: kb.label(c.id) || undefined, icon: Keyboard, run: () => setTimeout(() => kb.run(c.id), 30) }));
    if (q.trimStart().startsWith(">")) {
      const words = q.trim().slice(1).toLowerCase().split(/\s+/).filter(Boolean);
      return cmds.filter(i => words.every(w => i.label.toLowerCase().includes(w))).slice(0, 80);
    }
    const out: Item[] = [
      ...cmds,
      ...[["projects", "Projetos (hub)"], ["board", "Quadro"], ["ai", "IA — agentes, contas, skills e MCPs"], ["inbox", "Fila"], ["prs", "Pull requests"], ["builds", "Builds e Actions"], ["deploys", "Deploys"], ["issues", "Issues e tarefas"], ["sprints", "Sprints e projetos"],
          ["repos", "Repositórios"], ["automation", "Automação"], ["analytics", "Análise"], ["history", "Histórico"], ["settings", "Contas e ajustes"]]
        .map(([id, label]) => ({ group: "Ir para", label, icon: ArrowRight, run: () => go("/" + id) })),
      { group: "Ações", label: "Ler GitHub e Azure agora", icon: RefreshCw, run: async () => { const ok = await store.refresh(); ui.toast(ok ? "Tudo atualizado" : "A leitura está demorando — os dados chegam assim que ela terminar", ok ? "ok" : "info"); } },
      { group: "Ações", label: "Novo cartão no quadro", icon: KanbanSquare, run: () => go("/board/new") },
      { group: "Ações", label: "Novo grupo de projetos", icon: Layers, run: () => work.newGroup([]) },
      { group: "Ações", label: "Nova regra de automação", icon: Zap, run: () => go("/automation/new") },
      { group: "Ações", label: "Adicionar repositório local", icon: Plus, run: () => go("/repos/add") },
      { group: "Ações", label: "Novo catálogo de repositórios", icon: Plus, run: () => go("/repos/new-catalog") },
      { group: "Ações", label: "Conectar conta do GitHub", icon: Plus, run: () => go("/settings/github") },
      ...work.projects.map(p => ({ group: "Projetos abertos", label: p.name, sub: work.groupOf(p.id)?.name || p.path, icon: Code2, provider: p.provider || undefined,
                                    run: () => go("/work/" + p.id) })),
      ...work.projects.map(p => ({ group: "Abrir agente", label: `Abrir agente em ${p.name}`, sub: "escolher a conta de IA", icon: Sparkles, run: () => work.launch(p.id) })),
      ...work.groups.map(g => ({ group: "Grupos", label: g.name, sub: `${g.repoIds.length} projeto(s) — abrir todos`, icon: Layers, run: async () => { await work.openGroup(g.id); const id = g.repoIds[0]; if (id) go("/work/" + id); } })),
      ...repos.local.filter(r => !/[\\/]\.worktrees[\\/]/.test(r.path)).map(r => ({ group: "Repositórios", label: r.name, sub: r.status?.branch || r.path, icon: FolderGit2, provider: r.provider || undefined,
                                  run: () => go("/repo/" + r.id) })),
      ...repos.catalogs.map(c => ({ group: "Catálogos", label: c.name, sub: `${c.sources.length} origem(ns)`, icon: FolderGit2, run: () => go("/repos/catalog/" + c.id) })),
      ...(s ? [...s.myPrs, ...s.prs] : []).slice(0, 200).map(p => ({ group: "Pull requests", label: `#${p.prId} ${p.title}`, sub: `${p.org}/${p.repo} · ${p.creatorName}`,
        icon: GitPullRequest, provider: p.provider, run: () => go(`/prs/${s!.myPrs.includes(p) ? "mine" : "all"}/${encodeURIComponent(p.key)}`) })),
      ...(s?.builds || []).slice(0, 60).map(b => ({ group: "Builds", label: `${b.pipeline} ${b.number}`, sub: `${b.org} · ${b.branch}`, icon: Hammer,
        provider: b.provider, run: () => go("/builds/" + encodeURIComponent(b.key)) })),
    ];
    const t = q.trim().toLowerCase();
    if (!t) return out.filter(i => !["Pull requests", "Builds", "Abrir agente", "Comandos"].includes(i.group)).slice(0, 40);
    const words = t.split(/\s+/);
    return out.map(i => {
      const hay = `${i.label} ${i.sub || ""} ${i.group}`.toLowerCase();
      if (!words.every(w => hay.includes(w))) return null;
      const score = (i.label.toLowerCase().startsWith(t) ? 0 : 1) + (i.group === "Ir para" ? 0 : 0.5);
      return { i, score };
    }).filter(Boolean).sort((a, b) => a!.score - b!.score).slice(0, 60).map(x => x!.i);
  });
  $effect(() => { void q; idx = 0; });
  $effect(() => {
    if (!ui.palette) return;
    untrack(() => { q = ""; opened++; store.hold++; });
    setTimeout(() => input?.focus(), 20);
    return () => untrack(() => store.hold--);
  });

  function onkey(e: KeyboardEvent) {
    if (!ui.palette) return;
    if (e.key === "Escape") ui.palette = false;
    else if (e.key === "ArrowDown") { e.preventDefault(); idx = Math.min(idx + 1, items.length - 1); scroll(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); idx = Math.max(idx - 1, 0); scroll(); }
    else if (e.key === "Enter" && items[idx]) { e.preventDefault(); pick(items[idx]); }
  }
  function scroll() { requestAnimationFrame(() => document.querySelector(".pal .it.on")?.scrollIntoView({ block: "nearest" })); }
  function pick(i: Item) { ui.palette = false; i.run(); }
</script>

<svelte:window onkeydown={onkey} />

{#if ui.palette}
  <div class="wrap">
    <button class="scrim" aria-label="Fechar" onclick={() => (ui.palette = false)}></button>
    <div class="pal" role="dialog" aria-label="Paleta de comandos">
      <div class="in"><Search size={17} /><input bind:this={input} bind:value={q} placeholder="Buscar telas, repositórios, PRs, ações… (> para comandos)" /><span class="kbd">Esc</span></div>
      <div class="list">
        {#each items as it, i (it.group + it.label + i)}
          {#if i === 0 || items[i - 1].group !== it.group}<div class="grp">{it.group}</div>{/if}
          <button class="it" class:on={i === idx} onmouseenter={() => (idx = i)} onclick={() => pick(it)}>
            {#if it.provider}<ProviderIcon provider={it.provider} size={14} />{:else if it.icon}<it.icon size={15} />{/if}
            <span class="lbl ell">{it.label}</span>
            {#if it.sub}<span class="sub ell">{it.sub}</span>{/if}
          </button>
        {:else}
          <div class="none">Nada encontrado para “{q}”.</div>
        {/each}
      </div>
    </div>
  </div>
{/if}

<style>
  .wrap { position: fixed; inset: 0; z-index: 85; display: flex; justify-content: center; padding-top: 12vh; }
  .scrim { position: absolute; inset: 0; border: 0; background: rgba(5, 7, 12, 0.55); backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px); animation: fade 0.16s both; }
  .pal { position: relative; width: min(640px, 92vw); max-height: 62vh; display: flex; flex-direction: column; background: var(--elevated); border: 1px solid var(--line-2);
    border-radius: 16px; box-shadow: var(--shadow-3); overflow: hidden; animation: pal-in 0.26s var(--spring) both; }
  @keyframes pal-in { from { opacity: 0; transform: translateY(-10px) scale(0.98); } }
  .in { display: flex; align-items: center; gap: 10px; padding: 14px 16px; border-bottom: 1px solid var(--line); color: var(--muted); }
  .in input { flex: 1; border: 0; background: none; outline: none; color: var(--text); font: 15px var(--font); }
  .list { overflow-y: auto; padding: 6px; }
  .grp { font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); padding: 10px 10px 6px; }
  .it { display: flex; align-items: center; gap: 10px; width: 100%; height: 36px; padding: 0 10px; border: 0; border-radius: 8px; background: none; color: var(--text);
    font: 13.5px var(--font); text-align: left; cursor: pointer; }
  .it :global(svg) { color: var(--text-2); flex-shrink: 0; }
  .it.on { background: var(--accent-soft); }
  .it.on :global(svg) { color: var(--accent); }
  .lbl { flex: 1; }
  .sub { color: var(--muted); font-size: 12px; max-width: 45%; }
  .none { padding: 24px; text-align: center; color: var(--muted); }
</style>
