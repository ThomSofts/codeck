<script lang="ts">
  // Painel da direita do projeto, de cima para baixo:
  //   · Pedir à IA — o campo de pedido: Enter manda. Sem sessão escolhida, abre um agente NA CONTA DO PROJETO (a última
  //     usada, num chip que troca), no checkout/tarefa atual, com o pedido direto na CLI; com uma sessão aberta
  //     escolhida, o pedido vai para ela (como se fosse colado no terminal). ⌘⇧I põe o cursor aqui.
  //   · Sessões — os agentes deste checkout/tarefa: estado, contexto e custo; a selecionada mostra os detalhes.
  //   · Tarefa — branch, o que mudou e as ações (revisar, commitar, PR).
  //   · Limites das contas — a do agente aberto primeiro, com a contagem para o reset.
  import { ArrowUp, Bot, ChevronDown, ExternalLink, GitBranch, GitCommitHorizontal, GitCompareArrows, GitPullRequestCreate, Lightbulb, MessageSquareShare, ShieldOff, SlidersHorizontal, Trash2 } from "@lucide/svelte";
  import { tick, untrack } from "svelte";
  import { get, post } from "../../lib/api";
  import { repos } from "../../lib/repos.svelte";
  import { go } from "../../lib/router.svelte";
  import type { AiAccount, Project, Task, TermInfo } from "../../lib/work.svelte";
  import { STATUS, work } from "../../lib/work.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { kbd } from "../../lib/keys";
  import AccountAvatar from "../ai/AccountAvatar.svelte";
  import LimitRing from "../ai/LimitRing.svelte";
  import AgentIcon from "./AgentIcon.svelte";
  import { binding, clock, effUsed, resetLabel, stateRank, tone } from "../ai/limits.svelte";

  type Started = { projectId: string; taskId: string | null; termId?: string };
  let { project, task = null, term = null, onremoved, onreview, onstarted, onmore }:
    { project: Project; task?: Task | null; term?: TermInfo | null; onremoved?: () => void; onreview?: () => void;
      /** agente aberto/pedido enviado: a tela foca a aba do terminal (e a tarefa, se for nova) */
      onstarted?: (r: Started) => void;
      /** "Mais opções": o diálogo completo (issue/work item, fluxos, título da tarefa) com o texto já escrito */
      onmore?: (text: string) => void } = $props();

  const LS = (k: string, d: string) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
  const LSset = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* sem armazenamento */ } };

  // ------------------------------------------------------------ sessões do escopo (checkout principal ou tarefa)
  const agentsHere = $derived((task ? task.terms : project.terms).filter(t => t.kind === "agent"));
  const alive = $derived(agentsHere.filter(t => t.alive));
  // a sessão em destaque: a aba aberta, se for agente; senão a mais nova do escopo
  const cur = $derived(term?.kind === "agent" ? term : agentsHere[agentsHere.length - 1] || null);
  const s = $derived(work.session(cur));
  const acc = $derived(work.account(cur?.meta.account));

  // ------------------------------------------------------------ pedido
  let text = $state("");
  let box: HTMLTextAreaElement | undefined = $state();
  let busy = $state(false);
  /** para onde vai o pedido: "new" = agente novo; senão o id do terminal de uma sessão aberta. null = automático */
  let pick = $state<string | null>(null);
  $effect(() => { void term?.id; void task?.id; untrack(() => (pick = null)); });
  const target = $derived.by(() => {
    if (pick === "new") return "new";
    if (pick && alive.some(t => t.id === pick)) return pick;
    return term?.kind === "agent" && term.alive ? term.id : "new";
  });
  const targetTerm = $derived(target === "new" ? null : alive.find(t => t.id === target) || null);
  const installed = $derived(work.ai.filter(a => a.installed));
  // conta do projeto (a última usada nele — o servidor grava ao abrir um agente); o chip troca e grava
  const accountId = $derived(work.defaultAccount(project));
  const account = $derived(work.account(accountId));
  let plan = $state(LS("codeck.compose.plan", "0") === "1");
  let worktree = $state(false);
  const bypass = $derived(!!project.settings.bypass);

  // ⌘⇧I / "Pedir à IA" de outro lugar: cursor no campo
  $effect(() => {
    const f = work.composeFocus;
    if (!f || f.projectId !== project.id) return;
    untrack(() => { work.composeFocus = null; tick().then(() => { box?.focus(); box?.select(); }); });
  });
  function grow() {
    if (!box) return;
    box.style.height = "auto";
    box.style.height = Math.min(box.scrollHeight + 2, 260) + "px";
  }
  $effect(() => { void text; tick().then(grow); });

  const firstLine = (t: string) => t.split("\n").find(l => l.trim())?.trim().slice(0, 70) || "pedido";
  async function submit() {
    const t = text.trim();
    if (!t || busy) return;
    busy = true;
    try {
      if (targetTerm) {
        await work.sendToAgent(targetTerm.id, t);
        text = "";
        onstarted?.({ projectId: project.id, taskId: task?.id || null, termId: targetTerm.id });
      } else {
        if (!accountId) { ui.toast("Nenhuma conta de IA — configure em Contas e ajustes → IA", "info"); return; }
        const prog = worktree ? ui.progress("Criando a tarefa e abrindo o agente…") : null;
        try {
          const r = await work.askAi({ projectId: project.id, title: firstLine(t), text: t, flow: plan ? "plan-implement" : "implement", raw: !plan,
            accountId, worktree, taskId: worktree ? null : task?.id || null });
          prog?.done("Tarefa criada — o agente já está trabalhando");
          text = "";
          worktree = false;
          onstarted?.(r);
        } catch (e) { if (prog) prog.fail(e); else throw e; }
      }
    } catch (e) { ui.error(e); }
    finally { busy = false; }
  }
  async function openAgent(id = accountId) {
    if (!id) return ui.toast("Nenhuma conta de IA — configure em Contas e ajustes → IA", "info");
    try { onstarted?.(await work.openAgent(project.id, task?.id || null, id)); }
    catch (e) { ui.error(e); }
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
    else if (e.key === "Escape" && text) { e.preventDefault(); text = ""; }
  }
  const maxUsed = (a: AiAccount) => Math.max(0, ...(a.usage?.rateLimits || []).map(w => w.used || 0));
  function pickAccount(e: MouseEvent) {
    ui.contextMenu(e, [
      { heading: `Conta de ${project.name}` },
      ...installed.map(a => ({ label: `${a.id === accountId ? "● " : ""}${a.name} · ${a.label}${maxUsed(a) ? ` · ${Math.round(maxUsed(a))}%` : ""}`,
        icon: Bot, hint: a.email || undefined, onclick: () => work.setAccount(project.id, a.id) })),
      ...(installed.length ? [] : [{ label: "Nenhuma CLI de IA instalada", disabled: true }]),
      { separator: true },
      { label: "Abrir agente sem pedido", icon: Bot, onclick: () => openAgent() },
    ]);
  }

  // ------------------------------------------------------------ tarefa
  let diff = $state<any>(null);
  // a prop `task` troca de objeto a cada leitura (2,5 s): o efeito depende só do id (antes o diff sumia e era relido sem parar)
  const taskKey = $derived(task?.exists ? `${project.id}|${task.id}` : null);
  $effect(() => {
    const k = taskKey;
    diff = null;
    if (!k) return;
    const [repoId, taskId] = k.split("|");
    const load = () => get("ws/task/diff", { repoId, taskId }).then(d => { if (taskKey === k) diff = d; }).catch(() => {});
    load();
    const i = setInterval(load, 8000);
    return () => clearInterval(i);
  });
  const uncommitted = $derived(diff ? diff.status.unstaged.length + diff.status.staged.length + diff.status.untracked.length : 0);
  /** Revisão feita pelo agente → comentário na PR (você confere e edita o texto antes). */
  async function publishReview() {
    const ag = cur || task?.terms.find(x => x.kind === "agent") || null;
    if (!ag?.meta.sid || !task) return ui.toast("Nenhum agente nesta tarefa", "info");
    let txt = "";
    try { txt = (await get<{ text: string }>("ws/agent/last", { sid: ag.meta.sid })).text; } catch (e) { return ui.error(e); }
    const final = await ui.ask({ title: `Publicar na PR #${(task as any).reviewOf.prId}`, input: { label: "Comentário (confira antes de publicar)", value: txt, multiline: true, required: true }, confirm: "Publicar" });
    if (!final) return;
    const prog = ui.progress("Publicando a revisão…");
    try { await post("pr/comment", { key: (task as any).reviewOf.key, text: final }); prog.done("Revisão publicada na PR"); } catch (e) { prog.fail(e); }
  }
  async function removeTask() {
    if (!task) return;
    // estado ATUAL do worktree (o resumo da tela pode ainda não ter chegado — antes, o aviso dizia "sem alterações"
    // e a remoção normal era recusada pelo Git)
    const fresh = await get<any>("ws/task/diff", { repoId: project.id, taskId: task.id }).catch(() => diff);
    const dirtyN = fresh ? fresh.status.staged.length + fresh.status.unstaged.length + fresh.status.untracked.length : 0;
    const ok = await ui.ask({ title: `Remover a tarefa "${task.title}"?`, danger: true, confirm: "Remover worktree",
      message: dirtyN ? `⚠ O worktree tem ${dirtyN} alteração(ões) não commitada(s) — serão PERDIDAS.` : "O worktree sai do disco. A branch fica (já está no servidor se você fez push).",
      detail: [`branch ${task.branch}`, task.path] });
    if (!ok) return;
    const prog = ui.progress("Removendo o worktree…");
    try { await post("ws/task/remove", { repoId: project.id, taskId: task.id, force: dirtyN > 0 }); prog.done("Tarefa removida"); await work.load(); onremoved?.(); }
    catch (e) { prog.fail(e); }
  }

  // ------------------------------------------------------------ limites
  let limitsOpen = $state(LS("codeck.limitsOpen", "1") !== "0");
  const now = $derived(clock.now);
  // agente terminou: os limites da conta acabaram de chegar pela linha de status — relê sem esperar o ciclo de 30 s
  $effect(() => { if (s?.status === "done" || s?.status === "needs-you") setTimeout(() => work.loadAi(), 1500); });
  // contas: a do agente aberto primeiro, depois a do projeto e as que trabalham nele, depois quem está ativo
  const accounts = $derived.by(() => {
    const used = new Set(work.agents.filter(a => a.project.id === project.id).map(a => a.term.meta.account));
    let list = work.ai.filter(a => a.installed && (used.has(a.id) || a.usage?.rateLimits?.length || a.id === acc?.id || a.id === accountId));
    if (!list.length) list = installed.slice(0, 4);
    const r = (a: AiAccount) => (a.id === acc?.id ? -3 : a.id === accountId ? -2 : used.has(a.id) ? -1 : 0);
    return [...list].sort((x, y) => r(x) - r(y) || stateRank(work.activity[x.id]?.state) - stateRank(work.activity[y.id]?.state));
  });

  const EV: Record<string, string> = { UserPromptSubmit: "pedido recebido", Stop: "terminou", SessionStart: "sessão aberta", PreCompact: "compactando", SubagentStop: "subagente terminou" };
  const ctxSize = (n: number) => (n >= 1e6 ? `${n / 1e6}M` : `${Math.round(n / 1000)}k`);
  const stOf = (t: TermInfo) => { const x = work.session(t); return !t.alive ? ["encerrada", "off"] : x ? STATUS[x.status] || [x.status, "muted"] : ["abrindo…", "muted"]; };
  const focusTerm = (t: TermInfo) => onstarted?.({ projectId: project.id, taskId: task?.id || null, termId: t.id });
