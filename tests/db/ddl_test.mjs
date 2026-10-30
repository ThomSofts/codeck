// Alterações de estrutura nos bancos de verdade: o SQL que a tela monta (ui/src/lib/dbddl.ts — o mesmo arquivo, sem
// cópia) roda pela API do backend em cada banco SQL dos alvos e o catálogo confere o resultado: tabela nova com
// descrições, coluna nova, tipo/nulo/padrão/descrição, renomear coluna, índice, excluir coluna (no SQL Server, com o
// DEFAULT que o servidor nomeou), renomear e esvaziar tabela, o CREATE montado do catálogo e, em produção, a
// alteração desfeita pela transação.
//   node tests/db/ddl_test.mjs <pasta dos plugins> <alvos.json>
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { createRequire } from "node:module";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../..");
const PLUGINS = path.resolve(process.argv[2]);
const TARGETS = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

// o gerador da tela, transpilado na hora (o TypeScript já é dependência da ui/)
const ts = createRequire(path.join(ROOT, "ui/package.json"))("typescript");
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), "codeck-ddl-"));
const src = fs.readFileSync(path.join(ROOT, "ui/src/lib/dbddl.ts"), "utf8").replace(/^import type .*$/m, "");
fs.writeFileSync(path.join(TMP, "dbddl.mjs"), ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText);
const D = await import(path.join(TMP, "dbddl.mjs"));

const DATA = path.join(TMP, "data");
const TOKEN = Math.random().toString(36).slice(2) + Date.now().toString(36);
const port = await new Promise(r => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => r(p)); }); });
const BASE = `http://127.0.0.1:${port}`;
const backend = spawn("python3", ["-I", "-B", path.join(ROOT, "backend/server.py")],
  { env: { ...process.env, CODECK_PORT: String(port), CODECK_TOKEN: TOKEN, CODECK_DATA: DATA, CODECK_DB_PLUGINS: PLUGINS }, stdio: "ignore" });
