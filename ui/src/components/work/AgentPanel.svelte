<script lang="ts">
  // Painel da direita: o agente selecionado (estado, modelo, contexto, custo, o que ele fez), a tarefa (branch, o que
  // mudou, PR) e os limites das contas de IA com a contagem para o reset.
  import { ChevronDown, ExternalLink, GitBranch, GitCommitHorizontal, GitCompareArrows, MessageSquareShare, GitPullRequestCreate, Send, Trash2 } from "@lucide/svelte";
  import { get, post } from "../../lib/api";
  import { repos } from "../../lib/repos.svelte";
  import { go } from "../../lib/router.svelte";
  import type { AiAccount, Project, Task, TermInfo } from "../../lib/work.svelte";
  import { STATUS, work } from "../../lib/work.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { kbd } from "../../lib/keys";
  import AgentIcon from "./AgentIcon.svelte";
  import { typeInto } from "./Terminal.svelte";

  let { project, task = null, term = null, onremoved, onreview }:
    { project: Project; task?: Task | null; term?: TermInfo | null; onremoved?: () => void; onreview?: () => void } = $props();
  const s = $derived(work.session(term));
  const acc = $derived(work.account(term?.meta.account));
  let prompt = $state("");
  let limitsOpen = $state((() => { try { return localStorage.getItem("codeck.limitsOpen") !== "0"; } catch { return true; } })());
  let diff = $state<any>(null);
  let now = $state(Date.now());

  $effect(() => { const t = setInterval(() => (now = Date.now()), 30000); return () => clearInterval(t); });
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

  function until(iso: string | null) {
    if (!iso) return "";
    const ms = new Date(iso).getTime() - now;
    if (ms <= 0) return "resetou";
    const h = Math.floor(ms / 3.6e6), m = Math.round((ms % 3.6e6) / 6e4);
    return h >= 24 ? `reseta em ${Math.floor(h / 24)}d ${h % 24}h` : h ? `reseta em ${h}h${String(m).padStart(2, "0")}` : `reseta em ${m} min`;
  }
  const tone = (p: number | null | undefined) => (p == null ? "" : p >= 90 ? "bad" : p >= 70 ? "warn" : "good");
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
  const accounts = $derived.by(() => {
    const used = new Set(work.agents.filter(a => a.project.id === project.id).map(a => a.term.meta.account));
    const list = work.ai.filter(a => a.installed && (used.has(a.id) || a.usage?.rateLimits?.length));
    return list.length ? list : work.ai.filter(a => a.installed).slice(0, 4);
  });
</script>

