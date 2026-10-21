<script lang="ts">
  // Faxina das tarefas: os worktrees do projeto com o estado de cada um (já entrou na base? alterações sem commit?
  // agente vivo?) e os órfãos (worktrees na pasta que nenhuma tarefa usa). Já vêm marcadas as que dá para tirar sem
  // perder nada: branch já na base e nada sem commit.
  import { Brush, GitBranch, TriangleAlert } from "@lucide/svelte";
  import { get, post } from "../../lib/api";
  import type { Project } from "../../lib/work.svelte";
  import { work } from "../../lib/work.svelte";
  import { ui } from "../../lib/ui.svelte";
  import Drawer from "../Drawer.svelte";

  type Item = { id: string; title: string; branch: string; path: string; exists: boolean; dirty: number; merged: boolean; agents: boolean; createdAt?: string };
  let { project, onclose, onremoved }: { project: Project; onclose: () => void; onremoved?: (ids: string[]) => void } = $props();

  let info = $state<{ tasks: Item[]; orphans: { path: string; exists: boolean }[] } | null>(null);
  let picked = $state<string[]>([]);
  let orphans = $state<string[]>([]);
  let delBranch = $state(true);
  let busy = $state(false);
  const safe = (t: Item) => !t.exists || (t.merged && !t.dirty && !t.agents);

  $effect(() => {
    get<typeof info>("ws/task/cleanup", { repoId: project.id }).then(r => {
      info = r;
      picked = r!.tasks.filter(safe).map(t => t.id);
      orphans = r!.orphans.map(o => o.path);
    }).catch(e => { ui.error(e); onclose(); });
  });
  const risky = $derived(info ? info.tasks.filter(t => picked.includes(t.id) && t.exists && (t.dirty || t.agents)) : []);
  const toggle = (id: string) => (picked = picked.includes(id) ? picked.filter(x => x !== id) : [...picked, id]);
  const home = (p: string) => p.replace(/^\/Users\/[^/]+|^C:\\Users\\[^\\]+/i, "~");

  async function run() {
    const n = picked.length + orphans.length;
    if (!n) return;
    if (risky.length && !(await ui.ask({ title: "Remover com alterações?", danger: true, confirm: "Remover mesmo assim",
      message: `${risky.length} tarefa(s) têm alterações sem commit ou agente aberto — o que não foi commitado será PERDIDO.`, detail: risky.map(t => t.title) }))) return;
    busy = true;
    const prog = ui.progress(`Removendo ${n} worktree(s)…`);
    try {
      const r = await post<{ failed: { id?: string; path?: string; error: string }[] }>("ws/task/cleanup",
        { repoId: project.id, taskIds: picked, orphans, deleteBranch: delBranch, force: risky.length > 0 });
      const ok = n - r.failed.length;
      if (r.failed.length) prog.fail(new Error(`${ok} removido(s); ${r.failed.length} falharam: ${r.failed[0].error}`));
      else prog.done(`${ok} worktree(s) removido(s)`);
      await work.load();
      onremoved?.(picked.filter(id => !r.failed.some(f => f.id === id)));
      onclose();
    } catch (e) { prog.fail(e); }
    busy = false;
  }
</script>

