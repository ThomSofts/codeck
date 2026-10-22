<script lang="ts">
  // Agente parado pelo limite da conta (5 h, semanal, cota diária…): um cartão por cima do terminal com a contagem para
  // o reset e as outras contas para CONTINUAR o trabalho — o Codeck abre um terminal novo na conta escolhida, no mesmo
  // checkout/tarefa, e o agente já começa de onde o anterior parou. Funciona entre quaisquer CLIs (Claude → Claude,
  // Claude → Cursor, Codex → Gemini…).
  //   · Resumo enxuto (padrão): pedido original + últimos passos + estado do git; o histórico completo fica num arquivo
  //     que o agente só lê se precisar — gasta poucos tokens para recomeçar.
  //   · Conversa inteira (só na mesma CLI, Claude/Codex): a conversa é copiada para a conta nova e retomada.
  // Também abre pelo painel do agente ("Continuar em outra conta"), sem esperar o limite.
  import { ArrowRight, ChevronDown, Hourglass, Minimize2, Sparkles, X } from "@lucide/svelte";
  import type { TermInfo } from "../../lib/work.svelte";
  import { work } from "../../lib/work.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { go } from "../../lib/router.svelte";
  import AccountAvatar from "../ai/AccountAvatar.svelte";
  import { ACC_STATE, clock, countdown, rank, type Rec } from "../ai/limits.svelte";

  let { term, manual = false, onstarted, onclose }: {
    term: TermInfo;
    /** aberto pelo painel (sem limite): o cartão some ao fechar */
    manual?: boolean;
    onstarted?: (r: { projectId: string; taskId: string | null; termId: string }) => void;
    onclose?: () => void;
  } = $props();

  const LS = (k: string, d: string) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
  const s = $derived(work.session(term));
  const lim = $derived(s?.limit || null);
  const acc = $derived(work.account(term.meta.account));
  const done = $derived(s?.handedOff || null);
  const doneAcc = $derived(done ? work.account(done.account) : null);
  const show = $derived(manual || !!lim);

  let small = $state(false);
  let busy = $state<string | null>(null);
  let more = $state(false);
  let full = $state(LS("codeck.handoff.full", "0") === "1");
  const setFull = (v: boolean) => { full = v; try { localStorage.setItem("codeck.handoff.full", v ? "1" : "0"); } catch { /* sem armazenamento */ } };

  const now = $derived(clock.now);
  const left = $derived(lim?.resetsAt ? countdown(lim.resetsAt, now) : "");
  const at = $derived(lim?.resetsAt ? new Date(lim.resetsAt) : null);
  const atLabel = $derived(!at ? "" : at.toDateString() === new Date(now).toDateString()
    ? `hoje às ${at.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`
    : at.toLocaleString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }));
  // progresso da espera (anel): do momento em que parou até o reset
  const waitPct = $derived.by(() => {
    if (!lim?.resetsAt) return 0;
    const a = new Date(lim.at).getTime(), b = new Date(lim.resetsAt).getTime();
    return b > a ? Math.min(1, Math.max(0, (now - a) / (b - a))) : 1;
  });

  // candidatas: todas as contas instaladas menos a desta sessão, da mais livre para a mais apertada
  const ranked = $derived(rank(work.ai.filter(a => a.installed && a.id !== term.meta.account), now));
  const best = $derived(ranked.find(r => !r.blocked && r.free != null) || ranked.find(r => !r.blocked) || null);
  const shown = $derived(more ? ranked : ranked.slice(0, 5));
  const sameCli = (r: Rec) => r.a.provider === term.meta.provider && (r.a.provider === "claude" || r.a.provider === "codex");
  const anySame = $derived(ranked.some(sameCli));
  const busyOf = (id: string) => { const st = work.activity[id]?.state; return st && st !== "free" ? ACC_STATE[st]?.[0] : null; };

  async function go_(r: Rec) {
    if (busy) return;
    busy = r.a.id;
    const prog = ui.progress(`Passando o trabalho para ${r.a.name}…`);
    try {
      const t = await work.handoff(term.id, r.a.id, sameCli(r) && full ? "resume" : "brief");
      prog.done(t.mode === "resume" ? `${r.a.name} retomou a conversa` : `${r.a.name} continua com um resumo enxuto`);
      onstarted?.({ projectId: term.meta.project!, taskId: term.meta.task || null, termId: t.id });
      onclose?.();
    } catch (e) { prog.fail(e); }
    finally { busy = null; }
  }
  async function wait() {
    if (manual) return onclose?.();
    if (s && term.meta.sid) await work.dismissLimit(term.meta.sid).catch(e => ui.error(e));
  }
  const openNew = () => done && onstarted?.({ projectId: term.meta.project!, taskId: term.meta.task || null, termId: done.termId });
