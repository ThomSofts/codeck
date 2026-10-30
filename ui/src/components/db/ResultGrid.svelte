<script lang="ts">
  // Grade de resultados, como uma planilha: seleção retangular (clique, Shift, arrastar, cabeçalho = coluna, nº = linha),
  // ⌘C copia no formato padrão (o menu tem os outros: JSON, CSV, INSERT…), ⌘V cola do Excel. Na tabela aberta com chave
  // primária, dá para editar: as mudanças ficam pendentes (amarelo), linhas novas em verde e excluídas riscadas, até
  // Aplicar — tudo numa transação, conferindo a linha pela chave.
  import { ArrowUpRight, Ban, Check, Copy, CopyPlus, Image, Pencil, Plus, Trash2, Undo2, X } from "@lucide/svelte";
  import { tick } from "svelte";
  import { copyText } from "../../lib/clipboard";
  import type { Column, CopyFormat, Engine, TableInfo } from "../../lib/db.svelte";
  import { cellText, COPY_LABEL, formatCopy, parseTsv, type CopyKind } from "../../lib/dbcopy";
  import { ui } from "../../lib/ui.svelte";

  type FK = TableInfo["fks"][number];
  let { columns, rows, engine, copyFormat = "tsv", editable = null, onapply = undefined, onfk = undefined, onpng = undefined,
    sort = null, onsort = undefined, footer = "", flash = new Set<number>() }:
    { columns: Column[]; rows: any[][]; engine: Engine; copyFormat?: CopyFormat;
      editable?: { schema: string; name: string; info: TableInfo; pk: string[] } | null;
      onapply?: (changes: any[]) => Promise<boolean>; onfk?: (fk: FK, value: any) => void;
      onpng?: (cols: number[], rows: number[]) => void;
      sort?: { col: string; desc: boolean } | null; onsort?: (col: string) => void; footer?: string; flash?: Set<number> } = $props();

  const RH = 26, HH = 30, NW = 52;
  let scroller: HTMLDivElement | undefined = $state();
  let scrollTop = $state(0);
  let viewH = $state(400);
  // seleção: âncora e foco (linha/coluna)
  let anchor = $state<{ r: number; c: number } | null>(null);
  let focusC = $state<{ r: number; c: number } | null>(null);
  let dragging = false;
  // edições pendentes
  let edits = $state<Record<number, Record<number, any>>>({});
  let deleted = $state<Record<number, true>>({});
  let added = $state<any[][]>([]);
  let editing = $state<{ r: number; c: number; value: string } | null>(null);
  let applying = $state(false);
  let widths = $state<number[]>([]);

  const total = $derived(rows.length + added.length);
  const first = $derived(Math.max(0, Math.floor(scrollTop / RH) - 8));
  const last = $derived(Math.min(total, Math.ceil((scrollTop + viewH) / RH) + 8));
  const pendingCount = $derived(Object.keys(edits).length + Object.keys(deleted).length + added.length);
  const pkIdx = $derived(editable ? editable.pk.map(k => columns.findIndex(c => c.name === k)) : []);
  const canEdit = $derived(!!editable && editable.pk.length > 0 && pkIdx.every(i => i >= 0));
  const colInfo = $derived(columns.map(c => editable?.info.columns.find(x => x.name === c.name) || null));
  const fkOf = $derived(columns.map(c => editable?.info.fks.find(f => f.columns.length === 1 && f.columns[0] === c.name) || null));

  // larguras iniciais pelo conteúdo (amostra); a pessoa ajusta arrastando a borda do cabeçalho
  $effect(() => {
    const cols = columns, rs = rows;
    const m = document.createElement("canvas").getContext("2d")!;
    const sans = "13px Inter Variable, -apple-system, sans-serif", mono = "12px JetBrains Mono Variable, ui-monospace, monospace";
    widths = cols.map((c, i) => {
      m.font = "620 12.5px Inter Variable, -apple-system, sans-serif";
      let w = m.measureText(c.name).width;
      m.font = "10px JetBrains Mono Variable, ui-monospace, monospace";
      w += m.measureText(c.type.toLowerCase().slice(0, 12)).width + 40;
      m.font = isNum(c.type) ? mono : sans;
      for (const r of rs.slice(0, 200)) w = Math.max(w, m.measureText(show(r[i]).slice(0, 80)).width + 22);
      return Math.round(Math.min(360, Math.max(64, w)));
    });
  });
  // resultado novo: limpa seleção e edições
  $effect(() => { void rows; void columns; edits = {}; deleted = {}; added = []; editing = null; anchor = focusC = null; scrollTop = 0; if (scroller) scroller.scrollTop = 0; });

  const rowAt = (r: number) => (r < rows.length ? rows[r] : added[r - rows.length]);
  const valueAt = (r: number, c: number) => (r < rows.length && edits[r] && c in edits[r] ? edits[r][c] : rowAt(r)?.[c]);
  const isNum = (t: string) => /INT|DEC|NUM|MONEY|FLOAT|REAL|DOUBLE|SERIAL/i.test(t);
  function show(v: any): string {
    if (v === null || v === undefined) return "NULL";
    return cellText(v).replace(/\r?\n/g, " ⏎ ");
  }

  const rect = $derived.by(() => {
    if (!anchor || !focusC) return null;
    return { r0: Math.min(anchor.r, focusC.r), r1: Math.max(anchor.r, focusC.r), c0: Math.min(anchor.c, focusC.c), c1: Math.max(anchor.c, focusC.c) };
  });
  const inSel = (r: number, c: number) => !!rect && r >= rect.r0 && r <= rect.r1 && c >= rect.c0 && c <= rect.c1;

  // resumo da seleção (como no Excel): quantas células e, se forem números, soma e média
  const summary = $derived.by(() => {
    if (!rect) return "";
    const n = (rect.r1 - rect.r0 + 1) * (rect.c1 - rect.c0 + 1);
    if (n <= 1) return "";
    let sum = 0, cnt = 0;
    if (n <= 200_000) for (let r = rect.r0; r <= rect.r1; r++) for (let c = rect.c0; c <= rect.c1; c++) {
      const v = valueAt(r, c);
      const x = typeof v === "number" ? v : typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v) ? Number(v) : NaN;
      if (!Number.isNaN(x)) { sum += x; cnt++; }
    }
    const f = (x: number) => x.toLocaleString("pt-BR", { maximumFractionDigits: 4 });
    return `${(rect.r1 - rect.r0 + 1).toLocaleString("pt-BR")} × ${rect.c1 - rect.c0 + 1} selecionadas` + (cnt ? ` · soma ${f(sum)} · média ${f(sum / cnt)}` : "");
  });

  function selectCell(r: number, c: number, extend = false) {
    if (!extend || !anchor) anchor = { r, c };
    focusC = { r, c };
    reveal(r);
  }
  function reveal(r: number) {
    if (!scroller) return;
    const top = r * RH, bottom = top + RH + HH;
    if (top < scroller.scrollTop) scroller.scrollTop = top;
    else if (bottom > scroller.scrollTop + scroller.clientHeight) scroller.scrollTop = bottom - scroller.clientHeight;
  }
  function selectAll() { if (!total || !columns.length) return; anchor = { r: 0, c: 0 }; focusC = { r: total - 1, c: columns.length - 1 }; }
  function selectCol(c: number, extend: boolean) { anchor = extend && anchor ? { r: 0, c: anchor.c } : { r: 0, c }; focusC = { r: Math.max(0, total - 1), c }; }
  function selectRow(r: number, extend: boolean) { anchor = extend && anchor ? { r: anchor.r, c: 0 } : { r, c: 0 }; focusC = { r, c: columns.length - 1 }; }

  // ------------------------------------------------------------ cópia
  function selection() {
    const R = rect || (total ? { r0: 0, r1: total - 1, c0: 0, c1: columns.length - 1 } : null);
    if (!R) return null;
    const cIdx = Array.from({ length: R.c1 - R.c0 + 1 }, (_, i) => R.c0 + i);
    const rIdx = Array.from({ length: R.r1 - R.r0 + 1 }, (_, i) => R.r0 + i);
    return { cIdx, rIdx };
  }
  function copy(kind: CopyKind = copyFormat) {
    const s = selection();
    if (!s) return;
    const cols = s.cIdx.map(i => columns[i]);
    const data = s.rIdx.map(r => s.cIdx.map(c => valueAt(r, c)));
    const text = formatCopy(kind, cols, data, {
      engine, table: editable ? { schema: editable.schema, name: editable.name } : null, pk: editable?.pk,
      allColumns: columns, allRow: (i: number) => columns.map((_, c) => valueAt(s.rIdx[i], c)),
    });
    const n = s.rIdx.length * s.cIdx.length;
    copyText(text, `Copiado: ${s.rIdx.length.toLocaleString("pt-BR")} × ${s.cIdx.length} (${COPY_LABEL[kind]})${n > 1 ? "" : ""}`);
  }

  // ------------------------------------------------------------ edição
  function setValue(r: number, c: number, v: any) {
    if (!canEdit) return;
    if (r >= rows.length) { added[r - rows.length][c] = v; added = [...added]; return; }
    const orig = rows[r][c];
    const cur = { ...(edits[r] || {}) };
    if (v === orig || (v !== null && orig !== null && String(v) === String(orig))) delete cur[c]; else cur[c] = v;
    const next = { ...edits };
    if (Object.keys(cur).length) next[r] = cur; else delete next[r];
    edits = next;
  }
  async function startEdit(r: number, c: number) {
    if (!canEdit || deleted[r]) return;
    const v = valueAt(r, c);
    if (v && typeof v === "object") return ui.toast("Valor binário não é editável aqui", "info");
    const s = v === null || v === undefined ? "" : String(v);
    if (s.includes("\n") || s.length > 160) {   // texto longo: editor de várias linhas
      const out = await ui.ask({ title: `Editar ${columns[c].name}`, input: { label: columns[c].type, value: s, multiline: true }, confirm: "Ok" });
      if (typeof out === "string") setValue(r, c, out);
      return;
    }
    editing = { r, c, value: s };
    await tick();
    (document.querySelector(".rg .cellinput") as HTMLInputElement | null)?.select();
  }
  function commitEdit(move?: "down" | "right") {
    if (!editing) return;
    const { r, c, value } = editing;
    const orig = valueAt(r, c);
    // campo vazio numa célula NULL continua NULL (digitar nada não vira texto vazio sem querer)
    setValue(r, c, value === "" && (orig === null || orig === undefined) ? orig ?? null : value);
    editing = null;
    if (move === "down" && r + 1 < total) selectCell(r + 1, c);
    if (move === "right" && c + 1 < columns.length) selectCell(r, c + 1);
    scroller?.focus();
  }
  function setNull() {
    if (!canEdit || !rect) return;
    for (let r = rect.r0; r <= rect.r1; r++) for (let c = rect.c0; c <= rect.c1; c++) if (colInfo[c]?.nullable !== false) setValue(r, c, null);
  }
  function addRow(from?: number) {
    if (!canEdit) return;
    const base = from !== undefined ? columns.map((_, c) => (pkIdx.includes(c) && colInfo[c]?.identity ? undefined : valueAt(from, c))) : columns.map(() => undefined);
    added = [...added, base];
    tick().then(() => selectCell(total - 1, 0));
  }
  function deleteRows() {
    if (!canEdit || !rect) return;
    const next = { ...deleted };
    const keepAdded: any[][] = [];
    added.forEach((row, i) => { const r = rows.length + i; if (!(r >= rect!.r0 && r <= rect!.r1)) keepAdded.push(row); });
    for (let r = rect.r0; r <= Math.min(rect.r1, rows.length - 1); r++) next[r] = true;
    deleted = next; added = keepAdded;
  }
  function undoRows() {
    if (!rect) return;
    const d = { ...deleted }, e = { ...edits };
    for (let r = rect.r0; r <= rect.r1; r++) { delete d[r]; delete e[r]; }
    deleted = d; edits = e;
  }
  function discard() { edits = {}; deleted = {}; added = []; editing = null; }

  async function paste(text: string) {
    if (!canEdit || !focusC) return ui.toast(canEdit ? "Escolha a célula onde colar" : "Para colar, abra a tabela (precisa da chave primária)", "info");
    const grid = parseTsv(text);
    const { r, c } = rect ? { r: rect.r0, c: rect.c0 } : focusC;
    for (let i = 0; i < grid.length; i++) {
      while (r + i >= total) added = [...added, columns.map(() => undefined)];
      for (let j = 0; j < grid[i].length && c + j < columns.length; j++) {
        const v = grid[i][j];
        setValue(r + i, c + j, v === "NULL" ? null : v);
      }
    }
    anchor = { r, c }; focusC = { r: r + grid.length - 1, c: Math.min(columns.length - 1, c + (grid[0]?.length || 1) - 1) };
    ui.toast(`Colado: ${grid.length} × ${grid[0]?.length || 0} — revise e Aplique`, "info");
  }

  function changes() {
    const out: any[] = [];
    const key = (r: number) => Object.fromEntries(pkIdx.map(i => [columns[i].name, rows[r][i]]));
    for (const r of Object.keys(deleted).map(Number)) out.push({ op: "delete", schema: editable!.schema, table: editable!.name, key: key(r) });
    for (const [rs, vals] of Object.entries(edits)) {
      const r = Number(rs);
      if (deleted[r]) continue;
      out.push({ op: "update", schema: editable!.schema, table: editable!.name, key: key(r),
        values: Object.fromEntries(Object.entries(vals).map(([c, v]) => [columns[Number(c)].name, v])) });
    }
    for (const row of added) {
      const values = Object.fromEntries(row.map((v, c) => [columns[c].name, v]).filter(([, v]) => v !== undefined));
      if (Object.keys(values).length) out.push({ op: "insert", schema: editable!.schema, table: editable!.name, values });
    }
    return out;
  }
  async function apply() {
    if (!onapply || !pendingCount) return;
    applying = true;
    try { if (await onapply(changes())) discard(); } finally { applying = false; }
  }

  // ------------------------------------------------------------ teclado e mouse
  function onkey(e: KeyboardEvent) {
    if (editing) return;
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "c") { e.preventDefault(); copy(e.shiftKey ? "tsv-header" : copyFormat); return; }
    if (mod && e.key.toLowerCase() === "a") { e.preventDefault(); selectAll(); return; }
    if (mod && e.key.toLowerCase() === "s" && pendingCount) { e.preventDefault(); apply(); return; }
    if (!focusC) { if (["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].includes(e.key) && total) { e.preventDefault(); selectCell(0, 0); } return; }
    const { r, c } = focusC;
    const page = Math.max(1, Math.floor(viewH / RH) - 1);
    const mv: Record<string, [number, number]> = { ArrowDown: [1, 0], ArrowUp: [-1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1], PageDown: [page, 0], PageUp: [-page, 0] };
    if (mv[e.key]) {
      e.preventDefault();
      const [dr, dc] = mod && e.key.startsWith("Arrow") ? [mv[e.key][0] * total, mv[e.key][1] * columns.length] : mv[e.key];
      selectCell(Math.max(0, Math.min(total - 1, r + dr)), Math.max(0, Math.min(columns.length - 1, c + dc)), e.shiftKey);
    } else if (e.key === "Enter" || e.key === "F2") { e.preventDefault(); startEdit(r, c); }
    else if ((e.key === "Delete" || e.key === "Backspace") && canEdit) { e.preventDefault(); setNull(); }
    else if (e.key === "Escape") { anchor = focusC = null; }
    else if (canEdit && e.key.length === 1 && !mod && !e.altKey) { editing = { r, c, value: "" }; tick().then(() => (document.querySelector(".rg .cellinput") as HTMLInputElement | null)?.focus()); }
  }
  function onpaste(e: ClipboardEvent) {
    if (editing) return;
    const t = e.clipboardData?.getData("text/plain");
    if (t) { e.preventDefault(); paste(t); }
  }
  function down(e: MouseEvent, r: number, c: number) {
    if (e.button !== 0) return;
    if ((e.metaKey || e.ctrlKey) && fkOf[c] && onfk) { const v = valueAt(r, c); if (v !== null) { onfk(fkOf[c]!, v); return; } }
    if (editing && (editing.r !== r || editing.c !== c)) commitEdit();
    selectCell(r, c, e.shiftKey);
    dragging = true;
    scroller?.focus();
  }
  function enter(r: number, c: number) { if (dragging) focusC = { r, c }; }

  function cellMenu(e: MouseEvent, r: number, c: number) {
    e.preventDefault();
    if (!inSel(r, c)) selectCell(r, c);
    const fk = fkOf[c];
    const v = valueAt(r, c);
    const kinds: CopyKind[] = ["tsv", "tsv-header", "json", "csv", "markdown", "insert", ...(canEdit ? ["update" as CopyKind] : []), "in"];
    ui.contextMenu(e, [
      { label: "Copiar", icon: Copy, kbd: "⌘C", onclick: () => copy() },
      { heading: "Copiar como" },
      ...kinds.filter(k => k !== copyFormat).map(k => ({ label: COPY_LABEL[k], onclick: () => copy(k) })),
      { separator: true },
      ...(onpng ? [{ label: "Imagem (PNG) da seleção…", icon: Image, onclick: () => { const s = selection(); if (s) onpng!(s.cIdx, s.rIdx); } }] : []),
      ...(fk && onfk && v !== null ? [{ label: `Abrir ${fk.refTable} (${fk.refColumns[0]} = ${show(v)})`, icon: ArrowUpRight, onclick: () => onfk!(fk, v) }] : []),
      ...(canEdit ? [
        { separator: true },
        { label: "Editar célula", icon: Pencil, kbd: "Enter", onclick: () => startEdit(r, c) },
        { label: "Definir como NULL", icon: Ban, kbd: "⌫", onclick: setNull },
        { label: "Clonar linha", icon: CopyPlus, onclick: () => addRow(r) },
        { label: "Nova linha", icon: Plus, onclick: () => addRow() },
        deleted[r] || edits[r] ? { label: "Desfazer nesta(s) linha(s)", icon: Undo2, onclick: undoRows }
          : { label: "Excluir linha(s)", icon: Trash2, danger: true, onclick: deleteRows },
      ] : []),
    ]);
  }

  function resizeCol(e: PointerEvent, i: number) {
    e.preventDefault(); e.stopPropagation();
    const x0 = e.clientX, w0 = widths[i];
    const move = (ev: PointerEvent) => { widths[i] = Math.max(48, w0 + ev.clientX - x0); };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }
  $effect(() => {
    const up = () => (dragging = false);
    window.addEventListener("pointerup", up);
    return () => window.removeEventListener("pointerup", up);
  });
  $effect(() => {
    if (!scroller) return;
    const ro = new ResizeObserver(() => (viewH = scroller!.clientHeight));
    ro.observe(scroller);
    return () => ro.disconnect();
  });
  const tmpl = $derived(`${NW}px ${widths.map(w => w + "px").join(" ")}`);
</script>

<div class="rg">
  <div class="scroll" bind:this={scroller} tabindex="0" role="grid" aria-rowcount={total} aria-colcount={columns.length}
    onscroll={() => (scrollTop = scroller!.scrollTop)} onkeydown={onkey} onpaste={onpaste}>
    <div class="inner" style="height:{HH + total * RH}px; width:{NW + widths.reduce((a, b) => a + b, 0)}px">
      <div class="hrow" style="grid-template-columns:{tmpl}">
        <button class="corner" title="Selecionar tudo (⌘A)" onclick={selectAll}></button>
        {#each columns as col, c (c)}
          <div class="hc" class:sel={!!rect && c >= rect.c0 && c <= rect.c1} class:num={isNum(col.type)} role="columnheader" tabindex="-1"
            onclick={(e) => selectCol(c, e.shiftKey)} onkeydown={() => {}}
            ondblclick={() => onsort?.(col.name)} title={`${col.name} · ${col.type}${onsort ? " — dois cliques ordena" : ""}`}>
            {#if colInfo[c]?.pk}<span class="key" title="chave primária">🔑</span>{:else if fkOf[c]}<span class="key fk" title={`chave estrangeira → ${fkOf[c]!.refTable} (⌘-clique no valor abre)`}>↗</span>{/if}
            <span class="hn ell">{col.name}</span>
            {#if sort?.col === col.name}<span class="srt">{sort.desc ? "↓" : "↑"}</span>{/if}
            <span class="ht">{col.type.toLowerCase()}</span>
            <span class="rz" role="separator" aria-orientation="vertical" onpointerdown={(e) => resizeCol(e, c)}></span>
          </div>
        {/each}
      </div>
      {#each { length: last - first } as _, k (first + k)}
        {@const r = first + k}
        {@const isNew = r >= rows.length}
        <div class="rgr" class:alt={r % 2 === 1} class:flash={flash.has(r)} class:del={!!deleted[r]} class:new={isNew} style="top:{HH + r * RH}px; grid-template-columns:{tmpl}">
          <div class="rn" class:sel={!!rect && r >= rect.r0 && r <= rect.r1} role="rowheader" tabindex="-1" onclick={(e) => selectRow(r, e.shiftKey)} onkeydown={() => {}}>
            {isNew ? "+" : r + 1}
          </div>
          {#each columns as col, c (c)}
            {@const v = valueAt(r, c)}
            {@const changed = !isNew && !!edits[r] && c in edits[r]}
            <div class="cell" class:num={isNum(col.type) && v !== null} class:null={v === null || (isNew && v === undefined)} class:sel={inSel(r, c)}
              class:focus={focusC?.r === r && focusC?.c === c} class:changed class:fk={!!fkOf[c] && v !== null}
              role="gridcell" tabindex="-1"
              onpointerdown={(e) => down(e, r, c)} onpointerenter={() => enter(r, c)} ondblclick={() => startEdit(r, c)}
              oncontextmenu={(e) => cellMenu(e, r, c)} onkeydown={() => {}}
              title={changed ? `antes: ${show(rows[r][c])}` : undefined}>
              {#if editing && editing.r === r && editing.c === c}
                <!-- svelte-ignore a11y_autofocus -->
                <input class="cellinput" bind:value={editing.value} autofocus
                  onkeydown={(e) => { if (e.key === "Enter") { e.preventDefault(); commitEdit("down"); } else if (e.key === "Tab") { e.preventDefault(); commitEdit("right"); }
                    else if (e.key === "Escape") { editing = null; scroller?.focus(); } e.stopPropagation(); }}
                  onblur={() => commitEdit()} />
              {:else}
                <span class="ell">{isNew && v === undefined ? (colInfo[c]?.identity ? "auto" : "padrão") : show(v)}</span>
              {/if}
            </div>
          {/each}
        </div>
      {/each}
    </div>
  </div>
  <div class="foot">
    <span class="tiny muted">{footer}</span>
    {#if summary}<span class="tiny sum">{summary}</span>{/if}
    <span class="grow"></span>
    {#if canEdit && !pendingCount}<button class="btn sm ghost" title="Nova linha" onclick={() => addRow()}><Plus size={13} /> Linha</button>{/if}
    {#if pendingCount}
      <span class="pend tiny">{pendingCount} {pendingCount === 1 ? "alteração pendente" : "alterações pendentes"}</span>
      <button class="btn sm ghost" onclick={discard}><X size={13} /> Descartar</button>
      <button class="btn sm primary" disabled={applying} onclick={apply}><Check size={13} /> Aplicar <span class="kbd">⌘S</span></button>
    {/if}
  </div>
</div>

<style>
  .rg { display: flex; flex-direction: column; min-height: 0; height: 100%; }
  .scroll { flex: 1; min-height: 0; overflow: auto; position: relative; outline: none; font-size: 12.5px; }
  .inner { position: relative; }
  .hrow { position: sticky; top: 0; z-index: 3; display: grid; height: 30px; background: var(--surface-2); border-bottom: 1px solid var(--line-2); }
  .corner { position: sticky; left: 0; z-index: 4; background: var(--surface-2); border: 0; border-right: 1px solid var(--line); cursor: pointer; }
  .hc { position: relative; display: flex; align-items: center; gap: 5px; padding: 0 8px; border-right: 1px solid var(--line); cursor: pointer; min-width: 0;
    font-weight: 620; color: var(--text-2); user-select: none; }
  .hc.num { justify-content: flex-end; }
  .hc.sel { background: var(--accent-soft); color: var(--text); }
  .hn { min-width: 0; }
  .ht { font: 10px var(--mono); color: var(--faint); flex: none; max-width: 70px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .key { font-size: 10px; flex: none; }
  .key.fk { color: var(--info); font-weight: 700; }
  .srt { color: var(--accent); font-weight: 700; }
  .rz { position: absolute; right: -3px; top: 0; bottom: 0; width: 7px; cursor: col-resize; z-index: 2; }
  .rgr { position: absolute; left: 0; right: 0; display: grid; height: 26px; }
  .rgr.flash { animation: fl 2.4s var(--ease-out); }
  @keyframes fl { 0%, 30% { background: color-mix(in srgb, var(--good) 28%, transparent); } 100% { background: transparent; } }
  .rgr.alt { background: color-mix(in srgb, var(--text) 2.2%, transparent); }
  .rgr.del .cell { text-decoration: line-through; color: var(--bad); background: var(--bad-soft); }
  .rgr.new .cell { background: var(--good-soft); }
  .rn { position: sticky; left: 0; z-index: 2; display: flex; align-items: center; justify-content: flex-end; padding: 0 8px; color: var(--faint);
    background: var(--surface); border-right: 1px solid var(--line); font: 11px var(--mono); cursor: pointer; user-select: none; }
  .rn.sel { color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--surface)); }
  .cell { display: flex; align-items: center; padding: 0 8px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); min-width: 0;
    cursor: cell; user-select: none; white-space: nowrap; overflow: hidden; }
  .cell.num { justify-content: flex-end; font-family: var(--mono); font-size: 12px; }
  .cell.null { color: var(--faint); font-style: italic; font-size: 11.5px; }
  .cell.sel { background: color-mix(in srgb, var(--accent) 16%, transparent); }
  .cell.focus { box-shadow: inset 0 0 0 2px var(--accent); }
  .cell.changed { background: var(--warn-soft); color: var(--text); }
  .cell.changed.sel { background: color-mix(in srgb, var(--warn) 30%, transparent); }
  .cell.fk span { text-decoration: underline dotted color-mix(in srgb, var(--info) 60%, transparent); text-underline-offset: 3px; }
  .cellinput { width: 100%; height: 22px; border: 0; outline: none; background: var(--surface); color: var(--text); font: inherit; padding: 0 2px; }
  .foot { display: flex; align-items: center; gap: 10px; padding: 6px 10px; border-top: 1px solid var(--line); min-height: 38px; flex: none; }
  .sum { color: var(--text-2); }
  .pend { color: var(--warn); font-weight: 600; }
</style>
