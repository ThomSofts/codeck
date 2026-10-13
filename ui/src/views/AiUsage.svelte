<script lang="ts">
  // Uso de IA: quanto cada projeto consome — tempo do agente trabalhando, seu tempo com o projeto na tela, custo informado
  // pela CLI, linhas alteradas e quanto de cada limite (5 h / semanal) cada projeto gastou.
  import { Gauge, RefreshCw } from "@lucide/svelte";
  import { work } from "../lib/work.svelte";
  import AiAccountCard from "../components/settings/AiAccountCard.svelte";
  import { untrack } from "svelte";
  import { get } from "../lib/api";
  import { go, soft } from "../lib/router.svelte";
  import { repos } from "../lib/repos.svelte";
  import AgentIcon from "../components/work/AgentIcon.svelte";
  import Kpi from "../components/Kpi.svelte";
  import Page from "../components/Page.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Skeleton from "../components/Skeleton.svelte";

  type G = { cost: number; sessions: number; tokens: number; workMs: number; added: number; removed: number; focusS: number; limits: Record<string, number>; name?: string };
  type Cur = { account: string; accountName: string; provider: string; window: string; used: number; resetsAt: string | null; projects: Record<string, { name: string; used: number }> };
  type R = { days: (G & { day: string })[]; projects: Record<string, G>; totals: G; sessions: number; current: Cur[]; accountInfo: Record<string, { name: string; provider: string }> };

  let days = $state("7");
  let metric = $state("work");
  let A = $state<R | { error: string } | null>(null);
  let tip = $state<{ x: number; y: number; text: string } | null>(null);
  async function load() {
    try { const r = await get<R>("ai/usage", { days }); soft(() => { A = r; }); }
    catch (e: any) { A = { error: e.message }; }
  }
  $effect(() => { void days; untrack(() => { A = null; load(); }); });
  $effect(() => { const t = setInterval(load, 30000); return () => clearInterval(t); });
  $effect(() => { if (!repos.loaded) repos.load(false); });
  const R = $derived(A && !("error" in A) ? A : null);

  const dur = (ms: number) => { const m = Math.round(ms / 60000); return m < 1 ? (ms > 0 ? "< 1 min" : "—") : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`; };
  const money = (n: number) => (n ? `US$ ${n.toFixed(2)}` : "—");
  const tok = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : n ? String(n) : "—");
  const pct = (n: number) => `${n < 10 ? n.toFixed(1).replace(".0", "") : Math.round(n)}%`;
  const fmtD = (d: string) => new Date(d + "T12:00").toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  const resetIn = (iso: string | null) => {
    if (!iso) return "";
    const ms = new Date(iso).getTime() - Date.now();
    if (ms <= 0) return "resetou";
    const h = Math.floor(ms / 36e5), m = Math.round((ms % 36e5) / 6e4);
    return h >= 24 ? `reseta ${new Date(iso).toLocaleDateString("pt-BR", { weekday: "short", hour: "2-digit", minute: "2-digit" })}` : `reseta em ${h ? h + " h " : ""}${m} min`;
  };

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
  // quem precisa de você e quem está trabalhando primeiro
  const rank = (id: string) => ({ "needs-you": 0, working: 1, done: 2, idle: 3 } as Record<string, number>)[work.activity[id]?.state || ""] ?? 4;
  const dayTip = (d: G & { day: string }) => `${fmtD(d.day)}\nAgente trabalhando: ${dur(d.workMs)}\nSeu tempo: ${dur(d.focusS * 1000)}\nCusto: ${money(d.cost)}\nSessões: ${d.sessions}`;
</script>

<Page title="Uso de IA" sub="Tempo, custo e limites gastos por projeto">
  {#snippet actions()}
    {#if work.ai.some(a => a.provider === "claude" && a.installed)}<button class="btn sm" disabled={Object.keys(work.probing).length > 0} onclick={() => work.probe()}><Gauge size={14} /> Ler limites</button>{/if}
    <button class="btn sm ghost" onclick={load}><RefreshCw size={14} /> Recarregar</button>
  {/snippet}
  <div class="toolbar">
    <Segmented bind:value={days} options={[{ value: "1", label: "Hoje" }, { value: "7", label: "7 dias" }, { value: "30", label: "30 dias" }, { value: "90", label: "90 dias" }]} />
  </div>
  <div class="scroll">
    {#if work.ai.length}
      <h3 class="acch">Contas agora <span class="tiny muted">limite, onde estão atuando e se esperam você</span></h3>
      <div class="accgrid">
        {#each [...work.ai].sort((x, y) => rank(x.id) - rank(y.id)) as a (a.id)}
          <AiAccountCard {a} compact />
        {/each}
      </div>
    {/if}
    {#if !A}<Skeleton kpis={6} rows={4} avatar={false} />
    {:else if "error" in A}<div class="err">{A.error}</div>
    {:else if R}
      <div class="kpis">
        <Kpi index={0} label="Agente trabalhando" value={dur(R.totals.workMs)} sub="da pergunta até a resposta" />
        <Kpi index={1} label="Seu tempo nos projetos" value={dur(R.totals.focusS * 1000)} sub="projeto aberto e à vista" />
        <Kpi index={2} label="Sessões de agente" value={R.sessions} sub={`${Object.keys(R.projects).length} projeto(s)`} />
        <Kpi index={3} label="Linhas alteradas" value={R.totals.added + R.totals.removed ? `+${R.totals.added} −${R.totals.removed}` : "—"} sub="pelos agentes" />
        <Kpi index={4} label="Custo informado" value={money(R.totals.cost)} sub="equivalente API (referência)" />
        <Kpi index={5} label="Tokens" value={tok(R.totals.tokens)} sub="quando a CLI informa" />
      </div>

      <div class="card lim">
        <div class="card-h"><h3>Limites agora</h3><span class="muted small">quanto da janela atual cada projeto gastou</span></div>
        <div class="card-b">
          {#each R.current as c (c.account + c.window)}
            {@const parts = Object.entries(c.projects).sort((a, b) => b[1].used - a[1].used)}
            {@const mine = parts.reduce((s, [, p]) => s + p.used, 0)}
            {@const other = Math.max(0, (c.used || 0) - mine)}
            <div class="lw">
              <div class="lh"><AgentIcon provider={c.provider} size={14} /><b>{c.accountName}</b><span class="muted">· {c.window}</span>
                <span class="grow"></span><b class="num" class:warn={c.used >= 80} class:bad={c.used >= 95}>{pct(c.used || 0)}</b><span class="tiny muted">{resetIn(c.resetsAt)}</span></div>
              <div class="track" role="img" aria-label={`${c.accountName} ${c.window}: ${pct(c.used || 0)} usado`}>
                {#each parts as [id, p] (id)}
                  <i role="presentation" style="width:{p.used}%;background:{colorOf(id)}" onmousemove={(e) => (tip = { x: e.clientX, y: e.clientY, text: `${p.name}: ${pct(p.used)} desta janela` })} onmouseleave={() => (tip = null)}></i>
                {/each}
                {#if other > 0.05}<i role="presentation" class="rest" style="width:{other}%" onmousemove={(e) => (tip = { x: e.clientX, y: e.clientY, text: `Fora do app ou antes da 1ª leitura: ${pct(other)}` })} onmouseleave={() => (tip = null)}></i>{/if}
              </div>
              {#if parts.length || other > 0.05}
                <div class="legend">
                  {#each parts as [id, p] (id)}<span><i style="background:{colorOf(id)}"></i>{p.name} <b>{pct(p.used)}</b></span>{/each}
                  {#if other > 0.05}<span><i class="rest"></i>fora do app <b>{pct(other)}</b></span>{/if}
                </div>
              {/if}
            </div>
          {:else}<div class="small muted">Nenhuma leitura de limite ainda — ela chega quando um agente Claude ou Codex responde em Projetos.</div>{/each}
        </div>
      </div>

      <div class="card">
        <div class="card-h"><h3>Por dia</h3><span class="grow"></span>
          <Segmented size="sm" bind:value={metric} options={[{ value: "work", label: "Agente trabalhando" }, { value: "focus", label: "Seu tempo" }, { value: "cost", label: "Custo" }]} /></div>
        <div class="card-b">
          <div class="cols" class:few={series.length <= 7}>
            {#each series as s (s.day)}
              <div class="c" role="img" aria-label={dayTip(s.d)} onmousemove={(e) => (tip = { x: e.clientX, y: e.clientY, text: dayTip(s.d) })} onmouseleave={() => (tip = null)}>
                {#if s.v > 0}<div class="seg" style="height:{Math.max(2, (100 * s.v) / maxV)}%"></div>{/if}
              </div>
            {/each}
          </div>
          <div class="xaxis"><span>{series.length ? fmtD(series[0].day) : ""}</span><span>máx. {fmtV(maxV)}/dia</span><span>{series.length ? fmtD(series[series.length - 1].day) : ""}</span></div>
        </div>
      </div>

      <div class="card">
        <div class="card-h"><h3>Por projeto</h3><span class="muted small">limite = soma do que o projeto gastou em cada janela no período</span></div>
        <table>
          <thead><tr><th>Projeto</th><th style="width:22%">Agente trabalhando</th><th style="width:16%">Seu tempo</th><th class="num">Sessões</th><th class="num">Linhas</th><th class="num">Custo</th><th>Limites gastos</th></tr></thead>
          <tbody>
            {#each rows as r (r.id)}
              <tr class:link={isOpen(r.id)} onclick={() => isOpen(r.id) && go("/work/" + r.id)}>
                <td><b>{r.name}</b></td>
                <td><div class="bar">{#if r.workMs}<span style="width:{(80 * r.workMs) / maxWork}%"></span>{/if}<b>{dur(r.workMs)}</b></div></td>
                <td><div class="bar you">{#if r.focusS}<span style="width:{(80 * r.focusS) / maxFocus}%"></span>{/if}<b>{dur(r.focusS * 1000)}</b></div></td>
                <td class="num">{r.sessions || "—"}</td>
                <td class="num">{r.added + r.removed ? `+${r.added} −${r.removed}` : "—"}</td>
                <td class="num">{money(r.cost)}</td>
                <td class="small">{#each Object.entries(r.limits).sort((a, b) => b[1] - a[1]) as [k, v] (k)}<span class="lt">{accName(k)} {k.split("|")[1]} <b>{pct(v)}</b></span>{:else}<span class="muted">—</span>{/each}</td>
              </tr>
            {:else}<tr><td colspan="7" class="muted small">Nada no período. O uso aparece quando você trabalha com agentes em Projetos.</td></tr>{/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>
</Page>
{#if tip}<div class="tip" style="left:{tip.x + 12}px;top:{tip.y + 14}px">{tip.text}</div>{/if}

<style>
  .acch { display: flex; align-items: baseline; gap: 10px; margin: 4px 2px 10px; font-size: 14px; }
  .accgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; margin-bottom: 18px; }
  .toolbar { display: flex; gap: 8px; margin-bottom: 12px; flex: none; }
  .scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; padding-right: 2px; display: grid; gap: 14px; align-content: start; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
  .err { color: var(--bad); }
  .grow { flex: 1; }
  .lim .card-b { display: grid; gap: 16px; }
  .lw { display: grid; gap: 7px; }
  .lh { display: flex; align-items: center; gap: 7px; font-size: 13px; }
  .lh .num { font-variant-numeric: tabular-nums; }
  .lh .warn { color: var(--warn); } .lh .bad { color: var(--bad); }
  .track { display: flex; gap: 2px; height: 12px; border-radius: 4px; background: var(--surface-3); overflow: hidden; }
  .track i { height: 100%; min-width: 3px; animation: grow-x 0.6s var(--ease-out) both; transform-origin: left; }
  .track i:first-child { border-radius: 4px 0 0 4px; }
  .rest { background: repeating-linear-gradient(135deg, var(--line-3) 0 3px, transparent 3px 6px); }
  .legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12px; color: var(--text-2); }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .legend i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
  .legend b { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }
  .cols { display: flex; align-items: flex-end; gap: 2px; height: 160px; border-bottom: 1px solid var(--line-2); }
  .cols.few { gap: 10px; }
  .c { flex: 1; height: 100%; display: flex; align-items: flex-end; min-width: 2px; border-radius: 4px 4px 0 0; transition: background var(--t-fast); }
  .c:hover { background: var(--surface-2); }
  .seg { width: 100%; background: var(--accent); border-radius: 4px 4px 0 0; animation: grow 0.6s var(--ease-out) both; transform-origin: bottom; }
  .xaxis { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); padding-top: 6px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); padding: 10px 14px; white-space: nowrap; }
  td { padding: 8px 14px; border-top: 1px solid var(--line); font-size: 13px; }
  tr.link { cursor: pointer; } tr.link:hover td { background: var(--surface-2); }
  .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .bar { display: flex; align-items: center; gap: 8px; }
  .bar span { height: 8px; border-radius: 0 4px 4px 0; background: var(--accent); min-width: 2px; }
  .bar.you span { background: var(--text-3, var(--muted)); }
  .bar b { font-weight: 600; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .lt { display: inline-block; margin-right: 10px; white-space: nowrap; color: var(--text-2); }
  .lt b { color: var(--text); }
  .tip { position: fixed; z-index: 70; pointer-events: none; white-space: pre; background: var(--text); color: var(--bg); font-size: 12px; padding: 6px 9px; border-radius: 7px; box-shadow: var(--shadow-2); }
  @keyframes grow { from { transform: scaleY(0); } }
  @keyframes grow-x { from { transform: scaleX(0); } }
</style>
