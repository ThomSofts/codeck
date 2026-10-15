<script lang="ts">
  import { Bot, Eye, EyeOff, ExternalLink, KanbanSquare, MessageSquare, Sparkles } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { repos } from "../lib/repos.svelte";
  import { kanban } from "../lib/kanban.svelte";
  import { go } from "../lib/router.svelte";
  import { ui } from "../lib/ui.svelte";
  import Menu from "../components/Menu.svelte";
  import { work } from "../lib/work.svelte";
  import { ago } from "../lib/format";
  import { store } from "../lib/store.svelte";
  import Empty from "../components/Empty.svelte";
  import Page from "../components/Page.svelte";
  import ProviderIcon from "../components/ProviderIcon.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Skeleton from "../components/Skeleton.svelte";
  import SourceFilter from "../components/SourceFilter.svelte";
  import Toolbar from "../components/Toolbar.svelte";

  let q = $state("");
  let reason = $state("");
  let org = $state("");
  const s = $derived(store.s);
  const list = $derived((s?.issues || []).filter(i => (!reason || i.reason === reason) && (!org || i.org === org)
    && (!q || `${i.number} ${i.title} ${i.repo} ${i.labels.map(l => l.name).join(" ")} ${i.type}`.toLowerCase().includes(q.toLowerCase()))));
  const count = (r: string) => (s?.issues || []).filter(i => i.reason === r).length;
  $effect(() => { if (!repos.loaded) untrack(() => repos.load(false)); });

  // Parar de acompanhar as issues de um repositório (ou os work items de um projeto do Azure) sem mexer em PRs,
  // builds e deploys dele. Some da lista na hora; a próxima leitura confirma.
  let hiding = $state<string[]>([]);
  const scopeName = (k: string) => k.replace(/^(github|azure):/, "");
  async function setIssues(k: string, on: boolean) {
    if (!on) hiding = [...hiding, k];
    // voltar a acompanhar = apagar a escolha (não marcar "sim"): volta ao que era antes de ocultar
    try { await repos.setTrack(k, { issues: on ? null : false }); store.refreshSource("issues"); }
    catch (e) { hiding = hiding.filter(x => x !== k); ui.error(e); }
  }
  const hidden = $derived(Object.entries(repos.tracking.repos).filter(([, v]) => v.issues === false).map(([k]) => k));
  const shown = $derived(list.filter(i => !i.scopeKey || !hiding.includes(i.scopeKey)));
  $effect(() => { void s?.lastIssuePoll; untrack(() => (hiding = [])); });
  const REASON: Record<string, string> = { assigned: "atribuída a você", created: "criada por você", mentioned: "menciona você" };
  /** Work item do Azure não tem repositório: abre no projeto ativo. Issue do GitHub abre no clone do repo dela. */
  function startTask(i: any) {
    work.startTask(i.provider === "github" ? { provider: "github", org: i.repo.split("/")[0], repo: i.repo } : null, {
      title: i.title, kind: /bug|defeito/i.test(i.type || "") || i.labels.some((l: any) => /bug/i.test(l.name)) ? "fix" : "feature",
      workItem: i, prompt: `Implemente ${i.provider === "github" ? "a issue" : "o work item"} #${i.number}: ${i.title}\n${i.url}\n\nLeia a descrição completa no link antes de começar.`,
    });
  }
  const targetOf = (i: any) => (i.provider === "github" ? { provider: "github", org: i.repo.split("/")[0], repo: i.repo } : null);
  const textOf = (i: any) => `${i.provider === "github" ? "Issue" : i.type || "Work item"} #${i.number}: ${i.title}\n${i.url}\n\nLeia a descrição completa no link antes de começar.`;
  function ask(i: any, flow?: string) { work.askFrom(targetOf(i), { title: i.title, text: textOf(i), workItem: i, flow }); }
  async function toBoard(i: any) {
    const local = i.provider === "github" ? work.findLocal("github", i.repo.split("/")[0], i.repo) : null;
    const c = await kanban.saveCard({ title: i.title, description: textOf(i), labels: i.labels.map((l: any) => l.name).slice(0, 6),
      projects: local ? [local.id] : [], workItem: { number: i.number, title: i.title, url: i.url, provider: i.provider, key: i.key } });
    if (c) ui.toast("Cartão criado no quadro", "ok", { label: "Abrir", run: () => go("/board/c/" + c.id) });
  }
</script>

