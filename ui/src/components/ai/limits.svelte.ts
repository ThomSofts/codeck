// Contas de IA: o relógio compartilhado (as contagens para o reset andam sozinhas), a cor de cada conta, o tom de cada
// limite e qual janela está segurando a conta (a que está mais perto de acabar).
import { ago, colorFor } from "../../lib/format";
import type { AiAccount } from "../../lib/work.svelte";

export type Win = { window: string; used: number | null; resetsAt: string | null };

/** Um relógio para a tela toda: um intervalo só, por segundo (contagem regressiva < 1 h mostra os segundos). */
class Clock { now = $state(Date.now()); }
export const clock = new Clock();
setInterval(() => (clock.now = Date.now()), 1000);

/** Cor estável da conta: a escolhida, senão derivada do id (nunca da posição na lista). */
export const accColor = (a: Pick<AiAccount, "id" | "color">) => a.color || colorFor(a.id);

export const expired = (w: Win, now: number) => !!w.resetsAt && new Date(w.resetsAt).getTime() <= now;
/** Uso efetivo: janela que já resetou vale 0 até a próxima leitura. */
export const effUsed = (w: Win, now: number) => (expired(w, now) ? 0 : Math.max(0, w.used ?? 0));
export const tone = (p: number | null | undefined) => (p == null ? "muted" : p >= 90 ? "bad" : p >= 70 ? "warn" : "good");

/** A janela que limita a conta agora (a mais gasta). */
export function binding(ws: Win[] | undefined, now: number): Win | null {
  if (!ws?.length) return null;
  return [...ws].sort((x, y) => effUsed(y, now) - effUsed(x, now))[0];
}
/** Quanto ainda dá para usar (100 − a janela mais gasta); null sem leitura. */
export function headroom(a: AiAccount, now: number): number | null {
  const b = binding(a.usage?.rateLimits, now);
  return b ? Math.max(0, 100 - effUsed(b, now)) : null;
}

/** "42:13" (< 1 h, com segundos) · "2h43" · "3d 4h" · "resetou". */
export function countdown(iso: string | null | undefined, now: number): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - now;
  if (ms <= 0) return "resetou";
  const s = Math.floor(ms / 1000), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
  if (h >= 1) return `${h}h${String(m).padStart(2, "0")}`;
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}
export const resetLabel = (iso: string | null | undefined, now: number) => {
  const c = countdown(iso, now);
  return !c ? "" : c === "resetou" ? "resetou" : `reseta em ${c}`;
};

/** Leitura velha: mais de 6 h sem notícia do limite. */
export const stale = (iso: string | null | undefined, now: number) => !!iso && now - new Date(iso).getTime() > 6 * 36e5;

export const ACC_STATE: Record<string, [string, string]> = {
  "needs-you": ["precisa de você", "warn"], working: ["trabalhando", "accent"], done: ["terminou", "good"], idle: ["sessão aberta", "muted"], free: ["livre", "neutral"],
};
export const stateRank = (s?: string) => ({ "needs-you": 0, working: 1, done: 2, idle: 3 } as Record<string, number>)[s || ""] ?? 4;
export const home = (p: string) => p.replace(/^\/Users\/[^/]+|^C:\\Users\\[^\\]+/i, "~");

// ------------------------------------------------------------ recomendação: qual conta usar agora
const isWeekly = (w: Win) => /semanal/i.test(w.window);
export const winShort = (w: Win) => (isWeekly(w) ? "semanal" : w.window.replace(/\s+/g, " "));

export type Rec = {
  a: AiAccount;
  /** quanto ainda dá para usar (100 − a janela mais gasta); null = sem leitura de limite */
  free: number | null;
  score: number;
  /** a frase do porquê ("semanal zera em 9h — aproveite") */
  why: string;
  tone: "good" | "warn" | "bad" | "muted";
  /** leitura velha (> 6 h) sem reset no meio: o número pode estar errado */
  unsure: boolean;
  blocked: boolean;
};

/** Ordena as contas pelo fôlego de agora. Além do que sobra na janela mais gasta, dá preferência a quem tem semanal
 *  sobrando e zerando em menos de 24 h (o que não for usado se perde) e desconfia de leitura antiga. */
export function rank(list: AiAccount[], now: number): Rec[] {
  const out = list.map((a): Rec => {
    const ws = a.usage?.rateLimits || [];
    if (!ws.length) return { a, free: null, score: -1, why: a.provider === "claude" ? (a.installed ? "limite ainda não lido" : "CLI não encontrada") : "esta CLI não informa limite", tone: "muted", unsure: false, blocked: false };
    const b = binding(ws, now)!;
    const free = Math.max(0, 100 - effUsed(b, now));
    const reset = ws.some(w => expired(w, now));
    // leitura velha: mesmo com reset no meio, não dá para saber o que foi usado depois dele
    const unsure = stale(a.usage?.updated, now);
    const wk = ws.find(isWeekly);
    let score = free - (unsure ? 15 : 0) - (a.installed ? 0 : 200);
    let why = "";
    if (wk && !expired(wk, now) && wk.resetsAt) {
      const h = (new Date(wk.resetsAt).getTime() - now) / 36e5;
      const left = 100 - effUsed(wk, now);
      if (h < 24 && left > 20 && free > 20) { score += 10 * (1 - h / 24); why = `semanal zera ${resetLabel(wk.resetsAt, now).replace("reseta ", "")} com ${Math.round(left)}% sobrando — aproveite`; }
    }
    if (!why) {
      const used = effUsed(b, now);
      why = reset && used === 0 ? "os limites resetaram desde a última leitura"
        : used === 0 ? "nada usado nas janelas atuais"
        : `${winShort(b)} em ${Math.round(used)}%${b.resetsAt ? " · " + resetLabel(b.resetsAt, now) : ""}`;
    }
    if (unsure) why += ` · lido há ${ago(a.usage!.updated)}`;
    const blocked = free <= 5;
    return { a, free, score, why, tone: blocked ? "bad" : free < 30 ? "warn" : "good", unsure, blocked };
  });
  return out.sort((x, y) => y.score - x.score || (y.free ?? -1) - (x.free ?? -1));
}

/** Iniciais do apelido ("Dematec 2" → "D2", "ademar" → "Ad"). */
export function initials(name: string) {
  const w = (name || "?").replace(/[_\-.]+/g, " ").trim().split(/\s+/).filter(Boolean);
  if (w.length > 1) return (w[0][0] + w[1][0]).toUpperCase();
  const x = w[0] || "?";
  return x.length > 1 ? x[0].toUpperCase() + x[1].toLowerCase() : x.toUpperCase();
}

/** As cores que dá para escolher (a paleta categórica do app, boa nos dois temas). */
export const ACC_COLORS = ["var(--cat1)", "var(--cat2)", "var(--cat3)", "var(--cat4)", "var(--cat5)", "var(--cat6)"];
