<script lang="ts">
  // A estrutura de uma tabela, para ler e para mudar: cabeçalho com a descrição e os números (colunas, linhas estimadas,
  // tamanho, índices, chaves), as colunas com tipo, nulo, padrão, chaves e a descrição de cada uma, os índices, as chaves
  // estrangeiras e o CREATE. Cada mudança mostra o SQL antes de rodar (StructureEditor e as perguntas daqui).
  import { ArrowUpRight, Braces, Copy, Eraser, Hash, KeyRound, Link2, ListTree, MoreHorizontal, Pencil, Plus, RefreshCw, Search, Sparkles, Table2, Trash2, Type, Eye } from "@lucide/svelte";
  import { copyText } from "../../lib/clipboard";
  import type { Engine, TableInfo } from "../../lib/db.svelte";
  import { canAlter, createFromInfo, dropColumn, dropIndex, dropTable, renameTable, tableComment, truncateTable, type EditKind, type TCol } from "../../lib/dbddl";
  import { ui } from "../../lib/ui.svelte";
  import StructureEditor from "./StructureEditor.svelte";

  let { info, engine, kind = "table", prod = false, locked = false, onexec, onopen, oncount, onrenamed, ondropped, onrefresh }:
    { info: TableInfo; engine: Engine; kind?: string; prod?: boolean;
      /** produção em somente leitura: as ações aparecem, mas avisam que é preciso destravar */
      locked?: boolean;
      onexec: (sql: string[], touched: { schema: string; name: string }[]) => Promise<boolean>;
      onopen: (t: { schema: string; name: string }) => void; oncount?: () => Promise<number | null>;
      onrenamed?: (name: string) => void; ondropped?: () => void; onrefresh?: () => void } = $props();

  const E = $derived(engine as Exclude<Engine, "mongodb" | "firebase" | "redis">);
  const alter = $derived(canAlter(engine) && kind === "table");
  const lite = $derived(engine === "sqlite" || engine === "libsql");
  const t = $derived({ schema: info.schema, name: info.name });
  let edit = $state<EditKind | null>(null);
  let filter = $state("");
  let exact = $state<number | null>(null);
  let counting = $state(false);
  let showDdl = $state(false);

  const cols = $derived(info.columns as TCol[]);
  const shown = $derived(cols.map((c, i) => ({ c, i })).filter(({ c }) => !filter || (c.name + " " + c.type + " " + (c.comment || "")).toLowerCase().includes(filter.toLowerCase())));
  const pk = $derived(cols.filter(c => c.pk > 0).sort((a, b) => a.pk - b.pk));
  const fkOf = (name: string) => info.fks.find(f => f.columns.includes(name)) || null;
  const ixOf = (name: string) => info.indexes.filter(ix => !ix.primary && ix.columns.includes(name));
  const described = $derived(cols.filter(c => (c.comment || "").trim()).length);
  const ddl = $derived(canAlter(engine) && showDdl ? createFromInfo(E, info) : "");

  const nf = (n: number) => n.toLocaleString("pt-BR");
  function size(b: number) {
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0, v = b;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return `${v.toLocaleString("pt-BR", { maximumFractionDigits: v < 10 && i ? 1 : 0 })} ${u[i]}`;
  }
  /** cor do tipo (família): número, texto, data, lógico, binário, json/uuid */
  function fam(ty: string) {
    const x = ty.toLowerCase();
    if (/int|dec|num|money|float|real|double|serial|bit\b/.test(x) && !/point/.test(x)) return "n";
    if (/char|text|string|clob|enum|set\(/.test(x)) return "s";
    if (/date|time|year|interval/.test(x)) return "d";
    if (/bool/.test(x)) return "b";
    if (/json|uuid|uniqueidentifier|xml|array|\[\]/.test(x)) return "j";
    if (/bin|blob|bytea|image/.test(x)) return "x";
    return "o";
  }

  // ------------------------------------------------------------ ações
  const guard = () => { if (locked) ui.toast("Produção está somente leitura — ao executar, o Codeck pede para destravar esta conexão", "info"); };
  async function ask(title: string, sql: string[], o: { message?: string; confirm: string; danger?: boolean }) {
    guard();
    return !!(await ui.ask({ title, message: o.message, detail: sql, confirm: o.confirm, danger: o.danger }));
  }
  async function rename() {
    guard();
    const v = await ui.ask({ title: `Renomear ${kind === "view" ? "a view" : "a tabela"} ${info.name}`, input: { label: "Novo nome", value: info.name, required: true }, confirm: "Ver o SQL" });
    if (typeof v !== "string" || !v.trim() || v.trim() === info.name) return;
    const sql = renameTable(E, t, v.trim());
    if (!(await ask(`Renomear para ${v.trim()}?`, sql, { message: "Consultas, views e procedures que usam o nome antigo deixam de funcionar.", confirm: "Renomear" }))) return;
    if (await onexec(sql, [t, { schema: t.schema, name: v.trim() }])) onrenamed?.(v.trim());
  }
  async function drop() {
    const sql = dropTable(E, t, kind === "view");
    const typed = await ui.ask({ title: `Excluir ${kind === "view" ? "a view" : "a tabela"} ${info.name}?`, danger: true, confirm: "Excluir",
      message: kind === "view" ? "A view some (os dados das tabelas continuam)." : `A tabela e todos os dados${info.rows != null ? ` (~${nf(info.rows)} linhas)` : ""} somem. Para confirmar, digite o nome da tabela.`,
      input: kind === "view" ? undefined : { label: "Nome da tabela", placeholder: info.name, required: true } });
    if (!typed || (kind !== "view" && typed !== info.name)) { if (typed) ui.toast("O nome não confere — nada foi excluído", "error"); return; }
    if (await onexec(sql, [t])) ondropped?.();
  }
  async function truncate() {
    const sql = truncateTable(E, t);
    if (!(await ask(`Esvaziar ${info.name}?`, sql, { message: `Apaga todas as linhas${info.rows != null ? ` (~${nf(info.rows)})` : ""} e mantém a estrutura.${lite ? "" : " TRUNCATE não dispara triggers de DELETE e pode falhar se outra tabela aponta para esta."}`, confirm: "Esvaziar", danger: true }))) return;
    await onexec(sql, [t]);
  }
  async function editComment() {
    guard();
    const v = await ui.ask({ title: `Descrição de ${info.name}`, input: { label: "O que esta tabela guarda", value: info.comment || "", multiline: true }, confirm: "Ver o SQL" });
    if (typeof v !== "string" || v.trim() === (info.comment || "").trim()) return;
    const sql = tableComment(E, t, v.trim());
    if (sql.length && (await ask("Salvar a descrição?", sql, { confirm: "Salvar" }))) await onexec(sql, [t]);
  }
  async function delCol(c: TCol) {
    const sql = dropColumn(E, t, c.name);
    if (!(await ask(`Excluir a coluna ${c.name}?`, sql, { message: "Os valores desta coluna somem de todas as linhas.", confirm: "Excluir coluna", danger: true }))) return;
    await onexec(sql, [t]);
  }
  async function delIx(name: string) {
    const sql = dropIndex(E, t, name);
    if (!(await ask(`Excluir o índice ${name}?`, sql, { message: "Consultas que usavam este índice podem ficar mais lentas.", confirm: "Excluir índice", danger: true }))) return;
    await onexec(sql, [t]);
  }
  async function count() {
    if (!oncount || counting) return;
    counting = true;
    try { exact = await oncount(); } finally { counting = false; }
  }
  function colMenu(e: MouseEvent, c: TCol) {
    e.preventDefault();
    ui.contextMenu(e, [
      { heading: c.name },
      ...(alter ? [{ label: "Editar coluna…", icon: Pencil, onclick: () => { guard(); edit = { kind: "column", col: c }; } }] : []),
      { label: "Copiar o nome", icon: Copy, onclick: () => copyText(c.name) },
      ...(c.comment ? [{ label: "Copiar a descrição", onclick: () => copyText(c.comment!) }] : []),
      ...(fkOf(c.name) ? [{ label: `Abrir ${fkOf(c.name)!.refTable}`, icon: ArrowUpRight, onclick: () => onopen({ schema: fkOf(c.name)!.refSchema, name: fkOf(c.name)!.refTable }) }] : []),
      ...(alter && !c.pk ? [{ separator: true }, { label: "Excluir coluna…", icon: Trash2, danger: true, onclick: () => delCol(c) }] : []),
    ]);
  }
  function moreMenu(e: MouseEvent) {
    ui.contextMenu(e, [
      ...(alter ? [{ label: "Renomear…", icon: Pencil, onclick: rename }, { label: "Descrição…", icon: Type, disabled: lite, onclick: editComment }] : []),
      ...(canAlter(engine) ? [{ label: "Copiar o CREATE", icon: Braces, onclick: () => copyText(createFromInfo(E, info), "CREATE copiado") }] : []),
      { label: "Copiar o nome completo", icon: Copy, onclick: () => copyText(lite ? info.name : `${info.schema}.${info.name}`) },
      ...(alter ? [{ separator: true }, { label: "Esvaziar (apagar todas as linhas)…", icon: Eraser, danger: true, onclick: truncate }] : []),
      ...(canAlter(engine) && (kind === "table" || kind === "view") ? [{ label: kind === "view" ? "Excluir a view…" : "Excluir a tabela…", icon: Trash2, danger: true, onclick: drop }] : []),
    ]);
  }
</script>

<div class="ts">
  <!-- cabeçalho -->
  <header class="head">
    <div class="tile" class:view={kind === "view"}>{#if kind === "view"}<Eye size={20} />{:else}<Table2 size={20} />{/if}</div>
    <div class="ti">
      <div class="tn">{#if info.schema && !lite}<span class="sch">{info.schema}.</span>{/if}<h3>{info.name}</h3>{#if kind === "view"}<span class="pill info">view</span>{/if}</div>
      {#if info.comment}
        <button class="desc" disabled={!alter || lite} title={alter ? "Editar a descrição" : undefined} onclick={editComment}>{info.comment}</button>
      {:else if alter && !lite}
        <button class="desc empty" onclick={editComment}><Plus size={12} /> Adicionar uma descrição</button>
      {/if}
    </div>
    <span class="grow"></span>
    {#if onrefresh}<button class="btn sm ghost icon" title="Ler a estrutura de novo" onclick={onrefresh}><RefreshCw size={14} /></button>{/if}
    {#if alter}<button class="btn sm" onclick={() => { guard(); edit = { kind: "column", col: null }; }}><Plus size={13} /> Coluna</button>{/if}
    <button class="btn sm ghost icon" title="Mais ações" onclick={moreMenu}><MoreHorizontal size={15} /></button>
  </header>

  <div class="stats">
    <div class="st"><b>{cols.length}</b><span>colunas{#if described} · {described} descritas{/if}</span></div>
    <div class="st">
      <b>{exact != null ? nf(exact) : info.rows != null ? "~" + nf(info.rows) : "—"}</b>
      <span>{exact != null ? "linhas (contadas)" : "linhas (estimativa)"}
        {#if oncount}<button class="link" disabled={counting} onclick={count}>{counting ? "contando…" : exact != null ? "contar de novo" : "contar"}</button>{/if}</span>
    </div>
    {#if info.bytes != null}<div class="st"><b>{size(info.bytes)}</b><span>dados + índices</span></div>{/if}
    <div class="st"><b>{info.indexes.length}</b><span>{info.indexes.length === 1 ? "índice" : "índices"}</span></div>
    <div class="st"><b>{info.fks.length}</b><span>{info.fks.length === 1 ? "chave estrangeira" : "chaves estrangeiras"}</span></div>
    <div class="st pkst"><b class="mono">{pk.length ? pk.map(c => c.name).join(", ") : "—"}</b><span>chave primária{#if !pk.length && kind === "table"} · <em>sem ela a grade não edita</em>{/if}</span></div>
  </div>

  <!-- colunas -->
  <section>
    <div class="sh">
      <h4><ListTree size={14} /> Colunas</h4>
      <label class="flt"><Search size={12} /><input placeholder="Filtrar colunas…" bind:value={filter} /></label>
    </div>
    <div class="cols">
      {#each shown as { c, i } (c.name)}
        {@const fk = fkOf(c.name)}
        {@const ixs = ixOf(c.name)}
        <div class="col" role="row" tabindex="-1" oncontextmenu={(e) => colMenu(e, c)} ondblclick={() => alter && (guard(), (edit = { kind: "column", col: c }))}>
          <span class="ord">{i + 1}</span>
          <span class="ic">{#if c.pk}<span class="badge pk" title={`chave primária${pk.length > 1 ? ` (${c.pk}ª)` : ""}`}><KeyRound size={11} /></span>{:else if fk}<span class="badge fk" title="chave estrangeira"><Link2 size={11} /></span>{/if}</span>
          <div class="cn">
            <div class="cl"><b class="mono">{c.name}</b>
              {#if c.identity}<span class="chip auto" title="numeração automática"><Sparkles size={10} /> auto</span>{/if}
              {#if fk}<button class="chip fkc" title="Abrir a tabela referenciada" onclick={() => onopen({ schema: fk.refSchema, name: fk.refTable })}>→ {fk.refTable}.{fk.refColumns[fk.columns.indexOf(c.name)]}</button>{/if}
              {#each ixs as ix (ix.name)}<span class="chip ix" title={`índice ${ix.name}: ${ix.columns.join(", ")}`}><Hash size={10} />{ix.unique ? "único" : "índice"}</span>{/each}
            </div>
            {#if c.comment}<p class="cd">{c.comment}</p>{:else if alter && !lite}<button class="cd add" onclick={() => { guard(); edit = { kind: "column", col: c }; }}>+ descrição</button>{/if}
          </div>
          <span class="ty f-{fam(c.type)}">{c.type.toLowerCase()}</span>
          <span class="nl" class:req={!c.nullable}>{c.nullable ? "nulo" : "obrigatória"}</span>
          <span class="df mono ell" title={c.default ?? ""}>{c.default ?? ""}</span>
          <span class="acts">
            {#if alter}
              <button class="btn sm ghost icon" title="Editar coluna" onclick={() => { guard(); edit = { kind: "column", col: c }; }}><Pencil size={13} /></button>
              {#if !c.pk}<button class="btn sm ghost icon dz" title="Excluir coluna" onclick={() => delCol(c)}><Trash2 size={13} /></button>{/if}
            {/if}
          </span>
        </div>
      {:else}
        <p class="tiny muted pad">Nenhuma coluna com “{filter}”.</p>
      {/each}
    </div>
  </section>

  <!-- índices e chaves -->
  <div class="two">
    <section>
      <div class="sh"><h4><Hash size={14} /> Índices</h4>{#if alter}<button class="btn sm ghost" onclick={() => { guard(); edit = { kind: "index" }; }}><Plus size={13} /> Índice</button>{/if}</div>
      {#each info.indexes as ix (ix.name)}
        <div class="card">
          <div class="cl"><b class="mono ell">{ix.name}</b>{#if ix.primary}<span class="chip pkc">primária</span>{:else if ix.unique}<span class="chip ix">único</span>{/if}
            <span class="grow"></span>{#if alter && !ix.primary}<button class="btn sm ghost icon dz" title="Excluir índice" onclick={() => delIx(ix.name)}><Trash2 size={13} /></button>{/if}</div>
          <div class="chips">{#each ix.columns as c, k (k)}<span class="cc mono">{c}</span>{/each}</div>
        </div>
      {:else}<p class="tiny muted">Sem índices.</p>{/each}
    </section>
    <section>
      <div class="sh"><h4><Link2 size={14} /> Chaves estrangeiras</h4></div>
      {#each info.fks as fk (fk.name)}
        <button class="card fkcard" onclick={() => onopen({ schema: fk.refSchema, name: fk.refTable })} title="Abrir a tabela referenciada">
          <div class="cl"><span class="mono">{fk.columns.join(", ")}</span><ArrowUpRight size={13} /><b class="mono">{fk.refTable}</b><span class="mono muted">({fk.refColumns.join(", ")})</span></div>
          <span class="tiny muted mono">{fk.name}</span>
        </button>
      {:else}<p class="tiny muted">Esta tabela não aponta para outras.</p>{/each}
    </section>
  </div>

  {#if canAlter(engine)}
    <section>
      <div class="sh"><button class="h4b" onclick={() => (showDdl = !showDdl)}><Braces size={14} /> {info.ddl ? "CREATE (como o banco guardou)" : "CREATE (montado do catálogo)"} <span class="tiny muted">{showDdl ? "esconder" : "mostrar"}</span></button>
        {#if showDdl}<button class="btn sm ghost" onclick={() => copyText(ddl, "CREATE copiado")}><Copy size={12} /> Copiar</button>{/if}</div>
      {#if showDdl}<pre class="ddl">{ddl}</pre>{/if}
    </section>
  {/if}
</div>

{#if edit}
  <StructureEditor {engine} {info} what={edit} {prod} {onexec} onclose={() => (edit = null)} />
{/if}

<style>
  .ts { height: 100%; overflow: auto; padding: 16px 18px 26px; display: flex; flex-direction: column; gap: 16px; animation: fade .25s; }
  .head { display: flex; align-items: center; gap: 12px; }
  .tile { width: 44px; height: 44px; border-radius: 13px; display: grid; place-items: center; flex: none; color: var(--accent);
    background: linear-gradient(140deg, color-mix(in srgb, var(--accent) 26%, transparent), color-mix(in srgb, var(--accent) 6%, var(--surface-2)));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 35%, transparent); }
  .tile.view { color: var(--info); background: linear-gradient(140deg, color-mix(in srgb, var(--info) 26%, transparent), color-mix(in srgb, var(--info) 6%, var(--surface-2)));
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--info) 35%, transparent); }
  .ti { display: grid; gap: 3px; min-width: 0; }
  .tn { display: flex; align-items: baseline; gap: 2px; min-width: 0; }
  .tn h3 { margin: 0; font-size: 19px; letter-spacing: -0.02em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tn .pill { margin-left: 8px; align-self: center; }
  .sch { color: var(--muted); font-size: 15px; }
  .desc { border: 0; background: none; padding: 0; text-align: left; color: var(--text-2); font: 13px/1.45 var(--font); cursor: pointer; max-width: 760px; }
  .desc:disabled { cursor: default; }
  .desc:not(:disabled):hover { color: var(--text); text-decoration: underline dotted; }
  .desc.empty { display: inline-flex; align-items: center; gap: 4px; color: var(--muted); font-size: 12.5px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; }
  .st { display: grid; gap: 2px; padding: 10px 12px; border-radius: 12px; background: var(--surface-2); border: 1px solid var(--line); min-width: 0; }
  .st b { font-size: 17px; letter-spacing: -0.01em; font-variant-numeric: tabular-nums; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .st span { font-size: 11.5px; color: var(--muted); }
  .st em { color: var(--warn); font-style: normal; }
  .pkst b { font-size: 13.5px; padding-top: 3px; }
  .link { background: none; border: 0; color: var(--accent); cursor: pointer; font: inherit; padding: 0; margin-left: 4px; }
  section { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .sh { display: flex; align-items: center; gap: 10px; }
  .sh h4, .h4b { display: flex; align-items: center; gap: 6px; margin: 0; font: 650 12px var(--font); text-transform: uppercase; letter-spacing: .05em; color: var(--text-2); flex: 1; }
  .h4b { border: 0; background: none; cursor: pointer; padding: 0; text-align: left; }
  .h4b .tiny { text-transform: none; letter-spacing: 0; font-weight: 400; }
  .flt { display: flex; align-items: center; gap: 6px; height: 26px; padding: 0 8px; border-radius: 7px; background: var(--surface-2); border: 1px solid var(--line); color: var(--muted); width: 220px; }
  .flt input { flex: 1; min-width: 0; border: 0; outline: none; background: none; color: var(--text); font: 12px var(--font); }
  .cols { border: 1px solid var(--line); border-radius: 12px; overflow: hidden; background: var(--surface); }
  .col { display: grid; grid-template-columns: 28px 22px minmax(0, 1fr) minmax(90px, 170px) 84px minmax(60px, 150px) 62px; gap: 10px; align-items: center;
    padding: 8px 10px; border-bottom: 1px solid var(--line); transition: background var(--t-fast); }
  .col:last-child { border-bottom: 0; }
  .col:hover { background: var(--surface-2); }
  .ord { font: 11px var(--mono); color: var(--faint); text-align: right; }
  .badge { display: grid; place-items: center; width: 20px; height: 20px; border-radius: 6px; }
  .badge.pk { background: color-mix(in srgb, var(--warn) 20%, transparent); color: var(--warn); }
  .badge.fk { background: color-mix(in srgb, var(--info) 18%, transparent); color: var(--info); }
  .cn { min-width: 0; display: grid; gap: 2px; }
  .cl { display: flex; align-items: center; gap: 6px; min-width: 0; flex-wrap: wrap; }
  .cl b { font-size: 13px; }
  .cd { margin: 0; font-size: 12px; color: var(--muted); line-height: 1.4; }
  .cd.add { border: 0; background: none; padding: 0; text-align: left; cursor: pointer; color: var(--faint); font: 11.5px var(--font); opacity: 0; transition: opacity var(--t-fast); }
  .col:hover .cd.add { opacity: 1; }
  .chip { display: inline-flex; align-items: center; gap: 3px; font: 600 10.5px var(--font); padding: 1px 7px; border-radius: 99px; background: var(--surface-3); color: var(--text-2); border: 0; }
  .chip.auto { background: var(--accent-soft); color: var(--accent); }
  .chip.fkc { background: var(--info-soft); color: var(--info); cursor: pointer; font-family: var(--mono); }
  .chip.fkc:hover { text-decoration: underline; }
  .chip.ix { background: color-mix(in srgb, var(--good) 15%, transparent); color: var(--good); }
  .chip.pkc { background: color-mix(in srgb, var(--warn) 18%, transparent); color: var(--warn); }
  .ty { justify-self: start; font: 11.5px var(--mono); padding: 2px 8px; border-radius: 7px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    --tc: var(--muted); color: var(--tc); background: color-mix(in srgb, var(--tc) 12%, transparent); }
  .ty.f-n { --tc: var(--warn); } .ty.f-s { --tc: var(--good); } .ty.f-d { --tc: var(--info); } .ty.f-b { --tc: var(--accent); } .ty.f-j { --tc: var(--cat5, var(--accent)); } .ty.f-x { --tc: var(--bad); }
  .nl { font-size: 11.5px; color: var(--muted); }
  .nl.req { color: var(--text-2); font-weight: 600; }
  .df { font-size: 11.5px; color: var(--text-2); }
  .acts { display: flex; gap: 2px; justify-content: flex-end; opacity: 0; transition: opacity var(--t-fast); }
  .col:hover .acts { opacity: 1; }
  .dz:hover { color: var(--bad); background: var(--bad-soft); }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .card { display: grid; gap: 6px; padding: 10px 12px; border-radius: 11px; border: 1px solid var(--line); background: var(--surface-2); text-align: left; color: var(--text); font: 12.5px var(--font); }
  .fkcard { cursor: pointer; transition: border-color var(--t-fast); }
  .fkcard:hover { border-color: var(--info); }
  .fkcard :global(svg) { color: var(--info); }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .cc { font-size: 11.5px; padding: 1px 7px; border-radius: 6px; background: var(--surface-3); color: var(--text-2); }
  .ddl { margin: 0; padding: 12px 14px; border-radius: 11px; background: var(--bg-2); border: 1px solid var(--line); font: 12px/1.55 var(--mono); overflow: auto; max-height: 380px; user-select: text; white-space: pre; }
  .mono { font-family: var(--mono); }
  .pad { padding: 10px; margin: 0; }
  .grow { flex: 1; }
  @media (max-width: 980px) { .two { grid-template-columns: 1fr; } .col { grid-template-columns: 22px 20px minmax(0, 1fr) minmax(80px, 130px) 62px; } .col .df, .col .nl { display: none; } }
</style>