<Page live={["issues"]} title="Issues e tarefas" sub="Issues do GitHub e itens de trabalho do Azure Boards atribuídos a você">
  {#if !s?.lastIssuePoll}
    <Skeleton rows={9} />
  {:else}
    <Toolbar bind:query={q} placeholder="Buscar por título, número, repositório, etiqueta…">
      {#snippet left()}
        <Segmented bind:value={reason} options={[{ value: "", label: "Tudo", count: s.issues.length }, { value: "assigned", label: "Atribuídas", count: count("assigned") },
          { value: "created", label: "Criadas por mim", count: count("created") }, { value: "mentioned", label: "Menções", count: count("mentioned") }]} />
      {/snippet}
      <SourceFilter bind:value={org} items={s.issues} />
    </Toolbar>
    <div class="card scroll">
      {#each shown as i (i.key)}
        <a class="list-row" href={i.url} target="_blank" rel="noopener">
          <span class="ic" class:wi={i.provider === "azure"}><ProviderIcon provider={i.provider} size={15} /></span>
          <div class="grow">
            <div class="t"><span class="num">#{i.number}</span><span class="title ell">{i.title}</span></div>
            <div class="meta">
              <span>{i.repo}</span>
              {#if i.provider === "azure"}<span class="pill neutral">{i.type}</span><span class="pill info">{i.state}</span>{/if}
              {#each i.labels.slice(0, 5) as l (l.name)}<span class="label-chip" style="--c:{l.color || 'var(--muted)'}">{l.name}</span>{/each}
              <span>{REASON[i.reason] || ""} · atualizada há {ago(i.updated)}</span>
              {#if i.comments}<span class="row" style="gap:4px"><MessageSquare size={11} />{i.comments}</span>{/if}
            </div>
          </div>
          <span class="start" role="presentation" onclickcapture={(e) => e.preventDefault()} onclick={(e) => e.stopPropagation()}>
            <button class="btn sm ai" title="Pedir à IA: planejar e/ou implementar esta issue" onclick={() => ask(i)}><Sparkles size={13} /> Pedir à IA</button>
            <Menu items={[
              { label: "Planejar com IA", icon: Sparkles, onclick: () => ask(i, "plan") },
              { label: "Planejar e implementar com IA", icon: Sparkles, onclick: () => ask(i, "plan-implement") },
              { label: "Implementar direto com IA", icon: Sparkles, onclick: () => ask(i, "implement") },
              { separator: true },
              { label: "Começar tarefa (formulário completo)", icon: Bot, onclick: () => startTask(i) },
              { label: "Adicionar ao quadro", icon: KanbanSquare, onclick: () => toBoard(i) },
              ...(i.scopeKey ? [{ separator: true }, { label: i.provider === "azure" ? `Não acompanhar work items de ${i.repo}` : `Não acompanhar issues de ${i.repo}`,
                hint: "PRs, builds e deploys continuam", icon: EyeOff, onclick: () => setIssues(i.scopeKey!, false) }] : []),
            ]} />
          </span>
          <ExternalLink size={14} class="muted" />
        </a>
      {:else}
        <Empty done={!q && !reason && !org} title={q || reason || org ? "Nada com esses filtros" : "Nenhuma issue aberta com você"} />
      {/each}
    </div>
    {#if hidden.length}
      <div class="hidden small muted"><EyeOff size={13} /> Sem issues de:
        {#each hidden as k (k)}<button class="hchip" title="Voltar a acompanhar" onclick={() => setIssues(k, true)}>{scopeName(k)} <Eye size={11} /></button>{/each}
      </div>
    {/if}
    {#if Object.keys(s.issueErrors || {}).length}
      <p class="small muted note">Algumas origens não responderam: {Object.entries(s.issueErrors).map(([k, v]) => `${k} (${v.slice(0, 80)})`).join("; ")}</p>
    {/if}
  {/if}
</Page>

<style>
  .start { display: inline-flex; align-items: center; gap: 2px; opacity: 0; transition: opacity var(--t-fast); }
  .ai { color: var(--accent); }
  .list-row:hover .start { opacity: 1; }
  .scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; }
  .ic { width: 32px; height: 32px; border-radius: 10px; display: grid; place-items: center; background: var(--surface-2); border: 1px solid var(--line); }
  .t { display: flex; align-items: baseline; gap: 7px; min-width: 0; }
  .num { color: var(--muted); font-size: 12.5px; flex-shrink: 0; }
  .title { font-weight: 600; }
  .label-chip { font: 600 11px/1 var(--font); padding: 4px 8px; border-radius: 99px; color: var(--c); background: color-mix(in srgb, var(--c) 14%, transparent);
    border: 1px solid color-mix(in srgb, var(--c) 30%, transparent); }
  .note { margin: 10px 2px 0; flex: none; }
  .hidden { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 10px 2px 0; flex: none; }
  .hchip { display: inline-flex; align-items: center; gap: 5px; height: 22px; padding: 0 8px; border-radius: 99px; border: 1px solid var(--line-2);
    background: none; color: var(--text-2); font: 11.5px var(--font); cursor: pointer; }
  .hchip:hover { border-color: var(--line-3); color: var(--text); }
</style>