</script>

{#if show}
  {#if small && !manual}
    <button class="pillmin" onclick={() => (small = false)} title="Abrir as opções de continuação">
      <Hourglass size={13} /><span>No limite{left ? ` · ${left === "resetou" ? "resetou" : "reseta em " + left}` : ""}</span>
      {#if !done && ranked.length}<b>Trocar de conta</b>{:else if done}<b>Continuado em {doneAcc?.name}</b>{/if}
    </button>
  {:else}
    <div class="veil" aria-hidden="true"></div>
    <div class="card" role="dialog" aria-label="Continuar em outra conta">
      <header>
        {#if lim}
          <div class="ring" style="--p:{waitPct}">
            <svg viewBox="0 0 44 44" aria-hidden="true"><circle class="trk" cx="22" cy="22" r="19" /><circle class="val" cx="22" cy="22" r="19" pathLength="1" /></svg>
            <Hourglass size={18} />
          </div>
        {:else}
          <div class="ring calm"><Sparkles size={18} /></div>
        {/if}
        <div class="hd">
          <h3>{lim ? `${acc?.name || "A conta"} atingiu o limite` : "Continuar em outra conta"}</h3>
          {#if lim}
            <p class="sub">
              {#if left === "resetou"}O limite já resetou — dá para seguir nesta conta.
              {:else if left}Reseta em <b class="cd">{left}</b> <span class="muted">· {atLabel}{lim.window ? ` · janela ${lim.window}` : ""}</span>
              {:else}<span class="muted">Horário do reset não informado pela CLI</span>{/if}
            </p>
            {#if lim.text}<p class="why ell" title={lim.text}>{lim.text}</p>{/if}
          {:else}
            <p class="sub muted">O agente novo começa de onde este está, no mesmo checkout.</p>
          {/if}
        </div>
        {#if !manual}<button class="ic" title="Minimizar (ver o terminal)" aria-label="Minimizar" onclick={() => (small = true)}><Minimize2 size={14} /></button>{/if}
        {#if manual}<button class="ic" title="Fechar" aria-label="Fechar" onclick={() => onclose?.()}><X size={14} /></button>{/if}
      </header>

      {#if done}
        <div class="done">
          {#if doneAcc}<AccountAvatar a={doneAcc} size={26} state="working" />{/if}
          <span class="grow">Continuado em <b>{doneAcc?.name || "outra conta"}</b> · {done.mode === "resume" ? "conversa inteira" : "resumo enxuto"}</span>
          <button class="btn sm primary" onclick={openNew}>Ir para a sessão <ArrowRight size={13} /></button>
        </div>
      {:else if ranked.length}
        <div class="lh">
          <span>Continuar em</span>
          {#if anySame}
            <div class="seg" role="radiogroup" aria-label="Como passar o contexto (mesma CLI)">
              <button role="radio" aria-checked={!full} class:on={!full} onclick={() => setFull(false)} title="Pedido original, últimos passos e estado do git; o histórico completo fica num arquivo que o agente só lê se precisar">Resumo enxuto <small>menos tokens</small></button>
              <button role="radio" aria-checked={full} class:on={full} onclick={() => setFull(true)} title="Mesma CLI (Claude/Codex): copia a conversa para a conta nova e retoma com o contexto inteiro">Conversa inteira</button>
            </div>
          {/if}
        </div>
        <ul class="accs">
          {#each shown as r, i (r.a.id)}
            {@const b = busyOf(r.a.id)}
            <li style="--i:{i}">
              <button class="acc" class:best={r.a.id === best?.a.id} class:blocked={r.blocked} disabled={!!busy} onclick={() => go_(r)}>
                <AccountAvatar a={r.a} size={30} state={b === ACC_STATE.working[0] ? "working" : null} />
                <span class="who">
                  <b class="ell">{r.a.name}{#if r.a.id === best?.a.id}<span class="tag">recomendada</span>{/if}</b>
                  <span class="tiny muted ell">{r.a.label}{sameCli(r) ? (full ? " · retoma a conversa" : " · resumo enxuto") : " · resumo enxuto"}{b ? ` · ${b}` : ""} — {r.why}</span>
                </span>
                {#if r.free != null}
                  <span class="free {r.tone}"><span class="bar"><i style="width:{r.free}%"></i></span>{Math.round(r.free)}%</span>
                {/if}
                <span class="goar">{#if busy === r.a.id}<i class="spin"></i>{:else}<ArrowRight size={15} />{/if}</span>
              </button>
            </li>
          {/each}
        </ul>
        {#if ranked.length > 5}
          <button class="lnk" onclick={() => (more = !more)}>{more ? "Menos contas" : `Mais ${ranked.length - 5} conta(s)`} <ChevronDown size={12} class={more ? "rot" : ""} /></button>
        {/if}
      {:else}
        <p class="none">Nenhuma outra conta de IA configurada. <button class="lnk" onclick={() => go("/settings/ai")}>Adicionar contas</button> — com mais de uma, o trabalho continua na outra quando uma acabar.</p>
      {/if}

      {#if !done}
        <footer>
          <span class="tiny muted">O agente atual fica aberto; o novo abre ao lado, já trabalhando.</span>
          <button class="btn sm ghost" onclick={wait}>{manual ? "Cancelar" : "Esperar o reset"}</button>
        </footer>
      {/if}
    </div>
  {/if}
{/if}

<style>
  .veil { position: absolute; inset: 0; z-index: 6; pointer-events: none;
    background: linear-gradient(to top, color-mix(in srgb, var(--surface) 88%, transparent) 0%, color-mix(in srgb, var(--surface) 35%, transparent) 55%, transparent 100%);
    animation: fade 0.3s var(--ease-out); }
  .card { position: absolute; left: 50%; bottom: 18px; z-index: 7; width: min(560px, calc(100% - 32px)); max-height: calc(100% - 36px); overflow: auto;
    transform: translateX(-50%); display: grid; gap: 12px; padding: 16px; border-radius: 14px; border: 1px solid var(--line-2);
    background: color-mix(in srgb, var(--surface-2) 92%, transparent); backdrop-filter: blur(14px) saturate(1.2);
    box-shadow: 0 24px 60px -18px rgb(0 0 0 / 0.45), 0 0 0 1px color-mix(in srgb, var(--bad) 10%, transparent);
    animation: rise-in 0.35s var(--ease-out) both; }
  header { display: flex; align-items: flex-start; gap: 12px; min-width: 0; }
  .ring { position: relative; display: grid; place-items: center; width: 44px; height: 44px; flex: none; color: var(--bad); border-radius: 50%;
    background: var(--bad-soft); }
  .ring.calm { color: var(--accent); background: var(--accent-soft); }
  .ring svg { position: absolute; inset: 0; transform: rotate(-90deg); }
  .ring circle { fill: none; stroke-width: 2.5; }
  .ring .trk { stroke: color-mix(in srgb, var(--bad) 18%, transparent); }
  .ring .val { stroke: var(--bad); stroke-linecap: round; stroke-dasharray: 1; stroke-dashoffset: calc(1 - var(--p)); transition: stroke-dashoffset 1s linear; }
  .ring :global(svg.lucide) { animation: tilt 2.4s var(--ease) infinite; }
  .hd { flex: 1; min-width: 0; display: grid; gap: 3px; }
  h3 { margin: 0; font: 650 15px/1.25 var(--font); letter-spacing: -0.01em; }
  .sub { margin: 0; font-size: 13px; color: var(--text-2); }
  .cd { font: 700 15px/1 var(--font); font-variant-numeric: tabular-nums; color: var(--text); letter-spacing: -0.01em; }
  .why { margin: 0; font: 11.5px/1.4 var(--mono, ui-monospace, monospace); color: var(--muted); }
  .muted { color: var(--muted); }
  .ic { display: grid; place-items: center; width: 26px; height: 26px; border: 0; border-radius: 7px; background: none; color: var(--muted); cursor: pointer; flex: none; }
  .ic:hover { background: var(--surface-3); color: var(--text); }
  .lh { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; font: 600 12px var(--font); color: var(--text-2); }
  .seg { display: inline-flex; padding: 2px; border-radius: 8px; background: var(--surface); border: 1px solid var(--line); }
  .seg button { height: 24px; padding: 0 9px; border: 0; border-radius: 6px; background: none; color: var(--muted); font: 600 11.5px var(--font); cursor: pointer;
    transition: background var(--t-fast), color var(--t-fast); }
  .seg button small { font-weight: 500; opacity: 0.8; }
  .seg button.on { background: var(--surface-3); color: var(--text); box-shadow: 0 1px 2px rgb(0 0 0 / 0.15); }
  .accs { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
  .accs li { animation: rise-in 0.35s var(--ease-out) both; animation-delay: calc(var(--i) * 45ms + 80ms); }
  .acc { display: flex; align-items: center; gap: 11px; width: 100%; padding: 8px 10px; border-radius: 10px; border: 1px solid transparent; background: var(--surface);
    color: var(--text); text-align: left; cursor: pointer; min-width: 0; font: 13px var(--font);
    transition: border-color var(--t-fast), background var(--t-fast), transform var(--t-fast); }
  .acc:hover:not(:disabled) { border-color: var(--accent-line); background: color-mix(in srgb, var(--accent-soft) 60%, var(--surface)); transform: translateY(-1px); }
  .acc:focus-visible { outline: 0; box-shadow: var(--ring); }
  .acc.best { border-color: color-mix(in srgb, var(--good) 35%, transparent); }
  .acc.blocked { opacity: 0.6; }
  .acc:disabled { cursor: progress; }
  .who { display: grid; flex: 1; min-width: 0; line-height: 1.35; }
  .who b { display: flex; align-items: center; gap: 7px; font-weight: 650; min-width: 0; }
  .tag { font: 650 10px/1 var(--font); padding: 3px 6px; border-radius: 99px; color: var(--good); background: var(--good-soft); flex: none; }
  .free { display: inline-flex; align-items: center; gap: 6px; font: 650 12px var(--font); font-variant-numeric: tabular-nums; color: var(--good); flex: none; }
  .free.warn { color: var(--warn); } .free.bad { color: var(--bad); }
  .bar { width: 38px; height: 4px; border-radius: 4px; background: var(--line-2); overflow: hidden; }
  .bar i { display: block; height: 100%; border-radius: 4px; background: currentColor; transition: width 0.6s var(--ease-out); }
  .goar { display: grid; place-items: center; width: 22px; color: var(--muted); flex: none; }
  .acc:hover .goar { color: var(--accent); }
  .spin { width: 14px; height: 14px; border-radius: 50%; border: 2px solid var(--line-2); border-top-color: var(--accent); animation: spin 0.8s linear infinite; }
  .done { display: flex; align-items: center; gap: 10px; padding: 10px; border-radius: 10px; background: var(--good-soft); font-size: 13px; }
  .done b { font-weight: 650; }
  .grow { flex: 1; min-width: 0; }
  .none { margin: 0; font-size: 13px; color: var(--text-2); }
  .lnk { display: inline-flex; align-items: center; gap: 4px; justify-self: start; border: 0; background: none; padding: 0; color: var(--accent); font: 600 12px var(--font); cursor: pointer; }
  .lnk :global(.rot) { transform: rotate(180deg); }
  footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding-top: 10px; border-top: 1px solid var(--line); }
  .pillmin { position: absolute; right: 16px; bottom: 14px; z-index: 7; display: inline-flex; align-items: center; gap: 8px; height: 30px; padding: 0 12px;
    border-radius: 99px; border: 1px solid color-mix(in srgb, var(--bad) 35%, transparent); background: color-mix(in srgb, var(--surface-2) 92%, transparent);
    backdrop-filter: blur(10px); color: var(--bad); font: 600 12px var(--font); cursor: pointer; box-shadow: 0 10px 30px -12px rgb(0 0 0 / 0.4);
    animation: rise-in 0.25s var(--ease-out) both; }
  .pillmin span { color: var(--text-2); font-variant-numeric: tabular-nums; }
  .pillmin b { color: var(--accent); }
  @keyframes rise-in { from { opacity: 0; transform: translate(var(--tx, 0), 10px) scale(0.98); } }
  .card { --tx: -50%; }
  @keyframes fade { from { opacity: 0; } }
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes tilt { 0%, 70%, 100% { transform: rotate(0); } 80% { transform: rotate(180deg); } }
  @media (prefers-reduced-motion: reduce) { .card, .accs li, .pillmin, .veil, .ring :global(svg.lucide) { animation: none; } }
</style>
