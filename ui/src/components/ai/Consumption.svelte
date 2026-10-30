<script lang="ts">
  // Consumo das IAs: modelo, effort e tokens de cada resposta, de todas as contas — inclusive o uso fora do Codeck —,
  // lidos dos registros das CLIs (aiusage.py). Em cima, o que os números dizem (onde atuar); depois o dia a dia, o
  // de-para por modelo·effort (o que cada um custa por resposta, por sessão, no limite e em linhas), as contas e o Cursor.
  import { RefreshCw } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { consumption, effortLabel, modelLabel, num, PROV, tok, usd, type G } from "../../lib/consumption.svelte";
  import { ago } from "../../lib/format";
  import Segmented from "../Segmented.svelte";
  import Skeleton from "../Skeleton.svelte";

  let days = $state(String(consumption.days));
  $effect(() => { const d = Number(days); untrack(() => consumption.load(d)); });
  $effect(() => { const t = setInterval(() => consumption.load(consumption.days, true), 120000); return () => clearInterval(t); });
  const R = $derived(consumption.data);

  // ------------------------------------------------------------ por dia (barras empilhadas por CLI)
  let metric = $state<"tokens" | "cost" | "n">("tokens");
  const provs = $derived(R ? Object.keys(R.provider).sort((a, b) => R.provider[b].tokens - R.provider[a].tokens) : []);
  const val = (g: G | undefined) => (!g ? 0 : metric === "tokens" ? g.tokens : metric === "cost" ? g.cost || 0 : g.n);
  const dayTotal = (s: any) => provs.reduce((t, p) => t + val(s[p]), 0);
  const maxDay = $derived(R ? Math.max(1e-9, ...R.series.map(dayTotal)) : 1);
  const fmt = (v: number) => (metric === "tokens" ? tok(v) : metric === "cost" ? usd(v) : num(v));
  const fmtD = (d: string) => new Date(d + "T12:00").toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  const every = $derived(!R ? 1 : R.series.length <= 7 ? 1 : R.series.length <= 31 ? 5 : 15);
  let tip = $state<{ x: number; y: number; text: string } | null>(null);
  function dayTip(s: any) {
    const parts = provs.filter(p => s[p]).map(p => `${PROV[p]?.label || p}: ${fmt(val(s[p]))}${metric === "tokens" && s[p].cacheHit != null ? ` (${Math.round(s[p].cacheHit)}% cache)` : ""}`);
    return `${fmtD(s.day)}\n${parts.length ? parts.join("\n") : "sem uso"}`;
  }

  // ------------------------------------------------------------ modelo · effort
  type Row = { key: string; prov: string; model: string; effort: string; g: G; ln: any };
  const rows = $derived<Row[]>(R ? Object.entries(R.effort).map(([key, g]) => {
    const [prov, model, effort] = key.split("|");
    return { key, prov, model, effort, g, ln: R.lines[key] };
  }).sort((a, b) => b.g.tokens - a.g.tokens) : []);
  const maxShare = $derived(Math.max(1, ...rows.map(r => r.g.tokens)));
  const share = (t: number) => (R?.total.tokens ? Math.round((t / R.total.tokens) * 100) : 0);
  const accRows = $derived(R ? Object.entries(R.accounts).filter(([, a]) => a.week || a.last).sort((a, b) => (b[1].week?.tokens || 0) - (a[1].week?.tokens || 0)) : []);
  const projRows = $derived(R ? Object.entries(R.project).sort((a, b) => b[1].tokens - a[1].tokens).slice(0, 12) : []);
  const cursorModels = $derived(R ? Object.entries(R.cursor.models).sort((a, b) => b[1].chunks - a[1].chunks) : []);
  const cc = $derived(R?.cursor.commits);
  const TONE: Record<string, string> = { info: "accent", warn: "warn", good: "good", bad: "bad" };
</script>

