<script lang="ts">
  // Uso de IA: as contas agora (limite, contagem para o reset, onde estão atuando) e quanto cada projeto consome —
  // tempo do agente trabalhando, seu tempo com o projeto na tela, custo informado pela CLI, linhas alteradas e quanto
  // de cada limite (5 h / semanal) cada projeto gastou.
  import { Bot, Clock3, Coins, Gauge, GitCompareArrows, Hash, Layers, RefreshCw, Timer } from "@lucide/svelte";
  import { work } from "../lib/work.svelte";
  import AiAccountCard from "../components/settings/AiAccountCard.svelte";
  import { untrack } from "svelte";
  import { get } from "../lib/api";
  import { go, soft } from "../lib/router.svelte";
  import { repos } from "../lib/repos.svelte";
  import AgentIcon from "../components/work/AgentIcon.svelte";
  import Page from "../components/Page.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Skeleton from "../components/Skeleton.svelte";
  import Stat from "../components/ai/Stat.svelte";
  import { clock, headroom, resetLabel, stateRank, tone } from "../components/ai/limits.svelte";

  type G = { cost: number; sessions: number; tokens: number; workMs: number; added: number; removed: number; focusS: number; limits: Record<string, number>; name?: string };
  type Cur = { account: string; accountName: string; provider: string; window: string; used: number; resetsAt: string | null; projects: Record<string, { name: string; used: number }> };
  type R = { days: (G & { day: string })[]; projects: Record<string, G>; totals: G; sessions: number; current: Cur[]; accountInfo: Record<string, { name: string; provider: string }> };

  let days = $state("7");
  let metric = $state("work");
  let sortAcc = $state((() => { try { return localStorage.getItem("codeck.ai.sort") || "state"; } catch { return "state"; } })());
  $effect(() => { const v = sortAcc; try { localStorage.setItem("codeck.ai.sort", v); } catch { /* sem armazenamento */ } });
  let A = $state<R | { error: string } | null>(null);
  let tip = $state<{ x: number; y: number; text: string } | null>(null);
  let hover = $state<string | null>(null);
  async function load() {
    try { const r = await get<R>("ai/usage", { days }); soft(() => { A = r; }); }
    catch (e: any) { A = { error: e.message }; }
  }
  $effect(() => { void days; untrack(() => { A = null; load(); }); });
  $effect(() => { const t = setInterval(load, 30000); return () => clearInterval(t); });
  $effect(() => { if (!repos.loaded) repos.load(false); });
  const R = $derived(A && !("error" in A) ? A : null);

  const dur = (ms: number) => { const m = Math.round(ms / 60000); return m < 1 ? (ms > 0 ? "< 1 min" : "—") : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`; };
  const money = (n: number) => (n >= 0.005 ? `US$ ${n.toFixed(2)}` : "—");
  const tok = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : n >= 1 ? String(Math.round(n)) : "—");
  const pct = (n: number) => `${n < 10 ? n.toFixed(1).replace(".0", "") : Math.round(n)}%`;
  const fmtD = (d: string) => new Date(d + "T12:00").toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  const wday = (d: string) => new Date(d + "T12:00").toLocaleDateString("pt-BR", { weekday: "short" }).replace(".", "");
  const today = (() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; })();

  const rows = $derived(R ? Object.entries(R.projects).map(([id, g]) => ({ id, ...g })).sort((a, b) => b.workMs - a.workMs || b.focusS - a.focusS || b.cost - a.cost) : []);
  const maxWork = $derived(Math.max(1, ...rows.map(r => r.workMs)));
  const maxFocus = $derived(Math.max(1, ...rows.map(r => r.focusS)));
  const isOpen = (id: string) => repos.local.some(r => r.id === id);   // registros antigos guardavam só o nome
  const accName = (k: string) => R?.accountInfo[k.split("|")[0]]?.name || k.split("|")[0];

  // cor por projeto: segue o projeto (ordem alfabética entre os que aparecem nos limites), nunca a posição na barra.
  // Paleta categórica validada (6 cores, CVD e contraste) nos dois temas — tokens --cat1..6 no app.css.
  const SLOTS = 6;
  const colorOf = $derived.by(() => {
    const names = [...new Set((R?.current || []).flatMap(c => Object.keys(c.projects)))].sort((a, b) => a.localeCompare(b));
    return (id: string) => { const i = names.indexOf(id); return i >= 0 && i < SLOTS ? `var(--cat${i + 1})` : "var(--cat-other)"; };
  });

  const series = $derived(R ? R.days.map(d => ({ day: d.day, v: metric === "work" ? d.workMs / 6e4 : metric === "focus" ? d.focusS / 60 : d.cost, d })) : []);
  const maxV = $derived(Math.max(1e-6, ...series.map(s => s.v)));
  const fmtV = (v: number) => (metric === "cost" ? money(v) : dur(v * 6e4));
  const avgV = $derived(series.length ? series.reduce((n, s) => n + s.v, 0) / series.length : 0);
  const labelEvery = $derived(series.length <= 7 ? 1 : series.length <= 31 ? 5 : 15);
  // contas: quem precisa de você/está trabalhando primeiro, ou por folga
  const accounts = $derived.by(() => {
    const list = [...work.ai].filter(a => a.installed || a.usage);
    const h = (id: string) => headroom(work.ai.find(x => x.id === id)!, clock.now) ?? -1;
    if (sortAcc === "free") return list.sort((x, y) => h(y.id) - h(x.id));
    if (sortAcc === "tight") return list.sort((x, y) => (h(x.id) < 0 ? 999 : h(x.id)) - (h(y.id) < 0 ? 999 : h(y.id)));
    return list.sort((x, y) => stateRank(work.activity[x.id]?.state) - stateRank(work.activity[y.id]?.state) || h(y.id) - h(x.id));
  });
  const dayTip = (d: G & { day: string }) => `${wday(d.day)} ${fmtD(d.day)}${d.day === today ? " (hoje)" : ""}\nAgente trabalhando: ${dur(d.workMs)}\nSeu tempo: ${dur(d.focusS * 1000)}\nCusto: ${money(d.cost)}\nSessões: ${d.sessions}`;
</script>

<Page title="Uso de IA" sub="Contas, limites e o que cada projeto consome">
  {#snippet actions()}
    {#if work.ai.some(a => a.provider === "claude" && a.installed)}<button class="btn sm" disabled={Object.keys(work.probing).length > 0} onclick={() => work.probe()}><Gauge size={14} class={Object.keys(work.probing).length ? "spin" : ""} /> Ler limites</button>{/if}
    <button class="btn sm ghost" onclick={load}><RefreshCw size={14} /> Recarregar</button>
  {/snippet}
  <div class="scroll">
    {#if work.ai.length}
      <div class="sech">
        <h3>Contas agora</h3><span class="small muted">limite, quando reseta, onde estão atuando</span>
        <span class="grow"></span>
        <Segmented size="sm" bind:value={sortAcc} options={[{ value: "state", label: "Atividade" }, { value: "free", label: "Mais folga" }, { value: "tight", label: "Perto do limite" }]} />
      </div>
      <div class="accgrid">
        {#each accounts as a (a.id)}
          <AiAccountCard {a} compact />
        {/each}
      </div>
    {/if}

    <div class="sech period">
      <h3>Consumo</h3><span class="small muted">tempo, custo e limites por projeto</span><span class="grow"></span>
      <Segmented size="sm" bind:value={days} options={[{ value: "1", label: "Hoje" }, { value: "7", label: "7 dias" }, { value: "30", label: "30 dias" }, { value: "90", label: "90 dias" }]} />
    </div>
    {#if !A}<Skeleton kpis={6} rows={4} avatar={false} />
    {:else if "error" in A}<div class="err">{A.error}</div>
    {:else if R}
      <div class="kpis">
        <Stat index={0} icon={Bot} label="Agente trabalhando" value={R.totals.workMs} fmt={dur} sub="da pergunta até a resposta" />
        <Stat index={1} icon={Timer} label="Seu tempo nos projetos" value={R.totals.focusS * 1000} fmt={dur} sub="projeto aberto e à vista" tone="muted" />
        <Stat index={2} icon={Layers} label="Sessões de agente" value={R.sessions} sub={`${Object.keys(R.projects).length} projeto(s)`} tone="muted" />
        <Stat index={3} icon={GitCompareArrows} label="Linhas alteradas" value={R.totals.added + R.totals.removed} fmt={(n) => (n >= 1 ? `+${Math.round((R!.totals.added * n) / Math.max(1, R!.totals.added + R!.totals.removed))} −${Math.round((R!.totals.removed * n) / Math.max(1, R!.totals.added + R!.totals.removed))}` : "—")} sub="pelos agentes" tone="good" />
        <Stat index={4} icon={Coins} label="Custo informado" value={R.totals.cost} fmt={money} sub="equivalente API (referência)" tone="warn" />
        <Stat index={5} icon={Hash} label="Tokens" value={R.totals.tokens} fmt={tok} sub="quando a CLI informa" tone="muted" />
      </div>

      <div class="card lim">
        <div class="card-h"><h3>Limites agora</h3><span class="muted small">quanto da janela atual cada projeto gastou</span></div>
        <div class="card-b">
          {#each R.current as c, ci (c.account + c.window)}
            {@const parts = Object.entries(c.projects).sort((a, b) => b[1].used - a[1].used)}
            {@const mine = parts.reduce((s, [, p]) => s + p.used, 0)}
            {@const other = Math.max(0, (c.used || 0) - mine)}
            <div class="lw" style="--i:{ci}">
              <div class="lh"><AgentIcon provider={c.provider} size={14} /><b>{c.accountName}</b><span class="muted">· {c.window}</span>
                <span class="grow"></span><b class="num {tone(c.used)}">{pct(c.used || 0)}</b><span class="tiny muted cd"><Clock3 size={10} /> {resetLabel(c.resetsAt, clock.now)}</span></div>
              <div class="track" role="img" aria-label={`${c.accountName} ${c.window}: ${pct(c.used || 0)} usado`}>
                {#each parts as [id, p] (id)}
                  <i role="presentation" class:dim={hover && hover !== id} style="width:{p.used}%;background:{colorOf(id)}" onmousemove={(e) => { hover = id; tip = { x: e.clientX, y: e.clientY, text: `${p.name}: ${pct(p.used)} desta janela` }; }} onmouseleave={() => { tip = null; hover = null; }}></i>
                {/each}
                {#if other > 0.05}<i role="presentation" class="rest" class:dim={hover && hover !== "~"} style="width:{other}%" onmousemove={(e) => { hover = "~"; tip = { x: e.clientX, y: e.clientY, text: `Fora do app ou antes da 1ª leitura: ${pct(other)}` }; }} onmouseleave={() => { tip = null; hover = null; }}></i>{/if}
                {#if (c.used || 0) < 100}<span class="free" style="width:{100 - (c.used || 0)}%"></span>{/if}
              </div>
              {#if parts.length || other > 0.05}
                <div class="legend">
                  {#each parts as [id, p] (id)}<span role="presentation" class:dim={hover && hover !== id} onmouseenter={() => (hover = id)} onmouseleave={() => (hover = null)}><i style="background:{colorOf(id)}"></i>{p.name} <b>{pct(p.used)}</b></span>{/each}
                  {#if other > 0.05}<span class:dim={hover && hover !== "~"}><i class="rest"></i>fora do app <b>{pct(other)}</b></span>{/if}
                </div>
              {/if}
            </div>
          {:else}<div class="small muted">Nenhuma leitura de limite ainda — ela chega quando um agente Claude ou Codex responde em Projetos.</div>{/each}
        </div>
      </div>

      <div class="card">
        <div class="card-h"><h3>Por dia</h3><span class="muted small">média {fmtV(avgV)}/dia</span><span class="grow"></span>
          <Segmented size="sm" bind:value={metric} options={[{ value: "work", label: "Agente trabalhando" }, { value: "focus", label: "Seu tempo" }, { value: "cost", label: "Custo" }]} /></div>
        <div class="card-b">
          <div class="chart">
            <div class="yl"><span>{fmtV(maxV)}</span><span>{fmtV(maxV / 2)}</span><span>0</span></div>
            <div class="plot">
              <div class="grid-l" style="bottom:50%"></div><div class="grid-l" style="bottom:100%"></div>
              {#if avgV > 0}<div class="avg" style="bottom:{(100 * avgV) / maxV}%"><span>média</span></div>{/if}
              <div class="cols" class:few={series.length <= 7}>
                {#key metric + days}
                  {#each series as s, i (s.day)}
                    <div class="c" class:today={s.day === today} role="img" aria-label={dayTip(s.d)} onmousemove={(e) => (tip = { x: e.clientX, y: e.clientY, text: dayTip(s.d) })} onmouseleave={() => (tip = null)}>
                      {#if s.v > 0}<div class="seg" style="height:{Math.max(2, (100 * s.v) / maxV)}%;--i:{i}"></div>{/if}
                    </div>
                  {/each}
                {/key}
              </div>
            </div>
            <span></span>
          <div class="xaxis" class:few={series.length <= 7}>
            {#each series as s, i (s.day)}<span class:today={s.day === today}>{i % labelEvery === 0 || s.day === today ? (s.day === today ? "hoje" : series.length <= 7 ? `${wday(s.day)} ${fmtD(s.day).slice(0, 2)}` : fmtD(s.day)) : ""}</span>{/each}
          </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-h"><h3>Por projeto</h3><span class="muted small">limite = soma do que o projeto gastou em cada janela no período</span></div>
        <div class="tw">
          <table>
            <thead><tr><th>Projeto</th><th style="width:22%">Agente trabalhando</th><th style="width:16%">Seu tempo</th><th class="num">Sessões</th><th class="num">Linhas</th><th class="num">Custo</th><th>Limites gastos</th></tr></thead>
            <tbody>
              {#each rows as r, ri (r.id)}
                <tr class:link={isOpen(r.id)} style="--i:{ri}" onclick={() => isOpen(r.id) && go("/work/" + r.id)}>
                  <td><b>{r.name}</b></td>
                  <td><div class="bar">{#if r.workMs}<span style="width:{(80 * r.workMs) / maxWork}%"></span>{/if}<b>{dur(r.workMs)}</b></div></td>
                  <td><div class="bar you">{#if r.focusS}<span style="width:{(80 * r.focusS) / maxFocus}%"></span>{/if}<b>{dur(r.focusS * 1000)}</b></div></td>
                  <td class="num">{r.sessions || "—"}</td>
                  <td class="num">{#if r.added + r.removed}<span class="add">+{r.added}</span> <span class="del">−{r.removed}</span>{:else}—{/if}</td>
                  <td class="num">{money(r.cost)}</td>
                  <td class="small">{#each Object.entries(r.limits).sort((a, b) => b[1] - a[1]) as [k, v] (k)}<span class="lt">{accName(k)} <span class="muted">{k.split("|")[1]}</span> <b>{pct(v)}</b></span>{:else}<span class="muted">—</span>{/each}</td>
                </tr>
              {:else}<tr><td colspan="7" class="muted small">Nada no período. O uso aparece quando você trabalha com agentes em Projetos.</td></tr>{/each}
            </tbody>
          </table>
        </div>
      </div>
    {/if}
  </div>
</Page>
{#if tip}<div class="tip" style="left:{tip.x + 12}px;top:{tip.y + 14}px">{tip.text}</div>{/if}

<style>
  .scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; padding-right: 2px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; align-content: start; padding-bottom: 20px; }
  .sech { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 2px 2px -2px; }
  .sech h3 { margin: 0; font-size: 14px; font-weight: 650; }
  .sech.period { margin-top: 10px; }
  .accgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 10px; }
  .err { color: var(--bad); }
  .grow { flex: 1; }
  .lim .card-b { display: grid; gap: 18px; }
  .lw { display: grid; gap: 7px; animation: rise 0.35s var(--ease-out) both; animation-delay: calc(var(--i) * 50ms); }
  .lh { display: flex; align-items: center; gap: 7px; font-size: 13px; }
  .lh .num { font-variant-numeric: tabular-nums; }
  .lh .num.good { color: var(--text); } .lh .num.warn { color: var(--warn); } .lh .num.bad { color: var(--bad); }
  .cd { display: inline-flex; align-items: center; gap: 3px; font-variant-numeric: tabular-nums; min-width: 92px; justify-content: flex-end; }
  .track { display: flex; gap: 2px; height: 14px; overflow: hidden; border-radius: 4px; }
  .track i { height: 100%; min-width: 3px; animation: grow-x 0.7s var(--ease-out) both; transform-origin: left; transition: opacity var(--t); }
  .track i:first-child { border-radius: 4px 0 0 4px; }
  .track .free { flex: none; height: 100%; border-radius: 0 4px 4px 0; background: var(--surface-3); }
  .track i.dim, .legend .dim { opacity: 0.35; }
  .rest { background: repeating-linear-gradient(135deg, var(--line-3) 0 3px, transparent 3px 6px); }
  .legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12px; color: var(--text-2); }
  .legend span { display: inline-flex; align-items: center; gap: 6px; transition: opacity var(--t); cursor: default; }
  .legend i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
  .legend b { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }
  .chart { display: grid; grid-template-columns: auto 1fr; column-gap: 10px; }
  .yl { display: flex; flex-direction: column; justify-content: space-between; height: 170px; font-size: 10.5px; color: var(--faint); text-align: right; font-variant-numeric: tabular-nums;
    margin-top: -6px; margin-bottom: -6px; }
  .plot { position: relative; height: 170px; }
  .grid-l { position: absolute; left: 0; right: 0; height: 0; border-top: 1px dashed var(--line); }
  .avg { position: absolute; left: 0; right: 0; height: 0; border-top: 1px dashed var(--line-3); z-index: 1; pointer-events: none; }
  .avg span { position: absolute; right: 0; top: -15px; font-size: 10px; color: var(--muted); background: var(--surface); padding: 0 4px; }
  .cols { position: absolute; inset: 0; display: flex; align-items: flex-end; gap: 2px; border-bottom: 1px solid var(--line-2); }
  .cols.few { gap: 14px; }
  .c { flex: 1; height: 100%; display: flex; align-items: flex-end; min-width: 2px; border-radius: 4px 4px 0 0; transition: background var(--t-fast); cursor: default; }
  .c:hover { background: var(--surface-2); }
  .seg { width: 100%; background: color-mix(in srgb, var(--accent) 55%, var(--surface)); border-radius: 4px 4px 0 0;
    animation: grow 0.6s var(--ease-out) both; animation-delay: calc(min(var(--i), 30) * 18ms); transform-origin: bottom; transition: background var(--t-fast); }
  .c:hover .seg { background: color-mix(in srgb, var(--accent) 80%, var(--surface)); }
  .c.today .seg { background: var(--accent); box-shadow: 0 -2px 14px -4px color-mix(in srgb, var(--accent) 70%, transparent); }
  .xaxis { display: flex; gap: 2px; margin-left: 0; padding-top: 6px; font-size: 10.5px; color: var(--muted); }
  .xaxis.few { gap: 14px; }
  .xaxis span { flex: 1; min-width: 0; white-space: nowrap; overflow: visible; }
  .xaxis.few span { text-align: center; }
  .xaxis .today { color: var(--accent); font-weight: 650; }
  .tw { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); padding: 10px 14px; white-space: nowrap; }
  td { padding: 9px 14px; border-top: 1px solid var(--line); font-size: 13px; }
  tbody tr { animation: fade 0.3s var(--ease-out) both; animation-delay: calc(min(var(--i), 20) * 25ms); }
  tr.link { cursor: pointer; } tr.link:hover td { background: var(--surface-2); }
  .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .add { color: var(--good); } .del { color: var(--bad); }
  .bar { display: flex; align-items: center; gap: 8px; }
  .bar span { height: 8px; border-radius: 0 4px 4px 0; background: var(--accent); min-width: 2px; animation: grow-x 0.6s var(--ease-out) both; transform-origin: left; }
  .bar.you span { background: var(--muted); }
  .bar b { font-weight: 600; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .lt { display: inline-block; margin-right: 10px; white-space: nowrap; color: var(--text-2); }
  .lt b { color: var(--text); }
  .tip { position: fixed; z-index: 70; pointer-events: none; white-space: pre; background: var(--text); color: var(--bg); font-size: 12px; padding: 6px 9px; border-radius: 7px; box-shadow: var(--shadow-2); }
  @keyframes grow { from { transform: scaleY(0); } }
  @keyframes grow-x { from { transform: scaleX(0); } }
  @media (prefers-reduced-motion: reduce) { .seg, .track i, .bar span, .lw, tbody tr { animation: none; } }
</style>
