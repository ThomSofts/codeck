<script lang="ts">
  // Uma conta de IA por inteiro: os limites (5 h / semanal) em medidores com a contagem para o reset andando, qual
  // janela está segurando a conta, o que ela está fazendo agora (em qual projeto/tarefa, trabalhando ou esperando
  // você), as sessões abertas fora do app e as ações da conta (no "⋯" e no clique direito).
  import { AlertTriangle, ArrowRight, Clock, Copy, LogIn, RefreshCw, Star, Trash2 } from "@lucide/svelte";
  import { ago } from "../../lib/format";
  import { go } from "../../lib/router.svelte";
  import { post } from "../../lib/api";
  import { ui } from "../../lib/ui.svelte";
  import { STATUS, work, type AiAccount } from "../../lib/work.svelte";
  import Menu from "../Menu.svelte";
  import AccountAvatar from "../ai/AccountAvatar.svelte";
  import LimitRing from "../ai/LimitRing.svelte";
  import { ACC_STATE, accColor, binding, clock, effUsed, expired, home, resetLabel, stale } from "../ai/limits.svelte";

  let { a, compact = false, scopes = [], scopeLabel = (s: string) => s, onremove = undefined }:
    { a: AiAccount; compact?: boolean; scopes?: string[]; scopeLabel?: (s: string) => string; onremove?: () => void } = $props();

  const act = $derived(work.activity[a.id]);
  const probing = $derived(!!work.probing[a.id] || !!act?.probing);
  const limits = $derived(a.usage?.rateLimits || []);
  const now = $derived(clock.now);
  const bind = $derived(limits.length > 1 ? binding(limits, now) : null);
  const st = $derived(act ? ACC_STATE[act.state] : null);

  const src = (s?: string) => (s === "probe" ? "leitura direta" : s === "claude" ? "sessão do app" : s === "codex" ? "log do Codex" : s || "");
  const loginCmd = $derived(a.provider === "claude" ? `CLAUDE_CONFIG_DIR=${a.dir} claude` : a.provider === "codex" ? `CODEX_HOME=${a.dir} codex login` : a.provider === "cursor" ? "cursor-agent login" : a.provider);
  async function copy(t: string) { await navigator.clipboard.writeText(t); ui.toast("Comando copiado"); }
  async function login() {
    try { await post("ai/login", { id: a.id }); ui.toast("Terminal aberto — faça o login lá e depois clique em “Ler agora”", "info"); } catch (e) { ui.error(e); }
  }
  async function setDefault(scope: string) { await post("ai/default", { scope, id: a.id }); await work.loadAi(); ui.toast("Conta padrão salva"); }
  function openSession(repoId: string | null) { if (repoId) go("/work/" + repoId); }
  type Ses = { key: string; project: string | null; repoId: string | null; title: string | null; status: string; context: number | null; ext: boolean; cwd?: string };
  const sessions = $derived<Ses[]>([
    ...(act?.sessions || []).map(s => ({ key: s.sid, project: s.project, repoId: s.repoId, title: s.title, status: s.status, context: s.context, ext: false })),
    ...(act?.external || []).map(s => ({ key: "x" + s.session, project: s.project, repoId: s.repoId, title: null, status: s.status, context: null, ext: true, cwd: s.cwd })),
  ].sort((x, y) => rankS(x.status) - rankS(y.status)));
  const rankS = (s: string) => ({ "needs-you": 0, working: 1, done: 2 } as Record<string, number>)[s] ?? 3;
  const waiting = $derived(sessions.find(s => s.status === "needs-you") || null);
  const defaultsOf = $derived(Object.entries(work.defaults).filter(([, id]) => id === a.id).map(([sc]) => sc));
  const items = $derived([
    ...(a.provider === "claude" ? [{ label: "Ler o limite agora", icon: RefreshCw, onclick: () => work.probe(a.id), disabled: probing || !a.installed }] : []),
    { label: "Entrar (login da CLI)", icon: LogIn, onclick: login },
    { label: "Copiar comando de login", icon: Copy, onclick: () => copy(loginCmd) },
    ...(scopes.length ? [{ separator: true }, { heading: "Padrão para…" }, ...scopes.map(sc => ({ label: (defaultsOf.includes(sc) ? "★ " : "") + scopeLabel(sc), icon: Star, onclick: () => setDefault(sc) }))] : []),
    ...(onremove ? [{ separator: true }, { label: "Tirar do app", icon: Trash2, danger: true, onclick: onremove }] : []),
  ]);
  const ring = $derived(compact ? 58 : 70);
</script>

