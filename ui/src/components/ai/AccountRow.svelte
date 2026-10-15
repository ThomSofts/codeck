<script lang="ts">
  // Uma conta de IA numa linha da tabela de "Uso de IA", com as colunas alinhadas entre as contas: quem é (e o estado),
  // cada limite (quanto usou, quem gastou — por projeto —, quando reseta, qual janela segura a conta), onde está
  // atuando agora e as ações (ler o limite, login). A linha se reorganiza sozinha em largura estreita (container query
  // na lista). Mesmos dados e ações do AiAccountCard compacto, sem os medidores circulares.
  import { AlertTriangle, ArrowRight, Clock, Copy, LogIn, RefreshCw } from "@lucide/svelte";
  import { ago } from "../../lib/format";
  import { go } from "../../lib/router.svelte";
  import { post } from "../../lib/api";
  import { ui } from "../../lib/ui.svelte";
  import { STATUS, work, type AiAccount } from "../../lib/work.svelte";
  import Menu from "../Menu.svelte";
  import AccountAvatar from "./AccountAvatar.svelte";
  import { ACC_STATE, binding, clock, effUsed, expired, resetLabel, stale, tone } from "./limits.svelte";

  type Parts = Record<string, { name: string; used: number }>;
  let { a, breakdown = {}, colorOf, ontip, index = 0 }:
    { a: AiAccount; breakdown?: Record<string, Parts>; colorOf: (id: string) => string; ontip: (t: { x: number; y: number; text: string } | null) => void; index?: number } = $props();

  const act = $derived(work.activity[a.id]);
  const probing = $derived(!!work.probing[a.id] || !!act?.probing);
  const now = $derived(clock.now);
  // janelas em ordem de duração: "5 h" antes de "semanal"
  const span = (w: string) => (/semanal/i.test(w) ? 1e6 : parseFloat(w) || 1e5);
  const limits = $derived([...(a.usage?.rateLimits || [])].sort((x, y) => span(x.window) - span(y.window)));
  const bind = $derived(limits.length > 1 ? binding(limits, now) : null);
  const st = $derived(act ? ACC_STATE[act.state] : null);
  const pct = (n: number) => `${n < 10 && n > 0 ? n.toFixed(1).replace(".0", "") : Math.round(n)}%`;
  const winLabel = (w: string) => (/semanal/i.test(w) ? "Semanal" : w.replace(/\s*h$/, " horas"));

  const src = (s?: string) => (s === "probe" ? "leitura direta" : s === "claude" ? "sessão do app" : s === "codex" ? "log do Codex" : s || "");
  const loginCmd = $derived(a.provider === "claude" ? `CLAUDE_CONFIG_DIR=${a.dir} claude` : a.provider === "codex" ? `CODEX_HOME=${a.dir} codex login` : a.provider === "cursor" ? "cursor-agent login" : a.provider);
  async function copy(t: string) { await navigator.clipboard.writeText(t); ui.toast("Comando copiado"); }
  async function login() {
    try { await post("ai/login", { id: a.id }); ui.toast("Terminal aberto — faça o login lá e depois clique em “Ler agora”", "info"); } catch (e) { ui.error(e); }
  }
  const items = $derived([
    ...(a.provider === "claude" ? [{ label: "Ler o limite agora", icon: RefreshCw, onclick: () => work.probe(a.id), disabled: probing || !a.installed }] : []),
    { label: "Entrar (login da CLI)", icon: LogIn, onclick: login },
    { label: "Copiar comando de login", icon: Copy, onclick: () => copy(loginCmd) },
  ]);

  type Ses = { key: string; project: string | null; repoId: string | null; title: string | null; status: string; context: number | null; ext: boolean; cwd?: string };
  const rankS = (s: string) => ({ "needs-you": 0, working: 1, done: 2 } as Record<string, number>)[s] ?? 3;
  const sessions = $derived<Ses[]>([
    ...(act?.sessions || []).map(s => ({ key: s.sid, project: s.project, repoId: s.repoId, title: s.title, status: s.status, context: s.context, ext: false })),
    ...(act?.external || []).map(s => ({ key: "x" + s.session, project: s.project, repoId: s.repoId, title: null, status: s.status, context: null, ext: true, cwd: s.cwd })),
  ].sort((x, y) => rankS(x.status) - rankS(y.status)));
  const MAX = 3;

  // por janela: o que cada projeto gastou (da leitura de uso), o resto = fora do app ou antes da 1ª leitura
  function split(window: string, used: number) {
    const parts = Object.entries(breakdown[window] || {}).filter(([, p]) => p.used > 0).sort((x, y) => y[1].used - x[1].used);
    const mine = parts.reduce((s, [, p]) => s + p.used, 0);
    const scale = mine > used && mine > 0 ? used / mine : 1;   // leitura nova menor que a soma antiga: cabe na barra
    return { parts: parts.map(([id, p]) => ({ id, name: p.name, used: p.used * scale })), other: Math.max(0, used - mine * scale) };
  }
  const tipAt = (e: MouseEvent, text: string) => ontip({ x: e.clientX, y: e.clientY, text });
