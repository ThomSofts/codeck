// Teste da tela de Dados no Chrome headless: sobe o backend (pasta de dados temporária), cadastra um banco SQLite
// com dev e prod e faz o que a pessoa faria — conferindo o resultado no banco e na área de transferência.
//   node tests/db/ui_test.mjs <pasta dos plugins> <pasta para fotos>
import { spawn, execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import net from "node:net";

// o Playwright fica fora do repositório (scripts/test-db.sh instala num cache): o caminho vem por CODECK_PLAYWRIGHT
const { chromium } = await import(process.env.CODECK_PLAYWRIGHT || "playwright");
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../..");
const PLUGINS = path.resolve(process.argv[2]);
const SHOTS = path.resolve(process.argv[3] || fs.mkdtempSync(path.join(os.tmpdir(), "codeck-ui-")));
fs.mkdirSync(SHOTS, { recursive: true });
const DATA = fs.mkdtempSync(path.join(os.tmpdir(), "codeck-ui-data-"));
const TOKEN = Math.random().toString(36).slice(2) + Date.now().toString(36);
const port = await new Promise(r => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => r(p)); }); });
const BASE = `http://127.0.0.1:${port}`;
const backend = spawn("python3", ["-I", "-B", path.join(ROOT, "backend/server.py")], {
  env: { ...process.env, CODECK_PORT: String(port), CODECK_TOKEN: TOKEN, CODECK_DATA: DATA, CODECK_DB_PLUGINS: PLUGINS }, stdio: "ignore" });

