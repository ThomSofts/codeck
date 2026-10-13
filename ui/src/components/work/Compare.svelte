<script lang="ts">
  // Fan-out: o mesmo pedido feito a vários agentes, cada um no próprio worktree. Aqui dá para comparar o que cada um
  // mudou (arquivos, linhas, commits) e ficar com o vencedor — os outros worktrees e branches são descartados.
  import { Crown, Eye } from "@lucide/svelte";
  import { get, post } from "../../lib/api";
  import type { Project, Task } from "../../lib/work.svelte";
  import { STATUS, work } from "../../lib/work.svelte";
  import { ui } from "../../lib/ui.svelte";
  import Drawer from "../Drawer.svelte";
  import AgentIcon from "./AgentIcon.svelte";

  let { project, tasks, onclose, onview }: { project: Project; tasks: Task[]; onclose: () => void; onview: (t: Task) => void } = $props();
  let diffs = $state<Record<string, any>>({});
  const ids = $derived(tasks.map(t => t.id).join(","));   // a lista é recriada a cada leitura; só a troca de tarefas relê
  $effect(() => {
    const repoId = project.id;
    for (const id of ids.split(",").filter(Boolean)) get("ws/task/diff", { repoId, taskId: id }).then(d => (diffs = { ...diffs, [id]: d })).catch(() => {});
  });
  const stat = (d: any) => {
    if (!d) return null;
    const add = d.files.reduce((n: number, f: any) => n + (f.add || 0), 0), del = d.files.reduce((n: number, f: any) => n + (f.del || 0), 0);
    return { files: d.files.length + d.status.untracked.length, add, del, commits: d.commits, dirty: d.status.unstaged.length + d.status.staged.length + d.status.untracked.length };
  };
  const allFiles = $derived([...new Set(Object.values(diffs).flatMap((d: any) => [...d.files.map((f: any) => f.path), ...d.status.untracked.map((f: any) => f.path)]))].sort());

  async function keep(win: Task) {
    const others = tasks.filter(t => t.id !== win.id);
    if (!(await ui.ask({ title: `Ficar com "${win.title}"?`, danger: true, confirm: "Ficar com este",
      message: `Os outros ${others.length} worktree(s) e as branches deles serão apagados — incluindo alterações não commitadas.`,
      detail: others.map(t => t.branch) }))) return;
    const prog = ui.progress("Descartando as outras soluções…");
    try {
      for (const t of others) await post("ws/task/remove", { repoId: project.id, taskId: t.id, force: true, deleteBranch: true });
      await work.load();
      prog.done("Pronto — siga com a escolhida");
      onview(win);
      onclose();
    } catch (e) { prog.fail(e); }
  }
</script>

<Drawer title="Comparar soluções" subtitle={`${tasks.length} agentes no mesmo pedido — cada um no próprio worktree`} {onclose} width={Math.min(320 * tasks.length + 80, 1200)}>
  <div class="cols" style="grid-template-columns: repeat({tasks.length}, minmax(240px, 1fr))">
    {#each tasks as t (t.id)}
      {@const st = stat(diffs[t.id])}
      {@const ag = t.terms.find(x => x.kind === "agent")}
      {@const s = work.session(ag)}
      <div class="card col">
        <div class="h"><AgentIcon provider={ag?.meta.provider} size={20} /><div class="grow"><b class="ell">{work.account(ag?.meta.account)?.name || "agente"}</b><span class="tiny muted mono ell">{t.branch}</span></div>
          {#if s}<span class="pill {STATUS[s.status]?.[1]}">{STATUS[s.status]?.[0]}</span>{/if}</div>
        {#if st}
          <div class="nums"><div><b>{st.files}</b><span>arquivos</span></div><div><b class="add">+{st.add}</b><span>linhas</span></div><div><b class="del">−{st.del}</b><span>linhas</span></div><div><b>{st.commits}</b><span>commits</span></div></div>
          {#if st.dirty}<div class="tiny muted">{st.dirty} arquivo(s) ainda sem commit</div>{/if}
        {:else}<div class="tiny muted">lendo…</div>{/if}
        {#if s?.cost != null}<div class="tiny muted">custo da sessão US$ {s.cost.toFixed(2)} · contexto {Math.round(s.context?.used || 0)}%</div>{/if}
        <div class="acts"><button class="btn sm" onclick={() => { onview(t); onclose(); }}><Eye size={13} /> Ver</button>
          <button class="btn sm primary" onclick={() => keep(t)}><Crown size={13} /> Ficar com este</button></div>
      </div>
    {/each}
  </div>
  {#if allFiles.length}
    <h4>Arquivos tocados</h4>
    <div class="matrix">
      {#each allFiles as f (f)}
        <div class="mrow" style="grid-template-columns: minmax(0, 1fr) repeat({tasks.length}, 64px)"><span class="mono ell small">{f}</span>
          {#each tasks as t (t.id)}
            {@const d = diffs[t.id]}{@const hit = d?.files.find((x: any) => x.path === f)}{@const nw = d?.status.untracked.some((x: any) => x.path === f)}
            <span class="cell">{#if hit}<span class="add">+{hit.add ?? "·"}</span><span class="del">−{hit.del ?? "·"}</span>{:else if nw}<span class="add">novo</span>{:else}<span class="faint">—</span>{/if}</span>
          {/each}</div>
      {/each}
    </div>
  {/if}
</Drawer>

<style>
  .cols { display: grid; gap: 10px; padding-top: 12px; }
  .col { display: grid; gap: 10px; padding: 14px; align-content: start; }
  .h { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .h .grow { display: grid; min-width: 0; flex: 1; }
  .nums { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
  .nums div { display: grid; text-align: center; padding: 8px 4px; border-radius: 9px; background: var(--surface-2); }
  .nums b { font-size: 17px; }
  .nums span { font-size: 11px; color: var(--muted); }
  .add { color: var(--good); } .del { color: var(--bad); } .faint { color: var(--faint); }
  .acts { display: flex; gap: 6px; }
  h4 { margin: 18px 0 8px; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
  .matrix { display: grid; gap: 2px; }
  .mrow { display: grid; gap: 8px; align-items: center; padding: 4px 6px; border-radius: 6px; }
  .mrow:hover { background: var(--surface-2); }
  .cell { display: flex; gap: 6px; justify-content: flex-end; font: 11.5px var(--mono); }
</style>
