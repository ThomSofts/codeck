<script lang="ts">
  // Uso de IA: as contas agora numa tabela alinhada (cada limite com o quanto usou, quem gastou por projeto e quando
  // reseta; onde está atuando) e quanto cada projeto consome — tempo do agente trabalhando, seu tempo com o projeto na
  // tela, custo informado pela CLI, linhas alteradas e quanto de cada limite (5 h / semanal) cada projeto gastou.
  import { Gauge, RefreshCw } from "@lucide/svelte";
  import { work } from "../lib/work.svelte";
  import AccountRow from "../components/ai/AccountRow.svelte";
  import { untrack } from "svelte";
  import { get } from "../lib/api";
  import { go, soft } from "../lib/router.svelte";
  import { repos } from "../lib/repos.svelte";
  import AgentIcon from "../components/work/AgentIcon.svelte";
  import Page from "../components/Page.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Skeleton from "../components/Skeleton.svelte";
  import { clock, headroom, stateRank } from "../components/ai/limits.svelte";

  type G = { cost: number; sessions: number; tokens: number; workMs: number; added: number; removed: number; focusS: number; limits: Record<string, number>; name?: string };
  type Cur = { account: string; accountName: string; provider: string; window: string; used: number; resetsAt: string | null; projects: Record<string, { name: string; used: number }> };
  type R = { days: (G & { day: string })[]; projects: Record<string, G>; totals: G; sessions: number; current: Cur[]; accountInfo: Record<string, { name: string; provider: string }> };

  let days = $state("7");
  let metric = $state("work");
  let sortAcc = $state((() => { try { return localStorage.getItem("codeck.ai.sort") || "state"; } catch { return "state"; } })());
  $effect(() => { const v = sortAcc; try { localStorage.setItem("codeck.ai.sort", v); } catch { /* sem armazenamento */ } });
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
  // quanto cada projeto gastou de cada janela, por conta (a leitura de uso; os limites ao vivo vêm de work.ai)
  const breakdown = $derived.by(() => {
    const m: Record<string, Record<string, Record<string, { name: string; used: number }>>> = {};
    for (const c of R?.current || []) (m[c.account] ||= {})[c.window] = c.projects;
    return m;
  });
  const lines = $derived(R ? R.totals.added + R.totals.removed : 0);
  const dayTip = (d: G & { day: string }) => `${wday(d.day)} ${fmtD(d.day)}${d.day === today ? " (hoje)" : ""}\nAgente trabalhando: ${dur(d.workMs)}\nSeu tempo: ${dur(d.focusS * 1000)}\nCusto: ${money(d.cost)}\nSessões: ${d.sessions}`;
</script>

<Page title="Uso de IA" sub="Contas, limites e o que cada projeto consome">
  {#snippet actions()}
    {#if work.ai.some(a => a.provider === "claude" && a.installed)}<button class="btn sm" disabled={Object.keys(work.probing).length > 0} onclick={() => work.probe()}><Gauge size={14} class={Object.keys(work.probing).length ? "spin" : ""} /> Ler limites</button>{/if}
    <button class="btn sm ghost" onclick={load}><RefreshCw size={14} /> Recarregar</button>
  {/snippet}
  <div class="scroll">
    {#if work.ai.length}
      <div class="card accts">
        <div class="card-h"><h3>Contas</h3><span class="muted small hide-n">limites, quando resetam e onde estão atuando</span><span class="grow"></span>
          <Segmented size="sm" bind:value={sortAcc} options={[{ value: "state", label: "Atividade" }, { value: "free", label: "Mais folga" }, { value: "tight", label: "Perto do limite" }]} /></div>
        <div class="alist">
          <div class="ahead" aria-hidden="true"><span>Conta</span><span>Limites · usado por projeto e reset</span><span>Atuando em</span><span></span></div>
          {#each accounts as a, i (a.id)}
            <AccountRow {a} index={i} breakdown={breakdown[a.id]} {colorOf} ontip={(t) => (tip = t)} />
          {/each}
        </div>
      </div>
    {/if}

    <div class="sech period">
      <h3>Consumo</h3><span class="small muted">tempo, custo e limites por projeto</span><span class="grow"></span>
      <Segmented size="sm" bind:value={days} options={[{ value: "1", label: "Hoje" }, { value: "7", label: "7 dias" }, { value: "30", label: "30 dias" }, { value: "90", label: "90 dias" }]} />
    </div>
    {#if !A}<Skeleton kpis={6} rows={4} avatar={false} />
    {:else if "error" in A}<div class="err">{A.error}</div>
    {:else if R}
      <div class="card kpis">
        <div class="kpi"><span class="kl">Agente trabalhando</span><b>{dur(R.totals.workMs)}</b><span class="ks">da pergunta até a resposta</span></div>
        <div class="kpi"><span class="kl">Seu tempo nos projetos</span><b>{dur(R.totals.focusS * 1000)}</b><span class="ks">projeto aberto e à vista</span></div>
        <div class="kpi"><span class="kl">Sessões de agente</span><b>{R.sessions || "—"}</b><span class="ks">{Object.keys(R.projects).length} projeto(s)</span></div>
        <div class="kpi"><span class="kl">Linhas alteradas</span><b>{#if lines}<span class="add">+{R.totals.added}</span> <span class="del">−{R.totals.removed}</span>{:else}—{/if}</b><span class="ks">pelos agentes</span></div>
        <div class="kpi"><span class="kl">Custo informado</span><b>{money(R.totals.cost)}</b><span class="ks">equivalente API (referência)</span></div>
        <div class="kpi"><span class="kl">Tokens</span><b>{tok(R.totals.tokens)}</b><span class="ks">quando a CLI informa</span></div>
      </div>
      {#if !R.current.length}<div class="small muted note">Nenhuma leitura de limite ainda — ela chega quando um agente Claude ou Codex responde em Projetos.</div>{/if}

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
  .scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; padding-right: 2px; display: grid; grid-template-columns: minmax(0, 1fr); grid-auto-rows: max-content; gap: 14px; align-content: start; padding-bottom: 20px; }
  .sech { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 2px 2px -2px; }
  .sech h3 { margin: 0; font-size: 14px; font-weight: 650; }
  .sech.period { margin-top: 10px; }
  /* contas: a lista é o container das linhas (AccountRow muda o arranjo por container query) */
  .accts { overflow: hidden; }
  .accts .card-h { padding-block: 8px; row-gap: 8px; }
  .alist { container: accts / inline-size; }
  .ahead { display: grid; grid-template-columns: minmax(180px, 0.95fr) minmax(320px, 2.3fr) minmax(170px, 1fr) 60px; column-gap: 22px; padding: 9px 16px 7px;
    font: 600 11px/1.2 var(--font); color: var(--muted); }
  @container accts (max-width: 860px) { .ahead { display: none; } }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1px; background: var(--line); overflow: hidden; }
  .kpi { display: grid; gap: 3px; align-content: start; padding: 12px 16px 13px; background: var(--surface); min-width: 0; }
  .kpi .kl { font-size: 12px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .kpi b { font-size: 20px; font-weight: 680; letter-spacing: -0.025em; font-variant-numeric: tabular-nums; line-height: 1.25; white-space: nowrap; }
  .kpi .ks { font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .note { margin: -4px 2px 0; }
  .err { color: var(--bad); }
  .grow { flex: 1; }
  @media (max-width: 720px) { .hide-n { display: none; } }
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
  @media (prefers-reduced-motion: reduce) { .seg, .bar span, tbody tr { animation: none; } }
</style>