const results = [];
const check = (cond, what) => { results.push([!!cond, what]); console.log(`  ${cond ? "✓" : "✗"} ${what}`); };
async function api(p, body) {
  const r = await fetch(`${BASE}/api/${p}`, { method: body ? "POST" : "GET", headers: { "X-Codeck-Token": TOKEN, "X-Codeck": "1", "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined });
  const j = await r.json();
  if (!r.ok) throw new Error(`${p}: ${j.error}`);
  return j;
}
for (let i = 0; i < 100; i++) { try { await api("db"); break; } catch { await new Promise(r => setTimeout(r, 200)); } }

const dbFile = path.join(DATA, "loja.db");
execFileSync("sqlite3", [dbFile, "CREATE TABLE clientes (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, saldo REAL, email TEXT);" +
  "INSERT INTO clientes VALUES (1,'Ana',10.5,'ana@x.com'),(2,'Bruno',3,'b@x.com'),(3,'Carla',7.25,'c@x.com');"]);
const { bank } = await api("db/bank", { name: "Loja de teste", folder: "Testes", engine: "sqlite", envs: [{ kind: "dev", file: dbFile }, { kind: "prod", file: dbFile }] });
const sql = (q) => execFileSync("sqlite3", [dbFile, q]).toString().trim();

const browser = await chromium.launch({ channel: "chrome" });
const ctx = await browser.newContext({ viewport: { width: 1500, height: 920 } });
await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: BASE });
const page = await ctx.newPage();
await page.addInitScript((t) => { window.CODECK_TOKEN = t; window.webkit = { messageHandlers: { codeck: { postMessage() {} } } }; }, TOKEN);
const errors = [];
page.on("pageerror", e => errors.push(e.message));
const clip = () => page.evaluate(() => navigator.clipboard.readText());
const shot = (n) => page.screenshot({ path: path.join(SHOTS, n + ".png") });
const confirmDialog = async (label) => { await page.locator(`.dlg button:has-text("${label}")`).last().click(); };

try {
  await page.goto(`${BASE}/#/data`);
  await page.waitForSelector("text=Loja de teste", { timeout: 20000 });
  check(true, "lista de bancos mostra o banco cadastrado");
  await page.click("text=Loja de teste");
  await page.click(".obj:has-text('clientes')", { timeout: 20000 });
  await page.waitForSelector(".rg .cell", { timeout: 20000 });
  const cell = (r, c) => page.locator(".rg .rgr").nth(r).locator(".cell").nth(c);

  // cópia N × N (texto para o Excel) e JSON
  await cell(0, 1).click();
  await cell(1, 2).click({ modifiers: ["Shift"] });
  await page.keyboard.press("Meta+c");
  await page.waitForTimeout(300);
  check((await clip()) === "Ana\t10.5\nBruno\t3", "⌘C copia o retângulo como texto (2 × 2)");
  await cell(1, 2).click({ button: "right" });
  await page.click("text=JSON");
  await page.waitForTimeout(300);
  check(JSON.stringify(JSON.parse(await clip())) === JSON.stringify([{ nome: "Ana", saldo: 10.5 }, { nome: "Bruno", saldo: 3 }]), "Copiar como JSON");
  const sum = await page.locator(".rg .sum").textContent();
  check(/soma 13,5/.test(sum || ""), `soma da seleção (${sum})`);

  // edição pendente + aplicar
  await cell(2, 1).dblclick();
  await page.keyboard.press("Meta+a");
  await page.keyboard.type("Carla Dias");
  await page.keyboard.press("Enter");
  check(await page.locator(".rg .cell.changed").count() === 1, "edição fica pendente (amarelo)");
  await page.click("button:has-text('Aplicar')");
  await confirmDialog("Aplicar");
  await page.waitForTimeout(800);
  check(sql("SELECT nome FROM clientes WHERE id = 3") === "Carla Dias", "Aplicar grava no banco");

  // consulta + imagem
  await page.click("button[title='Nova consulta']");
  await page.click(".sqled");
  await page.keyboard.type("SELECT nome, saldo FROM clientes ORDER BY saldo DESC");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Meta+Enter");
  await page.waitForSelector(".rg .cell", { timeout: 15000 });
  check(await page.locator(".rg .rgr").count() === 3, "⌘↩ executa e mostra as linhas");
  await page.locator("button:has-text('Imagem')").first().click();
  await page.waitForSelector(".prev img", { timeout: 15000 });
  const src = await page.locator(".prev img").getAttribute("src");
  fs.writeFileSync(path.join(SHOTS, "imagem.png"), Buffer.from(src.split(",")[1], "base64"));
  check(src.startsWith("data:image/png;base64,") && src.length > 5000, "a imagem do resultado é gerada");
  await shot("01-imagem");
  await page.keyboard.press("Escape");
  await page.locator("button[aria-label='Fechar'], .drawer button:has(svg.lucide-x)").first().click().catch(() => {});

  // consulta salva (⌘S)
  await page.click(".sqled");
  await page.keyboard.press("Meta+s");
  await page.locator(".dlg input.input").last().fill("Ranking de saldo");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(600);
  check(await page.locator(".obj:has-text('Ranking de saldo')").count() === 1, "⌘S salva a consulta (aparece na árvore)");

  // produção: abre travada; alterar pede destravar, confirmar e fica esperando Confirmar/Desfazer
  await page.click(".ek.prod");
  await confirmDialog("Abrir produção");
  await page.waitForSelector(".prodbar", { timeout: 15000 });
  check(await page.waitForSelector("button:has-text('Somente leitura')", { timeout: 15000 }).then(() => true, () => false), "produção abre em somente leitura");
  await page.locator(".tab:has-text('Ranking de saldo')").click().catch(() => {});
  await page.click("button[title='Nova consulta']");
  await page.click(".sqled");
  await page.keyboard.type("UPDATE clientes SET saldo = 0 WHERE id = 1");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Meta+Enter");
  await page.waitForSelector("text=Destravar produção?", { timeout: 10000 });
  check(true, "alterar em produção pede para destravar");
  await confirmDialog("Destravar esta conexão");
  await page.waitForSelector("text=Alterar PRODUÇÃO", { timeout: 10000 });
  await confirmDialog("Executar (e decidir depois)");
  await page.waitForSelector(".txbar", { timeout: 10000 });
  await shot("02-producao-esperando");
  check(true, "a alteração fica esperando Confirmar/Desfazer");
  await page.click(".txbar button:has-text('Desfazer')");
  await page.waitForTimeout(800);
  check(sql("SELECT saldo FROM clientes WHERE id = 1") === "10.5", "Desfazer devolve o valor");

  // importar (só abre e lista — não importa nada)
  await page.goto(`${BASE}/#/data`);
  await page.click("button:has-text('Importar')");
  await page.waitForSelector("text=Importar conexões", { timeout: 10000 });
  await page.waitForTimeout(1500);
  await shot("03-importar");
  check(true, "a importação abre e lista o que achou");
  check(errors.length === 0, `sem erros na página${errors.length ? ": " + errors.join(" | ") : ""}`);
} catch (e) {
  check(false, `fluxo interrompido: ${e.message.split("\n")[0]}`);
  await shot("erro").catch(() => {});
} finally {
  await browser.close();
  try { await api("db/bank/delete", { id: bank.id }); } catch { /* backend caiu */ }
  backend.kill();
  fs.rmSync(DATA, { recursive: true, force: true });
}
const bad = results.filter(r => !r[0]).length;
console.log(`\nTELA: ${results.length - bad} ok, ${bad} falharam · fotos em ${SHOTS}`);
process.exit(bad ? 1 : 0);