</script>

<div class="arow" class:busy={act?.state === "working"} class:need={act?.state === "needs-you"} style="--i:{index}" data-menu-row>
  <div class="who">
    <AccountAvatar {a} state={act?.state} size={32} />
    <div class="id">
      <div class="nm"><b class="ell">{a.name}</b>{#if st && act?.state !== "free"}<span class="st {st[1]}"><i></i>{st[0]}</span>{/if}</div>
      <span class="sub ell" title={a.dir}>{a.email || a.label}</span>
      {#if a.usage?.updated && limits.length}
        <span class="upd" class:old={stale(a.usage.updated, now)}>{#if stale(a.usage.updated, now)}<Clock size={10} />{/if}lido há {ago(a.usage.updated)} · {src(a.usage.source)}</span>
      {/if}
    </div>
  </div>

  <div class="lims" class:none={!limits.length}>
    {#each limits as w (w.window)}
      {@const used = effUsed(w, now)}
      {@const isBind = bind?.window === w.window && used > 0}
      {@const sp = split(w.window, used)}
      {@const k = tone(w.used == null ? null : used)}
      <div class="lim {k}">
        <div class="lt">
          <span class="wl">{winLabel(w.window)}</span>
          {#if isBind}<span class="bind" title="A janela mais perto do fim — é ela que vai parar a conta">limita</span>{/if}
          <span class="grow"></span>
          <span class="cd" class:fresh={expired(w, now)}>{#if w.resetsAt && !expired(w, now)}<Clock size={10} />{/if}{resetLabel(w.resetsAt, now)}</span>
        </div>
        <div class="lv">
          <b class="pc" class:zero={used === 0}>{w.used == null ? "—" : pct(used)}</b>
          <div class="track" role="img" aria-label={`${winLabel(w.window)}: ${pct(used)} usado${w.resetsAt ? ", " + resetLabel(w.resetsAt, now) : ""}`}>
            {#each sp.parts as p (p.id)}
              <i role="presentation" style="width:{p.used}%;background:{colorOf(p.id)}" onmousemove={(e) => tipAt(e, `${p.name}: ${pct(p.used)} desta janela`)} onmouseleave={() => ontip(null)}></i>
            {/each}
            {#if sp.other > 0.05}<i role="presentation" class="rest" style="width:{sp.other}%" onmousemove={(e) => tipAt(e, `Fora do app ou antes da 1ª leitura: ${pct(sp.other)}`)} onmouseleave={() => ontip(null)}></i>{/if}
          </div>
        </div>
        <div class="lg">
          {#each sp.parts.slice(0, 2) as p (p.id)}<span title={`${p.name}: ${pct(p.used)}`}><i style="background:{colorOf(p.id)}"></i><span class="ell">{p.name}</span> <b>{pct(p.used)}</b></span>{/each}
          {#if sp.parts.length > 2}<span class="more" title={sp.parts.slice(2).map(p => `${p.name} ${pct(p.used)}`).join("\n")}>+{sp.parts.length - 2}</span>{/if}
          {#if sp.other > 0.05}<span class="out"><i class="rest"></i>{sp.parts.length ? "fora" : "fora do app"} <b>{pct(sp.other)}</b></span>{/if}
        </div>
      </div>
    {:else}
      <div class="nolim">
        {#if a.provider === "claude"}{a.installed ? "Limite ainda não lido." : "CLI não encontrada."}{:else if a.provider === "codex"}O limite aparece depois da primeira sessão do Codex.{:else}Esta CLI não informa limite.{/if}
      </div>
    {/each}
  </div>

  <div class="sess" class:empty={!sessions.length}>
    {#each sessions.slice(0, MAX) as s (s.key)}
      {@const ss = STATUS[s.status] || ACC_STATE[s.status] || [s.status, "muted"]}
      <button class="ses {ss[1]}" class:link={!!s.repoId} disabled={!s.repoId} onclick={() => s.repoId && go("/work/" + s.repoId)}
        title={s.ext ? `Sessão aberta fora do app · ${s.cwd}` : s.title || s.project || ""}>
        <i class="sd" class:pulse={s.status === "working" || s.status === "needs-you"}></i>
        <b class="ell">{s.project || "—"}</b>
        {#if s.title && !s.ext}<span class="ell t">{s.title.replace(/^.*· /, "")}</span>{/if}
        <span class="ss">{ss[0]}</span>
        {#if s.context != null}<span class="ctx" title="contexto usado">{Math.round(s.context)}%</span>{/if}
        {#if s.ext}<span class="ext" title="aberta fora do app (terminal, IDE)">fora</span>{/if}
        {#if s.status === "needs-you" && s.repoId}<span class="go">Ir <ArrowRight size={12} /></span>{/if}
      </button>
    {:else}<span class="idle">Sem sessão aberta</span>{/each}
    {#if sessions.length > MAX}<span class="moreS">+{sessions.length - MAX} sessão(ões)</span>{/if}
  </div>

  <div class="acts">
    {#if a.provider === "claude"}
      <button class="btn sm ghost icon" disabled={probing || !a.installed} onclick={() => work.probe(a.id)} aria-label="Ler o limite agora"
        title="Ler agora: manda um “ok” mínimo pelo Haiku na própria CLI e lê o limite que ela devolve (custa frações de centavo)"><RefreshCw size={14} class={probing ? "spin" : ""} /></button>
    {/if}
    <Menu {items} />
  </div>

  {#if act?.probeError}
    <div class="perr"><AlertTriangle size={13} /><span class="grow">{act.probeError.error}</span><button class="btn sm" onclick={login}><LogIn size={12} /> Entrar</button></div>
  {/if}
</div>

<style>
  /* colunas: conta | limites (uma por janela) | atuando em | ações — iguais em todas as linhas (a lista é o container) */
  .arow { display: grid; grid-template-columns: minmax(180px, 0.95fr) minmax(320px, 2.3fr) minmax(170px, 1fr) 60px; column-gap: 22px; row-gap: 10px;
    align-items: start; padding: 14px 16px; border-top: 1px solid var(--line); position: relative; transition: background var(--t-fast);
    animation: fade 0.3s var(--ease-out) both; animation-delay: calc(min(var(--i), 10) * 30ms); }
  .arow:hover { background: color-mix(in srgb, var(--surface-2) 60%, transparent); }
  .arow.need { background: color-mix(in srgb, var(--warn) 5%, transparent); }
  .grow { flex: 1; min-width: 0; }

  .who { display: flex; gap: 10px; align-items: flex-start; min-width: 0; }
  .id { display: grid; gap: 1px; min-width: 0; line-height: 1.35; }
  .nm { display: flex; align-items: center; gap: 7px; min-width: 0; }
  .nm b { font-size: 13.5px; font-weight: 650; letter-spacing: -0.01em; }
  .sub { font-size: 11.5px; color: var(--muted); }
  .upd { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; color: var(--muted); margin-top: 2px; white-space: nowrap; }
  .upd.old { color: var(--warn); }
  .st { --c: var(--muted); display: inline-flex; align-items: center; gap: 5px; height: 18px; padding: 0 7px; border-radius: 99px; flex: none;
    font: 600 10.5px/1 var(--font); color: var(--c); background: color-mix(in srgb, var(--c) 12%, transparent); white-space: nowrap; }
  .st i { width: 5px; height: 5px; border-radius: 50%; background: var(--c); }
  .st.accent { --c: var(--accent); } .st.good { --c: var(--good); } .st.warn { --c: var(--warn); } .st.neutral { --c: var(--faint); color: var(--muted); }

  .lims { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; min-width: 0; }
  .lim { --c: var(--text); display: grid; gap: 5px; align-content: start; min-width: 0; }
  .lim.warn { --c: var(--warn); } .lim.bad { --c: var(--bad); } .lim.muted { --c: var(--muted); }
  .lt { display: flex; align-items: center; gap: 6px; height: 18px; font-size: 11.5px; min-width: 0; }
  .wl { color: var(--text-2); font-weight: 550; white-space: nowrap; }
  .bind { font: 650 9.5px/15px var(--font); height: 16px; padding: 0 6px; border-radius: 99px; text-transform: uppercase; letter-spacing: 0.03em;
    color: var(--text-2); border: 1px solid var(--line-2); white-space: nowrap; }
  .warn .bind, .bad .bind { color: var(--c); border-color: color-mix(in srgb, var(--c) 45%, transparent); }
  .cd { display: inline-flex; align-items: center; gap: 4px; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .cd.fresh { color: var(--good); font-weight: 600; }
  .lv { display: grid; grid-template-columns: 46px minmax(0, 1fr); align-items: center; gap: 10px; }
  .pc { font-size: 17px; font-weight: 680; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; color: var(--c); line-height: 1; }
  .pc.zero { color: var(--muted); }
  .track { display: flex; gap: 1.5px; height: 8px; border-radius: 99px; overflow: hidden; background: var(--surface-3); }
  .warn .track { background: color-mix(in srgb, var(--warn) 16%, var(--surface-3)); }
  .bad .track { background: color-mix(in srgb, var(--bad) 18%, var(--surface-3)); }
  .track i { height: 100%; min-width: 3px; flex: none; animation: grow-x 0.6s var(--ease-out) both; transform-origin: left; transition: filter var(--t-fast); }
  .track i:hover { filter: brightness(1.18); }
  .rest { background: repeating-linear-gradient(135deg, var(--line-3) 0 3px, color-mix(in srgb, var(--line-3) 40%, transparent) 3px 6px); }
  .lg { display: flex; align-items: center; gap: 10px; overflow: hidden; min-height: 16px; font-size: 11.5px; color: var(--text-2); min-width: 0; }
  .lg > span { display: inline-flex; align-items: center; gap: 5px; min-width: 0; flex: 0 1 auto; white-space: nowrap; }
  .lg > .more, .lg > .out { flex: none; }
  .lg i { width: 7px; height: 7px; border-radius: 2px; flex: none; display: inline-block; }
  .lg b { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }
  .lg .ell { max-width: 96px; }
  .lg .more { color: var(--muted); }
  .nolim { grid-column: 1 / -1; align-self: center; font-size: 12.5px; color: var(--muted); padding: 6px 0; }

  .sess { display: grid; gap: 4px; justify-items: start; min-width: 0; }
  .ses { --c: var(--muted); display: flex; align-items: center; gap: 6px; max-width: 100%; min-width: 0; height: 24px; padding: 0 8px; border-radius: 7px;
    border: 1px solid var(--line-2); background: var(--surface); color: var(--text-2); font: 12px var(--font); text-align: left; transition: border-color var(--t-fast), background var(--t-fast); }
  .ses:disabled { cursor: default; opacity: 1; }
  .ses.link { cursor: pointer; }
  .ses.link:hover { border-color: var(--line-3); background: var(--surface-2); color: var(--text); }
  .ses.accent { --c: var(--accent); } .ses.good { --c: var(--good); } .ses.info { --c: var(--info); }
  .ses.warn { --c: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, transparent); background: var(--warn-soft); color: var(--text); }
  .ses b { color: var(--text); font-weight: 600; max-width: 130px; flex: 0 1 auto; }
  .ses .t { color: var(--muted); max-width: 120px; flex: 0 1 auto; }
  .ses .ss { color: var(--c); white-space: nowrap; flex: none; }
  .sd { width: 6px; height: 6px; border-radius: 50%; background: var(--c); flex: none; }
  .sd.pulse { animation: ping-c 1.3s var(--ease) infinite; }
  .ctx { font: 600 10.5px var(--mono); color: var(--text-2); flex: none; }
  .ext { font: 600 9.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.04em; color: var(--faint); flex: none; }
  .go { display: inline-flex; align-items: center; gap: 3px; font-weight: 650; color: var(--warn); flex: none; }
  .idle { font-size: 12px; color: var(--faint); padding-top: 3px; }
  .moreS { font-size: 11px; color: var(--muted); padding-left: 2px; }

  .acts { display: flex; align-items: center; justify-content: flex-end; gap: 2px; margin-top: -2px; }
  .perr { grid-column: 1 / -1; display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 9px; background: var(--bad-soft); color: var(--bad); font-size: 12px; }

  /* estreito: conta + ações em cima, limites lado a lado, sessões embaixo */
  @container accts (max-width: 860px) {
    .arow { grid-template-columns: minmax(0, 1fr) auto; }
    .lims { grid-column: 1 / -1; grid-row: 2; }
    .sess { grid-column: 1 / -1; grid-row: 3; display: flex; flex-wrap: wrap; }
    .sess.empty { display: none; }
    .acts { grid-column: 2; grid-row: 1; }
  }
  @container accts (max-width: 500px) {
    .lims { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  }
  @keyframes grow-x { from { transform: scaleX(0); } }
  @keyframes ping-c { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--c) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 5px transparent; } }
  @media (prefers-reduced-motion: reduce) { .arow, .track i, .sd.pulse { animation: none; } }
</style>