<section class="cons">
  <div class="head">
    <div>
      <h3>Consumo das IAs</h3>
      <p class="muted small">Modelo, effort e tokens de cada resposta — de todas as contas, também o uso fora do Codeck.
        {#if R?.scan.oldest}Base desde {fmtD(R.scan.oldest)}{/if}{#if R?.scan.at} · lida {ago(new Date(R.scan.at * 1000).toISOString())}{/if}</p>
    </div>
    <span class="grow"></span>
    <Segmented size="sm" bind:value={days} options={[{ value: "7", label: "7 dias" }, { value: "30", label: "30 dias" }, { value: "90", label: "90 dias" }, { value: "365", label: "1 ano" }]} />
    <button class="btn sm ghost icon" title="Ler agora o que as CLIs escreveram" aria-label="Ler agora" onclick={() => consumption.scan()}>
      <RefreshCw size={14} class={consumption.loading || R?.scan.scanning ? "spin" : ""} /></button>
  </div>

  {#if !R}
    {#if consumption.error}<div class="err">{consumption.error}</div>{:else}<Skeleton kpis={4} rows={5} avatar={false} />{/if}
  {:else if !R.total.n && !cursorModels.length}
    <div class="card empty">
      <b>{R.scan.scanning || !R.scan.at ? "Lendo os registros das CLIs…" : "Nenhum uso no período"}</b>
      <span class="muted small">O Codeck lê as conversas do Claude Code e do Codex nas pastas de cada conta e o banco do Cursor — a primeira leitura leva alguns segundos.</span>
    </div>
  {:else}
    <div class="card kpis">
      <div class="kpi"><span class="kl">Respostas</span><b>{num(R.total.n)}</b><span class="ks">{R.total.sessions} sessões</span></div>
      <div class="kpi" title="Entrada + saída + cache (lido e escrito)"><span class="kl">Tokens</span><b>{tok(R.total.tokens)}</b>
        <span class="ks">{R.total.cacheHit != null ? `${Math.round(R.total.cacheHit)}% do contexto veio do cache` : ""}</span></div>
      <div class="kpi" title="Saída = o que a IA escreveu (inclui o raciocínio)"><span class="kl">Saída por resposta</span><b>{tok(R.total.outPerCall)}</b>
        <span class="ks">{tok(R.total.perCall)} lidos por resposta</span></div>
      <div class="kpi" title="Preço de API da tabela oficial da Anthropic — no plano de assinatura é só referência para comparar modelos e effort. Modelos sem preço conhecido (Codex) ficam de fora.">
        <span class="kl">Equivalente em API</span><b>{usd(R.total.cost)}</b><span class="ks">{R.total.costPerSession != null ? `${usd(R.total.costPerSession)} por sessão` : "referência"}</span></div>
    </div>

    {#if R.insights.length}
      <div class="ins">
        {#each R.insights as i (i.title)}
          <div class="in {TONE[i.tone]}"><b>{i.title}</b><span>{i.text}</span></div>
        {/each}
      </div>
    {/if}

    <div class="card">
      <div class="card-h"><h3>Por dia</h3>
        <span class="legend">{#each provs as p (p)}<span><i style="background:{PROV[p]?.color || 'var(--cat-other)'}"></i>{PROV[p]?.label || p}</span>{/each}</span>
        <span class="grow"></span>
        <Segmented size="sm" bind:value={metric} options={[{ value: "tokens", label: "Tokens" }, { value: "cost", label: "US$ (API)" }, { value: "n", label: "Respostas" }]} />
      </div>
      <div class="card-b">
        <div class="chart">
          <div class="yl"><span>{fmt(maxDay)}</span><span>{fmt(maxDay / 2)}</span><span>0</span></div>
          <div class="plot">
            <div class="grid-l" style="bottom:50%"></div><div class="grid-l" style="bottom:100%"></div>
            <div class="cols">
              {#each R.series as s (s.day)}
                {@const tot = dayTotal(s)}
                <div class="c" role="img" aria-label={dayTip(s)} onmousemove={(e) => (tip = { x: e.clientX, y: e.clientY, text: dayTip(s) })} onmouseleave={() => (tip = null)}>
                  {#if tot > 0}
                    <div class="stack" style="height:{Math.max(2, (100 * tot) / maxDay)}%">
                      {#each provs as p (p)}{#if val(s[p] as G) > 0}<div class="seg" style="flex:{val(s[p] as G)};background:{PROV[p]?.color || 'var(--cat-other)'}"></div>{/if}{/each}
                    </div>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
          <span></span>
          <div class="xaxis">{#each R.series as s, i (s.day)}<span>{i % every === 0 ? fmtD(s.day) : ""}</span>{/each}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-h"><h3>Modelo · effort</h3><span class="muted small">o de-para: quanto cada combinação consome e rende</span></div>
      <div class="tw">
        <table>
          <thead><tr>
            <th>Modelo</th><th>Effort</th><th style="width:18%">Tokens</th><th class="num">Respostas</th><th class="num">Sessões</th>
            <th class="num" title="Tokens lidos + escritos por resposta (o contexto pesa: quase tudo vem do cache)">Por resposta</th>
            <th class="num" title="O que a IA escreveu por resposta (inclui o raciocínio)">Saída/resp.</th>
            <th class="num" title="Quanto do contexto veio do cache (mais = mais barato)">Cache</th>
            <th class="num" title="Preço de API (tabela oficial da Anthropic)">US$ (API)</th><th class="num">US$/sessão</th>
            <th class="num" title="Média do limite semanal gasto por sessão — só as sessões abertas pelo Codeck sabem disso">Semana/sessão</th>
            <th class="num" title="Linhas alteradas por US$ — sessões abertas pelo Codeck">Linhas/US$</th>
          </tr></thead>
          <tbody>
            {#each rows as r (r.key)}
              <tr>
                <td><span class="dot" style="background:{PROV[r.prov]?.color}"></span><b>{modelLabel(r.model)}</b> <span class="muted small">{PROV[r.prov]?.label || r.prov}</span></td>
                <td class:muted={r.effort === "—"}>{effortLabel(r.effort)}</td>
                <td><div class="bar"><span style="width:{(80 * r.g.tokens) / maxShare}%;background:{PROV[r.prov]?.color}"></span><b>{tok(r.g.tokens)}</b><em>{share(r.g.tokens)}%</em></div></td>
                <td class="num">{num(r.g.n)}</td><td class="num">{r.g.sessions || "—"}</td>
                <td class="num">{tok(r.g.perCall)}</td><td class="num">{tok(r.g.outPerCall)}</td>
                <td class="num">{r.g.cacheHit != null ? `${Math.round(r.g.cacheHit)}%` : "—"}</td>
                <td class="num">{usd(r.g.cost)}</td><td class="num">{usd(r.g.costPerSession)}</td>
                <td class="num">{r.ln?.sessions && r.ln.weekPct ? `${(r.ln.weekPct / r.ln.sessions).toFixed(1).replace(".", ",")}%` : "—"}</td>
                <td class="num">{r.ln?.cost > 0 && r.ln.lines ? Math.round(r.ln.lines / r.ln.cost) : "—"}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>

    <div class="two">
      <div class="card">
        <div class="card-h"><h3>Por conta</h3><span class="muted small">últimos 7 dias</span></div>
        <div class="tw">
          <table>
            <thead><tr><th>Conta</th><th title="O padrão da conta (settings.json do Claude, config.toml do Codex)">Configurado</th><th>Mais usado</th><th class="num">Tokens</th><th class="num">US$ (API)</th></tr></thead>
            <tbody>
              {#each accRows as [id, a] (id)}
                <tr>
                  <td><span class="dot" style="background:{PROV[a.provider || '']?.color}"></span><b>{a.name}</b></td>
                  <td class="small">{a.configured?.model || "—"}{a.configured?.effort ? ` · ${a.configured.effort}` : ""}</td>
                  <td class="small">{#if a.weekTop}{modelLabel(a.weekTop.model)} · {effortLabel(a.weekTop.effort)}{:else if a.last}<span class="muted">{modelLabel(a.last.model)} · {ago(a.last.ts)}</span>{:else}—{/if}</td>
                  <td class="num">{tok(a.week?.tokens)}</td><td class="num">{usd(a.week?.cost)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
      <div class="card">
        <div class="card-h"><h3>Por projeto</h3></div>
        <div class="tw">
          <table>
            <thead><tr><th>Projeto</th><th class="num">Tokens</th><th class="num">Sessões</th><th class="num">Cache</th><th class="num">US$ (API)</th></tr></thead>
            <tbody>
              {#each projRows as [name, g] (name)}
                <tr><td><b>{name}</b></td><td class="num">{tok(g.tokens)}</td><td class="num">{g.sessions || "—"}</td>
                  <td class="num">{g.cacheHit != null ? `${Math.round(g.cacheHit)}%` : "—"}</td><td class="num">{usd(g.cost)}</td></tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-h"><h3>Cursor</h3><span class="muted small">o Cursor não guarda tokens no disco: aqui, o modelo de cada trecho gerado e as linhas da IA nos commits</span></div>
      <div class="card-b cur">
        {#if cursorModels.length || cc?.commits}
          {#if cc?.commits}<div class="kpi"><span class="kl">Linhas commitadas da IA</span><b>{Math.round((cc.ai / Math.max(1, cc.ai + cc.human)) * 100)}%</b>
            <span class="ks">{num(cc.ai)} da IA · {num(cc.human)} suas · {cc.commits} commits</span></div>{/if}
          <div class="cm">{#each cursorModels as [m, v] (m)}<span class="chip"><b>{m}</b> {num(v.chunks)} trechos · {v.conversations} conversas</span>{/each}</div>
        {:else}<span class="muted small">Sem uso do Cursor no período.</span>{/if}
      </div>
    </div>
    {#if R.scan.error}<p class="muted small">Leitura com aviso: {R.scan.error}</p>{/if}
  {/if}
</section>

{#if tip}<div class="tip" style="left:{tip.x + 12}px;top:{tip.y + 14}px">{tip.text}</div>{/if}

<style>
  .cons { display: grid; gap: 12px; }
  .head { display: flex; align-items: flex-start; gap: 10px; flex-wrap: wrap; }
  .head h3 { margin: 0; font-size: 15px; font-weight: 680; }
  .head p { margin: 2px 0 0; }
  .grow { flex: 1; }
  .err { color: var(--bad); font-size: 13px; }
  .empty { display: grid; gap: 4px; padding: 16px; }
  .kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .kpi { display: grid; gap: 2px; padding: 12px 14px; border-left: 1px solid var(--line); min-width: 0; }
  .kpis .kpi:first-child { border-left: 0; }
  .kl { font-size: 11.5px; color: var(--muted); }
  .kpi b { font-size: 21px; font-weight: 700; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
  .ks { font-size: 11.5px; color: var(--text-2); }
  .ins { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 8px; }
  .in { display: grid; gap: 3px; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface); font-size: 12.5px; position: relative; }
  .in::before { content: ""; position: absolute; left: 0; top: 10px; bottom: 10px; width: 3px; border-radius: 0 3px 3px 0; background: var(--accent); }
  .in.warn::before { background: var(--warn); } .in.good::before { background: var(--good); } .in.bad::before { background: var(--bad); }
  .in b { font-size: 13px; }
  .in span { color: var(--text-2); }
  .legend { display: inline-flex; gap: 10px; font-size: 12px; color: var(--text-2); }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .legend i, .dot { display: inline-block; width: 9px; height: 9px; border-radius: 3px; flex: none; }
  .dot { margin-right: 6px; vertical-align: 0; }
  .chart { display: grid; grid-template-columns: auto 1fr; column-gap: 10px; }
  .yl { display: flex; flex-direction: column; justify-content: space-between; height: 150px; font-size: 11px; color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }
  .plot { position: relative; height: 150px; border-bottom: 1px solid var(--line-2); }
  .grid-l { position: absolute; left: 0; right: 0; border-top: 1px dashed var(--line); }
  .cols { position: absolute; inset: 0; display: flex; align-items: flex-end; gap: 2px; }
  .c { flex: 1; height: 100%; display: flex; align-items: flex-end; min-width: 2px; cursor: default; }
  .c:hover .stack { filter: brightness(1.12); }
  .stack { width: 100%; display: flex; flex-direction: column-reverse; gap: 2px; border-radius: 4px 4px 0 0; overflow: hidden; animation: grow 0.4s var(--ease-out) both; transform-origin: bottom; }
  @keyframes grow { from { transform: scaleY(0); } }
  .seg { min-height: 1px; }
  .xaxis { display: flex; gap: 2px; font-size: 10.5px; color: var(--muted); margin-top: 4px; }
  .xaxis span { flex: 1; min-width: 2px; white-space: nowrap; overflow: visible; }
  .tw { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th { text-align: left; font: 600 11px var(--font); color: var(--muted); padding: 8px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  td { padding: 7px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  tr:last-child td { border-bottom: 0; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .bar { display: flex; align-items: center; gap: 6px; }
  .bar span { height: 8px; border-radius: 0 4px 4px 0; min-width: 2px; }
  .bar b { font-weight: 600; font-variant-numeric: tabular-nums; }
  .bar em { font-style: normal; color: var(--muted); font-size: 11px; }
  .two { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 12px; }
  .cur { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  .cur .kpi { border: 0; padding: 0; }
  .cm { display: flex; gap: 6px; flex-wrap: wrap; }
  .chip { font-size: 12px; padding: 4px 9px; border-radius: 99px; background: var(--surface-2); border: 1px solid var(--line); color: var(--text-2); }
  .tip { position: fixed; z-index: 70; pointer-events: none; white-space: pre; background: var(--text); color: var(--bg); font-size: 12px; padding: 6px 9px; border-radius: 7px; box-shadow: var(--shadow-2); }
  @media (max-width: 900px) { .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
