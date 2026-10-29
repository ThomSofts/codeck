<script lang="ts">
  // "Contas": um cartão por conta, da mais livre para a mais apertada — o anel da janela que segura a conta, quanto
  // sobra, as barras de 5 h e semanal com a contagem para o reset, o porquê e o que ela está fazendo agora. A conta
  // recomendada (mais fôlego) ganha o contorno vivo e o selo "Use agora". Os grupos (Dematec, Pessoal…) filtram.
  import { ArrowRight, Copy, Gauge, LogIn, Pencil, RefreshCw, Sparkles } from "@lucide/svelte";
  import LimitRing from "./LimitRing.svelte";
  import { post } from "../../lib/api";
  import { go } from "../../lib/router.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { work, type AiAccount } from "../../lib/work.svelte";
  import Menu from "../Menu.svelte";
  import AccountAvatar from "./AccountAvatar.svelte";
  import AccountEdit from "./AccountEdit.svelte";
  import Fuel from "./Fuel.svelte";
  import { accColor, ACC_STATE, binding, clock, effUsed, rank, winShort } from "./limits.svelte";

  const LS = "codeck.ai.group";
  let group = $state((() => { try { return localStorage.getItem(LS) || ""; } catch { return ""; } })());
  $effect(() => { const g = group; try { localStorage.setItem(LS, g); } catch { /* sem armazenamento */ } });
  let editing = $state<string | null>(null);

  const groups = $derived([...new Set(work.ai.map(a => a.group).filter(Boolean) as string[])].sort());
  $effect(() => { if (group && !groups.includes(group)) group = ""; });
  const pool = $derived(work.ai.filter(a => (a.installed || a.usage) && (!group || a.group === group)));
  const ranked = $derived(rank(pool, clock.now));
  const withLimit = $derived(ranked.filter(r => r.free != null));
  const without = $derived(ranked.filter(r => r.free == null));
  const best = $derived(withLimit.find(r => r.a.installed && !r.blocked) || null);
  const probingAny = $derived(Object.keys(work.probing).length > 0);

  // o que a conta está fazendo: a sessão mais urgente (precisa de você > trabalhando)
  function doing(a: AiAccount) {
    const act = work.activity[a.id];
    if (!act) return null;
    const all = [...act.sessions.map(s => ({ status: s.status, project: s.project, repoId: s.repoId })),
      ...act.external.map(s => ({ status: s.status, project: s.project, repoId: s.repoId }))];
    return all.find(s => s.status === "needs-you") || all.find(s => s.status === "working") || null;
  }
  const loginCmd = (a: AiAccount) => a.provider === "claude" ? `CLAUDE_CONFIG_DIR=${a.dir} claude` : a.provider === "codex" ? `CODEX_HOME=${a.dir} codex login` : a.provider === "cursor" ? "cursor-agent login" : a.provider;
  const items = (a: AiAccount) => [
    { label: "Renomear, grupo e cor…", icon: Pencil, onclick: () => (editing = a.id) },
    ...(a.provider === "claude" ? [{ label: "Ler o limite agora", icon: RefreshCw, disabled: !!work.probing[a.id] || !a.installed, onclick: () => work.probe(a.id) }] : []),
    { separator: true },
    { label: "Entrar (login da CLI)", icon: LogIn, onclick: () => post("ai/login", { id: a.id }).then(() => ui.toast("Terminal aberto — faça o login lá", "info")).catch(ui.error) },
    { label: "Copiar comando de login", icon: Copy, onclick: () => navigator.clipboard.writeText(loginCmd(a)).then(() => ui.toast("Comando copiado")) },
  ];
</script>

