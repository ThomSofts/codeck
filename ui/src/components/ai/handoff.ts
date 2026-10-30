// Continuar o trabalho de uma sessão em outra conta de IA, sem esperar o limite: resumo enxuto (qualquer CLI) ou a
// conversa inteira (mesma CLI, Claude/Codex). Usado pela tela do agente e pelo menu da aba do agente.
import { Bot } from "@lucide/svelte";
import { ui } from "../../lib/ui.svelte";
import type { TermInfo } from "../../lib/work.svelte";
import { work } from "../../lib/work.svelte";
import { clock, rank, type Rec } from "./limits.svelte";

export function handoffMenu(e: MouseEvent, t: TermInfo, done: (termId: string) => void) {
  if (!t.alive) return;
  const list = rank(work.ai.filter(a => a.installed && a.id !== t.meta.account), clock.now);
  const hint = (r: Rec) => (r.free == null ? r.a.label : r.blocked ? "no limite" : `${Math.round(r.free)}% livre`);
  const run = async (r: Rec, mode: "brief" | "resume") => {
    const prog = ui.progress(`Passando o trabalho para ${r.a.name}…`);
    try {
      const n = await work.handoff(t.id, r.a.id, mode);
      prog.done(n.mode === "resume" ? `${r.a.name} retomou a conversa` : `${r.a.name} continua com um resumo enxuto`);
      done(n.id);
    } catch (err) { prog.fail(err); }
  };
  const same = (r: Rec) => r.a.provider === t.meta.provider && (r.a.provider === "claude" || r.a.provider === "codex");
  ui.contextMenu(e, [
    { heading: "Continuar em outra conta · resumo enxuto" },
    ...list.map(r => ({ label: r.a.name, icon: Bot, hint: hint(r), onclick: () => run(r, "brief") })),
    ...(list.some(same) ? [{ heading: "Retomar a conversa inteira (mais tokens)" }, ...list.filter(same).map(r => ({ label: r.a.name, icon: Bot, hint: hint(r), onclick: () => run(r, "resume") }))] : []),
    ...(list.length ? [] : [{ label: "Nenhuma outra conta de IA", disabled: true }]),
  ]);
}