<div class="panel">
  {#if term?.kind === "agent"}
    <section>
      <div class="who"><AgentIcon provider={term.meta.provider} size={22} />
        <div class="grow"><b>{acc?.name || "agente"}</b><span class="tiny muted ell">{acc?.label}{acc?.email ? " · " + acc.email : ""}</span></div>
        {#if s}<span class="pill {STATUS[s.status]?.[1]}" class:pulse={s.status === "working"}>{STATUS[s.status]?.[0] || s.status}</span>{/if}
      </div>
      {#if s?.status === "starting" && Date.now() / 1000 - s.started > 8}
        <div class="hint small">Aguardando no terminal — se o agente perguntou se você confia na pasta, responda lá.</div>
      {/if}
      <div class="kv"><span>Modelo</span><b>{s?.model || "—"}</b></div>
      <div class="ctx">
        <div class="kv"><span>Contexto</span><b>{s?.context?.used != null ? `${Math.round(s.context.used)}%` : "—"}{#if s?.context?.size}<span class="muted"> de {s.context.size >= 1e6 ? `${s.context.size / 1e6}M` : `${Math.round(s.context.size / 1000)}k`}</span>{/if}</b></div>
        <div class="bar"><span class={tone(s?.context?.used)} style="width:{Math.min(100, s?.context?.used || 0)}%"></span></div>
        {#if (s?.context?.used || 0) >= 80}<div class="hint small warn">Contexto quase cheio — peça para compactar (/compact) ou abra uma sessão nova com um resumo.</div>{/if}
      </div>
      {#if s?.cost != null}<div class="kv"><span>Custo da sessão</span><b>US$ {s.cost.toFixed(2)}</b></div>{/if}
      {#if s?.events?.length}
        <div class="events">{#each s.events.slice(-5).reverse() as ev, i (i)}<div class="ev"><span class="dot"></span>{({ UserPromptSubmit: "prompt recebido", Stop: "terminou", Notification: ev.message || "pediu atenção", SessionStart: "sessão aberta", PreCompact: "compactando", SubagentStop: "subagente terminou" } as Record<string, string>)[ev.event] || ev.event}<span class="tiny muted">{new Date(ev.at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span></div>{/each}</div>
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
      <div class="kv"><span>Branch</span><b class="mono ell"><GitBranch size={11} /> {task.branch}</b></div>
      <div class="kv"><span>Base</span><b class="mono ell">{task.base}</b></div>
      {#each (task as any).linked || [] as x (x.repoId)}
        <div class="kv"><span>Também em</span><button class="lnk" onclick={() => go("/repo/" + x.wtRepoId)}>{x.name}</button></div>
      {/each}
      {#if task.workItem}<div class="kv"><span>Work item</span><a class="ell" href={task.workItem.url} target="_blank" rel="noopener">#{task.workItem.number}</a></div>{/if}
      {#if diff}
        <div class="kv"><span>Commits na branch</span><b>{diff.commits}</b></div>
        <div class="kv"><span>Arquivos alterados</span><b>{diff.files.length + diff.status.untracked.length}</b></div>
        {#if diff.status.unstaged.length + diff.status.staged.length + diff.status.untracked.length}<div class="kv"><span>Sem commit</span><span class="pill warn">{diff.status.unstaged.length + diff.status.staged.length + diff.status.untracked.length} arquivo(s)</span></div>{/if}
      {/if}
      <div class="acts">
        {#if (task as any).reviewOf}<button class="btn sm brand" onclick={publishReview}><MessageSquareShare size={13} /> Publicar revisão na PR</button>{/if}
        <button class="btn sm" onclick={() => onreview?.()}><GitCompareArrows size={13} /> Revisar</button>
        <button class="btn sm" onclick={() => go("/repo/" + task!.repoId)}><GitCommitHorizontal size={13} /> Commitar</button>
        {#if diff?.commits}<button class="btn sm brand" onclick={() => { repos.prIntent = task!.repoId; go("/repo/" + task!.repoId); }}><GitPullRequestCreate size={13} /> Criar PR</button>{/if}
        <button class="btn sm ghost" title="Abrir no editor externo" onclick={() => post("open", { id: task!.repoId, target: "editor" }).catch(e => ui.error(e))}><ExternalLink size={13} /></button>
        <button class="btn sm ghost danger-text" title="Remover tarefa (worktree)" onclick={removeTask}><Trash2 size={13} /></button>
      </div>
    </section>
  {/if}

  <section class="limits" class:shut={!limitsOpen}>
    <button class="lh" onclick={() => { limitsOpen = !limitsOpen; try { localStorage.setItem("codeck.limitsOpen", limitsOpen ? "1" : "0"); } catch { /* */ } }} aria-expanded={limitsOpen}>
      <h4>Limites das contas</h4><ChevronDown size={13} class="chev {limitsOpen ? '' : 'rot'}" /></button>
    {#if limitsOpen}
    {#each accounts as a (a.id)}
      <div class="lim">
        <div class="who sm"><AgentIcon provider={a.provider} size={15} /><b class="grow ell">{a.name}</b><span class="tiny muted">{a.label}</span></div>
        {#if a.usage?.rateLimits?.length}
          {#each a.usage.rateLimits as w (w.window)}
            <div class="win"><span class="tiny">{w.window}</span><div class="bar"><span class={tone(w.used)} style="width:{Math.min(100, w.used || 0)}%"></span></div>
              <span class="tiny num">{w.used != null ? Math.round(w.used) + "%" : "—"}</span></div>
            {#if w.resetsAt}<div class="tiny muted reset">{until(w.resetsAt)}</div>{/if}
          {/each}
          <div class="tiny muted reset">lido {new Date(a.usage.updated).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</div>
        {:else}
          {#if a.provider === "claude"}
            <button class="tiny readlim" disabled={!!work.probing[a.id]} onclick={() => work.probe(a.id)}>{work.probing[a.id] ? "lendo o limite…" : work.activity[a.id]?.probeError ? work.activity[a.id]!.probeError!.error : "limite não lido — ler agora"}</button>
          {:else}<div class="tiny muted">{a.telemetry ? "aparece depois da 1ª resposta do agente" : "esta CLI não informa limites"}</div>{/if}
        {/if}
      </div>
    {:else}<div class="small muted">Nenhuma conta de IA. Configure em Contas e ajustes → IA.</div>{/each}
    {/if}
  </section>
</div>

<style>
  .readlim { border: 0; background: none; padding: 0; color: var(--accent); cursor: pointer; text-align: left; font-family: var(--font); }
  .readlim:disabled { color: var(--muted); cursor: default; }
  .panel { display: flex; flex-direction: column; gap: 14px; padding: 12px; overflow-y: auto; overflow-x: hidden; height: 100%; }
  section { min-width: 0; }
  section { display: grid; gap: 8px; padding-bottom: 14px; border-bottom: 1px solid var(--line); animation: rise 0.25s var(--ease-out); }
  section:last-child { border-bottom: 0; }
  h4 { margin: 0; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
  .who { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .who .grow { display: grid; min-width: 0; flex: 1; }
  .who.sm { gap: 8px; }
  .ttl { font-weight: 600; }
  .kv { display: flex; justify-content: space-between; gap: 10px; font-size: 12.5px; align-items: center; }
  .kv span:first-child { color: var(--muted); white-space: nowrap; }
  .kv b { font-weight: 600; min-width: 0; display: inline-flex; align-items: center; gap: 4px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .kv b.mono { display: block; }
  .bar { height: 6px; border-radius: 99px; background: var(--surface-3); overflow: hidden; flex: 1; }
  .bar span { display: block; height: 100%; border-radius: 99px; background: var(--accent); transition: width 0.6s var(--ease-out); }
  .bar .good { background: var(--good); } .bar .warn { background: var(--warn); } .bar .bad { background: var(--bad); }
  .ctx { display: grid; gap: 6px; }
  .hint { padding: 7px 9px; border-radius: 8px; background: var(--info-soft); color: var(--text-2); }
  .hint.warn { background: var(--warn-soft); }
  .pulse { animation: breathe 1.4s var(--ease) infinite; }
  @keyframes breathe { 50% { opacity: 0.55; } }
  .events { display: grid; gap: 4px; }
  .ev { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text-2); }
  .ev .tiny { margin-left: auto; }
  .ev .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); flex: none; }
  .send { display: grid; gap: 6px; justify-items: end; }
  .send textarea { width: 100%; resize: vertical; font: 12.5px/1.45 var(--font); padding: 7px 9px; height: auto; }
  .acts { display: flex; flex-wrap: wrap; gap: 6px; }
  .danger-text { color: var(--bad); }
  .lim { display: grid; gap: 5px; }
  .win { display: flex; align-items: center; gap: 8px; }
  .win .tiny:first-child { width: 58px; color: var(--text-2); }
  .num { width: 34px; text-align: right; font-variant-numeric: tabular-nums; }
  .reset { padding-left: 66px; margin-top: -3px; }
  a { color: var(--accent); }
  .lh { display: flex; align-items: center; justify-content: space-between; width: 100%; border: 0; background: none; padding: 0; cursor: pointer; color: var(--muted); }
  .lh :global(.chev) { transition: transform var(--t); }
  .lh :global(.chev.rot) { transform: rotate(-90deg); }
  .limits.shut { padding-bottom: 0; }
  .lnk { border: 0; background: none; color: var(--accent); font: 600 12.5px var(--font); cursor: pointer; padding: 0; }
</style>
