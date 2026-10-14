<script lang="ts">
  // Painel da direita: o agente selecionado (estado, modelo, contexto num medidor, custo, o que ele fez), a tarefa
  // (branch, o que mudou, PR) e os limites das contas de IA — a conta do agente aberto em destaque, com a contagem
  // para o reset andando.
  import { ChevronDown, ExternalLink, GitBranch, GitCommitHorizontal, GitCompareArrows, MessageSquareShare, GitPullRequestCreate, Send, Trash2 } from "@lucide/svelte";
  import { get, post } from "../../lib/api";
  import { repos } from "../../lib/repos.svelte";
  import { go } from "../../lib/router.svelte";
  import type { AiAccount, Project, Task, TermInfo } from "../../lib/work.svelte";
  import { STATUS, work } from "../../lib/work.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { kbd } from "../../lib/keys";
  import { typeInto } from "./Terminal.svelte";
  import AccountAvatar from "../ai/AccountAvatar.svelte";
  import LimitRing from "../ai/LimitRing.svelte";
  import { binding, clock, effUsed, resetLabel, stateRank, tone } from "../ai/limits.svelte";

  let { project, task = null, term = null, onremoved, onreview }:
    { project: Project; task?: Task | null; term?: TermInfo | null; onremoved?: () => void; onreview?: () => void } = $props();
  const s = $derived(work.session(term));
  const acc = $derived(work.account(term?.meta.account));
  let prompt = $state("");
  let limitsOpen = $state((() => { try { return localStorage.getItem("codeck.limitsOpen") !== "0"; } catch { return true; } })());
  let diff = $state<any>(null);
  const now = $derived(clock.now);

  // agente terminou: os limites da conta acabaram de chegar pela linha de status — relê sem esperar o ciclo de 30 s
  $effect(() => { if (s?.status === "done" || s?.status === "needs-you") setTimeout(() => work.loadAi(), 1500); });
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

  function send() {
    if (!term || !prompt.trim()) return;
    typeInto(term.id, prompt.trim() + "\r");
    prompt = "";
    ui.toast("Prompt enviado ao agente");
  }
  /** Revisão feita pelo agente → comentário na PR (você confere e edita o texto antes). */
  async function publishReview() {
    const ag = term?.kind === "agent" ? term : task?.terms.find(x => x.kind === "agent") || null;
    if (!ag?.meta.sid || !task) return ui.toast("Nenhum agente nesta tarefa", "info");
    let text = "";
    try { text = (await get<{ text: string }>("ws/agent/last", { sid: ag.meta.sid })).text; } catch (e) { return ui.error(e); }
    const final = await ui.ask({ title: `Publicar na PR #${(task as any).reviewOf.prId}`, input: { label: "Comentário (confira antes de publicar)", value: text, multiline: true, required: true }, confirm: "Publicar" });
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
  // contas: a do agente aberto primeiro, depois as que trabalham neste projeto, depois quem está ativo
  const accounts = $derived.by(() => {
    const used = new Set(work.agents.filter(a => a.project.id === project.id).map(a => a.term.meta.account));
    let list = work.ai.filter(a => a.installed && (used.has(a.id) || a.usage?.rateLimits?.length || a.id === acc?.id));
    if (!list.length) list = work.ai.filter(a => a.installed).slice(0, 4);
    const r = (a: AiAccount) => (a.id === acc?.id ? -2 : used.has(a.id) ? -1 : 0);
    return [...list].sort((x, y) => r(x) - r(y) || stateRank(work.activity[x.id]?.state) - stateRank(work.activity[y.id]?.state));
  });
  const EV: Record<string, string> = { UserPromptSubmit: "prompt recebido", Stop: "terminou", SessionStart: "sessão aberta", PreCompact: "compactando", SubagentStop: "subagente terminou" };
  const ctxSize = (n: number) => (n >= 1e6 ? `${n / 1e6}M` : `${Math.round(n / 1000)}k`);
  const uncommitted = $derived(diff ? diff.status.unstaged.length + diff.status.staged.length + diff.status.untracked.length : 0);
</script>

<div class="panel">
  {#if term?.kind === "agent"}
    <section class="agent" class:working={s?.status === "working"} class:need={s?.status === "needs-you"}>
      <div class="who">
        {#if acc}<AccountAvatar a={acc} state={s?.status === "working" ? "working" : s?.status === "needs-you" ? "needs-you" : s?.status === "done" ? "done" : null} size={34} />{/if}
        <div class="grow"><b class="ell">{acc?.name || "agente"}</b><span class="tiny muted ell">{acc?.label}{acc?.email ? " · " + acc.email : ""}</span></div>
      </div>
      {#if s}<div class="stl {STATUS[s.status]?.[1]}"><i class:pulse={s.status === "working" || s.status === "needs-you"}></i>{STATUS[s.status]?.[0] || s.status}
        {#if s.status === "needs-you"}<span class="tiny">— responda no terminal</span>{/if}</div>{/if}
      {#if s?.status === "starting" && Date.now() / 1000 - s.started > 8}
        <div class="hint small">Aguardando no terminal — se o agente perguntou se você confia na pasta, responda lá.</div>
      {/if}
      <div class="ctxrow">
        <LimitRing used={s?.context?.used ?? null} size={68} label="contexto" binding={(s?.context?.used || 0) >= 80} />
        <div class="kvs">
          <div class="kv"><span>Modelo</span><b class="ell">{s?.model || "—"}</b></div>
          <div class="kv"><span>Janela</span><b>{s?.context?.size ? ctxSize(s.context.size) : "—"}</b></div>
          <div class="kv"><span>Custo</span><b>{s?.cost != null ? `US$ ${s.cost.toFixed(2)}` : "—"}</b></div>
        </div>
      </div>
      {#if (s?.context?.used || 0) >= 80}<div class="hint small warn">Contexto quase cheio — peça para compactar (/compact) ou abra uma sessão nova com um resumo.</div>{/if}
      {#if s?.events?.length}
        <ol class="events">{#each s.events.slice(-5).reverse() as ev, i (i)}<li style="--i:{i}"><span class="dot"></span><span class="ell">{EV[ev.event] || (ev.event === "Notification" ? ev.message || "pediu atenção" : ev.event)}</span><span class="tiny muted">{new Date(ev.at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span></li>{/each}</ol>
      {/if}
      <div class="send">
        <textarea class="input" rows="3" bind:value={prompt} placeholder="Mandar um prompt para este agente…" onkeydown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send(); }}></textarea>
        <button class="btn sm primary" disabled={!prompt.trim()} onclick={send}><Send size={13} /> Enviar <span class="kbd">{kbd("mod+enter")}</span></button>
      </div>
    </section>
  {/if}

  {#if task}
    <section>
      <h4>Tarefa</h4>
      <div class="ttl">{task.title}</div>
      <div class="brs"><span class="br mono ell" title={task.branch}><GitBranch size={11} /> {task.branch}</span><span class="tiny muted">de</span><span class="br base mono ell" title={task.base}>{task.base}</span></div>
      {#if diff}
        <div class="nums">
          <div><b>{diff.commits}</b><span>commit{diff.commits === 1 ? "" : "s"}</span></div>
          <div><b>{diff.files.length + diff.status.untracked.length}</b><span>arquivos</span></div>
          <div class:warn={uncommitted}><b>{uncommitted}</b><span>sem commit</span></div>
        </div>
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
        <button class="btn sm ghost icon" title="Abrir no editor externo" onclick={() => post("open", { id: task!.repoId, target: "editor" }).catch(e => ui.error(e))}><ExternalLink size={13} /></button>
        <button class="btn sm ghost icon danger-text" title="Remover tarefa (worktree)" onclick={removeTask}><Trash2 size={13} /></button>
      </div>
    </section>
  {/if}

  <section class="limits" class:shut={!limitsOpen}>
    <button class="lh" onclick={() => { limitsOpen = !limitsOpen; try { localStorage.setItem("codeck.limitsOpen", limitsOpen ? "1" : "0"); } catch { /* */ } }} aria-expanded={limitsOpen}>
      <h4>Limites das contas</h4><ChevronDown size={13} class="chev {limitsOpen ? '' : 'rot'}" /></button>
    {#if limitsOpen}
    {#each accounts as a (a.id)}
      {@const ws = a.usage?.rateLimits || []}
      {@const b = binding(ws, now)}
      {@const st = work.activity[a.id]?.state}
      <div class="lim" class:cur={a.id === acc?.id}>
        <AccountAvatar {a} state={st === "working" || st === "needs-you" ? st : null} size={26} />
        <div class="lt">
          <b class="ell">{a.name}{#if a.id === acc?.id}<span class="this">este agente</span>{/if}</b>
          {#if ws.length && b}
            <span class="tiny cd {tone(effUsed(b, now))}" title="A janela mais gasta e quando ela reseta">{b.window} · {resetLabel(b.resetsAt, now)}</span>
          {:else if a.provider === "claude"}
            <button class="tiny readlim" disabled={!!work.probing[a.id]} onclick={() => work.probe(a.id)}>{work.probing[a.id] ? "lendo o limite…" : work.activity[a.id]?.probeError ? work.activity[a.id]!.probeError!.error : "limite não lido — ler agora"}</button>
          {:else}<span class="tiny muted">{a.telemetry ? "aparece após a 1ª resposta" : "esta CLI não informa limites"}</span>{/if}
        </div>
        {#if ws.length === 1}<div class="mw"></div>{/if}
        {#each ws as w (w.window)}
          <div class="mw" title={`${w.window}: ${Math.round(effUsed(w, now))}% · ${resetLabel(w.resetsAt, now)}`}>
            <LimitRing used={effUsed(w, now)} size={34} binding={ws.length > 1 && b?.window === w.window && effUsed(w, now) > 0} />
            <span>{w.window === "semanal" ? "sem." : w.window}</span>
          </div>
        {/each}
      </div>
    {:else}<div class="small muted">Nenhuma conta de IA. Configure em Contas e ajustes → IA.</div>{/each}
    {/if}
  </section>
</div>

<style>
  .readlim { border: 0; background: none; padding: 0; color: var(--accent); cursor: pointer; text-align: left; font-family: var(--font); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .readlim:disabled { color: var(--muted); cursor: default; }
  .panel { display: flex; flex-direction: column; gap: 14px; padding: 12px; overflow-y: auto; overflow-x: hidden; height: 100%; }
  section { min-width: 0; display: grid; gap: 10px; padding-bottom: 14px; border-bottom: 1px solid var(--line); animation: rise 0.25s var(--ease-out); }
  section:last-child { border-bottom: 0; }
  h4 { margin: 0; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
  .agent { padding: 12px; margin: -2px -2px 0; border: 1px solid var(--line); border-radius: 14px; background: var(--surface-2); transition: border-color var(--t), box-shadow var(--t); }
  .agent.working { border-color: var(--accent-line); box-shadow: 0 8px 26px -14px color-mix(in srgb, var(--accent) 60%, transparent); }
  .agent.need { border-color: color-mix(in srgb, var(--warn) 50%, transparent); }
  .who { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .who .grow { display: grid; min-width: 0; flex: 1; line-height: 1.35; }
  .who b { font-weight: 650; }
  .stl { --c: var(--muted); display: flex; align-items: center; gap: 7px; padding: 6px 9px; border-radius: 9px; font: 600 12px var(--font); color: var(--c);
    background: color-mix(in srgb, var(--c) 11%, transparent); }
  .stl i { width: 7px; height: 7px; border-radius: 50%; background: var(--c); flex: none; }
  .stl .tiny { font-weight: 500; color: var(--text-2); }
  .stl.accent { --c: var(--accent); } .stl.good { --c: var(--good); } .stl.warn { --c: var(--warn); } .stl.info { --c: var(--info); }
  .pulse { animation: ping 1.3s var(--ease) infinite; }
  @keyframes ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--c) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 6px transparent; } }
  .ctxrow { display: flex; align-items: center; gap: 12px; min-width: 0; }
  .kvs { display: grid; gap: 4px; flex: 1; min-width: 0; }
  .ttl { font-weight: 600; }
  .kv { display: flex; justify-content: space-between; gap: 10px; font-size: 12.5px; align-items: center; min-width: 0; }
  .kv span:first-child { color: var(--muted); white-space: nowrap; }
  .kv b { font-weight: 600; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .hint { padding: 7px 9px; border-radius: 8px; background: var(--info-soft); color: var(--text-2); }
  .hint.warn { background: var(--warn-soft); }
  .events { list-style: none; margin: 0; padding: 0 0 0 3px; display: grid; gap: 0; }
  .events li { position: relative; display: flex; align-items: center; gap: 8px; padding: 3px 0 3px 12px; font-size: 12px; color: var(--text-2); min-width: 0;
    animation: rise 0.3s var(--ease-out) both; animation-delay: calc(var(--i) * 40ms); }
  .events li::before { content: ""; position: absolute; left: 2px; top: 0; bottom: 0; width: 1px; background: var(--line-2); }
  .events li:first-child::before { top: 50%; } .events li:last-child::before { bottom: 50%; }
  .events .dot { position: absolute; left: -1px; width: 7px; height: 7px; border-radius: 50%; background: var(--surface-3); box-shadow: inset 0 0 0 1.5px var(--line-3); }
  .events li:first-child .dot { background: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .events li:first-child { color: var(--text); }
  .events .ell { flex: 1; }
  .send { display: grid; gap: 6px; justify-items: end; }
  .send textarea { width: 100%; resize: vertical; font: 12.5px/1.45 var(--font); padding: 7px 9px; height: auto; }
  .brs { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .br { display: inline-flex; align-items: center; gap: 4px; max-width: 70%; height: 22px; padding: 0 8px; border-radius: 6px; background: var(--accent-soft); color: var(--accent); font-size: 11.5px; }
  .br.base { background: var(--surface-2); color: var(--text-2); max-width: 40%; }
  .nums { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
  .nums > div { display: grid; gap: 1px; padding: 7px 9px; border-radius: 9px; background: var(--surface-2); border: 1px solid var(--line); min-width: 0; }
  .nums b { font: 680 17px/1.15 var(--font); font-variant-numeric: tabular-nums; }
  .nums span { font-size: 10.5px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .nums .warn { border-color: color-mix(in srgb, var(--warn) 35%, transparent); background: var(--warn-soft); }
  .nums .warn b { color: var(--warn); }
  .acts { display: flex; flex-wrap: wrap; gap: 6px; }
  .danger-text { color: var(--bad); }
  .lim { display: flex; align-items: center; gap: 9px; padding: 7px 8px; margin: 0 -8px; border-radius: 10px; min-width: 0; transition: background var(--t); }
  .lim:hover { background: var(--surface-2); }
  .lim.cur { background: var(--accent-soft); box-shadow: inset 0 0 0 1px var(--accent-line); }
  .lt { display: grid; min-width: 0; flex: 1; line-height: 1.35; }
  .lt b { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 12.5px; min-width: 0; }
  .this { font: 650 9.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.04em; color: var(--accent); flex: none; }
  .cd { font-variant-numeric: tabular-nums; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .cd.warn { color: var(--warn); } .cd.bad { color: var(--bad); }
  .mw { display: grid; justify-items: center; gap: 1px; flex: none; min-width: 34px; }
  .mw span { font-size: 9.5px; color: var(--muted); line-height: 1; }
  a { color: var(--accent); }
  .lh { display: flex; align-items: center; justify-content: space-between; width: 100%; border: 0; background: none; padding: 0; cursor: pointer; color: var(--muted); }
  .lh :global(.chev) { transition: transform var(--t); }
  .lh :global(.chev.rot) { transform: rotate(-90deg); }
  .limits { gap: 4px; }
  .limits .lh { margin-bottom: 6px; }
  .limits.shut { padding-bottom: 0; }
  .lnk { border: 0; background: none; color: var(--accent); font: 600 12.5px var(--font); cursor: pointer; padding: 0; }
  @media (prefers-reduced-motion: reduce) { .pulse, .events li { animation: none; } }
</style>
