<script lang="ts">
  import { Bot, CheckCircle2, CircleDot, Eye, EyeOff, ExternalLink, KanbanSquare, MessageSquare, RefreshCw, Sparkles, Users } from "@lucide/svelte";
  import { flip } from "svelte/animate";
  import { fade } from "svelte/transition";
  import { get, post } from "../lib/api";
  import { matchesAssignee, people, personOf } from "../lib/people";
  import { prefs } from "../lib/prefs.svelte";
  import type { Issue } from "../lib/types";
  import { untrack } from "svelte";
  import { repos } from "../lib/repos.svelte";
  import { kanban } from "../lib/kanban.svelte";
  import { go } from "../lib/router.svelte";
  import { ui } from "../lib/ui.svelte";
  import Menu from "../components/Menu.svelte";
  import { work } from "../lib/work.svelte";
  import Ago from "../components/Ago.svelte";
  import { store } from "../lib/store.svelte";
  import Empty from "../components/Empty.svelte";
  import Page from "../components/Page.svelte";
  import ProviderIcon from "../components/ProviderIcon.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Skeleton from "../components/Skeleton.svelte";
  import SourceFilter from "../components/SourceFilter.svelte";
  import Toolbar from "../components/Toolbar.svelte";
  import IssueDetail from "../components/work/IssueDetail.svelte";

  let q = $state("");
  let org = $state("");
  let who = $state("");
  const s = $derived(store.s);
  // escopo: todas (dos projetos/repositórios), as minhas (atribuídas, criadas ou que me mencionam) ou uma delas;
  // estado: abertas, fechadas ou todas. As minhas abertas vêm da leitura de fundo (ao vivo); o resto é lido sob demanda.
  const scope = $derived(String(prefs.get("issues.scope") || "mine"));
  const st = $derived(String(prefs.get("issues.state") || "open"));
  const live = $derived(st === "open" && scope !== "all");
  let browsed = $state<{ k: string; issues: Issue[]; errors: Record<string, string>; at: string } | null>(null);
  let loading = $state(false);
  async function browse(fresh = false) {
    const k = `${scope === "all" ? "all" : "mine"}|${st}`;
    if (!fresh && browsed?.k === k) return;
    loading = true;
    try { const r = await get<any>("issues/browse", { scope: scope === "all" ? "all" : "mine", state: st, fresh: fresh ? 1 : undefined }); browsed = { k, ...r }; }
    catch (e) { ui.error(e); }
    loading = false;
  }
  $effect(() => { if (!live) { void scope; void st; untrack(() => browse()); } });
  const base = $derived<Issue[]>(live ? s?.issues || [] : browsed?.k === `${scope === "all" ? "all" : "mine"}|${st}` ? browsed.issues : []);
  const reasonsOf = (i: Issue) => i.reasons || (i.reason && i.reason !== "other" ? [i.reason] : []);
  const inScope = (i: Issue, sc: string) => sc === "all" || (sc === "mine" ? reasonsOf(i).length > 0 || live : reasonsOf(i).includes(sc));
  const list = $derived(base.filter(i => inScope(i, scope) && (!org || i.org === org) && matchesAssignee(i.assignees, who)
    && (!q || `${i.number} ${i.title} ${i.repo} ${i.labels.map(l => l.name).join(" ")} ${i.type} ${(i.assignees || []).map(a => a.login).join(" ")}`.toLowerCase().includes(q.toLowerCase()))));
  const count = (sc: string) => base.filter(i => inScope(i, sc)).length;
  // responsáveis: as pessoas de Configurações (juntam os nomes de cada conta) e os demais nomes que aparecem na lista
  const whoOptions = $derived.by(() => {
    const ps = Object.keys(people()).sort((a, b) => a.localeCompare(b));
    const loose = new Map<string, number>();
    for (const i of base) for (const a of i.assignees || []) if (a.login && !personOf(a)) loose.set(a.login, (loose.get(a.login) || 0) + 1);
    return { ps, loose: [...loose.entries()].sort((a, b) => a[0].localeCompare(b[0])) };
  });
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
  // clique na linha abre a issue/work item no app (descrição, discussão, implementar); o ícone ao lado abre no navegador
  let opened = $state<any>(null);
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
  // fechar/reabrir uma issue do GitHub direto da lista (otimista: a linha muda na hora e volta se o GitHub recusar)
  let pulsing = $state<string | null>(null);
  async function toggleState(i: Issue) {
    const was = i.state, next = String(was).toLowerCase() === "closed" ? "open" : "closed";
    i.state = next;
    pulsing = i.key;
    try {
      await post("issue/edit", { provider: i.provider, account: i.account || undefined, org: i.org, repo: i.repo, number: i.number, key: i.key, changes: { state: next } });
      ui.toast(next === "closed" ? `#${i.number} fechada` : `#${i.number} reaberta`, "ok", { label: "Desfazer", run: () => toggleState(i) });
    } catch (e) { i.state = was; ui.error(e); }
    if (pulsing === i.key) pulsing = null;
  }
  const isClosed = (i: Issue) => String(i.state).toLowerCase() === "closed";