<div class="acc" class:compact class:busy={act?.state === "working"} class:need={act?.state === "needs-you"} style="--ac:{accColor(a)}" data-menu-row>
  <div class="head">
    <AccountAvatar {a} state={act?.state} size={compact ? 34 : 38} />
    <div class="who">
      <b class="ell">{a.name}</b>
      <span class="tiny muted ell" title={a.dir}>{a.email || a.label}{compact ? "" : " · " + home(a.dir)}</span>
    </div>
    {#if st}<span class="st {st[1]}"><i></i>{st[0]}</span>{/if}
    <Menu {items} />
  </div>

  {#if defaultsOf.length && !compact}
    <div class="defs">{#each defaultsOf as sc (sc)}<span class="def" title="Conta padrão para novos agentes"><Star size={10} /> {scopeLabel(sc)}</span>{/each}</div>
  {/if}

  {#if waiting}
    <button class="cta" onclick={() => openSession(waiting.repoId)} disabled={!waiting.repoId}>
      <span class="grow ell">Esperando você em <b>{waiting.project || "uma sessão"}</b></span><span class="go">Ir <ArrowRight size={13} /></span>
    </button>
  {/if}

  {#if act?.probeError}
    <div class="err small"><AlertTriangle size={13} /><span class="grow">{act.probeError.error}</span>
      <button class="btn sm" onclick={login}><LogIn size={12} /> Entrar</button></div>
  {/if}

  <div class="meters">
    {#each limits as w (w.window)}
      {@const used = effUsed(w, now)}
      {@const isBind = bind?.window === w.window && used > 0}
      <div class="m" class:bind={isBind}>
        <LimitRing used={used} size={ring} label={w.window} binding={isBind} />
        <span class="cd" class:fresh={expired(w, now)}>{resetLabel(w.resetsAt, now) || " "}</span>
        {#if isBind}<span class="tag" title="A janela mais perto do fim — é ela que vai parar a conta">limita</span>{/if}
      </div>
    {:else}
      <div class="nolim">
        <div class="emptyring" style="--s:{ring}px"></div>
        <span class="small muted">{#if a.provider === "claude"}{a.installed ? "Limite ainda não lido." : "CLI não encontrada."}{:else if a.provider === "codex"}O limite aparece depois da primeira sessão do Codex.{:else}Esta CLI não informa limite.{/if}</span>
      </div>
    {/each}
    {#if a.provider === "claude"}
      <div class="side">
        <button class="btn sm ghost read" disabled={probing || !a.installed} title="Manda um “ok” mínimo pelo Haiku na própria CLI e lê o limite que ela devolve (custa frações de centavo)"
          onclick={() => work.probe(a.id)}><RefreshCw size={12} class={probing ? "spin" : ""} /> {probing ? "Lendo…" : "Ler agora"}</button>
      </div>
    {/if}
  </div>
  {#if a.usage?.updated && limits.length}
    <div class="tiny upd" class:old={stale(a.usage.updated, now)}>{#if stale(a.usage.updated, now)}<Clock size={10} />{/if} lido há {ago(a.usage.updated)} · {src(a.usage.source)}</div>
  {/if}

  {#if sessions.length}
    <div class="sess">
      {#each sessions.slice(0, compact ? 3 : 8) as s (s.key)}
        {@const ss = STATUS[s.status] || ACC_STATE[s.status] || [s.status, "muted"]}
        <button class="chip {ss[1]}" class:link={!!s.repoId} onclick={() => openSession(s.repoId)} title={s.ext ? `Sessão aberta fora do app · ${s.cwd}` : s.title || ""}>
          <i class="sd" class:pulse={s.status === "working" || s.status === "needs-you"}></i>
          <b class="ell">{s.project || "—"}</b>
          {#if s.title && !s.ext}<span class="ell muted">{s.title.replace(/^.*· /, "")}</span>{/if}
          <span class="muted">{ss[0]}</span>
          {#if s.context != null}<span class="ctx" title="contexto usado">{Math.round(s.context)}%</span>{/if}
          {#if s.ext}<span class="ext" title="aberta fora do app (terminal, IDE)">fora</span>{/if}
        </button>
      {/each}
      {#if sessions.length > (compact ? 3 : 8)}<span class="tiny muted more">+{sessions.length - (compact ? 3 : 8)}</span>{/if}
    </div>
  {/if}
</div>

<style>
  .acc { position: relative; display: grid; gap: 12px; padding: 14px 14px 12px; border-radius: 14px; min-width: 0;
    background: radial-gradient(120% 90% at 0% 0%, color-mix(in srgb, var(--ac) 9%, transparent), transparent 60%), var(--surface-2);
    border: 1px solid var(--line); animation: rise 0.3s var(--ease-out) both; transition: border-color var(--t), box-shadow var(--t), transform var(--t) var(--ease); }
  .acc:hover { border-color: var(--line-2); }
  .acc.busy { border-color: var(--accent-line); box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 18%, transparent), 0 8px 28px -12px color-mix(in srgb, var(--accent) 45%, transparent); }
  .acc.need { border-color: color-mix(in srgb, var(--warn) 55%, transparent); animation: rise 0.3s var(--ease-out) both, glow 2.2s var(--ease) infinite; }
  @keyframes glow { 50% { box-shadow: 0 0 0 3px color-mix(in srgb, var(--warn) 14%, transparent); } }
  .head { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .who { display: grid; min-width: 0; flex: 1; line-height: 1.35; }
  .who b { font-size: 14px; font-weight: 650; letter-spacing: -0.01em; }
  .st { --c: var(--muted); display: inline-flex; align-items: center; gap: 6px; height: 22px; padding: 0 9px; border-radius: 99px; flex: none;
    font: 600 11px/1 var(--font); color: var(--c); background: color-mix(in srgb, var(--c) 12%, transparent); }
  .st i { width: 6px; height: 6px; border-radius: 50%; background: var(--c); }
  .st.accent { --c: var(--accent); } .st.good { --c: var(--good); } .st.warn { --c: var(--warn); } .st.neutral { --c: var(--faint); color: var(--muted); }
  .st.accent i, .st.warn i { animation: ping 1.3s var(--ease) infinite; }
  .defs { display: flex; flex-wrap: wrap; gap: 4px; margin-top: -4px; }
  .def { display: inline-flex; align-items: center; gap: 4px; height: 19px; padding: 0 7px; border-radius: 99px; font: 600 10.5px/1 var(--font);
    color: var(--accent); background: var(--accent-soft); }
  .cta { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 10px; border: 1px solid color-mix(in srgb, var(--warn) 40%, transparent);
    background: var(--warn-soft); color: var(--text); font: 12.5px var(--font); text-align: left; cursor: pointer; transition: background var(--t); }
  .cta:hover { background: color-mix(in srgb, var(--warn) 20%, transparent); }
  .cta .go { display: inline-flex; align-items: center; gap: 4px; font-weight: 650; color: var(--warn); }
  .cta:hover .go :global(svg) { transform: translateX(2px); }
  .cta .go :global(svg) { transition: transform var(--t); }
  .grow { flex: 1; min-width: 0; }
  .err { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 9px; background: var(--bad-soft); color: var(--bad); }
  .meters { display: flex; align-items: flex-start; gap: 18px; min-width: 0; }
  .m { position: relative; display: grid; justify-items: center; gap: 5px; min-width: 0; }
  .cd { font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .cd.fresh { color: var(--good); font-weight: 600; }
  .tag { position: absolute; top: -6px; right: -10px; height: 16px; padding: 0 6px; border-radius: 99px; font: 650 9.5px/16px var(--font); letter-spacing: 0.02em;
    text-transform: uppercase; color: var(--text-2); background: var(--surface-3); border: 1px solid var(--line-2); }
  .nolim { display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; }
  .emptyring { width: var(--s); height: var(--s); border-radius: 50%; border: 5px dashed var(--line-2); flex: none; opacity: 0.8; }
  .side { margin-left: auto; align-self: center; }
  .upd { display: flex; align-items: center; gap: 4px; margin-top: -6px; color: var(--muted); }
  .upd.old { color: var(--warn); }
  .sess { display: flex; flex-wrap: wrap; gap: 5px; padding-top: 10px; border-top: 1px solid var(--line); }
  .chip { --c: var(--muted); display: inline-flex; align-items: center; gap: 6px; max-width: 100%; height: 26px; padding: 0 9px; border-radius: 99px;
    border: 1px solid var(--line-2); background: var(--surface); color: var(--text-2); font: 12px var(--font); cursor: default; min-width: 0; transition: border-color var(--t), background var(--t); }
  .chip.link { cursor: pointer; }
  .chip.link:hover { border-color: var(--line-3); background: var(--surface-3); color: var(--text); }
  .chip b { color: var(--text); font-weight: 600; max-width: 140px; }
  .chip > .ell { max-width: 120px; }
  .chip.accent { --c: var(--accent); border-color: var(--accent-line); } .chip.good { --c: var(--good); } .chip.warn { --c: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, transparent); } .chip.info { --c: var(--info); }
  .sd { width: 7px; height: 7px; border-radius: 50%; background: var(--c); flex: none; }
  .sd.pulse { animation: ping-c 1.3s var(--ease) infinite; }
  .ctx { font: 600 10.5px var(--mono); color: var(--text-2); }
  .ext { font: 600 9.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.04em; color: var(--faint); }
  .more { align-self: center; }
  @keyframes ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, currentColor 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 5px transparent; } }
  @keyframes ping-c { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--c) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 5px transparent; } }
  .compact { padding: 12px 12px 10px; gap: 10px; }
  .compact .meters { gap: 14px; }
  @media (prefers-reduced-motion: reduce) { .acc.need, .st i, .sd.pulse { animation: none; } }
</style>