<section class="now" aria-label="Contas agora">
  <div class="top">
    <h3>Contas</h3>
    {#if groups.length}
      <div class="grp" role="tablist" aria-label="Grupo">
        <button role="tab" aria-selected={!group} class:on={!group} onclick={() => (group = "")}>Todas</button>
        {#each groups as g (g)}<button role="tab" aria-selected={group === g} class:on={group === g} onclick={() => (group = g)}>{g}</button>{/each}
      </div>
    {:else}
      <span class="hint">Dê apelido e grupo às contas (✎) para separar por cliente.</span>
    {/if}
    <span class="grow"></span>
    {#if work.ai.some(a => a.provider === "claude" && a.installed)}
      <button class="btn sm" disabled={probingAny} onclick={() => work.probe()}><Gauge size={13} class={probingAny ? "spin" : ""} /> {probingAny ? "Lendo…" : "Ler limites"}</button>
    {/if}
  </div>

  {#if !best && withLimit.length}
    <div class="none">Todas as contas{group ? ` de ${group}` : ""} estão no limite — a próxima a liberar aparece primeiro.</div>
  {/if}

  <div class="cards">
    {#each withLimit as r, i (r.a.id)}
      {#if editing === r.a.id}
        <div class="acard ed"><AccountEdit a={r.a} ondone={() => (editing = null)} /></div>
      {:else}
        {@const d = doing(r.a)}
        {@const st = work.activity[r.a.id]?.state}
        {@const b = binding(r.a.usage?.rateLimits, clock.now)}
        <article class="acard {r.tone}" class:best={best?.a.id === r.a.id} class:blocked={r.blocked} class:probing={!!work.probing[r.a.id]} style="--ac:{accColor(r.a)};--i:{i}" data-menu-row>
          {#if best?.a.id === r.a.id}<span class="seal"><Sparkles size={11} /> Use agora</span>{/if}
          <header>
            <AccountAvatar a={r.a} state={st} size={36} />
            <div class="who">
              <div class="nm"><b class="ell">{r.a.name}</b>
                <button class="pen" title="Renomear, grupo e cor" aria-label="Editar conta" onclick={() => (editing = r.a.id)}><Pencil size={11} /></button></div>
              <span class="sub ell">{r.a.group && !group ? r.a.group + " · " : ""}{r.a.label}{r.a.usage?.plan ? " · " + r.a.usage.plan : ""}</span>
            </div>
            <Menu items={items(r.a)} />
          </header>
          <div class="mid">
            <LimitRing used={b ? effUsed(b, clock.now) : null} size={66} label={b ? winShort(b) : ""} binding />
            <div class="fr" class:unsure={r.unsure} title={r.unsure ? "Leitura antiga — o uso desde então é desconhecido; “Ler o limite agora” confirma" : undefined}>
              <b>{r.unsure ? "~" : ""}{Math.round(r.free!)}<small>%</small></b>
              <span>{r.blocked ? "no limite" : r.unsure ? "livre (incerto)" : "livre"}</span>
            </div>
          </div>
          <Fuel a={r.a} />
          <p class="why">{r.why}</p>
          <footer>
            {#if d}
              <button class="ses {d.status === 'needs-you' ? 'warn' : 'accent'}" disabled={!d.repoId} onclick={() => d.repoId && go("/work/" + d.repoId)}>
                <i></i><span class="ell">{d.status === "needs-you" ? "esperando em" : "trabalhando em"} {d.project || "sessão"}</span>{#if d.repoId}<ArrowRight size={11} />{/if}</button>
            {:else if st && st !== "free" && ACC_STATE[st]}<span class="idle">{ACC_STATE[st][0]}</span>
            {:else}<span class="idle">livre para uma tarefa</span>{/if}
          </footer>
        </article>
      {/if}
    {/each}
  </div>
  {#if without.length}
    <div class="nolim">
      <span>Sem limite informado:</span>
      {#each without as r (r.a.id)}
        {#if editing === r.a.id}<div class="acard ed"><AccountEdit a={r.a} ondone={() => (editing = null)} /></div>
        {:else}<button class="mini" title={`${r.a.label} — ${r.why}. Clique para renomear.`} onclick={() => (editing = r.a.id)}><AccountAvatar a={r.a} size={20} state={work.activity[r.a.id]?.state} />{r.a.name}</button>{/if}
      {/each}
    </div>
  {/if}
  {#if !pool.length}<div class="none">Nenhuma conta{group ? ` em ${group}` : ""}. Configure em Contas e ajustes → IA.</div>{/if}
</section>

<style>
  .now { display: grid; gap: 10px; }
  .top { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; min-height: 30px; }
  .top h3 { margin: 0; font-size: 15px; font-weight: 680; letter-spacing: -0.01em; }
  .hint { font-size: 12px; color: var(--muted); }
  .grow { flex: 1; }
  .grp { display: flex; gap: 2px; padding: 2px; border-radius: 9px; background: var(--surface-2); border: 1px solid var(--line); }
  .grp button { height: 24px; padding: 0 10px; border: 0; border-radius: 7px; background: none; color: var(--text-2); font: 550 12px var(--font); cursor: pointer;
    transition: background var(--t-fast), color var(--t-fast); }
  .grp button:hover { color: var(--text); }
  .grp button.on { background: var(--surface-3); color: var(--text); box-shadow: var(--shadow-1); }
  .none { padding: 12px 14px; border-radius: var(--r); border: 1px solid var(--line); background: var(--surface); color: var(--text-2); font-size: 13px; }

  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 10px; }
  .acard { position: relative; display: grid; gap: 10px; align-content: start; padding: 14px 14px 12px; border-radius: var(--r-lg); border: 1px solid var(--line); isolation: isolate;
    background: radial-gradient(120% 80% at 0% 0%, color-mix(in srgb, var(--ac) 10%, transparent), transparent 60%), var(--surface);
    animation: rise 0.4s var(--ease-out) both; animation-delay: calc(min(var(--i), 10) * 40ms);
    transition: transform var(--t) var(--spring), border-color var(--t), box-shadow var(--t); }
  .acard:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--ac) 35%, var(--line)); box-shadow: var(--shadow-2); }
  .acard.blocked { opacity: 0.72; }
  .acard.ed { display: block; padding: 8px; animation: none; }
  /* a recomendada: contorno girando na cor da conta */
  .acard.best { border-color: transparent; }
  .acard.best::before { content: ""; position: absolute; inset: -1px; border-radius: inherit; padding: 1.5px; z-index: -1; pointer-events: none;
    background: conic-gradient(from var(--ang, 0deg), var(--ac), color-mix(in srgb, var(--good) 80%, transparent), transparent 40%, var(--ac) 70%, var(--good));
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); -webkit-mask-composite: xor; mask-composite: exclude; animation: orbit 5s linear infinite; }
  .acard.best::after { content: ""; position: absolute; inset: 0; border-radius: inherit; z-index: -2; box-shadow: 0 10px 40px -16px color-mix(in srgb, var(--good) 55%, transparent); }
  .acard.probing { animation: rise 0.4s var(--ease-out) both, shimmer-b 1.4s linear infinite; }
  .seal { position: absolute; top: -9px; right: 12px; display: inline-flex; align-items: center; gap: 4px; height: 19px; padding: 0 8px; border-radius: 99px;
    font: 700 10.5px/1 var(--font); color: #04170e; background: var(--good); box-shadow: 0 4px 14px -4px color-mix(in srgb, var(--good) 70%, transparent); }
  header { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .who { display: grid; gap: 1px; flex: 1; min-width: 0; }
  .nm { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .nm b { font-size: 14px; font-weight: 680; letter-spacing: -0.01em; }
  .sub { font-size: 11.5px; color: var(--muted); }
  .pen { display: grid; place-items: center; width: 20px; height: 20px; border: 0; border-radius: 5px; background: none; color: var(--muted); cursor: pointer; opacity: 0;
    transition: opacity var(--t-fast); flex: none; }
  .acard:hover .pen, .pen:focus-visible { opacity: 1; }
  .pen:hover { background: var(--surface-3); color: var(--text); }
  .mid { display: flex; align-items: center; gap: 14px; }
  .fr { display: grid; line-height: 1; gap: 3px; }
  .fr b { font-size: 30px; font-weight: 740; letter-spacing: -0.04em; font-variant-numeric: tabular-nums; color: var(--c, var(--good)); }
  .acard.warn .fr b { color: var(--warn); } .acard.bad .fr b { color: var(--bad); }
  .fr small { font-size: 15px; font-weight: 650; margin-left: 1px; }
  .fr span { font-size: 11.5px; color: var(--text-2); }
  .fr.unsure b { color: var(--text-2) !important; }
  .why { margin: 0; font-size: 11.5px; color: var(--text-2); line-height: 1.4; min-height: 16px; }
  footer { display: flex; min-width: 0; padding-top: 8px; border-top: 1px dashed var(--line); }
  .ses { --c: var(--accent); display: inline-flex; align-items: center; gap: 6px; max-width: 100%; height: 24px; padding: 0 8px; border-radius: 7px; border: 1px solid var(--line-2);
    background: var(--surface); color: var(--text); font: 12px var(--font); cursor: pointer; }
  .ses:disabled { cursor: default; }
  .ses i { width: 6px; height: 6px; border-radius: 50%; background: var(--c); flex: none; animation: ping-c 1.3s var(--ease) infinite; }
  .ses.warn { --c: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, transparent); background: var(--warn-soft); }
  .idle { font-size: 12px; color: var(--faint); line-height: 24px; }
  .nolim { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 4px 2px; font-size: 12px; color: var(--muted); }
  .nolim .acard.ed { flex-basis: 100%; }
  .mini { display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 10px 0 4px; border-radius: 99px; border: 1px solid var(--line-2); background: var(--surface);
    color: var(--text-2); font: 12px var(--font); cursor: pointer; transition: border-color var(--t-fast), color var(--t-fast); }
  .mini:hover { color: var(--text); border-color: var(--line-3); }
  .ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }

  @property --ang { syntax: "<angle>"; initial-value: 0deg; inherits: false; }
  @keyframes orbit { to { --ang: 360deg; } }
  @keyframes shimmer-b { 50% { border-color: color-mix(in srgb, var(--ac) 50%, var(--line)); } }
  @keyframes ping-c { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--c) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 5px transparent; } }
  @media (prefers-reduced-motion: reduce) { .acard, .acard.best::before, .ses i { animation: none; } }
</style>
