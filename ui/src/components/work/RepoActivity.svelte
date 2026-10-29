<script lang="ts">
  // Aba "PRs" do projeto: pull requests (minhas e de outros) e builds DESTE repositório, com o detalhe ao lado —
  // o mesmo de Fila/Builds, filtrado pelo projeto. O grafo de commits fica na aba Git.
  import { GitPullRequest, Hammer } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { clearSize, dragX, loadSize, saveSize } from "../../lib/resize";
  import { store } from "../../lib/store.svelte";
  import type { Build, PR } from "../../lib/types";
  import type { Project } from "../../lib/work.svelte";
  import BuildPane from "../build/BuildPane.svelte";
  import BuildRow from "../build/BuildRow.svelte";
  import Empty from "../Empty.svelte";
  import PrPane from "../pr/PrPane.svelte";
  import PrRow from "../pr/PrRow.svelte";

  let { project }: { project: Project } = $props();
  const n = (s?: string | null) => (s || "").toLowerCase();
  // GitHub: "dono/repo"; Azure: "org/projeto/repo"
  const slug = $derived((project.slug || "").split("/"));
  function ofRepo(x: { provider: string; org: string; project?: string; repo?: string | null }) {
    if (!project.provider || x.provider !== project.provider) return false;
    if (project.provider === "github") return n(x.project) === n(project.slug);
    return n(x.org) === n(slug[0]) && n(x.repo) === n(slug[slug.length - 1]);
  }
  const mine = $derived((store.s?.myPrs || []).filter(ofRepo));
  const others = $derived(store.open.filter(ofRepo).filter(p => !mine.some(m => m.key === p.key)));
  const builds = $derived((store.s?.builds || []).filter(b => ofRepo({ ...b, repo: b.provider === "github" ? b.project : b.repo })).slice(0, 25));
  let sel = $state<{ kind: "pr" | "mine" | "build"; key: string } | null>(null);
  const selPr = $derived(sel && sel.kind !== "build" ? [...mine, ...others].find(p => p.key === sel!.key) || null : null);
  const selBuild = $derived(sel?.kind === "build" ? builds.find(b => b.key === sel!.key) || null : null);
  const pick = (kind: "pr" | "mine" | "build", x: PR | Build) => (sel = { kind, key: x.key });
  // divisória arrastável: a fração da largura que o detalhe ocupa (a mesma em todos os projetos)
  const DEF = 0.6;
  let frac = $state(untrack(() => loadSize("repo-activity") || DEF));
  let box: HTMLDivElement | undefined = $state();
  function start(e: PointerEvent) {
    const r = box!.getBoundingClientRect();
    dragX(e, x => (frac = Math.max(0.25, Math.min(0.8, (r.right - x) / r.width))), () => saveSize("repo-activity", frac));
  }
  function reset() { frac = DEF; clearSize("repo-activity"); }
</script>

{#if !project.provider}
  <Empty title="Repositório sem remoto do GitHub/Azure" text="PRs e builds aparecem quando o repositório tem um remoto conectado numa das suas contas." />
{:else}
  <div class="act" bind:this={box} style="--pf:{frac}">
    <div class="list">
      <div class="sect"><GitPullRequest size={13} /> Minhas PRs <span>{mine.length}</span></div>
      {#each mine as p (p.key)}<PrRow pr={p} selected={sel?.key === p.key} onselect={() => pick("mine", p)} showVote={false} />
      {:else}<div class="none">Nenhuma PR sua aberta neste repositório.</div>{/each}
      <div class="sect"><GitPullRequest size={13} /> PRs abertas <span>{others.length}</span></div>
      {#each others as p (p.key)}<PrRow pr={p} selected={sel?.key === p.key} onselect={() => pick("pr", p)} />
      {:else}<div class="none">Nenhuma outra PR aberta.</div>{/each}
      <div class="sect"><Hammer size={13} /> Builds e Actions <span>{builds.length}</span></div>
      {#each builds as b (b.key)}<BuildRow {b} selected={sel?.key === b.key} onselect={() => pick("build", b)} />
      {:else}<div class="none">Nenhum build recente.</div>{/each}
    </div>
    <div class="handle" role="separator" aria-orientation="vertical" aria-label="Redimensionar" title="Arraste para redimensionar · duplo clique volta ao padrão"
      onpointerdown={start} ondblclick={reset}></div>
    <div class="pane">
      {#if selPr}{#key selPr.key}<PrPane pr={selPr} mine={sel?.kind === "mine"} />{/key}
      {:else if selBuild}{#key selBuild.key}<BuildPane b={selBuild} />{/key}
      {:else}<Empty title="Selecione uma PR ou um build" text="Revise, aprove, veja os checks — sem sair do projeto." />{/if}
    </div>
  </div>
{/if}

<style>
  .act { height: 100%; display: grid; grid-template-columns: minmax(260px, calc((1 - var(--pf)) * 100%)) 0 minmax(0, 1fr); min-height: 0; }
  .list { overflow: auto; border-right: 1px solid var(--line); min-height: 0; }
  .handle { position: relative; z-index: 4; cursor: col-resize; }
  .handle::before { content: ""; position: absolute; top: 0; bottom: 0; left: -5px; width: 10px; }
  .handle::after { content: ""; position: absolute; top: 30%; bottom: 30%; left: -1px; width: 2px; border-radius: 2px; background: transparent; transition: background var(--t); }
  .handle:hover::after { background: var(--accent-line); }
  .pane { overflow: auto; min-height: 0; }
  .sect { display: flex; align-items: center; gap: 6px; padding: 12px 16px 6px; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
  .sect span { margin-left: auto; color: var(--text-2); }
  .none { padding: 6px 16px 10px; font-size: 12.5px; color: var(--faint); }
</style>
