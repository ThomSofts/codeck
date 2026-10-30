<script lang="ts">
  // A tela inicial do projeto (e o botão Agente): escolher com qual IA trabalhar. Cada conta mostra o fôlego agora (as
  // janelas de 5 h e semanal, com a contagem para o reset), o que está fazendo (livre, trabalhando, no limite), o consumo
  // da semana e o modelo que vem usando; a recomendada (mais fôlego no grupo do projeto) vem marcada. Em cima, as sessões
  // já abertas neste checkout/tarefa (com "continuar em outra conta") e, numa tarefa, o que mudou e as ações dela
  // (revisar, commitar, PR, publicar a revisão); embaixo, retomar uma conversa, terminal e nova tarefa.
  import { ArrowRight, ArrowRightLeft, Bot, ExternalLink, GitBranch, GitCommitHorizontal, GitCompareArrows, GitPullRequestCreate, MessageSquareShare, Plus, RefreshCw,
    RotateCcw, SquareTerminal, Sparkles, Trash2, Zap } from "@lucide/svelte";
  import { onMount } from "svelte";
  import { get, post } from "../../lib/api";
  import { consumption, modelLabel, tok, usd } from "../../lib/consumption.svelte";
  import { kb } from "../../lib/keybindings.svelte";
  import { repos } from "../../lib/repos.svelte";
  import { go } from "../../lib/router.svelte";
  import { ui } from "../../lib/ui.svelte";
  import type { AiAccount, Project, Task, TermInfo } from "../../lib/work.svelte";
  import { STATUS, work } from "../../lib/work.svelte";
  import AccountAvatar from "../ai/AccountAvatar.svelte";
  import { handoffMenu } from "../ai/handoff";
  import Fuel from "../ai/Fuel.svelte";
  import { accColor, ACC_STATE, binding, clock, countdown, rank, type Rec } from "../ai/limits.svelte";
  import AgentIcon from "./AgentIcon.svelte";

  let { project, task = null, resumable = [], onagent, onterm, onresume, onfocus, ontask, onreview, onremoved }:
    { project: Project; task?: Task | null; resumable?: { sid: string; account: string; provider: string; title: string; updated: string }[];
      onagent: (accountId: string) => void; onterm: () => void; onresume: (accountId: string, sid: string) => void;
      onfocus: (termId: string) => void; ontask?: () => void; onreview?: () => void; onremoved?: () => void } = $props();

  onMount(() => { consumption.load(7); work.loadActivity(); });
  const now = $derived(clock.now);
  const installed = $derived(work.ai.filter(a => a.installed));
  const mine = $derived(work.defaultAccount(project));
  const group = $derived(work.account(mine)?.group || null);
  // as do grupo do projeto primeiro (o cliente), depois as outras; dentro de cada, pelo fôlego
  const ranked = $derived([...rank(installed.filter(a => !group || a.group === group), now), ...(group ? rank(installed.filter(a => a.group !== group), now) : [])]);
  const best = $derived(ranked.find(r => r.free != null && !r.blocked) || null);
  const sessions = $derived((task ? task.terms : project.terms).filter(t => t.kind === "agent" && t.alive));
  const week = (a: AiAccount) => consumption.data?.accounts[a.id]?.week || null;
  const lastModel = (a: AiAccount) => { const x = consumption.data?.accounts[a.id]; return x?.weekTop?.model || x?.last?.model || x?.configured?.model || null; };
  const projUse = $derived(consumption.data ? consumption.data.project[project.name] || consumption.data.project[project.id] || null : null);
  const weekTotal = $derived(installed.reduce((s, a) => s + (week(a)?.tokens || 0), 0));

  function accState(r: Rec): { label: string; tone: string; live: boolean } {
    const act = work.activity[r.a.id];
    if (r.blocked) {
      const b = binding(r.a.usage?.rateLimits, now);
      const cd = countdown(b?.resetsAt, now);
      return { label: cd && cd !== "resetou" ? `no limite · volta em ${cd}` : "no limite", tone: "bad", live: false };
    }
    if (act && act.state !== "free") {
      const st = ACC_STATE[act.state];
      const where = act.sessions.find(s => s.project)?.project;
      return { label: `${st?.[0] || act.state}${where ? " · " + where : ""}${act.sessions.length > 1 ? ` (+${act.sessions.length - 1})` : ""}`, tone: st?.[1] || "muted", live: act.state === "working" };
    }
    return { label: r.free == null ? "pronta para abrir" : r.free < 30 ? `${Math.round(r.free)}% livre — pouco fôlego` : `${Math.round(r.free)}% livre`, tone: r.free == null ? "muted" : r.free < 30 ? "warn" : "good", live: false };
  }
  // ------------------------------------------------------------ tarefa: o que mudou e as ações
  let diff = $state<any>(null);
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
    const ag = task?.terms.find(x => x.kind === "agent") || null;
    if (!ag?.meta.sid || !task) return ui.toast("Nenhum agente nesta tarefa", "info");
    let txt = "";
    try { txt = (await get<{ text: string }>("ws/agent/last", { sid: ag.meta.sid })).text; } catch (e) { return ui.error(e); }
    const final = await ui.ask({ title: `Publicar na PR #${(task as any).reviewOf.prId}`, input: { label: "Comentário (confira antes de publicar)", value: txt, multiline: true, required: true }, confirm: "Publicar" });
    if (!final) return;
    const prog = ui.progress("Publicando a revisão…");
    try { await post("pr/comment", { key: (task as any).reviewOf.key, text: final }); prog.done("Revisão publicada na PR"); } catch (e) { prog.fail(e); }
  }
  async function removeTask() { if (task && (await work.removeTask(project, task))) onremoved?.(); }

  const stOf = (t: TermInfo) => { const x = work.session(t); return x ? STATUS[x.status] || [x.status, "muted"] : ["abrindo…", "muted"]; };
  const ago = (iso: string) => { const m = Math.round((Date.now() - new Date(iso).getTime()) / 6e4); return m < 60 ? `${m} min` : m < 1440 ? `${Math.round(m / 60)} h` : `${Math.round(m / 1440)} d`; };
