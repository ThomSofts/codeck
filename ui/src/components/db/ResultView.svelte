<script lang="ts">
  // O resultado de uma consulta (ou os dados de uma tabela) em três formas: a grade (planilha), JSON (os objetos, com
  // cor) e a ficha (uma linha por vez, campo por campo — boa para tabela larga). A busca filtra as linhas nas três, as
  // colunas escondidas somem das três; tudo fica guardado na aba.
  import { Braces, ChevronLeft, ChevronRight, Columns3, Copy, Eye, EyeOff, PanelRight, Search, Table2, X } from "@lucide/svelte";
  import type { Snippet } from "svelte";
  import { copyText } from "../../lib/clipboard";
  import type { Column, CopyFormat, Engine, ResultView, TableInfo } from "../../lib/db.svelte";
  import { cellText, formatCopy } from "../../lib/dbcopy";
  import ResultGrid from "./ResultGrid.svelte";

  type FK = TableInfo["fks"][number];
  let { columns, rows, engine, view, copyFormat = "tsv", editable = null, info = null, onapply, onfk, onpng, sort = null, onsort, footer = "",
    flash = new Set<number>(), tools }:
    { columns: Column[]; rows: any[][]; engine: Engine; view: ResultView; copyFormat?: CopyFormat;
      editable?: { schema: string; name: string; info: TableInfo; pk: string[] } | null; info?: TableInfo | null;
      onapply?: (changes: any[]) => Promise<boolean>; onfk?: (fk: FK, value: any) => void; onpng?: (cols: number[], rows: number[]) => void;
      sort?: { col: string; desc: boolean } | null; onsort?: (col: string, desc?: boolean) => void; footer?: string; flash?: Set<number>;
      /** botões extras à direita da barra (Imagem…) */
      tools?: Snippet } = $props();

  let searchEl: HTMLInputElement | undefined = $state();
  let colsOpen = $state(false);
  let colQ = $state("");
  let cur = $state(0);
  let jsonMax = $state(200);

  const needle = $derived(view.search.trim().toLowerCase());
  const vc = $derived(columns.map((_, i) => i).filter(i => !view.hidden.includes(columns[i].name)));
  /** linhas que passam na busca (JSON e ficha; a grade filtra sozinha, contando as edições pendentes) */
  const fr = $derived(needle ? rows.map((_, i) => i).filter(r => vc.some(c => rows[r][c] !== null && rows[r][c] !== undefined && cellText(rows[r][c]).toLowerCase().includes(needle))) : rows.map((_, i) => i));
  $effect(() => { void needle; void rows; cur = 0; jsonMax = 200; });
  const colMeta = (name: string) => (editable?.info || info)?.columns.find(c => c.name === name) || null;
  const fkOf = (name: string) => (editable?.info || info)?.fks.find(f => f.columns.length === 1 && f.columns[0] === name) || null;

  // ------------------------------------------------------------ JSON
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  /** pinta o JSON (o texto já vem escapado: o {@html} só recebe as marcas daqui) */
  function paint(json: string) {
    return esc(json).replace(/("(?:\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g,
      (m, str, colon, kw) => str ? (colon ? `<span class="jk">${str}</span>${colon}` : `<span class="js">${str}</span>`)
        : kw ? `<span class="${kw === "null" ? "jn" : "jb"}">${m}</span>` : `<span class="jd">${m}</span>`);
  }
  const jsonOf = (idx: number[]) => formatCopy("json", vc.map(c => columns[c]), idx.map(r => vc.map(c => rows[r][c])), { engine });
  const jsonHtml = $derived(view.mode === "json" ? paint(jsonOf(fr.slice(0, jsonMax))) : "");

  // ------------------------------------------------------------ ficha
  const rec = $derived(fr[cur] ?? null);
  function step(d: number) { if (fr.length) cur = Math.max(0, Math.min(fr.length - 1, cur + d)); }
  function openRecord(r: number) { const i = fr.indexOf(r); cur = i >= 0 ? i : 0; view.mode = "record"; }
  function onkey(e: KeyboardEvent) {
    if (view.mode !== "record" || (e.target as HTMLElement)?.tagName === "INPUT") return;
    if (e.key === "ArrowRight" || e.key === "j") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowLeft" || e.key === "k") { e.preventDefault(); step(-1); }
    else if (e.key === "Home") { cur = 0; } else if (e.key === "End") { cur = Math.max(0, fr.length - 1); }
  }
  /** valor para a ficha: JSON vira texto arrumado; o resto como está */
  function pretty(v: any, type: string): string {
    if (v === null || v === undefined) return "NULL";
    const s = cellText(v);
    if (/json/i.test(type) || /^\s*[[{]/.test(s)) { try { return JSON.stringify(JSON.parse(s), null, 2); } catch { /* texto */ } }
    return s;
  }
  function parts(text: string): { t: string; m: boolean }[] {
    if (!needle) return [{ t: text, m: false }];
    const out: { t: string; m: boolean }[] = [];
    const low = text.toLowerCase();
    let i = 0;
    for (let k = low.indexOf(needle); k >= 0 && out.length < 60; k = low.indexOf(needle, k + needle.length)) {
      if (k > i) out.push({ t: text.slice(i, k), m: false });
      out.push({ t: text.slice(k, k + needle.length), m: true });
      i = k + needle.length;
    }
    if (i < text.length) out.push({ t: text.slice(i), m: false });
    return out;
  }

  // ------------------------------------------------------------ colunas
  function toggleCol(name: string) {
    const h = new Set(view.hidden);
    if (h.has(name)) h.delete(name);
    else if (columns.length - h.size > 1) h.add(name);
    view.hidden = [...h];
  }
  function onlyMatching() {
    const f = colQ.trim().toLowerCase();
    if (!f) return;
    const keep = columns.filter(c => c.name.toLowerCase().includes(f)).map(c => c.name);
    if (keep.length) view.hidden = columns.map(c => c.name).filter(n => !keep.includes(n));
  }
  function outside(node: HTMLElement) {
    const h = (e: PointerEvent) => { if (!node.contains(e.target as Node) && !(e.target as HTMLElement).closest?.(".colbtn")) colsOpen = false; };
    window.addEventListener("pointerdown", h, true);
    return { destroy() { window.removeEventListener("pointerdown", h, true); } };
  }
  function findKey(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "f") { e.preventDefault(); searchEl?.focus(); searchEl?.select(); }
  }
  const isNum = (t: string) => /INT|DEC|NUM|MONEY|FLOAT|REAL|DOUBLE|SERIAL/i.test(t);
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div class="rv" role="region" aria-label="Resultado" onkeydown={(e) => { findKey(e); onkey(e); }} tabindex="-1">
  <div class="rbar">
    <div class="modes" role="tablist" aria-label="Como ver o resultado">
      <button role="tab" class:on={view.mode === "grid"} aria-selected={view.mode === "grid"} title="Grade (planilha)" onclick={() => (view.mode = "grid")}><Table2 size={13} /> Grade</button>
      <button role="tab" class:on={view.mode === "json"} aria-selected={view.mode === "json"} title="JSON: as linhas como objetos" onclick={() => (view.mode = "json")}><Braces size={13} /> JSON</button>
      <button role="tab" class:on={view.mode === "record"} aria-selected={view.mode === "record"} title="Ficha: uma linha por vez, campo a campo" onclick={() => (view.mode = "record")}><PanelRight size={13} /> Ficha</button>
    </div>
    <label class="find" class:on={!!needle}>
      <Search size={13} />
      <input bind:this={searchEl} placeholder="Buscar no resultado…" bind:value={view.search} onkeydown={(e) => e.key === "Escape" && (view.search = "")} />
      {#if needle}<span class="cnt">{fr.length.toLocaleString("pt-BR")}</span><button class="clr" title="Limpar a busca" onclick={() => (view.search = "")}><X size={12} /></button>{/if}
    </label>
    <div class="cwrap">
      <button class="btn sm ghost colbtn" class:on={colsOpen || view.hidden.length > 0} title="Mostrar ou esconder colunas" onclick={() => (colsOpen = !colsOpen)}>
        <Columns3 size={13} /> Colunas {#if view.hidden.length}<span class="n">{columns.length - view.hidden.length}/{columns.length}</span>{/if}
      </button>
      {#if colsOpen}
        <div class="pop" use:outside>
          <div class="pf"><Search size={12} /><input placeholder="Filtrar colunas…" bind:value={colQ} onkeydown={(e) => e.key === "Enter" && onlyMatching()} /></div>
          <div class="pa">
            <button class="link" onclick={() => (view.hidden = [])}>Todas</button>
            {#if colQ.trim()}<button class="link" onclick={onlyMatching}>Só as filtradas</button>{/if}
            <button class="link" onclick={() => { const v = columns.map(c => c.name).filter(n => view.hidden.includes(n)); view.hidden = v.length ? columns.map(c => c.name).filter(n => !v.includes(n)) : view.hidden; }}>Inverter</button>
          </div>
          <div class="pl">
            {#each columns.filter(c => !colQ.trim() || c.name.toLowerCase().includes(colQ.trim().toLowerCase())) as c (c.name)}
              {@const off = view.hidden.includes(c.name)}
              <button class="pc" class:off onclick={() => toggleCol(c.name)}>
                {#if off}<EyeOff size={13} />{:else}<Eye size={13} />{/if}
                <span class="ell">{c.name}</span>
                <span class="ty">{c.type.toLowerCase()}</span>
              </button>
            {/each}
          </div>
        </div>
      {/if}
    </div>
    <span class="grow"></span>
    {@render tools?.()}
  </div>

  <div class="rbody">
    {#if view.mode === "grid"}
      <ResultGrid {columns} {rows} {engine} {copyFormat} {editable} {onapply} {onfk} {onpng} {sort} {onsort} {footer} {flash}
        search={view.search} hidden={view.hidden} onhide={(n) => toggleCol(n)} onrecord={openRecord} />
    {:else if view.mode === "json"}
      <div class="json">
        <div class="jbar tiny muted">
          <span>{Math.min(jsonMax, fr.length).toLocaleString("pt-BR")} de {fr.length.toLocaleString("pt-BR")} {fr.length === 1 ? "objeto" : "objetos"} · {vc.length} {vc.length === 1 ? "campo" : "campos"}</span>
          <span class="grow"></span>
          <button class="btn sm ghost" onclick={() => copyText(jsonOf(fr), `JSON copiado: ${fr.length.toLocaleString("pt-BR")} objeto(s)`)}><Copy size={12} /> Copiar JSON</button>
        </div>
        <!-- eslint-disable-next-line svelte/no-at-html-tags -- texto escapado em paint() -->
        <pre class="jcode">{@html jsonHtml}</pre>
        {#if fr.length > jsonMax}<button class="btn sm more" onclick={() => (jsonMax += 500)}>Mostrar mais {Math.min(500, fr.length - jsonMax)}</button>{/if}
      </div>
    {:else}
      <div class="rec">
        <div class="rnav">
          <button class="btn sm ghost icon" title="Anterior (←)" disabled={cur <= 0} onclick={() => step(-1)}><ChevronLeft size={15} /></button>
          <span class="pos">{fr.length ? `Linha ${(rec ?? 0) + 1}` : "Nenhuma linha"}{#if fr.length}<span class="muted"> · {cur + 1} de {fr.length.toLocaleString("pt-BR")}</span>{/if}</span>
          <button class="btn sm ghost icon" title="Próxima (→)" disabled={cur >= fr.length - 1} onclick={() => step(1)}><ChevronRight size={15} /></button>
          <input class="jump" type="range" min="0" max={Math.max(0, fr.length - 1)} bind:value={cur} disabled={fr.length < 2} aria-label="Ir para a linha" />
          <span class="grow"></span>
          {#if rec !== null}<button class="btn sm ghost" onclick={() => copyText(formatCopy("json", vc.map(c => columns[c]), [vc.map(c => rows[rec!][c])], { engine }).replace(/^\[\n|\n\]$/g, "").replace(/^ {2}/gm, ""), "Linha copiada como JSON")}><Copy size={12} /> Copiar a linha</button>{/if}
        </div>
        {#if rec !== null}
          <div class="fields">
            {#each vc as c (c)}
              {@const col = columns[c]}
              {@const m = colMeta(col.name)}
              {@const fk = fkOf(col.name)}
              {@const v = rows[rec][c]}
              {@const text = pretty(v, col.type)}
              <div class="f" class:hit={!!needle && v !== null && cellText(v).toLowerCase().includes(needle)}>
                <div class="fl">
                  <span class="fn">{#if m?.pk}<span class="key" title="chave primária">🔑</span>{:else if fk}<span class="key fk" title={`→ ${fk.refTable}`}>↗</span>{/if}<b class="ell">{col.name}</b></span>
                  <span class="ft">{col.type.toLowerCase()}</span>
                  {#if m?.comment}<span class="fc">{m.comment}</span>{/if}
                </div>
                <div class="fv" class:null={v === null || v === undefined} class:num={isNum(col.type)} class:block={text.includes("\n") || text.length > 90}>
                  {#if v === null || v === undefined}NULL{:else}{#each parts(text) as p, i (i)}{#if p.m}<mark>{p.t}</mark>{:else}{p.t}{/if}{/each}{/if}
                  <span class="fa">
                    {#if fk && onfk && v !== null && v !== undefined}<button class="mini" title={`Abrir ${fk.refTable}`} onclick={() => onfk!(fk, v)}>abrir ↗</button>{/if}
                    {#if v !== null && v !== undefined}<button class="mini" title="Copiar o valor" onclick={() => copyText(cellText(v), "Valor copiado")}><Copy size={11} /></button>{/if}
                  </span>
                </div>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
  .rv { display: flex; flex-direction: column; height: 100%; min-height: 0; outline: none; }
  .rbar { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-bottom: 1px solid var(--line); flex: none; min-width: 0; }
  .modes { display: flex; gap: 2px; padding: 2px; border-radius: 9px; background: var(--bg-2); border: 1px solid var(--line); flex: none; }
  .modes button { display: inline-flex; align-items: center; gap: 5px; height: 24px; padding: 0 9px; border: 0; border-radius: 7px; background: none;
    color: var(--muted); font: 600 12px var(--font); cursor: pointer; transition: background var(--t-fast), color var(--t-fast); }
  .modes button:hover { color: var(--text); }
  .modes button.on { background: var(--surface-3); color: var(--text); box-shadow: var(--shadow-1); }
  .find { display: flex; align-items: center; gap: 6px; height: 28px; padding: 0 8px; border-radius: 8px; background: var(--surface-2); border: 1px solid var(--line);
    color: var(--muted); min-width: 160px; flex: 0 1 300px; transition: border-color var(--t-fast), box-shadow var(--t-fast); }
  .find:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .find.on { border-color: color-mix(in srgb, var(--warn) 50%, var(--line)); }
  .find input { flex: 1; min-width: 0; border: 0; background: none; outline: none; color: var(--text); font: 12.5px var(--font); }
  .find .cnt { font: 650 11px var(--font); color: var(--text-2); font-variant-numeric: tabular-nums; }
  .clr { display: grid; place-items: center; border: 0; background: none; color: var(--muted); cursor: pointer; padding: 2px; border-radius: 4px; }
  .clr:hover { background: var(--surface-3); color: var(--text); }
  .cwrap { position: relative; flex: none; }
  .colbtn.on { color: var(--accent); background: var(--accent-soft); }
  .colbtn .n { font: 650 10.5px var(--font); padding: 1px 6px; border-radius: 99px; background: var(--surface-3); color: var(--text-2); }
  .pop { position: absolute; z-index: 30; top: calc(100% + 6px); left: 0; width: 290px; max-height: 380px; display: flex; flex-direction: column;
    border-radius: 12px; border: 1px solid var(--line-2); background: var(--surface); box-shadow: var(--shadow-3, 0 18px 40px -12px rgba(0,0,0,.45)); animation: pop .14s var(--ease-out); }
  @keyframes pop { from { opacity: 0; transform: translateY(-4px); } }
  .pf { display: flex; align-items: center; gap: 6px; padding: 8px 10px; border-bottom: 1px solid var(--line); color: var(--muted); }
  .pf input { flex: 1; border: 0; outline: none; background: none; color: var(--text); font: 12.5px var(--font); }
  .pa { display: flex; gap: 12px; padding: 6px 10px; font-size: 12px; border-bottom: 1px solid var(--line); }
  .pl { overflow: auto; padding: 4px; }
  .pc { display: flex; align-items: center; gap: 8px; width: 100%; padding: 5px 8px; border: 0; border-radius: 7px; background: none; color: var(--text); font: 12.5px var(--font); cursor: pointer; text-align: left; }
  .pc:hover { background: var(--surface-2); }
  .pc :global(svg) { color: var(--accent); flex: none; }
  .pc.off { color: var(--muted); }
  .pc.off :global(svg) { color: var(--faint); }
  .pc .ty { margin-left: auto; font: 10.5px var(--mono); color: var(--faint); flex: none; max-width: 90px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .link { background: none; border: 0; color: var(--accent); cursor: pointer; font: inherit; padding: 0; }
  .rbody { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .json { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .jbar { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-bottom: 1px solid var(--line); flex: none; }
  .jcode { flex: 1; min-height: 0; margin: 0; overflow: auto; padding: 12px 16px; font: 12.5px/1.6 var(--mono); color: var(--text-2); tab-size: 2; user-select: text; }
  .jcode :global(.jk) { color: var(--info); }
  .jcode :global(.js) { color: var(--good); }
  .jcode :global(.jd) { color: var(--warn); }
  .jcode :global(.jb) { color: var(--accent); font-weight: 600; }
  .jcode :global(.jn) { color: var(--faint); font-style: italic; }
  .more { margin: 8px 16px 12px; align-self: flex-start; }
  .rec { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .rnav { display: flex; align-items: center; gap: 6px; padding: 6px 10px; border-bottom: 1px solid var(--line); flex: none; }
  .pos { font: 650 13px var(--font); font-variant-numeric: tabular-nums; }
  .pos .muted { font-weight: 400; }
  .jump { width: 160px; accent-color: var(--accent); }
  .fields { flex: 1; min-height: 0; overflow: auto; padding: 8px 14px 18px; display: grid; gap: 2px; align-content: start; }
  .f { display: grid; grid-template-columns: minmax(150px, 260px) minmax(0, 1fr); gap: 14px; padding: 7px 8px; border-radius: 8px; border-bottom: 1px solid var(--line); }
  .f:hover { background: var(--surface-2); }
  .f.hit { background: color-mix(in srgb, var(--warn) 7%, transparent); }
  .fl { display: grid; gap: 1px; min-width: 0; align-content: start; }
  .fn { display: flex; align-items: center; gap: 5px; min-width: 0; font-size: 12.5px; }
  .key { font-size: 10px; flex: none; }
  .key.fk { color: var(--info); font-weight: 700; }
  .ft { font: 10.5px var(--mono); color: var(--faint); }
  .fc { font-size: 11.5px; color: var(--muted); line-height: 1.35; }
  .fv { position: relative; min-width: 0; font-size: 13px; color: var(--text); overflow-wrap: anywhere; padding-right: 70px; user-select: text; }
  .fv.num { font-family: var(--mono); font-size: 12.5px; }
  .fv.block { white-space: pre-wrap; font: 12px/1.55 var(--mono); background: var(--bg-2); border: 1px solid var(--line); border-radius: 8px; padding: 8px 70px 8px 10px; max-height: 320px; overflow: auto; }
  .fv.null { color: var(--faint); font-style: italic; font-size: 12px; }
  .fa { position: absolute; top: 2px; right: 4px; display: flex; gap: 4px; opacity: 0; transition: opacity var(--t-fast); }
  .f:hover .fa { opacity: 1; }
  .mini { display: inline-flex; align-items: center; gap: 3px; border: 1px solid var(--line-2); background: var(--surface); color: var(--text-2); font: 600 11px var(--font);
    padding: 2px 6px; border-radius: 6px; cursor: pointer; }
  .mini:hover { color: var(--text); border-color: var(--accent); }
  mark { background: color-mix(in srgb, var(--warn) 42%, transparent); color: var(--text); border-radius: 3px; padding: 0 1px; }
  .grow { flex: 1; }
  @media (max-width: 760px) { .f { grid-template-columns: 1fr; gap: 4px; } }
</style>