<Drawer title="Limpar tarefas" subtitle={`${project.name} — remove os worktrees que não servem mais`} {onclose} width={600}>
  {#if !info}
    <div class="sk">{#each [0, 1, 2] as i (i)}<div class="skr"></div>{/each}</div>
  {:else if !info.tasks.length && !info.orphans.length}
    <p class="small muted pad">Nenhum worktree neste projeto. Tudo limpo.</p>
  {:else}
    <div class="list">
      {#each info.tasks as t (t.id)}
        <label class="it" class:on={picked.includes(t.id)}>
          <input type="checkbox" checked={picked.includes(t.id)} onchange={() => toggle(t.id)} />
          <span class="grow"><b class="ell">{t.title}</b><span class="tiny muted mono ell"><GitBranch size={10} /> {t.branch}</span></span>
          <span class="tags">
            {#if !t.exists}<span class="tag muted">pasta apagada</span>
            {:else}
              {#if t.merged}<span class="tag good">já na base</span>{:else}<span class="tag">não mesclada</span>{/if}
              {#if t.dirty}<span class="tag warn">{t.dirty} sem commit</span>{/if}
              {#if t.agents}<span class="tag accent">agente aberto</span>{/if}
            {/if}
          </span>
        </label>
      {/each}
      {#if info.orphans.length}
        <div class="sub">Worktrees sem tarefa</div>
        {#each info.orphans as o (o.path)}
          <label class="it" class:on={orphans.includes(o.path)}>
            <input type="checkbox" checked={orphans.includes(o.path)} onchange={() => (orphans = orphans.includes(o.path) ? orphans.filter(x => x !== o.path) : [...orphans, o.path])} />
            <span class="grow mono tiny ell" title={o.path}>{home(o.path)}</span>
            {#if !o.exists}<span class="tag muted">pasta apagada</span>{/if}
          </label>
        {/each}
      {/if}
    </div>
    <label class="chk small"><input type="checkbox" bind:checked={delBranch} /> Apagar também a branch local das que já entraram na base</label>
    {#if risky.length}<p class="warnp small"><TriangleAlert size={13} /> {risky.length} marcada(s) com alterações sem commit ou agente aberto — serão perdidas.</p>{/if}
  {/if}
  {#snippet footer()}
    <span class="small muted">{picked.length + orphans.length} selecionado(s)</span>
    <span class="spacer"></span>
    <button class="btn" onclick={onclose}>Cancelar</button>
    <button class="btn primary" class:danger={risky.length > 0} disabled={busy || !(picked.length + orphans.length)} onclick={run}><Brush size={14} /> Remover</button>
  {/snippet}
</Drawer>

<style>
  .pad { padding: 16px 0; }
  .list { display: grid; gap: 4px; padding-top: 12px; }
  .it { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 9px; border: 1px solid var(--line); background: var(--surface-2); cursor: pointer;
    min-width: 0; transition: border-color var(--t-fast), background var(--t-fast); }
  .it:hover { border-color: var(--line-3); }
  .it.on { border-color: var(--accent-line); background: var(--accent-soft); }
  .grow { display: grid; flex: 1; min-width: 0; line-height: 1.35; }
  .grow b { font-weight: 600; font-size: 13px; }
  .tags { display: flex; gap: 4px; flex: none; }
  .tag { padding: 2px 7px; border-radius: 99px; font: 600 10.5px/1.4 var(--font); background: var(--surface-3); color: var(--text-2); }
  .tag.good { background: var(--good-soft); color: var(--good); }
  .tag.warn { background: var(--warn-soft); color: var(--warn); }
  .tag.accent { background: var(--accent-soft); color: var(--accent); }
  .tag.muted { color: var(--muted); }
  .sub { margin-top: 10px; font: 600 11.5px var(--font); color: var(--muted); }
  .chk { display: flex; align-items: center; gap: 8px; margin-top: 12px; color: var(--text-2); cursor: pointer; }
  .warnp { display: flex; align-items: center; gap: 6px; margin: 8px 0 0; padding: 7px 10px; border-radius: 9px; background: var(--warn-soft); color: var(--text-2); }
  .warnp :global(svg) { color: var(--warn); flex: none; }
  .spacer { flex: 1; }
  .sk { display: grid; gap: 6px; padding-top: 12px; }
  .skr { height: 46px; border-radius: 9px; background: linear-gradient(90deg, var(--surface-2), var(--surface-3), var(--surface-2)); background-size: 200% 100%; animation: sh 1.2s linear infinite; }
  @keyframes sh { to { background-position: -200% 0; } }
  @media (prefers-reduced-motion: reduce) { .skr { animation: none; } }
</style>