</script>

<div class="panel">
  <!-- pedir à IA -->
  <section class="compose" aria-label="Pedir à IA">
    {#if alive.length}
      <div class="to" role="radiogroup" aria-label="Para onde vai o pedido">
        <button role="radio" aria-checked={target === "new"} class:on={target === "new"} onclick={() => (pick = "new")}>Nova sessão</button>
        {#each alive as t (t.id)}
          {@const a = work.account(t.meta.account)}
          {@const st = work.session(t)?.status}
          <button role="radio" aria-checked={target === t.id} class:on={target === t.id} onclick={() => (pick = t.id)} title={`Mandar para ${t.title}`}>
            <i class="dot {STATUS[st || '']?.[1] || 'muted'}" class:pulse={st === "working"}></i><span class="ell">{a?.name || t.title}</span>
          </button>
        {/each}
      </div>
    {/if}
    <div class="box send" class:busy>
      <textarea bind:this={box} bind:value={text} rows="2" onkeydown={onKey} oninput={grow} disabled={busy}
        aria-label={targetTerm ? "Mensagem para a sessão" : "Pedido para a IA"}
        placeholder={targetTerm ? `Mensagem para ${work.account(targetTerm.meta.account)?.name || "o agente"}…` : `O que a IA deve fazer em ${task ? "esta tarefa" : project.name}?`}></textarea>
      <div class="bar">
        {#if !targetTerm}
          {#if account}
            <button class="chip" title={`Conta de IA do projeto: ${account.label} · ${account.name}${account.email ? " · " + account.email : ""} — clique para trocar`} onclick={pickAccount}>
              <AgentIcon provider={account.provider} size={13} /><span class="ell">{account.name}</span><ChevronDown size={11} /></button>
          {:else}
            <span class="tiny muted">Nenhuma CLI de IA — Contas e ajustes → IA</span>
          {/if}
        {/if}
        {#if bypass}<span class="byp" title="Pular permissões está ligado neste projeto: os agentes editam e rodam comandos sem perguntar (Ajustes do projeto)"><ShieldOff size={11} /> bypass</span>{/if}
        <span class="grow"></span>
        <button class="btn sm ghost icon" title="Mais opções: issue/work item, fluxo e título (diálogo completo)" onclick={() => onmore?.(text)}><SlidersHorizontal size={13} /></button>
        <button class="btn sm primary icon go" title={`${targetTerm ? "Enviar à sessão" : "Enviar"} (Enter · ⇧Enter quebra a linha)`} aria-label="Enviar"
          disabled={busy || !text.trim() || (!targetTerm && !accountId)} onclick={submit}><ArrowUp size={15} /></button>
      </div>
    </div>
    {#if !targetTerm}
      <div class="opts">
        <button class="tg" class:on={plan} aria-pressed={plan} title="Mostra o plano, espera você aprovar no terminal e então implementa"
          onclick={() => { plan = !plan; LSset("codeck.compose.plan", plan ? "1" : "0"); }}><Lightbulb size={12} /> Planejar</button>
        <button class="tg" class:on={worktree} aria-pressed={worktree} title={worktree ? "Cria uma tarefa nova: branch + worktree próprios (não mexe no seu checkout)" : `Roda ${task ? "nesta tarefa" : "no checkout principal"}`}
          onclick={() => (worktree = !worktree)}><GitBranch size={12} /> Tarefa nova</button>
        <span class="grow"></span>
        <button class="lnk" disabled={!accountId} title="Abre um agente nesta conta, sem pedido" onclick={() => openAgent()}><Bot size={12} /> Abrir agente</button>
      </div>
    {/if}
  </section>

  <!-- sessões -->
  {#if agentsHere.length}
    <section class="sess">
      <h4>Sessões <span class="n">{alive.length}</span></h4>
      <ul>
        {#each agentsHere as t (t.id)}
          {@const a = work.account(t.meta.account)}
          {@const x = work.session(t)}
          {@const [lbl, tn] = stOf(t)}
          <li class:cur={cur?.id === t.id} class:dead={!t.alive}>
            <button class="row" onclick={() => focusTerm(t)} title={t.title}>
              {#if a}<AccountAvatar {a} state={x?.status === "working" ? "working" : x?.status === "needs-you" ? "needs-you" : null} size={22} />
              {:else}<AgentIcon provider={t.meta.provider} size={15} />{/if}
              <span class="who"><b class="ell">{a?.name || t.title}</b><span class="tiny st {tn}">{lbl}{#if t.meta.bypass} · bypass{/if}</span></span>
              {#if x?.context?.used != null}<span class="ctx {tone(x.context.used)}" title="contexto usado">{Math.round(x.context.used)}%</span>{/if}
            </button>
          </li>
        {/each}
      </ul>
      {#if cur}
        <div class="detail">
          {#if s}<span class="pill st {STATUS[s.status]?.[1]}"><i class:pulse={s.status === "working" || s.status === "needs-you"}></i>{STATUS[s.status]?.[0] || s.status}</span>{/if}
          {#if s?.status === "needs-you"}<p class="hint">Responda no terminal do agente.</p>{/if}
          {#if s?.status === "starting" && now / 1000 - s.started > 8}
            <p class="hint">Aguardando no terminal — se o agente perguntou se você confia na pasta (ou confirma o bypass), responda lá.</p>
          {/if}
          {#if s?.model || s?.context || s?.cost != null}
          <div class="ctxrow">
            <LimitRing used={s?.context?.used ?? null} size={52} label="contexto" binding={(s?.context?.used || 0) >= 80} />
            <div class="kvs">
              <div class="kv"><span>Modelo</span><b class="ell">{s?.model || "—"}</b></div>
              <div class="kv"><span>Contexto</span><b>{s?.context?.used != null ? `${Math.round(s.context.used)}%` : "—"}{s?.context?.size ? ` de ${ctxSize(s.context.size)}` : ""}</b></div>
              <div class="kv"><span>Custo</span><b>{s?.cost != null ? `US$ ${s.cost.toFixed(2)}` : "—"}</b></div>
            </div>
          </div>
          {:else if cur.alive}
            <p class="tiny muted wait">Contexto, modelo e custo aparecem depois da 1ª resposta.</p>
          {/if}
          {#if (s?.context?.used || 0) >= 80}<p class="hint warn">Contexto quase cheio — peça /compact ou abra uma sessão nova com um resumo.</p>{/if}
          {#if s?.events?.length}
            <ol class="events">{#each s.events.slice(-4).reverse() as ev, i (i)}<li><span class="ell">{EV[ev.event] || (ev.event === "Notification" ? ev.message || "pediu atenção" : ev.event)}</span><time class="tiny">{new Date(ev.at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</time></li>{/each}</ol>
          {/if}
        </div>
      {/if}
    </section>
  {/if}

  <!-- tarefa -->
  {#if task}
    <section class="task">
      <h4>Tarefa</h4>
      <div class="ttl">{task.title}</div>
      <div class="brs"><span class="br mono ell" title={task.branch}><GitBranch size={11} /> {task.branch}</span><span class="tiny muted">de</span><span class="base mono ell" title={task.base}>{task.base}</span></div>
      {#if diff}
        <p class="nums small">
          <span><b>{diff.commits}</b> commit{diff.commits === 1 ? "" : "s"}</span>
          <span><b>{diff.files.length + diff.status.untracked.length}</b> arquivo(s)</span>
          <span class:warn={uncommitted}><b>{uncommitted}</b> sem commit</span>
        </p>
      {/if}
      {#each (task as any).linked || [] as x (x.repoId)}
        <div class="kv"><span>Também em</span><button class="lnk" onclick={() => go("/repo/" + x.wtRepoId)}>{x.name}</button></div>
      {/each}
      {#if task.workItem}<div class="kv"><span>Work item</span><a class="ell" href={task.workItem.url} target="_blank" rel="noopener">#{task.workItem.number}</a></div>{/if}
      <div class="acts">
        {#if (task as any).reviewOf}<button class="btn sm brand" onclick={publishReview}><MessageSquareShare size={13} /> Publicar revisão na PR</button>{/if}
        <button class="btn sm" onclick={() => onreview?.()}><GitCompareArrows size={13} /> Revisar</button>
        <button class="btn sm" onclick={() => go("/repo/" + task!.repoId)}><GitCommitHorizontal size={13} /> Commitar</button>
        {#if diff?.commits}<button class="btn sm brand" onclick={() => { repos.prIntent = task!.repoId; go("/repo/" + task!.repoId); }}><GitPullRequestCreate size={13} /> Criar PR</button>{/if}
        <span class="grow"></span>
        <button class="btn sm ghost icon" title="Abrir no editor externo" onclick={() => post("open", { id: task!.repoId, target: "editor" }).catch(e => ui.error(e))}><ExternalLink size={13} /></button>
        <button class="btn sm ghost icon danger-text" title="Remover tarefa (worktree)" onclick={removeTask}><Trash2 size={13} /></button>
      </div>
    </section>
  {/if}

  <!-- limites -->
  <section class="limits" class:shut={!limitsOpen}>
    <button class="lh" onclick={() => { limitsOpen = !limitsOpen; LSset("codeck.limitsOpen", limitsOpen ? "1" : "0"); }} aria-expanded={limitsOpen}>
      <h4>Limites das contas</h4><ChevronDown size={13} class="chev {limitsOpen ? '' : 'rot'}" /></button>
    {#if limitsOpen}
    {#each accounts as a (a.id)}
      {@const ws = a.usage?.rateLimits || []}
      {@const b = binding(ws, now)}
      {@const st = work.activity[a.id]?.state}
      <div class="lim" class:cur={a.id === (acc?.id || accountId)}>
        <AccountAvatar {a} state={st === "working" || st === "needs-you" ? st : null} size={24} />
        <div class="lt">
          <b class="ell">{a.name}{#if a.id === acc?.id}<span class="this">esta sessão</span>{:else if a.id === accountId}<span class="this">do projeto</span>{/if}</b>
          {#if ws.length && b}
            <span class="tiny cd {tone(effUsed(b, now))}" title="A janela mais gasta e quando ela reseta">{b.window} · {resetLabel(b.resetsAt, now)}</span>
          {:else if a.provider === "claude"}
            <button class="tiny readlim" disabled={!!work.probing[a.id]} onclick={() => work.probe(a.id)}>{work.probing[a.id] ? "lendo o limite…" : work.activity[a.id]?.probeError ? work.activity[a.id]!.probeError!.error : "limite não lido — ler agora"}</button>
          {:else}<span class="tiny muted">{a.telemetry ? "aparece após a 1ª resposta" : "esta CLI não informa limites"}</span>{/if}
        </div>
        {#each ws as w (w.window)}
          <div class="mw win" title={`${w.window}: ${Math.round(effUsed(w, now))}% · ${resetLabel(w.resetsAt, now)}`}>
            <LimitRing used={effUsed(w, now)} size={30} binding={ws.length > 1 && b?.window === w.window && effUsed(w, now) > 0} />
            <span>{w.window === "semanal" ? "sem." : w.window}</span>
          </div>
        {/each}
      </div>
    {:else}<div class="small muted">Nenhuma conta de IA. Configure em Contas e ajustes → IA.</div>{/each}
    {/if}
  </section>
</div>

<style>
  .panel { display: flex; flex-direction: column; gap: 0; padding: 12px; overflow-y: auto; overflow-x: hidden; height: 100%; }
  section { min-width: 0; display: grid; gap: 8px; padding: 14px 0; border-top: 1px solid var(--line); }
  section:first-child { padding-top: 0; border-top: 0; }
  h4 { display: flex; align-items: center; gap: 6px; margin: 0; font: 600 12px/1 var(--font); color: var(--text-2); }
  h4 .n { font: 600 10.5px/1 var(--font); color: var(--muted); font-variant-numeric: tabular-nums; }
  .grow { flex: 1; }
  .pulse { animation: ping 1.3s var(--ease) infinite; }
  @keyframes ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--c, var(--accent)) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 5px transparent; } }

  /* ---------- pedir à IA */
  .compose { gap: 6px; }
  .to { display: flex; gap: 4px; overflow-x: auto; scrollbar-width: none; }
  .to button { display: inline-flex; align-items: center; gap: 5px; height: 22px; padding: 0 8px; border: 1px solid transparent; border-radius: 99px; background: none;
    color: var(--muted); font: 500 11.5px var(--font); cursor: pointer; flex: none; max-width: 140px; transition: background var(--t-fast), color var(--t-fast); }
  .to button:hover { color: var(--text); background: var(--surface-2); }
  .to button.on { color: var(--text); background: var(--surface-2); border-color: var(--line-2); }
  .dot { --c: var(--muted); width: 6px; height: 6px; border-radius: 50%; background: var(--c); flex: none; }
  .dot.accent { --c: var(--accent); } .dot.good { --c: var(--good); } .dot.warn { --c: var(--warn); } .dot.info { --c: var(--info); }
  .box { display: grid; border: 1px solid var(--line-2); border-radius: var(--r); background: var(--surface-2); transition: border-color var(--t-fast), box-shadow var(--t-fast); }
  .box:focus-within { border-color: var(--accent-line); box-shadow: var(--ring); }
  .box.busy { opacity: 0.7; }
  .box textarea { width: 100%; min-height: 52px; max-height: 260px; resize: none; border: 0; outline: 0; background: none; color: var(--text);
    font: 13px/1.5 var(--font); padding: 9px 11px 4px; }
  .box textarea::placeholder { color: var(--muted); }
  .bar { display: flex; align-items: center; gap: 5px; padding: 4px 5px 5px 7px; min-width: 0; }
  .chip { display: inline-flex; align-items: center; gap: 5px; height: 24px; padding: 0 7px; border: 1px solid var(--line-2); border-radius: 99px; background: var(--surface);
    color: var(--text-2); font: 500 12px var(--font); cursor: pointer; min-width: 0; max-width: 140px; transition: border-color var(--t-fast), color var(--t-fast); }
  .chip:hover { border-color: var(--line-3); color: var(--text); }
  .chip :global(svg:last-child) { color: var(--muted); flex: none; }
  .byp { display: inline-flex; align-items: center; gap: 3px; height: 20px; padding: 0 6px; border-radius: 99px; background: var(--warn-soft); color: var(--warn);
    font: 650 10.5px/1 var(--font); flex: none; cursor: help; }
  .go { border-radius: 8px; }
  .opts { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 4px; min-width: 0; }
  .opts > button { flex: none; white-space: nowrap; }
  .tg { display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 7px; border: 1px solid transparent; border-radius: var(--r-xs); background: none;
    color: var(--muted); font: 500 11.5px var(--font); cursor: pointer; transition: background var(--t-fast), color var(--t-fast), border-color var(--t-fast); }
  .tg:hover { color: var(--text); background: var(--surface-2); }
  .tg.on { color: var(--accent); background: var(--accent-soft); border-color: var(--accent-line); }
  .lnk { display: inline-flex; align-items: center; gap: 4px; border: 0; background: none; padding: 0 2px; color: var(--text-2); font: 500 11.5px var(--font); cursor: pointer; }
  .lnk:hover:not(:disabled) { color: var(--accent); }
  .lnk:disabled { opacity: 0.5; cursor: default; }

  /* ---------- sessões */
  .sess ul { list-style: none; margin: 0 -6px; padding: 0; display: grid; gap: 1px; }
  .row { display: flex; align-items: center; gap: 9px; width: 100%; padding: 5px 6px; border: 0; border-radius: var(--r-sm); background: none; color: var(--text);
    font: 12.5px var(--font); text-align: left; cursor: pointer; min-width: 0; transition: background var(--t-fast); }
  .row:hover { background: var(--surface-2); }
  li.cur .row { background: var(--surface-2); box-shadow: inset 0 0 0 1px var(--line-2); }
  li.dead .row { opacity: 0.55; }
  .who { display: grid; flex: 1; min-width: 0; line-height: 1.3; }
  .who b { font-weight: 600; }
  .st { color: var(--muted); }
  .st.accent { color: var(--accent); } .st.good { color: var(--good); } .st.warn { color: var(--warn); } .st.info { color: var(--info); }
  .ctx { font: 600 11px var(--font); font-variant-numeric: tabular-nums; color: var(--muted); }
  .ctx.warn { color: var(--warn); } .ctx.bad { color: var(--bad); }
  .detail { display: grid; gap: 8px; padding: 4px 0 0; min-width: 0; }
  .detail:empty { display: none; }
  .wait { margin: 0; }
  .pill.st { --c: var(--muted); justify-self: start; display: inline-flex; align-items: center; gap: 6px; color: var(--c); background: color-mix(in srgb, var(--c) 12%, transparent); }
  .pill.st i { width: 6px; height: 6px; border-radius: 50%; background: var(--c); }
  .pill.st.accent { --c: var(--accent); } .pill.st.good { --c: var(--good); } .pill.st.warn { --c: var(--warn); } .pill.st.info { --c: var(--info); }
  .hint { margin: 0; padding: 6px 8px; border-radius: var(--r-xs); background: var(--info-soft); color: var(--text-2); font-size: 12px; }
  .hint.warn { background: var(--warn-soft); }
  .ctxrow { display: flex; align-items: center; gap: 12px; min-width: 0; }
  .kvs { display: grid; gap: 3px; flex: 1; min-width: 0; }
  .kv { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; align-items: center; min-width: 0; padding: 0; border: 0; }
  .kv span:first-child { color: var(--muted); white-space: nowrap; }
  .kv b { font-weight: 600; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
  .events { list-style: none; margin: 0; padding: 6px 0 0; border-top: 1px solid var(--line); display: grid; gap: 2px; }
  .events li { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted); min-width: 0; }
  .events li:first-child { color: var(--text-2); }
  .events .ell { flex: 1; }
  .events time { font-variant-numeric: tabular-nums; }

  /* ---------- tarefa */
  .ttl { font-weight: 600; font-size: 13px; line-height: 1.35; }
  .brs { display: flex; align-items: center; gap: 6px; min-width: 0; font-size: 11.5px; }
  .br { display: inline-flex; align-items: center; gap: 4px; max-width: 70%; color: var(--accent); }
  .base { color: var(--text-2); max-width: 40%; }
  .nums { display: flex; flex-wrap: wrap; gap: 4px 12px; margin: 0; color: var(--muted); }
  .nums b { color: var(--text); font-weight: 650; font-variant-numeric: tabular-nums; }
  .nums .warn, .nums .warn b { color: var(--warn); }
  .acts { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
  .danger-text { color: var(--bad); }
  a { color: var(--accent); }

  /* ---------- limites */
  .limits { gap: 2px; }
  .limits.shut { padding-bottom: 0; }
  .lh { display: flex; align-items: center; justify-content: space-between; width: 100%; border: 0; background: none; padding: 0 0 6px; cursor: pointer; color: var(--muted); }
  .lh :global(.chev) { transition: transform var(--t); }
  .lh :global(.chev.rot) { transform: rotate(-90deg); }
  .lim { display: flex; align-items: center; gap: 9px; padding: 6px; margin: 0 -6px; border-radius: var(--r-sm); min-width: 0; }
  .lim.cur { background: var(--surface-2); }
  .lt { display: grid; min-width: 0; flex: 1; line-height: 1.35; }
  .lt b { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 12.5px; min-width: 0; }
  .this { font: 600 10px/1 var(--font); color: var(--accent); flex: none; }
  .cd { font-variant-numeric: tabular-nums; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .cd.warn { color: var(--warn); } .cd.bad { color: var(--bad); }
  .mw { display: grid; justify-items: center; gap: 1px; flex: none; min-width: 30px; }
  .mw span { font-size: 9.5px; color: var(--muted); line-height: 1; }
  .readlim { border: 0; background: none; padding: 0; color: var(--accent); cursor: pointer; text-align: left; font-family: var(--font); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .readlim:disabled { color: var(--muted); cursor: default; }
  @media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }
</style>