</script>

<Page live={["issues"]} title="Issues e tarefas" sub="Issues do GitHub e itens de trabalho do Azure Boards — todos dos projetos ou os seus (atribuídos, criados, que mencionam você), abertos ou fechados">
  {#if !s?.lastIssuePoll}
    <Skeleton rows={9} />
  {:else}
    <Toolbar bind:query={q} placeholder="Buscar por título, número, repositório, etiqueta…">
      {#snippet left()}
        <Segmented value={scope} onchange={(v) => prefs.set("issues.scope", v)} options={[{ value: "all", label: "Todas", ...(scope === "all" ? { count: count("all") } : {}) },
          { value: "mine", label: "Minhas", count: count("mine") }, { value: "assigned", label: "Atribuídas", count: count("assigned") },
          { value: "created", label: "Criadas por mim", count: count("created") }, { value: "mentioned", label: "Menções", count: count("mentioned") }]} />
        <Segmented size="sm" value={st} onchange={(v) => prefs.set("issues.state", v)} options={[{ value: "open", label: "Abertas" }, { value: "closed", label: "Fechadas" }, { value: "all", label: "Todas" }]} />
      {/snippet}
      <select class="select" style="width:auto;min-width:170px" bind:value={who} title="Responsável">
        <option value="">Qualquer responsável</option>
        <option value="-">Sem responsável</option>
        {#if whoOptions.ps.length}<optgroup label="Pessoas (Configurações)">{#each whoOptions.ps as p (p)}<option value={"p:" + p}>{p}</option>{/each}</optgroup>{/if}
        {#if whoOptions.loose.length}<optgroup label="Na lista">{#each whoOptions.loose as [n, c] (n)}<option value={"u:" + n}>{n} ({c})</option>{/each}</optgroup>{/if}
      </select>
      <button class="btn sm ghost icon" title="Pessoas: juntar os nomes de cada conta" onclick={() => { go("/settings/accounts"); setTimeout(() => document.getElementById("people")?.scrollIntoView({ behavior: "smooth" }), 400); }}><Users size={14} /></button>
      <SourceFilter bind:value={org} items={base} />
      {#if !live}<button class="btn sm ghost icon" title="Ler de novo" onclick={() => browse(true)}><RefreshCw size={14} class={loading ? "spin" : ""} /></button>{/if}
    </Toolbar>
    <div class="card scroll">
      {#each shown as i (i.key)}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <div class="list-row" role="button" tabindex="0" class:sel={opened?.key === i.key} class:closed={i.provider === "github" && isClosed(i)} class:pulse={pulsing === i.key}
          animate:flip={{ duration: 260 }} in:fade={{ duration: 180 }} onclick={() => (opened = i)} onkeydown={(e) => e.key === "Enter" && (opened = i)}>
          <span class="ic" class:wi={i.provider === "azure"}><ProviderIcon provider={i.provider} size={15} /></span>
          <div class="grow">
            <div class="t"><span class="num">#{i.number}</span><span class="title ell">{i.title}</span></div>
            <div class="meta">
              <span>{i.repo}</span>
              {#if i.provider === "azure"}<span class="pill neutral">{i.type}</span>{#key i.state}<span class="pill info stp">{i.state}</span>{/key}
              {:else if isClosed(i)}<span class="pill good stp"><CheckCircle2 size={11} /> fechada</span>{/if}
              {#each i.labels.slice(0, 5) as l (l.name)}<span class="label-chip" style="--c:{l.color || 'var(--muted)'}">{l.name}</span>{/each}
              {#if i.assignees?.length}<span title="Responsável">{i.assignees.map(a => personOf(a) || a.login).join(", ")}</span>{/if}
              <span>{reasonsOf(i).map(r => REASON[r]).filter(Boolean).join(" · ")}{reasonsOf(i).length ? " · " : ""}atualizada <Ago iso={i.updated} prefix="há " /></span>
              {#if i.comments}<span class="row" style="gap:4px"><MessageSquare size={11} />{i.comments}</span>{/if}
            </div>
          </div>
          <span class="start" role="presentation" onclick={(e) => e.stopPropagation()}>
            <button class="btn sm ai" title="Pedir à IA: planejar e/ou implementar esta issue" onclick={() => ask(i)}><Sparkles size={13} /> Pedir à IA</button>
            <Menu items={[
              { label: "Planejar com IA", icon: Sparkles, onclick: () => ask(i, "plan") },
              { label: "Planejar e implementar com IA", icon: Sparkles, onclick: () => ask(i, "plan-implement") },
              { label: "Implementar direto com IA", icon: Sparkles, onclick: () => ask(i, "implement") },
              { separator: true },
              { label: "Começar tarefa (formulário completo)", icon: Bot, onclick: () => startTask(i) },
              { label: "Adicionar ao quadro", icon: KanbanSquare, onclick: () => toBoard(i) },
              ...(i.provider === "github" ? [{ label: isClosed(i) ? "Reabrir issue" : "Fechar issue", icon: isClosed(i) ? CircleDot : CheckCircle2, onclick: () => toggleState(i) }] : []),
              ...(i.scopeKey ? [{ separator: true }, { label: i.provider === "azure" ? `Não acompanhar work items de ${i.repo}` : `Não acompanhar issues de ${i.repo}`,
                hint: "PRs, builds e deploys continuam", icon: EyeOff, onclick: () => setIssues(i.scopeKey!, false) }] : []),
            ]} />
          </span>
          <a class="ext" href={i.url} target="_blank" rel="noopener" title="Abrir no navegador" onclick={(e) => e.stopPropagation()}><ExternalLink size={14} /></a>
        </div>
      {:else}
        {#if loading}<Skeleton rows={6} />
        {:else}<Empty done={!q && !org && !who && scope === "mine" && st === "open"} title={q || org || who || scope !== "mine" || st !== "open" ? "Nada com esses filtros" : "Nenhuma issue aberta com você"} />{/if}
      {/each}
    </div>
    {#if hidden.length}
      <div class="hidden small muted"><EyeOff size={13} /> Sem issues de:
        {#each hidden as k (k)}<button class="hchip" title="Voltar a acompanhar" onclick={() => setIssues(k, true)}>{scopeName(k)} <Eye size={11} /></button>{/each}
      </div>
    {/if}
    {#if Object.keys((live ? s.issueErrors : browsed?.errors) || {}).length}
      <p class="small muted note">Algumas origens não responderam: {Object.entries((live ? s.issueErrors : browsed?.errors) || {}).map(([k, v]) => `${k} (${v.slice(0, 80)})`).join("; ")}</p>
    {/if}
  {/if}
</Page>

{#if opened}<IssueDetail item={opened} onclose={() => (opened = null)} onboard={(i) => toBoard(i)} onchange={(p) => {
  // a edição da gaveta vale na linha também (o item é o mesmo da lista: muda na hora; a leitura seguinte confirma)
  for (const x of base) if (x.key === opened.key) Object.assign(x, p);
  Object.assign(opened, p);
}} />{/if}

<style>
  .start { display: inline-flex; align-items: center; gap: 2px; opacity: 0; transition: opacity var(--t-fast); }
  .ai { color: var(--accent); }
  .list-row { cursor: pointer; }
  .list-row.closed .title { color: var(--text-2); }
  .list-row.pulse { background-image: linear-gradient(100deg, transparent 30%, var(--accent-soft) 50%, transparent 70%); background-size: 250% 100%;
    animation: shimmer 1.2s linear infinite; }
  .stp { animation: pop 0.4s var(--spring); }
  .list-row:hover .start, .list-row:focus-visible .start { opacity: 1; }
  .ext { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 7px; color: var(--muted); flex: none; }
  .ext:hover { background: var(--surface-3); color: var(--text); }
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
