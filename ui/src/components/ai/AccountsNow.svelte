<script lang="ts">
  // "Agora": qual conta usar (a com mais fôlego, e o porquê) e o fôlego de todas, da mais livre para a mais apertada —
  // uma linha por conta com o apelido, o grupo, as barras de 5 h e semanal, o que ela está fazendo e quanto sobra.
  // Os grupos (Dematec, Pessoal…) filtram a lista e a recomendação. Editar o apelido é ali mesmo.
  import { ArrowRight, Copy, Gauge, LogIn, Pencil, RefreshCw, Sparkles } from "@lucide/svelte";
  import { post } from "../../lib/api";
  import { go } from "../../lib/router.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { work, type AiAccount } from "../../lib/work.svelte";
  import Menu from "../Menu.svelte";
  import AccountAvatar from "./AccountAvatar.svelte";
  import AccountEdit from "./AccountEdit.svelte";
  import Fuel from "./Fuel.svelte";
  import { accColor, ACC_STATE, clock, rank } from "./limits.svelte";

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
    <h3>Agora</h3>
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

  {#if best}
    {@const doing0 = doing(best.a)}
    <div class="rec" style="--ac:{accColor(best.a)}">
      <AccountAvatar a={best.a} state={work.activity[best.a.id]?.state} size={52} />
      <div class="rt">
        <span class="k"><Sparkles size={12} /> Use agora</span>
        <div class="rn"><b>{best.a.name}</b>{#if best.a.group}<span class="gchip">{best.a.group}</span>{/if}</div>
        <p class="why">{best.why}{doing0 ? ` · ${doing0.status === "needs-you" ? "esperando você" : "trabalhando"} em ${doing0.project}` : ""}</p>
      </div>
      <div class="rf"><Fuel a={best.a} /></div>
      <div class="big" aria-label={`${Math.round(best.free!)}% livre`}><b>{Math.round(best.free!)}<small>%</small></b><span>livre</span></div>
    </div>
  {:else if withLimit.length}
    <div class="rec none"><span>Todas as contas{group ? ` de ${group}` : ""} estão no limite — a próxima a liberar aparece na lista.</span></div>
  {/if}

  <div class="list">
    {#each withLimit as r, i (r.a.id)}
      {#if editing === r.a.id}
        <div class="row ed"><AccountEdit a={r.a} ondone={() => (editing = null)} /></div>
      {:else}
        {@const d = doing(r.a)}
        {@const st = work.activity[r.a.id]?.state}
        <div class="row" class:best={best?.a.id === r.a.id} class:blocked={r.blocked} style="--i:{i}" data-menu-row>
          <AccountAvatar a={r.a} state={st} size={32} />
          <div class="who">
            <div class="nm"><b class="ell">{r.a.name}</b>{#if r.a.group && !group}<span class="gchip">{r.a.group}</span>{/if}
              <button class="pen" title="Renomear, grupo e cor" aria-label="Editar conta" onclick={() => (editing = r.a.id)}><Pencil size={11} /></button></div>
            <span class="sub ell">{r.why}</span>
          </div>
          <div class="fu"><Fuel a={r.a} /></div>
          <div class="doing">
            {#if d}
              <button class="ses {d.status === 'needs-you' ? 'warn' : 'accent'}" disabled={!d.repoId} onclick={() => d.repoId && go("/work/" + d.repoId)}>
                <i></i><span class="ell">{d.project || "sessão"}</span>{#if d.status === "needs-you"}<span class="go">Ir <ArrowRight size={11} /></span>{/if}</button>
            {:else if st && st !== "free" && ACC_STATE[st]}<span class="idle">{ACC_STATE[st][0]}</span>{/if}
          </div>
          <div class="fr {r.tone}" class:unsure={r.unsure} title={r.unsure ? "Leitura antiga — o uso desde então é desconhecido; “Ler o limite agora” confirma" : undefined}>
            <b>{r.unsure ? "~" : ""}{Math.round(r.free!)}%</b><span>{r.blocked ? "no limite" : r.unsure ? "incerto" : "livre"}</span></div>
          <Menu items={items(r.a)} />
        </div>
      {/if}
    {/each}
    {#if without.length}
      <div class="nolim">
        <span>Sem limite informado:</span>
        {#each without as r (r.a.id)}
          {#if editing === r.a.id}<div class="row ed"><AccountEdit a={r.a} ondone={() => (editing = null)} /></div>
          {:else}<button class="mini" title={`${r.a.label} — ${r.why}. Clique para renomear.`} onclick={() => (editing = r.a.id)}><AccountAvatar a={r.a} size={20} />{r.a.name}</button>{/if}
        {/each}
      </div>
    {/if}
    {#if !pool.length}<div class="nolim"><span>Nenhuma conta{group ? ` em ${group}` : ""}. Configure em Contas e ajustes → IA.</span></div>{/if}
  </div>
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

  /* a recomendada: tingida com a cor da conta */
  .rec { display: grid; grid-template-columns: auto minmax(0, 1fr) minmax(220px, 300px) auto; align-items: center; gap: 18px; padding: 16px 20px;
    border-radius: var(--r-lg); border: 1px solid color-mix(in srgb, var(--ac) 35%, var(--line));
    background: radial-gradient(90% 140% at 0% 0%, color-mix(in srgb, var(--ac) 14%, transparent), transparent 70%), var(--surface);
    animation: rise 0.35s var(--ease-out) both; }
  .rec.none { display: block; color: var(--text-2); font-size: 13px; background: var(--surface); border-color: var(--line); }
  .rt { display: grid; gap: 3px; min-width: 0; }
  .k { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 600; color: color-mix(in srgb, var(--ac) 60%, var(--text)); }
  .rn { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .rn b { font-size: 20px; font-weight: 700; letter-spacing: -0.02em; }
  .why { margin: 0; font-size: 12.5px; color: var(--text-2); line-height: 1.4; }
  .big { display: grid; justify-items: end; line-height: 1; }
  .big b { font-size: 40px; font-weight: 720; letter-spacing: -0.04em; font-variant-numeric: tabular-nums; color: var(--good); }
  .big small { font-size: 20px; font-weight: 650; margin-left: 1px; }
  .big span { font-size: 12px; color: var(--text-2); margin-top: 3px; }

  .gchip { flex: none; height: 18px; padding: 0 7px; border-radius: 99px; font: 600 10.5px/18px var(--font); color: var(--text-2); background: var(--surface-3); white-space: nowrap; }

  .list { display: grid; border-radius: var(--r); border: 1px solid var(--line); background: var(--surface); overflow: hidden; container: rows / inline-size; }
  .row { display: grid; grid-template-columns: auto minmax(150px, 1fr) minmax(240px, 1.35fr) minmax(110px, 0.7fr) 64px 28px; align-items: center; gap: 14px;
    padding: 11px 12px 11px 16px; border-top: 1px solid var(--line); transition: background var(--t-fast);
    animation: fade 0.3s var(--ease-out) both; animation-delay: calc(min(var(--i), 10) * 25ms); }
  .row:first-child { border-top: 0; }
  .row:hover { background: color-mix(in srgb, var(--surface-2) 70%, transparent); }
  .row.best { background: color-mix(in srgb, var(--good) 5%, transparent); }
  .row.blocked { opacity: 0.7; }
  .row.ed { display: block; padding: 8px; animation: none; }
  .who { display: grid; gap: 2px; min-width: 0; }
  .nm { display: flex; align-items: center; gap: 7px; min-width: 0; }
  .nm b { font-size: 13.5px; font-weight: 650; }
  .pen { display: grid; place-items: center; width: 20px; height: 20px; border: 0; border-radius: 5px; background: none; color: var(--muted); cursor: pointer; opacity: 0;
    transition: opacity var(--t-fast); flex: none; }
  .row:hover .pen, .pen:focus-visible { opacity: 1; }
  .pen:hover { background: var(--surface-3); color: var(--text); }
  .sub { font-size: 11.5px; color: var(--muted); }
  .fu { min-width: 0; }
  .doing { min-width: 0; }
  .ses { --c: var(--accent); display: inline-flex; align-items: center; gap: 6px; max-width: 100%; height: 24px; padding: 0 8px; border-radius: 7px; border: 1px solid var(--line-2);
    background: var(--surface); color: var(--text); font: 12px var(--font); cursor: pointer; }
  .ses:disabled { cursor: default; }
  .ses i { width: 6px; height: 6px; border-radius: 50%; background: var(--c); flex: none; animation: ping-c 1.3s var(--ease) infinite; }
  .ses.warn { --c: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, transparent); background: var(--warn-soft); }
  .ses .go { display: inline-flex; align-items: center; gap: 2px; color: var(--warn); font-weight: 650; flex: none; }
  .idle { font-size: 12px; color: var(--faint); }
  .fr { --c: var(--good); display: grid; justify-items: end; line-height: 1.1; }
  .fr.warn { --c: var(--warn); } .fr.bad { --c: var(--bad); }
  .fr b { font-size: 17px; font-weight: 700; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; color: var(--c); }
  .fr span { font-size: 10.5px; color: var(--muted); }
  .fr.unsure b { color: var(--text-2); }
  .nolim { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 10px 16px; border-top: 1px solid var(--line); font-size: 12px; color: var(--muted); }
  .nolim:first-child { border-top: 0; }
  .nolim .row.ed { flex-basis: 100%; border: 0; }
  .mini { display: inline-flex; align-items: center; gap: 6px; height: 26px; padding: 0 9px 0 4px; border-radius: 99px; border: 1px solid var(--line-2); background: var(--surface-2);
    color: var(--text-2); font: 12px var(--font); cursor: pointer; }
  .mini:hover { color: var(--text); border-color: var(--line-3); }
  .ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }

  @container rows (max-width: 820px) {
    .row { grid-template-columns: auto minmax(0, 1fr) 64px 28px; row-gap: 8px; }
    .fu { grid-column: 2 / -1; grid-row: 2; }
    .doing { grid-column: 2 / -1; grid-row: 3; }
    .doing:empty { display: none; }
  }
  @media (max-width: 900px) { .rec { grid-template-columns: auto minmax(0, 1fr) auto; } .rf { grid-column: 1 / -1; } }
  @keyframes ping-c { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--c) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 5px transparent; } }
  @media (prefers-reduced-motion: reduce) { .rec, .row, .ses i { animation: none; } }
</style>
