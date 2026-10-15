import type { Build } from "../../lib/types";

export type BuildState = { icon: string; cls: string; label: string; spin?: boolean; detail?: string };

/** Sem andamento há mais que isso (nenhuma etapa mudou), o build "rodando" provavelmente está parado. */
const STALL_MS = 90 * 60 * 1000;

export function buildState(b: Build): BuildState {
  if (b.waiting) return { icon: "⏸", cls: "warn", label: "aguardando" };
  const ph = b.phase;
  if (b.status !== "completed" && ph) {
    if (ph.state === "failing") return { icon: "✕", cls: "bad", label: "falhando", spin: b.status === "inProgress", detail: ph.label };
    if (ph.state === "approval") return { icon: "⏸", cls: "warn", label: "aguardando aprovação", detail: ph.stage || undefined };
    if (ph.state === "check") return { icon: "⏸", cls: "warn", label: "em verificação", detail: ph.label };
    if (ph.state === "agent") return { icon: "⏱", cls: "neutral", label: "esperando agente", detail: ph.job || undefined };
    const stalled = ph.since && Date.now() - new Date(ph.since).getTime() > STALL_MS;
    if (stalled) return { icon: "!", cls: "warn", label: "sem progresso", detail: ph.label };
  }
  if (b.status === "inProgress") return { icon: "⟳", cls: "warn", label: "rodando", spin: true, detail: ph?.label };
  if (b.status === "notStarted") return { icon: "⏱", cls: "neutral", label: "na fila" };
  if (b.status === "cancelling") return { icon: "⊘", cls: "neutral", label: "cancelando", spin: true };
  if (b.status === "postponed") return { icon: "⏱", cls: "neutral", label: "adiado" };
  return ({ succeeded: { icon: "✓", cls: "good", label: "sucesso" }, failed: { icon: "✕", cls: "bad", label: "falhou" },
    partiallySucceeded: { icon: "!", cls: "warn", label: "parcial" }, canceled: { icon: "⊘", cls: "neutral", label: "cancelado" } } as Record<string, BuildState>)[b.result || ""]
    || { icon: "?", cls: "neutral", label: b.result || b.status };
}
export const REASON: Record<string, string> = { individualCI: "CI", batchedCI: "CI", pullRequest: "PR", manual: "manual", schedule: "agendado",
  resourceTrigger: "gatilho", buildCompletion: "gatilho" };
