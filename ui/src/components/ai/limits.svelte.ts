// Contas de IA: o relógio compartilhado (as contagens para o reset andam sozinhas), a cor de cada conta, o tom de cada
// limite e qual janela está segurando a conta (a que está mais perto de acabar).
import { colorFor } from "../../lib/format";
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
