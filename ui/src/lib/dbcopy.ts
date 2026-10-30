// Cópia da grade de resultados: um retângulo de N colunas × N linhas vira texto no formato escolhido.
import type { Column, CopyFormat, Engine } from "./db.svelte";
import { quoteFor } from "./db.svelte";

export type CopyKind = CopyFormat | "tsv-header" | "update" | "in";
export const COPY_LABEL: Record<CopyKind, string> = {
  "tsv": "Texto (cola no Excel)", "tsv-header": "Texto com cabeçalho", "csv": "CSV", "json": "JSON", "markdown": "Tabela Markdown",
  "insert": "INSERT", "update": "UPDATE (pela chave)", "in": "Lista para IN (…)",
};

export interface CopyCtx { engine: Engine; table?: { schema: string; name: string } | null; pk?: string[]; allColumns?: Column[]; allRow?: (r: number) => any[] }

const isBin = (v: any) => v && typeof v === "object" && "$bin" in v;

export function cellText(v: any): string {
  if (v === null || v === undefined) return "";
  if (isBin(v)) return `(binário, ${v.$bin} bytes)`;
  return typeof v === "string" ? v : String(v);
}

function tsvCell(v: any) {
  const s = cellText(v);
  return /[\t\n\r"]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function csvCell(v: any) {
  if (v === null || v === undefined) return "";
  const s = cellText(v);
  return /[",\n\r;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function mdCell(v: any) {
  return v === null || v === undefined ? "" : cellText(v).replace(/\|/g, "\\|").replace(/\r?\n/g, "<br>");
}

/** Valor para JSON: número continua número; texto que é JSON (coluna json/jsonb) vira objeto. */
function jsonValue(v: any, type: string) {
  if (v === null || v === undefined) return null;
  if (isBin(v)) return null;
  if (typeof v === "string" && /^(JSON|JSONB)$/i.test(type)) { try { return JSON.parse(v); } catch { /* fica texto */ } }
  if (typeof v === "string" && /^(INT|INTEGER|BIGINT|SMALLINT|TINYINT|INT2|INT4|INT8|DECIMAL|NUMERIC|MONEY|FLOAT|REAL|DOUBLE)/i.test(type) &&
    /^-?\d+(\.\d+)?$/.test(v) && v.replace(/[-.]/g, "").replace(/^0+/, "").length <= 15) return Number(v);
  return v;
}

export function sqlLiteral(v: any, engine: Engine, type = "") {
  if (v === null || v === undefined || isBin(v)) return "NULL";
  if (typeof v === "number") return String(v);
  if (typeof v === "boolean") return engine === "postgres" ? (v ? "TRUE" : "FALSE") : v ? "1" : "0";
  const s = String(v);
  if (/^0x[0-9A-F]+$/i.test(s) && /BIN|BLOB|BYTEA|IMAGE/i.test(type))
    return engine === "sqlserver" ? s : engine === "postgres" ? `'\\x${s.slice(2)}'::bytea` : `X'${s.slice(2)}'`;
  if (/^-?\d+(\.\d+)?$/.test(s) && /INT|DEC|NUM|MONEY|FLOAT|REAL|DOUBLE/i.test(type)) return s;
  const esc = s.replace(/'/g, "''");
  if (engine === "mysql") return `'${esc.replace(/\\/g, "\\\\")}'`;
  return engine === "sqlserver" ? `N'${esc}'` : `'${esc}'`;
}

export function formatCopy(kind: CopyKind, cols: Column[], rows: any[][], ctx: CopyCtx): string {
  const q = quoteFor(ctx.engine);
  const tableName = ctx.table ? (ctx.table.schema && ctx.engine !== "sqlite" ? `${q(ctx.table.schema)}.` : "") + q(ctx.table.name) : "tabela";
  switch (kind) {
    case "tsv":
      return rows.map(r => r.map(tsvCell).join("\t")).join("\n");
    case "tsv-header":
      return [cols.map(c => tsvCell(c.name)).join("\t"), ...rows.map(r => r.map(tsvCell).join("\t"))].join("\n");
    case "csv":
      return [cols.map(c => csvCell(c.name)).join(","), ...rows.map(r => r.map(csvCell).join(","))].join("\n");
    case "json": {
      const objs = rows.map(r => Object.fromEntries(cols.map((c, i) => [c.name, jsonValue(r[i], c.type)])));
      return JSON.stringify(objs, null, 2);
    }
    case "markdown":
      return [`| ${cols.map(c => mdCell(c.name)).join(" | ")} |`, `| ${cols.map(() => "---").join(" | ")} |`,
        ...rows.map(r => `| ${r.map(mdCell).join(" | ")} |`)].join("\n");
    case "insert": {
      const names = cols.map(c => q(c.name)).join(", ");
      return rows.map(r => `INSERT INTO ${tableName} (${names}) VALUES (${r.map((v, i) => sqlLiteral(v, ctx.engine, cols[i].type)).join(", ")});`).join("\n");
    }
    case "update": {
      if (!ctx.pk?.length || !ctx.allColumns || !ctx.allRow) return "-- Para gerar UPDATE, abra a tabela (precisa da chave primária)";
      return rows.map((r, ri) => {
        const full = ctx.allRow!(ri);
        const where = ctx.pk!.map(k => {
          const i = ctx.allColumns!.findIndex(c => c.name === k);
          return `${q(k)} = ${sqlLiteral(full[i], ctx.engine, ctx.allColumns![i]?.type)}`;
        }).join(" AND ");
        const set = cols.filter(c => !ctx.pk!.includes(c.name)).map(c => `${q(c.name)} = ${sqlLiteral(r[cols.indexOf(c)], ctx.engine, c.type)}`);
        return set.length ? `UPDATE ${tableName} SET ${set.join(", ")} WHERE ${where};` : "";
      }).filter(Boolean).join("\n");
    }
    case "in": {
      const vals = [...new Set(rows.flatMap(r => r.map((v, i) => sqlLiteral(v, ctx.engine, cols[i].type))))];
      return `(${vals.join(", ")})`;
    }
  }
  return "";
}

/** Texto colado (do Excel, de outra grade): linhas por quebra, células por tab — com aspas de célula com quebra. */
export function parseTsv(text: string): string[][] {
  const out: string[][] = [];
  let row: string[] = [], cell = "", i = 0, quoted = false;
  const t = text.replace(/\r\n/g, "\n").replace(/\n$/, "");
  while (i < t.length) {
    const c = t[i];
    if (quoted) {
      if (c === '"' && t[i + 1] === '"') { cell += '"'; i += 2; continue; }
      if (c === '"') { quoted = false; i++; continue; }
      cell += c; i++; continue;
    }
    if (c === '"' && cell === "") { quoted = true; i++; continue; }
    if (c === "\t") { row.push(cell); cell = ""; i++; continue; }
    if (c === "\n") { row.push(cell); out.push(row); row = []; cell = ""; i++; continue; }
    cell += c; i++;
  }
  row.push(cell); out.push(row);
  return out;
}
