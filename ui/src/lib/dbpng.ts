// Imagem do resultado (o "print" bonito): moldura no gradiente da marca, cartão com o banco/ambiente, a consulta
// (opcional), a tabela e o ponto verde do Codeck — com olhos, espiando os dados e comentando num balão.
// Desenhado em canvas a 2x: nítido em tela Retina e ao colar no chat/e-mail.
import type { Column, EnvKind } from "./db.svelte";
import { cellText } from "./dbcopy";

export interface PngInput {
  title: string; envKind: EnvKind; envLabel: string; database: string; engineLabel: string; legacy?: boolean;
  sql: string | null; columns: Column[]; rows: any[][]; ms: number | null; totalRows: number;
  mask: Set<number>; maskMode: "partial" | "full"; theme: "dark" | "light"; mascot: boolean; logoSvg: string | null; when: Date;
}

const ENV_COLOR: Record<EnvKind, string> = { dev: "#3ccf91", hml: "#f5b84f", prod: "#ff6b7d" };
const THEMES = {
  dark: { card: "#12151c", text: "#e9ebf1", muted: "#7d869b", faint: "#5a6276", line: "rgba(255,255,255,0.07)", zebra: "rgba(255,255,255,0.028)",
    head: "rgba(255,255,255,0.045)", code: "rgba(255,255,255,0.04)", codeText: "#c9d1e6", bubble: "#1d2230" },
  light: { card: "#ffffff", text: "#141824", muted: "#6b7489", faint: "#a9b0c0", line: "rgba(15,23,42,0.08)", zebra: "rgba(15,23,42,0.028)",
    head: "rgba(15,23,42,0.045)", code: "rgba(15,23,42,0.045)", codeText: "#2b3247", bubble: "#f1f3f9" },
};
const FONT = '"Inter Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
const MONO = '"JetBrains Mono Variable", ui-monospace, "SF Mono", Menlo, Consolas, monospace';

export function maskValue(s: string, mode: "partial" | "full") {
  if (!s) return s;
  if (mode === "full" || s.length <= 4) return "•".repeat(Math.min(Math.max(s.length, 4), 10));
  return s.slice(0, 2) + "•".repeat(Math.min(s.length - 4, 8)) + s.slice(-2);
}

function phrase(n: number, total: number, prod: boolean) {
  const fmt = (x: number) => x.toLocaleString("pt-BR");
  if (n === 0) return "Nenhuma linha… tudo quieto por aqui.";
  if (prod) return `Direto da produção: ${fmt(total)} ${total === 1 ? "linha" : "linhas"}. Com carinho 👀`;
  if (total > n) return `Aqui vão ${fmt(n)} de ${fmt(total)} linhas!`;
  const opts = [`${fmt(n)} ${n === 1 ? "linha fresquinha" : "linhas fresquinhas"}!`, `Prontinho: ${fmt(n)} ${n === 1 ? "linha" : "linhas"}.`,
    `Olha o que eu achei: ${fmt(n)} ${n === 1 ? "linha" : "linhas"}.`];
  return opts[n % opts.length];
}

function loadImage(svg: string): Promise<HTMLImageElement | null> {
  return new Promise(res => {
    const img = new Image();
    img.onload = () => res(img);
    img.onerror = () => res(null);
    const src = svg.includes("xmlns=") ? svg : svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(src);
  });
}

function rrect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  g.beginPath();
  g.roundRect(x, y, w, h, r);
}

function fit(g: CanvasRenderingContext2D, s: string, w: number) {
  if (g.measureText(s).width <= w) return s;
  let lo = 0, hi = s.length;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (g.measureText(s.slice(0, m) + "…").width <= w) lo = m; else hi = m - 1; }
  return s.slice(0, lo) + "…";
}

const numeric = (t: string) => /INT|DEC|NUM|MONEY|FLOAT|REAL|DOUBLE/i.test(t);

