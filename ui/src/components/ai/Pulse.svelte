<script lang="ts">
  // O pulso da IA agora: quantos agentes estão trabalhando e quantos esperam você (a linha de batimento acelera com o
  // trabalho), as sessões ao vivo como fichas clicáveis e o "Radar" — o que vale fazer agora, em frases: quem está
  // esperando, que conta usar, quem está perto do limite, semanal que vai zerar com sobra, leitura velha, o dia de hoje
  // contra a média e o projeto que mais consome.
  import { ArrowRight, Flame, Gauge, Hourglass, Radar, Sparkles, TrendingUp, TriangleAlert, Zap } from "@lucide/svelte";
  import { go } from "../../lib/router.svelte";
  import { work, type AiAccount } from "../../lib/work.svelte";
  import AccountAvatar from "./AccountAvatar.svelte";
  import { clock, rank } from "./limits.svelte";

  type Day = { day: string; workMs: number };
  let { report = null }: { report?: { days: Day[]; totals: { workMs: number }; projects: Record<string, { workMs: number; name?: string }> } | null } = $props();

  type Live = { a: AiAccount; status: string; project: string; repoId: string | null; title?: string | null };
  const live = $derived.by(() => {
    const out: Live[] = [];
    for (const a of work.ai) {
      const act = work.activity[a.id];
      if (!act) continue;
      for (const s of act.sessions) if (s.status === "working" || s.status === "needs-you") out.push({ a, status: s.status, project: s.project || "sessão", repoId: s.repoId, title: s.task || s.title });
      for (const s of act.external) if (s.status === "working" || s.status === "needs-you") out.push({ a, status: s.status, project: s.project || "sessão", repoId: s.repoId });
    }
    return out.sort((x, y) => (x.status === "needs-you" ? 0 : 1) - (y.status === "needs-you" ? 0 : 1));
  });
  const working = $derived(live.filter(x => x.status === "working").length);
  const waiting = $derived(live.filter(x => x.status === "needs-you").length);
  const ranked = $derived(rank(work.ai.filter(a => a.installed || a.usage), clock.now));
  const probingAny = $derived(Object.keys(work.probing).length > 0);

  const dur = (ms: number) => { const m = Math.round(ms / 60000); return m < 60 ? `${m} min` : `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}`; };
  const todayKey = (() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; })();

  type Tip = { id: string; tone: "warn" | "bad" | "good" | "accent"; icon: any; text: string; strong?: string; act?: { label: string; run: () => void }; a?: AiAccount };
  const radar = $derived.by((): Tip[] => {
    const out: Tip[] = [];
    for (const w of live.filter(x => x.status === "needs-you").slice(0, 2))
      out.push({ id: "w" + w.a.id + w.project, tone: "warn", icon: Hourglass, a: w.a, strong: w.a.name, text: `está esperando você em ${w.project}`,
        act: w.repoId ? { label: "Ir", run: () => go("/work/" + w.repoId) } : undefined });
    const best = ranked.find(r => r.free != null && r.a.installed && !r.blocked);
    if (best) out.push({ id: "best", tone: "good", icon: Sparkles, a: best.a, strong: `Use ${best.a.name}`, text: `— ${best.why}` });
    for (const r of ranked.filter(r => r !== best && /aproveite/.test(r.why)).slice(0, 1))
      out.push({ id: "wk" + r.a.id, tone: "accent", icon: Zap, a: r.a, strong: r.a.name, text: `— ${r.why}` });
    for (const r of ranked.filter(r => r.free != null && r.free < 15).slice(0, 2))
      out.push({ id: "lim" + r.a.id, tone: r.blocked ? "bad" : "warn", icon: TriangleAlert, a: r.a, strong: r.a.name, text: r.blocked ? `no limite — ${r.why}` : `perto do limite (${Math.round(r.free!)}% livre) — ${r.why}` });
    const old = ranked.filter(r => r.unsure);
    if (old.length) out.push({ id: "old", tone: "accent", icon: Gauge, strong: `${old.length} leitura${old.length > 1 ? "s" : ""} antiga${old.length > 1 ? "s" : ""}`, text: "de limite — o número pode estar errado",
      act: probingAny ? undefined : { label: "Ler agora", run: () => work.probe() } });
    if (report?.days?.length) {
      const today = report.days.find(d => d.day === todayKey)?.workMs || 0;
      const prev = report.days.filter(d => d.day !== todayKey && d.workMs > 0);
      const avg = prev.length ? prev.reduce((n, d) => n + d.workMs, 0) / prev.length : 0;
      if (today > 0 && avg > 0) {
        const diff = Math.round(((today - avg) / avg) * 100);
        if (Math.abs(diff) >= 25) out.push({ id: "today", tone: diff > 0 ? "accent" : "good", icon: TrendingUp, strong: `Hoje: ${dur(today)}`,
          text: `de agente trabalhando — ${Math.abs(diff)}% ${diff > 0 ? "acima" : "abaixo"} da média`});
      }
      const tot = report.totals.workMs;
      const top = Object.entries(report.projects).sort((a, b) => b[1].workMs - a[1].workMs)[0];
      if (top && tot > 0 && top[1].workMs / tot >= 0.4 && Object.keys(report.projects).length > 1)
        out.push({ id: "top", tone: "accent", icon: Flame, strong: top[1].name || "Um projeto", text: `levou ${Math.round((100 * top[1].workMs) / tot)}% do tempo de agente no período` });
    }
    return out.slice(0, 6);
  });
  // a linha de batimento: mais trabalho, mais rápida; alguém esperando, quente
  const speed = $derived(working ? Math.max(0.7, 2.4 - working * 0.35) : 4);
