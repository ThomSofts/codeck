<script lang="ts">
  // Formulário das alterações de estrutura, com o SQL montado ao vivo embaixo: nova coluna, editar coluna (nome, tipo,
  // nulo, padrão, descrição), novo índice e nova tabela. "Executar" manda o SQL que está na tela — com as regras de
  // produção de sempre (destravar; a alteração fica esperando Confirmar/Desfazer).
  import { Copy, KeyRound, Play, Plus, Trash2, TriangleAlert } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { copyText } from "../../lib/clipboard";
  import type { Engine, TableInfo } from "../../lib/db.svelte";
  import { addColumn, alterColumn, createIndex, createTable, renameColumn, TYPES, type ColDef, type EditKind, type TCol } from "../../lib/dbddl";
  import Drawer from "../Drawer.svelte";
  import Switch from "../Switch.svelte";

  let { engine, info = null, what, prod = false, onexec, onclose }:
    { engine: Engine; info?: TableInfo | null; what: EditKind; prod?: boolean;
      onexec: (sql: string[], touched: { schema: string; name: string }[]) => Promise<boolean>; onclose: () => void } = $props();

  const E = untrack(() => engine) as Exclude<Engine, "mongodb" | "firebase" | "redis">;
  const lite = E === "sqlite" || E === "libsql";
  const t = untrack(() => (info ? { schema: info.schema, name: info.name } : null));
  const blank = (): ColDef => ({ name: "", type: TYPES[E][0], nullable: true, default: "", identity: false, pk: false, comment: "" });
  const fromCol = (c: TCol): ColDef => ({ name: c.name, type: c.type, nullable: c.nullable, default: c.default ?? "", identity: c.identity, pk: c.pk > 0, comment: c.comment || "" });

  // ------------------------------------------------------------ estado do formulário
  const w = untrack(() => what);
  let col = $state<ColDef>(w.kind === "column" && w.col ? fromCol(w.col) : blank());
  let ixName = $state("");
  let ixCols = $state<string[]>([]);
  let ixUnique = $state(false);
  let tSchema = $state(w.kind === "table" ? w.schema : "");
  let tName = $state("");
  let tComment = $state("");
  let tCols = $state<ColDef[]>(w.kind === "table" ? [{ ...blank(), name: "id", type: lite ? "INTEGER" : E === "sqlserver" ? "int" : E === "mysql" ? "int" : "bigint", nullable: false, identity: true, pk: true }] : []);
  let running = $state(false);
  let edited = $state<string | null>(null);   // SQL ajustado à mão

  $effect(() => { if (w.kind === "index" && !ixName && ixCols.length && t) ixName = `ix_${t.name}_${ixCols.join("_")}`.replace(/[^\w]/g, "_").slice(0, 60); });

  const built = $derived.by((): { sql: string[]; warn?: string; error?: string } => {
    try {
      if (w.kind === "column" && t) {
        if (!col.name.trim()) return { sql: [], error: "Dê um nome à coluna." };
        if (!col.type.trim()) return { sql: [], error: "Escolha o tipo." };
        if (!w.col) {
          const warn = lite && !col.nullable && !col.default.trim() ? "No SQLite, coluna NOT NULL nova precisa de um padrão (as linhas que já existem recebem ele)." : undefined;
          return { sql: addColumn(E, t, { ...col, name: col.name.trim() }), warn };
        }
        const out: string[] = [];
        let warn: string | undefined;
        if (col.name.trim() !== w.col.name) out.push(...renameColumn(E, t, w.col.name, col.name.trim()));
        const a = alterColumn(E, t, w.col, { ...col, name: col.name.trim() });
        if (a.error && (a.sql.length || out.length === 0)) return { sql: out, error: a.error };
        out.push(...a.sql);
        warn = a.warn;
        if (!out.length) return { sql: [], error: "Nada mudou ainda." };
        return { sql: out, warn };
      }
      if (w.kind === "index" && t) {
        if (!ixCols.length) return { sql: [], error: "Marque as colunas do índice (na ordem em que clicar)." };
        if (!ixName.trim()) return { sql: [], error: "Dê um nome ao índice." };
        return { sql: createIndex(E, t, ixName.trim(), ixCols, ixUnique) };
      }
      if (w.kind === "table") {
        if (!tName.trim()) return { sql: [], error: "Dê um nome à tabela." };
        const cols = tCols.filter(c => c.name.trim());
        if (!cols.length) return { sql: [], error: "Inclua ao menos uma coluna." };
        const dup = cols.map(c => c.name.trim().toLowerCase()).find((n, i, a) => a.indexOf(n) !== i);
        if (dup) return { sql: [], error: `Coluna repetida: ${dup}` };
        const warn = !cols.some(c => c.pk) ? "Sem chave primária a grade não consegue editar as linhas desta tabela (não sabe qual linha é qual)." : undefined;
        return { sql: createTable(E, { schema: tSchema.trim(), name: tName.trim() }, cols.map(c => ({ ...c, name: c.name.trim() })), tComment), warn };
      }
    } catch (e: any) { return { sql: [], error: e?.message || String(e) }; }
    return { sql: [] };
  });
  const sqlText = $derived(edited ?? built.sql.join("\n\n"));
  // o formulário mudou: volta a valer o SQL gerado
  $effect(() => { void built; untrack(() => (edited = null)); });

  const title = $derived(w.kind === "column" ? (w.col ? `Coluna ${w.col.name}` : "Nova coluna") : w.kind === "index" ? "Novo índice" : "Nova tabela");
  const sub = $derived(w.kind === "table" ? "Monte as colunas — o SQL aparece embaixo" : `${t?.schema && !lite ? t.schema + "." : ""}${t?.name || ""}`);
  async function run() {
    const sql = sqlText.trim();
    if (!sql || running) return;
    running = true;
    try {
      const touched = w.kind === "table" ? [{ schema: tSchema.trim() || (info?.schema ?? ""), name: tName.trim() }] : t ? [t] : [];
      if (await onexec([sql], touched)) onclose();
    } finally { running = false; }
  }
  function toggleIx(name: string) { ixCols = ixCols.includes(name) ? ixCols.filter(x => x !== name) : [...ixCols, name]; }
