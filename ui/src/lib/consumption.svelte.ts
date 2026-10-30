// Consumo das IAs (backend: aiusage.py) — modelo, effort e tokens de cada resposta, lidos dos registros das CLIs.
// Uma leitura só, dividida entre a aba Consumo e os cartões de conta.
import { get, post } from "./api";

export type G = {
  n: number; i: number; o: number; cr: number; cw: number; r: number; tokens: number; sessions: number;
  perCall: number; outPerCall: number; cacheHit: number | null; cost: number | null; costPerCall: number | null; costPerSession: number | null;
};
export type Acc = {
  name: string; provider: string | null; configured: { model?: string | null; effort?: string | null };
  last: { ts: string; model: string; effort: string; prov: string } | null; week: G | null; weekTop: { model: string; effort: string } | null;
};
export type Lines = { sessions: number; lines: number; tokens: number; cost: number; weekPct: number; fiveHPct: number };
export type Report = {
  days: number; since: string; total: G; provider: Record<string, G>; model: Record<string, G>; effort: Record<string, G>;
  account: Record<string, G>; project: Record<string, G>; series: ({ day: string } & Record<string, G | string>)[];
  accounts: Record<string, Acc>; lines: Record<string, Lines>;
  cursor: { models: Record<string, { chunks: number; conversations: number }>; commits: { ai: number; human: number; commits: number } };
  insights: { tone: "info" | "warn" | "good" | "bad"; title: string; text: string }[];
  scan: { scanning: boolean; at: number | null; error: string | null; files: number; oldest: string | null };
};

class Consumption {
  data = $state<Report | null>(null);
  error = $state<string | null>(null);
  days = $state(30);
  loading = $state(false);
  private at = 0;

  async load(days = this.days, force = false) {
    if (!force && this.data && this.days === days && Date.now() - this.at < 60000) return;
    this.days = days;
    this.loading = true;
    try {
      const r = await get<Report>("ai/consumption", { days });
      if (days === this.days) { this.data = r; this.error = null; this.at = Date.now(); }
    } catch (e: any) { this.error = e.message || String(e); }
    this.loading = false;
  }
  /** Lê agora o que as CLIs escreveram desde a última leitura (o normal é a cada 10 min). */
  async scan() {
    this.loading = true;
    try { await post("ai/consumption/scan", {}, { quiet: true }); } catch { /* a leitura de fundo segue */ }
    await this.load(this.days, true);
  }
}
export const consumption = new Consumption();

// ---------------------------------------------------------------- formatos
/** "claude-opus-5-5" → "Opus 5.5"; o que não é do Claude fica como veio (gpt-5.6-luna). */
export function modelLabel(m?: string | null) {
  const x = /claude-(opus|sonnet|haiku|fable|mythos)-(\d+)(?:-(\d{1,2}))?/.exec(m || "");
  if (x) return `${x[1][0].toUpperCase()}${x[1].slice(1)} ${x[2]}${x[3] ? "." + x[3] : ""}`;
  return m || "—";
}
export const effortLabel = (e?: string | null) => (!e || e === "—" ? "não informado" : e);
export const tok = (n?: number | null) => {
  const v = n || 0;
  return v >= 1e9 ? `${(v / 1e9).toFixed(1).replace(".", ",")} bi` : v >= 1e6 ? `${(v / 1e6).toFixed(1).replace(".", ",")} M`
    : v >= 1e3 ? `${Math.round(v / 1e3)} mil` : v > 0 ? String(Math.round(v)) : "—";
};
export const usd = (n?: number | null) => (n == null ? "—" : n >= 100 ? `US$ ${Math.round(n).toLocaleString("pt-BR")}` : `US$ ${n.toFixed(2).replace(".", ",")}`);
export const num = (n?: number | null) => (n ? Math.round(n).toLocaleString("pt-BR") : "—");
export const PROV: Record<string, { label: string; color: string }> = {
  claude: { label: "Claude", color: "var(--cat2)" }, codex: { label: "Codex", color: "var(--cat1)" }, cursor: { label: "Cursor", color: "var(--cat3)" },
};