</script>

<section class="pulse" class:hot={waiting > 0} class:busy={working > 0} style="--sp:{speed}s">
  <div class="mesh" aria-hidden="true"><i></i><i></i><i></i></div>
  <div class="now">
    <div class="beat" aria-hidden="true">
      <svg viewBox="0 0 240 48" preserveAspectRatio="none"><path d="M0 24 H70 L80 24 L88 8 L98 42 L106 16 L112 24 H240" /></svg>
    </div>
    <div class="head">
      <span class="k"><span class="live"></span>{working || waiting ? "Ao vivo" : "Agora"}</span>
      <h2>{#if working}{working} agente{working > 1 ? "s" : ""} trabalhando{:else if waiting}Agentes parados esperando você{:else}Tudo calmo{/if}</h2>
      <p>{#if waiting}<b>{waiting}</b> esperando você{working ? " · " : ""}{/if}{#if working}em {new Set(live.filter(x => x.status === "working").map(x => x.project)).size} projeto(s){/if}{#if !working && !waiting}Nenhum agente trabalhando agora — abra uma tarefa num projeto.{/if}</p>
    </div>
    {#if live.length}
      <div class="chips">
        {#each live.slice(0, 8) as s, i (s.a.id + s.project + i)}
          <button class="chip {s.status}" style="--i:{i}" disabled={!s.repoId} onclick={() => s.repoId && go("/work/" + s.repoId)} title={s.title || s.project}>
            <AccountAvatar a={s.a} size={20} state={s.status} /><span class="ell">{s.project}</span>
            {#if s.status === "needs-you"}<span class="go">esperando <ArrowRight size={11} /></span>{/if}
          </button>
        {/each}
        {#if live.length > 8}<span class="more">+{live.length - 8}</span>{/if}
      </div>
    {/if}
  </div>
  <div class="radar">
    <div class="rh"><Radar size={13} /> Radar</div>
    {#each radar as t, i (t.id)}
      <div class="rt {t.tone}" style="--i:{i}">
        <span class="ri">{#if t.a}<AccountAvatar a={t.a} size={22} />{:else}<t.icon size={13} />{/if}</span>
        <span class="tx">{#if t.strong}<b>{t.strong}</b>{" "}{/if}{t.text}</span>
        {#if t.act}<button class="btn sm" onclick={t.act.run}>{t.act.label}</button>{/if}
      </div>
    {:else}
      <div class="rt good"><span class="ri"><Sparkles size={13} /></span><span class="tx">Nada pedindo atenção. Bom trabalho.</span></div>
    {/each}
  </div>
</section>

<style>
  .pulse { position: relative; display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(280px, 1fr); gap: 18px; padding: 18px 20px; border-radius: var(--r-lg); overflow: hidden;
    border: 1px solid var(--line); background: var(--surface); isolation: isolate; --hc: var(--accent); }
  .pulse.hot { --hc: var(--warn); }
  .mesh { position: absolute; inset: 0; z-index: -1; opacity: 0.9; pointer-events: none; }
  .mesh i { position: absolute; width: 60%; aspect-ratio: 1; border-radius: 50%; filter: blur(60px); opacity: 0.18; animation: drift 18s var(--ease) infinite alternate; }
  .mesh i:nth-child(1) { left: -15%; top: -60%; background: var(--hc); }
  .mesh i:nth-child(2) { right: -10%; bottom: -70%; background: var(--cat6); animation-duration: 22s; animation-delay: -6s; }
  .mesh i:nth-child(3) { left: 30%; top: -30%; width: 40%; background: var(--cat3); opacity: 0.1; animation-duration: 26s; }
  .now { display: grid; gap: 12px; align-content: start; min-width: 0; position: relative; }
  .beat { position: absolute; right: 0; top: 0; width: 46%; height: 48px; opacity: 0.55; pointer-events: none; }
  .beat svg { width: 100%; height: 100%; overflow: visible; }
  .beat path { fill: none; stroke: var(--hc); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 60 400; stroke-dashoffset: 460;
    animation: beat var(--sp) linear infinite; filter: drop-shadow(0 0 4px var(--hc)); }
  .pulse:not(.busy):not(.hot) .beat { opacity: 0.25; }
  .head { display: grid; gap: 4px; }
  .k { display: inline-flex; align-items: center; gap: 7px; font: 650 11px/1 var(--font); text-transform: uppercase; letter-spacing: 0.08em; color: var(--hc); }
  .live { width: 8px; height: 8px; border-radius: 50%; background: var(--hc); animation: ping 1.6s var(--ease) infinite; }
  .pulse:not(.busy):not(.hot) .live { animation: none; background: var(--muted); }
  .pulse:not(.busy):not(.hot) .k { color: var(--muted); }
  h2 { margin: 0; font-size: 26px; font-weight: 740; letter-spacing: -0.035em; line-height: 1.15;
    background: linear-gradient(95deg, var(--text) 30%, color-mix(in srgb, var(--hc) 75%, var(--text))); -webkit-background-clip: text; background-clip: text; color: transparent; }
  .head p { margin: 0; font-size: 13px; color: var(--text-2); }
  .head p b { color: var(--warn); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { display: inline-flex; align-items: center; gap: 7px; max-width: 240px; height: 30px; padding: 0 10px 0 5px; border-radius: 99px; cursor: pointer;
    border: 1px solid var(--line-2); background: color-mix(in srgb, var(--surface) 85%, transparent); color: var(--text); font: 12.5px var(--font); backdrop-filter: blur(8px);
    animation: rise 0.35s var(--ease-out) both; animation-delay: calc(var(--i) * 45ms); transition: transform var(--t) var(--spring), border-color var(--t-fast); }
  .chip:hover:not(:disabled) { transform: translateY(-1px); border-color: var(--line-3); }
  .chip:disabled { cursor: default; }
  .chip.needs-you { border-color: color-mix(in srgb, var(--warn) 45%, transparent); background: color-mix(in srgb, var(--warn-soft) 80%, var(--surface)); }
  .chip .go { display: inline-flex; align-items: center; gap: 2px; font-weight: 650; color: var(--warn); font-size: 11.5px; flex: none; }
  .more { align-self: center; font-size: 12px; color: var(--muted); }
  .radar { display: grid; gap: 6px; align-content: start; min-width: 0; }
  .rh { display: inline-flex; align-items: center; gap: 6px; font: 650 11px/1 var(--font); text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-bottom: 2px; }
  .rh :global(svg) { animation: spin 6s linear infinite; }
  .rt { --tc: var(--accent); display: flex; align-items: center; gap: 9px; min-height: 36px; padding: 5px 6px 5px 6px; border-radius: 10px;
    background: color-mix(in srgb, var(--surface) 80%, transparent); border: 1px solid color-mix(in srgb, var(--tc) 18%, var(--line)); backdrop-filter: blur(8px);
    animation: slide-in 0.4s var(--ease-out) both; animation-delay: calc(var(--i) * 70ms + 0.1s); }
  .rt.warn { --tc: var(--warn); } .rt.bad { --tc: var(--bad); } .rt.good { --tc: var(--good); }
  .ri { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 8px; flex: none; color: var(--tc); background: color-mix(in srgb, var(--tc) 13%, transparent); }
  .ri:has(:global(.av)) { background: none; }
  .tx { flex: 1; min-width: 0; font-size: 12.5px; color: var(--text-2); line-height: 1.35; }
  .tx b { color: color-mix(in srgb, var(--tc) 55%, var(--text)); font-weight: 650; }
  .ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  @media (max-width: 960px) { .pulse { grid-template-columns: minmax(0, 1fr); } }
  @keyframes beat { to { stroke-dashoffset: 0; } }
  @keyframes drift { 0% { transform: translate(0, 0) scale(1); } 100% { transform: translate(12%, 18%) scale(1.15); } }
  @keyframes ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--hc) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 7px transparent; } }
  @keyframes slide-in { from { opacity: 0; transform: translateX(10px); } }
  @media (prefers-reduced-motion: reduce) { .mesh i, .beat path, .live, .chip, .rt, .rh :global(svg) { animation: none; } }
</style>