export async function renderPng(inp: PngInput): Promise<HTMLCanvasElement> {
  await document.fonts?.ready;
  const T = THEMES[inp.theme];
  const S = 2;
  const m = document.createElement("canvas").getContext("2d")!;
  const cellFont = `13px ${FONT}`, headFont = `600 12px ${FONT}`;
  const cells = inp.rows.map(r => r.map((v, i) => {
    const t = v === null || v === undefined ? null : cellText(v).replace(/\s+/g, " ");
    return t !== null && inp.mask.has(i) ? maskValue(t, inp.maskMode) : t;
  }));
  // larguras: o maior entre o nome e os valores (até 340px)
  const widths = inp.columns.map((c, i) => {
    m.font = headFont;
    let w = m.measureText(c.name).width;
    m.font = numeric(c.type) ? `13px ${MONO}` : cellFont;
    for (const r of cells.slice(0, 300)) w = Math.max(w, m.measureText(r[i] ?? "NULL").width);
    return Math.ceil(Math.min(340, Math.max(48, w)) + 26);
  });
  let cols = inp.columns.length;
  let tableW = widths.reduce((a, b) => a + b, 0);
  while (cols > 1 && tableW > 2600) { cols--; tableW -= widths[cols]; }   // largura máxima: corta colunas e avisa
  const hiddenCols = inp.columns.length - cols;

  const OUT = 36, PAD = 28, ROW = 30, HEAD = 34;
  const sqlLines = inp.sql ? inp.sql.trim().split("\n").slice(0, 8) : [];
  const sqlMore = inp.sql ? inp.sql.trim().split("\n").length > 8 : false;
  const mascotH = inp.mascot ? 64 : 0;
  const headerH = 58;
  const sqlH = sqlLines.length ? sqlLines.length * 19 + 24 + 16 : 0;
  const tableH = HEAD + Math.max(1, cells.length) * ROW;
  const footH = 44;
  const cardW = Math.max(tableW, 620) + PAD * 2;
  if (tableW < cardW - PAD * 2) {   // tabela estreita: as colunas crescem até a largura do cartão
    const extra = cardW - PAD * 2 - tableW;
    for (let i = 0; i < cols; i++) widths[i] += Math.floor(extra * widths[i] / tableW);
    tableW = widths.slice(0, cols).reduce((a, b) => a + b, 0);
  }
  const cardH = PAD + headerH + sqlH + mascotH + tableH + footH;
  const W = cardW + OUT * 2, H = cardH + OUT * 2;

  const cv = document.createElement("canvas");
  cv.width = W * S; cv.height = H * S;
  const g = cv.getContext("2d")!;
  g.scale(S, S);

  // moldura: gradiente da marca com um brilho
  const grad = g.createLinearGradient(0, 0, W, H);
  grad.addColorStop(0, "#7b5cfa"); grad.addColorStop(1, "#3f8cf0");
  g.fillStyle = grad; g.fillRect(0, 0, W, H);
  const glow = g.createRadialGradient(W * 0.85, H * 0.1, 10, W * 0.85, H * 0.1, Math.max(W, H) * 0.7);
  glow.addColorStop(0, "rgba(255,255,255,0.22)"); glow.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = glow; g.fillRect(0, 0, W, H);

  // cartão
  g.save();
  g.shadowColor = "rgba(10,12,30,0.35)"; g.shadowBlur = 40; g.shadowOffsetY = 14;
  g.fillStyle = T.card; rrect(g, OUT, OUT, cardW, cardH, 18); g.fill();
  g.restore();
  const x0 = OUT + PAD;
  let y = OUT + PAD;

  // cabeçalho: logo, banco, ambiente, banco/motor, data
  const logo = inp.logoSvg ? await loadImage(inp.logoSvg) : null;
  if (logo) g.drawImage(logo, x0, y + 2, 34, 34);
  const tx = x0 + (logo ? 46 : 0);
  g.fillStyle = T.text; g.font = `700 19px ${FONT}`; g.textBaseline = "alphabetic";
  const title = fit(g, inp.title, cardW - PAD * 2 - 260);
  g.fillText(title, tx, y + 18);
  let px = tx + g.measureText(title).width + 10;
  const pill = (label: string, color: string) => {
    g.font = `700 11px ${FONT}`;
    const w = g.measureText(label).width + 16;
    g.fillStyle = color + "26"; rrect(g, px, y + 3, w, 20, 10); g.fill();
    g.fillStyle = color; g.fillText(label, px + 8, y + 17);
    px += w + 6;
  };
  pill(inp.envLabel, ENV_COLOR[inp.envKind]);
  if (inp.legacy) pill("legado", "#f5b84f");
  g.fillStyle = T.muted; g.font = `13px ${FONT}`;
  g.fillText([inp.database, inp.engineLabel].filter(Boolean).join(" · "), tx, y + 38);
  g.textAlign = "right";
  g.fillText(inp.when.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }), OUT + cardW - PAD, y + 18);
  g.textAlign = "left";
  y += headerH;

  // consulta
  if (sqlLines.length) {
    g.fillStyle = T.code; rrect(g, x0, y, cardW - PAD * 2, sqlH - 16, 10); g.fill();
    g.fillStyle = T.codeText; g.font = `12.5px ${MONO}`;
    sqlLines.forEach((ln, i) => {
      const t = fit(g, ln.replace(/\t/g, "  ") + (sqlMore && i === sqlLines.length - 1 ? "  …" : ""), cardW - PAD * 2 - 28);
      g.fillText(t, x0 + 14, y + 12 + 14 + i * 19);
    });
    y += sqlH;
  }

  // o ponto verde: olhos olhando para a tabela, e um balão com o comentário
  if (inp.mascot) {
    const cx = OUT + cardW - PAD - 26, cy = y + 26, r = 22;
    const shade = g.createRadialGradient(cx - 7, cy - 8, 4, cx, cy, r);
    shade.addColorStop(0, "#5ff0b8"); shade.addColorStop(1, "#18a877");
    g.fillStyle = shade; g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.fill();
    for (const ex of [-8, 8]) {
      g.fillStyle = "#ffffff"; g.beginPath(); g.ellipse(cx + ex, cy - 3, 5.5, 6.5, 0, 0, Math.PI * 2); g.fill();
      g.fillStyle = "#0e1726"; g.beginPath(); g.arc(cx + ex - 1.8, cy - 0.5, 2.8, 0, Math.PI * 2); g.fill();
      g.fillStyle = "#ffffff"; g.beginPath(); g.arc(cx + ex - 2.6, cy - 1.6, 0.9, 0, Math.PI * 2); g.fill();
    }
    g.strokeStyle = "#0e1726"; g.lineWidth = 1.6; g.lineCap = "round";
    g.beginPath(); g.arc(cx - 1, cy + 7, 4.5, 0.15 * Math.PI, 0.85 * Math.PI); g.stroke();
    const say = phrase(inp.rows.length, Math.max(inp.totalRows, inp.rows.length), inp.envKind === "prod");
    g.font = `600 13px ${FONT}`;
    const bw = g.measureText(say).width + 26, bx = cx - r - 14 - bw, by = cy - 17;
    g.fillStyle = T.bubble; rrect(g, bx, by, bw, 34, 12); g.fill();
    g.beginPath(); g.moveTo(bx + bw, cy - 5); g.lineTo(bx + bw + 9, cy); g.lineTo(bx + bw, cy + 5); g.fill();
    g.fillStyle = T.text; g.fillText(say, bx + 13, by + 22);
    y += mascotH;
  }

  // tabela
  const tx0 = x0;
  g.fillStyle = T.head; rrect(g, tx0, y, tableW, HEAD, 8); g.fill();
  g.font = headFont; g.fillStyle = T.muted;
  let cx = tx0;
  for (let i = 0; i < cols; i++) {
    const num = numeric(inp.columns[i].type);
    const t = fit(g, inp.columns[i].name, widths[i] - 26);
    g.textAlign = num ? "right" : "left";
    g.fillText(t, num ? cx + widths[i] - 13 : cx + 13, y + 21);
    cx += widths[i];
  }
  g.textAlign = "left";
  y += HEAD;
  cells.forEach((r, ri) => {
    if (ri % 2 === 1) { g.fillStyle = T.zebra; g.fillRect(tx0, y, tableW, ROW); }
    let x = tx0;
    for (let i = 0; i < cols; i++) {
      const v = r[i];
      const num = numeric(inp.columns[i].type);
      if (v === null) { g.font = `italic 12px ${FONT}`; g.fillStyle = T.faint; }
      else { g.font = num ? `13px ${MONO}` : cellFont; g.fillStyle = inp.mask.has(i) ? T.muted : T.text; }
      const t = fit(g, v === null ? "NULL" : v, widths[i] - 26);
      g.textAlign = num && v !== null ? "right" : "left";
      g.fillText(t, num && v !== null ? x + widths[i] - 13 : x + 13, y + 20);
      x += widths[i];
    }
    g.textAlign = "left";
    y += ROW;
  });
  if (!cells.length) { g.fillStyle = T.muted; g.font = `13px ${FONT}`; g.fillText("Sem linhas", tx0 + 13, y + 20); y += ROW; }
  g.strokeStyle = T.line; g.lineWidth = 1;
  g.beginPath(); g.moveTo(tx0, y + 0.5); g.lineTo(tx0 + tableW, y + 0.5); g.stroke();

  // rodapé
  y += 28;
  g.fillStyle = T.muted; g.font = `12.5px ${FONT}`;
  const n = inp.rows.length, total = Math.max(inp.totalRows, n);
  const info = [`${total > n ? `${n.toLocaleString("pt-BR")} de ${total.toLocaleString("pt-BR")}` : n.toLocaleString("pt-BR")} ${total === 1 ? "linha" : "linhas"}`,
    inp.ms != null ? `${inp.ms.toLocaleString("pt-BR")} ms` : "", hiddenCols ? `+${hiddenCols} colunas fora da imagem` : "",
    inp.mask.size ? "valores mascarados" : ""].filter(Boolean).join("  ·  ");
  g.fillText(info, x0, y);
  g.textAlign = "right"; g.fillStyle = T.faint; g.font = `600 12px ${FONT}`;
  g.fillText("feito com Codeck", OUT + cardW - PAD, y);
  g.textAlign = "left";
  return cv;
}