</script>

<Drawer {title} subtitle={sub} {onclose} width={w.kind === "table" ? 860 : 600} resizeKey={w.kind === "table" ? "db.newTable" : null}>
  <div class="se">
    {#if w.kind === "column"}
      <div class="row2">
        <label class="label">Nome <input class="input mono" bind:value={col.name} placeholder="nome_da_coluna" /></label>
        <label class="label">Tipo <input class="input mono" list="db-types" bind:value={col.type} /></label>
      </div>
      <div class="row2">
        <label class="label">Padrão <span class="hint">expressão SQL: 0, 'ativo', CURRENT_TIMESTAMP</span>
          <input class="input mono" bind:value={col.default} placeholder="sem padrão" disabled={col.identity} /></label>
        <div class="sw"><Switch bind:checked={col.nullable} label="Aceita nulo" hint={col.nullable ? "NULL permitido" : "NOT NULL"} /></div>
      </div>
      {#if !w.col && !lite}<Switch bind:checked={col.identity} label="Numeração automática" hint={E === "postgres" ? "GENERATED BY DEFAULT AS IDENTITY" : E === "sqlserver" ? "IDENTITY(1,1)" : "AUTO_INCREMENT (precisa de índice)"} />{/if}
      <label class="label">Descrição <textarea class="input" rows="3" bind:value={col.comment} placeholder={lite ? "o SQLite não guarda descrição" : "para que serve esta coluna — aparece na estrutura e na ficha"} disabled={lite}></textarea></label>
    {:else if w.kind === "index"}
      <label class="label">Nome <input class="input mono" bind:value={ixName} /></label>
      <Switch bind:checked={ixUnique} label="Único" hint="não deixa repetir a combinação de valores" />
      <div class="label">Colunas <span class="hint">na ordem em que clicar</span></div>
      <div class="pick">
        {#each info?.columns || [] as c (c.name)}
          {@const n = ixCols.indexOf(c.name)}
          <button class="pk" class:on={n >= 0} onclick={() => toggleIx(c.name)}>{#if n >= 0}<span class="ord">{n + 1}</span>{/if}<span class="mono">{c.name}</span><span class="ty">{c.type.toLowerCase()}</span></button>
        {/each}
      </div>
    {:else}
      <div class="row3">
        {#if !lite}<label class="label">Schema <input class="input mono" bind:value={tSchema} /></label>{/if}
        <label class="label">Nome da tabela <input class="input mono" bind:value={tName} placeholder="clientes" /></label>
      </div>
      {#if !lite}<label class="label">Descrição <input class="input" bind:value={tComment} placeholder="o que esta tabela guarda" /></label>{/if}
      <div class="tc">
        <div class="tch"><span>Coluna</span><span>Tipo</span><span title="aceita nulo">Nulo</span><span title="chave primária">PK</span><span title="numeração automática">Auto</span><span>Padrão</span><span>Descrição</span><span></span></div>
        {#each tCols as c, i (i)}
          <div class="tcr">
            <input class="input mono" bind:value={c.name} placeholder="nome" />
            <input class="input mono" list="db-types" bind:value={c.type} />
            <input type="checkbox" bind:checked={c.nullable} disabled={c.pk} title="aceita nulo" />
            <input type="checkbox" bind:checked={c.pk} title="chave primária" />
            <input type="checkbox" bind:checked={c.identity} title="numeração automática" />
            <input class="input mono" bind:value={c.default} placeholder="—" disabled={c.identity} />
            <input class="input" bind:value={c.comment} placeholder={lite ? "—" : "descrição"} disabled={lite} />
            <button class="btn sm ghost icon" title="Tirar a coluna" onclick={() => (tCols = tCols.filter((_, k) => k !== i))}><Trash2 size={13} /></button>
          </div>
        {/each}
        <button class="btn sm ghost add" onclick={() => (tCols = [...tCols, blank()])}><Plus size={13} /> Coluna</button>
      </div>
    {/if}
    <datalist id="db-types">{#each TYPES[E] as ty (ty)}<option value={ty}></option>{/each}</datalist>

    <div class="sqlh">
      <span>SQL que vai rodar</span>
      {#if edited !== null}<span class="pill warn">editado à mão</span>{/if}
      <span class="grow"></span>
      {#if sqlText}<button class="btn sm ghost" onclick={() => copyText(sqlText, "SQL copiado")}><Copy size={12} /> Copiar</button>{/if}
    </div>
    {#if built.error && !edited}
      <div class="msg"><KeyRound size={14} /> {built.error}</div>
    {/if}
    {#if sqlText}
      <textarea class="sql" spellcheck="false" value={sqlText} oninput={(e) => (edited = (e.target as HTMLTextAreaElement).value)}
        rows={Math.min(16, Math.max(3, sqlText.split("\n").length + 1))}></textarea>
    {/if}
    {#if built.warn}<div class="msg warn"><TriangleAlert size={14} /> {built.warn}</div>{/if}
    {#if prod}<div class="msg bad"><TriangleAlert size={14} /> PRODUÇÃO: roda numa transação e espera você Confirmar ou Desfazer (desfeita sozinha em 5 minutos){E === "mysql" ? " — no MySQL, alteração de estrutura não volta atrás" : ""}.</div>{/if}
  </div>
  {#snippet footer()}
    <span class="grow"></span>
    <button class="btn" onclick={onclose}>Cancelar</button>
    <button class="btn {prod ? 'danger-solid' : 'primary'}" disabled={!sqlText.trim() || running || (!!built.error && edited === null)} onclick={run}><Play size={13} /> {running ? "Executando…" : "Executar"}</button>
  {/snippet}
</Drawer>

<style>
  .se { display: flex; flex-direction: column; gap: 14px; }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: end; }
  .row3 { display: grid; grid-template-columns: 200px 1fr; gap: 12px; }
  .sw { padding-bottom: 6px; }
  .hint { font-weight: 400; color: var(--muted); font-size: 11.5px; margin-left: 4px; }
  .mono { font-family: var(--mono); }
  .pick { display: flex; flex-wrap: wrap; gap: 6px; }
  .pk { display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 99px; border: 1px solid var(--line-2); background: var(--surface-2);
    color: var(--text-2); font: 12.5px var(--font); cursor: pointer; }
  .pk.on { border-color: var(--accent); background: var(--accent-soft); color: var(--text); }
  .pk .ord { display: grid; place-items: center; width: 17px; height: 17px; border-radius: 50%; background: var(--accent); color: #fff; font: 700 10px var(--font); }
  .pk .ty { font: 10.5px var(--mono); color: var(--faint); }
  .tc { display: grid; gap: 4px; }
  .tch, .tcr { display: grid; grid-template-columns: minmax(110px, 1.2fr) minmax(110px, 1fr) 38px 30px 38px minmax(80px, .8fr) minmax(100px, 1.2fr) 30px; gap: 6px; align-items: center; }
  .tch { font: 650 11px var(--font); color: var(--muted); text-transform: uppercase; letter-spacing: .04em; padding: 0 2px; }
  .tcr .input { height: 30px; font-size: 12.5px; }
  .tcr input[type="checkbox"] { justify-self: center; accent-color: var(--accent); width: 15px; height: 15px; }
  .add { justify-self: start; }
  .sqlh { display: flex; align-items: center; gap: 8px; font: 650 12px var(--font); color: var(--text-2); text-transform: uppercase; letter-spacing: .04em; margin-top: 4px; }
  .sql { width: 100%; resize: vertical; font: 12.5px/1.55 var(--mono); padding: 10px 12px; border-radius: 10px; border: 1px solid var(--line-2);
    background: var(--bg-2); color: var(--text); outline: none; }
  .sql:focus { border-color: var(--accent); }
  .msg { display: flex; align-items: flex-start; gap: 8px; padding: 9px 12px; border-radius: 10px; background: var(--surface-2); color: var(--text-2); font-size: 12.5px; line-height: 1.45; }
  .msg :global(svg) { flex: none; margin-top: 1px; color: var(--muted); }
  .msg.warn { background: var(--warn-soft); color: var(--text); } .msg.warn :global(svg) { color: var(--warn); }
  .msg.bad { background: var(--bad-soft); color: var(--text); } .msg.bad :global(svg) { color: var(--bad); }
  .grow { flex: 1; }
  @media (max-width: 700px) { .row2, .row3 { grid-template-columns: 1fr; } }
</style>