</script>

<div class="al">
  <header class="hero">
    <div class="orb" aria-hidden="true"><span></span><Bot size={26} /></div>
    <div class="ht">
      <h2>Com qual IA vamos trabalhar?</h2>
      <p class="muted">{task ? `Tarefa ${task.title} · worktree` : `${project.name} · checkout principal`}{group ? ` · contas de ${group}` : ""}</p>
    </div>
    <span class="grow"></span>
    <div class="kpis">
      <div class="kpi"><b>{installed.length}</b><span>contas</span></div>
      <div class="kpi"><b>{ranked.filter(r => r.free != null && !r.blocked).length}</b><span>com fôlego</span></div>
      <div class="kpi"><b>{tok(weekTotal)}</b><span>tokens · 7 dias</span></div>
      {#if projUse}<div class="kpi"><b>{usd(projUse.cost)}</b><span>neste projeto · 7 d</span></div>{/if}
    </div>
    <button class="btn sm ghost icon" title="Ler os limites agora" aria-label="Ler os limites agora" onclick={() => work.probe()}>
      <RefreshCw size={14} class={Object.keys(work.probing || {}).length ? "spin" : ""} /></button>
  </header>

  {#if best}
    <button class="rec" style="--ac:{accColor(best.a)}" onclick={() => onagent(best!.a.id)}>
      <Sparkles size={16} />
      <span><b>Recomendada agora: {best.a.name}</b> <span class="muted">— {Math.round(best.free!)}% livre · {best.why}</span></span>
      <span class="go">Abrir <ArrowRight size={14} /></span>
    </button>
  {/if}

  {#if task}
    <section class="task">
      <div class="tk">
        <div class="tt">
          <b class="ell">{task.title}</b>
          <span class="brs tiny"><span class="br mono ell" title={task.branch}><GitBranch size={11} /> {task.branch}</span><span class="muted">de</span><span class="mono muted ell">{task.base}</span></span>
        </div>
        {#if diff}
          <div class="nums">
            <span><b>{diff.commits}</b> commit{diff.commits === 1 ? "" : "s"}</span>
            <span><b>{diff.files.length + diff.status.untracked.length}</b> arquivo(s)</span>
            <span class:warn={uncommitted}><b>{uncommitted}</b> sem commit</span>
          </div>
        {/if}
      </div>
      <div class="tacts">
        {#if (task as any).reviewOf}<button class="btn sm primary" onclick={publishReview}><MessageSquareShare size={13} /> Publicar revisão na PR</button>{/if}
        <button class="btn sm" onclick={() => onreview?.()}><GitCompareArrows size={13} /> Revisar</button>
        <button class="btn sm" onclick={() => go("/repo/" + task!.repoId)}><GitCommitHorizontal size={13} /> Commitar</button>
        {#if diff?.commits}<button class="btn sm" onclick={() => { repos.prIntent = task!.repoId; go("/repo/" + task!.repoId); }}><GitPullRequestCreate size={13} /> Criar PR</button>{/if}
        {#if task.workItem}<a class="btn sm ghost" href={task.workItem.url} target="_blank" rel="noopener">#{task.workItem.number}</a>{/if}
        <span class="grow"></span>
        <button class="btn sm ghost icon" title="Abrir no editor externo" onclick={() => post("open", { id: task!.repoId, target: "editor" }).catch(e => ui.error(e))}><ExternalLink size={13} /></button>
        <button class="btn sm ghost icon dz" title="Remover tarefa (worktree)" onclick={removeTask}><Trash2 size={13} /></button>
      </div>
    </section>
  {/if}

  {#if sessions.length}
    <section>
      <h4>Abertas {task ? "nesta tarefa" : "neste checkout"}</h4>
      <div class="sess">
        {#each sessions as t (t.id)}
          {@const s = work.session(t)}
          {@const st = stOf(t)}
          <button class="srow" onclick={() => onfocus(t.id)}>
            <AgentIcon provider={t.meta.provider} size={16} />
            <span class="ell sn">{t.title}</span>
            <span class="pill {st[1] === 'muted' ? 'neutral' : st[1]}" class:pulse={s?.status === "working"}>{st[0]}</span>
            {#if s?.model}<span class="tiny muted">{modelLabel(s.model)}</span>{/if}
            {#if s?.context?.used != null}<span class="ctx" style="--p:{Math.min(100, s.context.used)}%" title="contexto usado"><i></i>{Math.round(s.context.used)}%</span>{/if}
            {#if s?.cost != null}<span class="tiny muted">{usd(s.cost)}</span>{/if}
            {#if installed.length > 1 && !s?.handedOff}<span class="ho" role="button" tabindex="0" title="Continuar este trabalho em outra conta (sem esperar o limite)"
              onclick={(e) => { e.stopPropagation(); handoffMenu(e, t, onfocus); }} onkeydown={(e) => e.key === "Enter" && e.stopPropagation()}><ArrowRightLeft size={13} /></span>{/if}
            <ArrowRight size={14} class="muted" />
          </button>
          {#if s?.status === "needs-you"}<p class="hint warn">{s.ask?.text ? s.ask.text + " — " : ""}responda no terminal do agente.</p>{/if}
          {#if s?.limit && !s.handedOff}<p class="hint bad">A conta atingiu o limite{s.limit.resetsAt ? ` — reseta em ${countdown(s.limit.resetsAt, now)}` : ""}: continue em outra conta (⇄).</p>{/if}
        {/each}
      </div>
    </section>
  {/if}

  <section>
    <h4>Contas <span class="tiny muted">clique para abrir o agente {task ? "na tarefa" : "no checkout"}</span></h4>
    {#if !installed.length}
      <p class="muted small">Nenhuma CLI de IA encontrada (Claude Code, Codex, Cursor, Gemini, OpenCode). Instale uma e configure em Contas e ajustes → IA.</p>
    {/if}
    <div class="cards">
      {#each ranked as r, i (r.a.id)}
        {@const st = accState(r)}
        {@const w = week(r.a)}
        {@const m = lastModel(r.a)}
        <button class="acc {st.tone}" class:best={best?.a.id === r.a.id} class:mine={r.a.id === mine} style="--ac:{accColor(r.a)}; --d:{i * 40}ms"
          title={`Abrir ${r.a.label} · ${r.a.name}`} onclick={() => onagent(r.a.id)}>
          <div class="top">
            <AccountAvatar a={r.a} size={38} state={work.activity[r.a.id]?.state === "working" ? "working" : work.activity[r.a.id]?.state === "needs-you" ? "needs-you" : null} />
            <div class="nm">
              <b class="ell">{r.a.name}</b>
              <span class="tiny muted ell">{r.a.label}{r.a.group ? " · " + r.a.group : ""}{r.a.usage?.plan ? " · " + r.a.usage.plan : ""}</span>
            </div>
            {#if best?.a.id === r.a.id}<span class="tag star">recomendada</span>{:else if r.a.id === mine}<span class="tag">do projeto</span>{/if}
          </div>
          <div class="state"><span class="dot" class:live={st.live}></span><span class="ell">{st.label}</span></div>
          {#if r.a.usage?.rateLimits?.length}<Fuel a={r.a} />{:else}<div class="nofuel tiny muted">{r.why}</div>{/if}
          <div class="foot tiny">
            {#if w}<span title="tokens nos últimos 7 dias"><Zap size={11} /> {tok(w.tokens)}</span><span title="custo estimado nos últimos 7 dias">{usd(w.cost)}</span><span title="sessões nos últimos 7 dias">{w.sessions} sess.</span>
            {:else}<span class="muted">sem uso nos últimos 7 dias</span>{/if}
            {#if m}<span class="mdl ell" title="modelo mais usado">{modelLabel(m)}</span>{/if}
          </div>
          <span class="open">Abrir agente <ArrowRight size={13} /></span>
        </button>
      {/each}
    </div>
  </section>

  <section class="more">
    {#if resumable.length}
      <div class="resume">
        <h4><RotateCcw size={13} /> Retomar de onde parou</h4>
        {#each resumable.slice(0, 5) as r (r.sid)}
          <button class="btn sm" onclick={() => onresume(r.account, r.sid)}><AgentIcon provider={r.provider} size={14} /> <span class="ell">{r.title}</span> <span class="tiny muted">há {ago(r.updated)}</span></button>
        {/each}
      </div>
    {/if}
    <div class="acts">
      <button class="cardbtn" onclick={onterm}><SquareTerminal size={18} /><span><b>Terminal</b><span class="tiny muted">shell na pasta {task ? "da tarefa" : "do projeto"}</span></span></button>
      {#if ontask}<button class="cardbtn accent" onclick={ontask}><Plus size={18} /><span><b>Nova tarefa</b><span class="tiny muted">agente + branch (worktree opcional)</span></span></button>{/if}
    </div>
    <p class="tiny muted keys"><span class="kbd">{kb.label("codeck.askAi")}</span> esta tela · <span class="kbd">{kb.label("workbench.action.quickOpen")}</span> abrir arquivo · <span class="kbd">{kb.label("workbench.action.terminal.new")}</span> terminal · dois cliques na barra de abas: arquivo sem título</p>
  </section>
</div>

<style>
  .al { height: 100%; overflow: auto; padding: 26px clamp(16px, 4vw, 48px) 30px; display: flex; flex-direction: column; gap: 18px; animation: fade 0.3s; }
  .hero { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  .orb { position: relative; width: 54px; height: 54px; border-radius: 16px; display: grid; place-items: center; color: var(--accent); flex: none;
    background: radial-gradient(circle at 30% 25%, color-mix(in srgb, var(--accent) 34%, transparent), color-mix(in srgb, var(--accent) 8%, var(--surface-2)));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 40%, transparent), 0 8px 24px -10px color-mix(in srgb, var(--accent) 60%, transparent); }
  .orb span { position: absolute; inset: -5px; border-radius: 20px; border: 1.5px solid color-mix(in srgb, var(--accent) 45%, transparent); animation: breathe 3.2s ease-in-out infinite; }
  @keyframes breathe { 0%, 100% { opacity: .15; transform: scale(.96); } 50% { opacity: .7; transform: scale(1.02); } }
  .ht h2 { margin: 0; font-size: 21px; letter-spacing: -0.02em; }
  .ht p { margin: 3px 0 0; font-size: 13px; }
  .kpis { display: flex; gap: 6px; flex-wrap: wrap; }
  .kpi { display: grid; padding: 7px 12px; border-radius: 11px; background: var(--surface-2); border: 1px solid var(--line); min-width: 82px; }
  .kpi b { font-size: 16px; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }
  .kpi span { font-size: 11px; color: var(--muted); }
  .rec { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-radius: 13px; cursor: pointer; text-align: left; font: 13px var(--font); color: var(--text);
    border: 1px solid color-mix(in srgb, var(--ac) 45%, var(--line)); background: linear-gradient(100deg, color-mix(in srgb, var(--ac) 16%, var(--surface)), var(--surface) 70%);
    transition: transform var(--t-fast), box-shadow var(--t-fast); }
  .rec:hover { transform: translateY(-1px); box-shadow: 0 10px 28px -16px var(--ac); }
  .rec :global(svg:first-child) { color: var(--ac); flex: none; }
  .rec > span:nth-child(2) { flex: 1; min-width: 0; }
  .rec .go { display: inline-flex; align-items: center; gap: 4px; font-weight: 650; color: var(--ac); flex: none; }
  section h4 { display: flex; align-items: baseline; gap: 8px; margin: 0 0 9px; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-2); }
  section h4 .tiny { text-transform: none; letter-spacing: 0; font-weight: 400; }
  .sess { display: grid; gap: 4px; }
  .srow { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface-2); color: var(--text);
    font: 13px var(--font); cursor: pointer; text-align: left; min-width: 0; }
  .srow:hover { border-color: var(--accent); }
  .srow .sn { flex: 1; min-width: 0; font-weight: 600; }
  .pill.pulse { animation: pulse 1.6s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: .55; } }
  .ctx { position: relative; display: inline-flex; align-items: center; gap: 5px; font: 600 11px var(--font); color: var(--text-2); font-variant-numeric: tabular-nums; }
  .ctx i { width: 34px; height: 5px; border-radius: 9px; background: linear-gradient(90deg, var(--accent) var(--p), var(--surface-3) var(--p)); }
  .task { padding: 12px 14px; border-radius: 13px; border: 1px solid var(--line-2); background: var(--surface-2); gap: 10px; }
  .tk { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; min-width: 0; }
  .tt { display: grid; gap: 3px; min-width: 0; flex: 1; }
  .tt b { font-size: 14px; }
  .brs { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .br { display: inline-flex; align-items: center; gap: 4px; color: var(--accent); }
  .nums { display: flex; gap: 12px; font-size: 12px; color: var(--muted); }
  .nums b { color: var(--text); font-variant-numeric: tabular-nums; }
  .nums .warn b { color: var(--warn); }
  .tacts { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .dz:hover { color: var(--bad); background: var(--bad-soft); }
  .ho { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 7px; color: var(--muted); }
  .ho:hover { background: var(--surface-3); color: var(--accent); }
  .hint { margin: 2px 0 4px 38px; font-size: 12px; color: var(--text-2); }
  .hint.warn { color: var(--warn); } .hint.bad { color: var(--bad); }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
  .acc { --tone: var(--good); position: relative; display: flex; flex-direction: column; gap: 10px; padding: 14px; border-radius: 14px; text-align: left; cursor: pointer;
    border: 1px solid var(--line-2); background: linear-gradient(160deg, color-mix(in srgb, var(--ac) 9%, var(--surface-2)), var(--surface-2) 55%); color: var(--text);
    font: 13px var(--font); min-width: 0; overflow: hidden; animation: rise .4s var(--ease-out) both; animation-delay: var(--d);
    transition: transform var(--t-fast), border-color var(--t-fast), box-shadow var(--t-fast); }
  @keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  .acc::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--ac); opacity: .8; }
  .acc:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--ac) 60%, var(--line)); box-shadow: 0 14px 30px -20px var(--ac); }
  .acc.best { border-color: color-mix(in srgb, var(--ac) 55%, var(--line)); }
  .acc.bad { --tone: var(--bad); opacity: .82; } .acc.warn { --tone: var(--warn); } .acc.accent { --tone: var(--accent); } .acc.muted { --tone: var(--muted); }
  .top { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .nm { display: grid; min-width: 0; flex: 1; }
  .nm b { font-size: 14px; }
  .tag { font: 650 10.5px var(--font); padding: 2px 8px; border-radius: 99px; background: var(--surface-3); color: var(--text-2); flex: none; }
  .tag.star { background: color-mix(in srgb, var(--ac) 22%, transparent); color: color-mix(in srgb, var(--ac) 60%, var(--text)); }
  .state { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text-2); min-width: 0; }
  .state .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--tone); flex: none; box-shadow: 0 0 0 3px color-mix(in srgb, var(--tone) 18%, transparent); }
  .state .dot.live { animation: pulse 1.2s ease-in-out infinite; }
  .nofuel { min-height: 18px; }
  .foot { display: flex; align-items: center; gap: 10px; color: var(--text-2); flex-wrap: wrap; padding-top: 8px; border-top: 1px dashed var(--line-2); }
  .foot span { display: inline-flex; align-items: center; gap: 3px; font-variant-numeric: tabular-nums; }
  .foot .mdl { margin-left: auto; padding: 1px 7px; border-radius: 6px; background: var(--surface-3); max-width: 120px; }
  .open { position: absolute; right: 12px; top: 14px; display: inline-flex; align-items: center; gap: 4px; font: 650 12px var(--font); color: var(--ac);
    opacity: 0; transform: translateX(-4px); transition: opacity var(--t-fast), transform var(--t-fast); background: var(--surface-2); padding: 3px 6px; border-radius: 8px; }
  .acc:hover .open { opacity: 1; transform: none; }
  .more { display: grid; gap: 12px; }
  .resume { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .resume h4 { width: 100%; margin-bottom: 2px; display: flex; align-items: center; gap: 6px; }
  .resume .btn { max-width: 340px; }
  .acts { display: flex; gap: 8px; flex-wrap: wrap; }
  .cardbtn { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--line-2); background: var(--surface-2);
    color: var(--text); font: 13px var(--font); cursor: pointer; text-align: left; min-width: 230px; transition: transform var(--t-fast), border-color var(--t-fast); }
  .cardbtn:hover { border-color: var(--accent); transform: translateY(-2px); }
  .cardbtn span { display: grid; }
  .cardbtn.accent { border-style: dashed; color: var(--accent); }
  .keys { margin: 0; }
  .grow { flex: 1; }
  @media (prefers-reduced-motion: reduce) { .acc, .orb span, .pill.pulse, .state .dot.live { animation: none; } }
</style>
