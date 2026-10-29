// A PR no projeto: abrir o código dela numa tarefa (worktree) e "Ajustar com IA" na minha PR — o agente recebe os
// comentários em aberto (de gente ou da revisão da IA) e trabalha na branch da PR (backend: prreview.py).
import { post } from "../../lib/api";
import type { PR } from "../../lib/types";
import { ui } from "../../lib/ui.svelte";
import { work } from "../../lib/work.svelte";

export async function openPrWorkspace(pr: PR) {
  const prog = ui.progress(`Abrindo a PR #${pr.prId} no projeto…`);
  try {
    const r = await post<{ projectId: string; taskId: string | null }>("pr/open-workspace", { key: pr.key });
    await work.load();
    prog.done(r.taskId ? "Código da PR aberto numa tarefa do projeto" : "Projeto aberto — o checkout já está na branch da PR");
    work.focus(r.projectId, r.taskId);
  } catch (e) { prog.fail(e); }
}

export async function fixPr(pr: PR, accountId: string) {
  const prog = ui.progress("Lendo os comentários em aberto da PR…");
  try {
    const r = await post<{ projectId: string; taskId: string | null; termId: string; points: number }>("pr/fix", { key: pr.key, accountId });
    await work.load();
    prog.done(`Agente ajustando ${r.points} ponto(s) da PR #${pr.prId}`);
    work.focus(r.projectId, r.taskId, r.termId);
  } catch (e) { prog.fail(e); }
}