class ApiError extends Error { constructor(m, data) { super(m); this.data = data; } }
async function api(p, body) {
  const r = await fetch(`${BASE}/api/${p}`, { method: body ? "POST" : "GET", headers: { "X-Codeck-Token": TOKEN, "X-Codeck": "1", "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined });
  const j = await r.json();
  if (!r.ok) throw new ApiError(`${p}: ${j.error}`, j);
  return j;
}
for (let i = 0; i < 100; i++) { try { await api("db"); break; } catch { await new Promise(r => setTimeout(r, 200)); } }

const results = [];
const check = (cond, what) => { results.push([!!cond, what]); console.log(`  ${cond ? "✓" : "✗"} ${what}`); };
const SCHEMA = { postgres: "public", sqlserver: "dbo", libsql: "main" };

async function engine(name, t) {
  const E = t.engine, lite = E === "libsql";
  console.log(`\n▸ ${name}`);
  const { bank } = await api("db/bank", { name: `DDL ${name}`, engine: E, envs: [{ ...t.env, kind: "dev" }, { ...t.env, kind: "prod" }] });
  const [dev, prod] = bank.envs.map(e => e.id);
  try {
    await api("db/test", { engine: E, bank: bank.id, envId: dev, env: { ...t.env } });
  } catch (e) {
    if (e.data?.code !== "cert-unknown") throw e;
    for (const env of [dev, prod]) await api("db/pin", { bank: bank.id, env, sha256: e.data.data.sha256 });
  }
  const s = (await api("db/open", { bank: bank.id, env: dev })).id;
  const S = SCHEMA[E] || t.env.database;
  const run = async (sql) => api("db/query", { session: s, sql: sql.join("\n"), confirm: true });
  const info = (name) => api("db/catalog", { session: s, what: "table", schema: S, name });
  const T = { schema: S, name: "cdk_ddl" };
  const col = (o) => ({ name: "", type: "", nullable: true, default: "", identity: false, pk: false, comment: "", ...o });
  const num = E === "postgres" ? "numeric" : "decimal";
  const vc = E === "sqlserver" ? "nvarchar" : lite ? "TEXT" : "varchar";
  try {
    try { await run(D.dropTable(E, T)); } catch { /* não existia */ }
    try { await run(D.dropTable(E, { schema: S, name: "cdk_ddl2" })); } catch { /* não existia */ }

    await run(D.createTable(E, T, [
      col({ name: "id", type: lite ? "INTEGER" : "int", nullable: false, identity: true, pk: true }),
      col({ name: "nome", type: lite ? "TEXT" : `${vc}(80)`, nullable: false, comment: "Nome do cliente" }),
      col({ name: "saldo", type: lite ? "REAL" : `${num}(12,2)`, default: "0", comment: "Saldo em reais" }),
    ], "Clientes de teste"));
    let i = await info("cdk_ddl");
    check(i.columns.map(c => c.name).join() === "id,nome,saldo", "tabela nova com as colunas");
    check(i.columns[0].pk === 1 && i.columns[0].identity, "chave primária com numeração automática");
    if (!lite) {
      check(i.columns[1].comment === "Nome do cliente", `descrição da coluna (${i.columns[1].comment})`);
      check(i.comment === "Clientes de teste", `descrição da tabela (${i.comment})`);
      // o Postgres só estima depois de um ANALYZE (antes, a tela mostra "—" e oferece contar); tabela vazia no SQL Server ocupa 0 bytes
      if (E === "postgres") { check(i.rows == null, "Postgres: sem ANALYZE, sem estimativa"); await run(["ANALYZE " + D.tbl(E, T) + ";"]); i = await info("cdk_ddl"); }
      check(i.rows != null, `estimativa de linhas (${i.rows})`);
      check(i.bytes != null && i.bytes >= 0, `tamanho (${i.bytes})`);
    } else check(/CREATE TABLE/.test(i.ddl || ""), "o SQLite/libSQL traz o CREATE guardado");

    await run(D.addColumn(E, T, col({ name: "email", type: lite ? "TEXT" : `${vc}(120)`, comment: "E-mail" })));
    i = await info("cdk_ddl");
    check(i.columns.some(c => c.name === "email") && (lite || i.columns.find(c => c.name === "email").comment === "E-mail"), "coluna nova (com descrição)");

    if (!lite) {
      const before = i.columns.find(c => c.name === "saldo");
      const a = D.alterColumn(E, T, before, col({ name: "saldo", type: `${num}(14,2)`, nullable: false, default: "1", comment: "Saldo atualizado" }));
      await run(a.sql);
      i = await info("cdk_ddl");
      const sd = i.columns.find(c => c.name === "saldo");
      check(/14,\s*2/.test(sd.type) && !sd.nullable && /1/.test(sd.default || "") && sd.comment === "Saldo atualizado", `tipo, nulo, padrão e descrição (${sd.type} · ${sd.nullable} · ${sd.default} · ${sd.comment})`);
      const b2 = D.alterColumn(E, T, sd, col({ name: "saldo", type: sd.type, nullable: false, default: "", comment: "" }));
      await run(b2.sql);
      i = await info("cdk_ddl");
      const sd2 = i.columns.find(c => c.name === "saldo");
      check(!sd2.default && !sd2.comment, `tirar o padrão e a descrição (${sd2.default} · ${sd2.comment})`);
      await run(D.alterColumn(E, T, sd2, col({ name: "saldo", type: sd2.type, nullable: false, default: "5", comment: "" })).sql);
    } else check(!!D.alterColumn(E, T, i.columns[2], col({ name: "saldo", type: "TEXT" })).error, "SQLite: mudar tipo explica que não dá");

    await run(D.renameColumn(E, T, "email", "correio"));
    i = await info("cdk_ddl");
    check(i.columns.some(c => c.name === "correio") && !i.columns.some(c => c.name === "email"), "renomear coluna");

    await run(D.createIndex(E, T, "ix_cdk_ddl_nome", ["nome"], true));
    i = await info("cdk_ddl");
    check(i.indexes.some(x => x.name === "ix_cdk_ddl_nome" && x.unique), "índice único");
    await run(D.dropIndex(E, T, "ix_cdk_ddl_nome"));
    i = await info("cdk_ddl");
    check(!i.indexes.some(x => x.name === "ix_cdk_ddl_nome"), "excluir índice");

    if (!lite) {
      await run(D.tableComment(E, T, "Descrição nova"));
      check((await info("cdk_ddl")).comment === "Descrição nova", "trocar a descrição da tabela");
    }
    // a coluna com DEFAULT (no SQL Server o nome do DEFAULT é descoberto antes)
    await run(D.dropColumn(E, T, lite ? "correio" : "saldo"));
    i = await info("cdk_ddl");
    check(!i.columns.some(c => c.name === (lite ? "correio" : "saldo")), "excluir coluna" + (E === "sqlserver" ? " (com DEFAULT)" : ""));

    // o CREATE montado do catálogo recria a mesma tabela
    const create = D.createFromInfo(E, i);
    await run(D.dropTable(E, T));
    await run([create]);
    const j = await info("cdk_ddl");
    check(j.columns.map(c => `${c.name}:${c.nullable}`).join() === i.columns.map(c => `${c.name}:${c.nullable}`).join(), "o CREATE do catálogo recria a tabela");

    await run(D.renameTable(E, T, "cdk_ddl2"));
    const T2 = { schema: S, name: "cdk_ddl2" };
    check((await api("db/catalog", { session: s, what: "objects" })).some(o => o.name === "cdk_ddl2"), "renomear tabela");
    await api("db/query", { session: s, sql: `INSERT INTO ${D.tbl(E, T2)} (nome) VALUES ('Ana'), ('Bruno')`, confirm: true });
    await run(D.truncateTable(E, T2));
    const cnt = await api("db/query", { session: s, sql: `SELECT COUNT(*) FROM ${D.tbl(E, T2)}` });
    check(Number(cnt.results[0].rows[0][0]) === 0, "esvaziar tabela");

    // produção: alteração de estrutura fica na transação e o Desfazer volta (o MySQL não desfaz DDL; o libSQL não segura transação)
    if (E === "postgres" || E === "sqlserver") {
      const p = (await api("db/open", { bank: bank.id, env: prod })).id;
      await api("db/unlock", { session: p });
      const r = await api("db/query", { session: p, sql: D.addColumn(E, T2, col({ name: "extra", type: "int" })).join("\n"), confirm: true });
      check(!!r.pendingTx, "produção: a coluna nova espera Confirmar/Desfazer");
      await api("db/tx", { session: p, txId: r.pendingTx.id, commit: false });
      check(!(await api("db/catalog", { session: p, what: "table", schema: S, name: "cdk_ddl2" })).columns.some(c => c.name === "extra"), "produção: Desfazer tira a coluna");
      await api("db/close", { session: p });
    }
    await run(D.dropTable(E, T2));
    check(!(await api("db/catalog", { session: s, what: "objects" })).some(o => o.name.startsWith("cdk_ddl")), "excluir tabela");
  } catch (e) {
    check(false, `${name}: fluxo interrompido — ${e.message}`);
  } finally {
    await api("db/close", { session: s }).catch(() => {});
    await api("db/bank/delete", { id: bank.id }).catch(() => {});
  }
}

try {
  for (const [name, t] of Object.entries(TARGETS)) if (["postgres", "mysql", "sqlserver", "libsql"].includes(t.engine) && !t.kind) await engine(name, t);
} finally {
  backend.kill();
  fs.rmSync(TMP, { recursive: true, force: true });
}
const bad = results.filter(r => !r[0]).length;
console.log(`\nESTRUTURA: ${results.length - bad} ok, ${bad} falharam`);
process.exit(bad ? 1 : 0);
