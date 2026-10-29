// Ações sobre uma issue do GitHub ou work item do Azure (Issues e tarefas, Sprints e projetos): pedir à IA, começar uma
// tarefa e levar para o quadro local. O pedido cita o item e diz como referenciá-lo nos commits e na PR, para o
// GitHub/Azure ligarem o código à task.
import { kanban } from "./kanban.svelte";
import { go } from "./router.svelte";
import { ui } from "./ui.svelte";
import { work } from "./work.svelte";

/** Issue do GitHub abre no clone do repositório dela; work item do Azure não tem repositório: o projeto ativo. */
export const issueTarget = (i: any) => (i.provider === "github" && i.repo ? { provider: "github", org: i.repo.split("/")[0], repo: i.repo } : null);

export const refLine = (i: any) => i.provider === "github"
  ? `Nos commits, cite a issue (ex.: "refs #${i.number}"); na descrição da PR, "Closes #${i.number}" — o GitHub liga e fecha a issue.`
  : `Nos commits e na PR, cite o work item (#${i.number}) — o Azure liga o código ao item.`;

export const issueText = (i: any) =>
  `${i.provider === "github" ? "Issue" : i.type || "Work item"} #${i.number}: ${i.title}\n${i.url}\n\nLeia a descrição completa no link antes de começar.\n${refLine(i)}`;

const isBug = (i: any) => /bug|defeito|defect/i.test(i.type || "") || (i.labels || []).some((l: any) => /bug/i.test(l.name));

export function askIssue(i: any, flow?: string) {
  work.askFrom(issueTarget(i), { title: i.title, text: issueText(i), workItem: i, flow });
}

export function startIssueTask(i: any) {
  work.startTask(issueTarget(i), { title: i.title, kind: isBug(i) ? "fix" : "feature", workItem: i,
    prompt: `Implemente ${i.provider === "github" ? "a issue" : "o work item"} #${i.number}: ${i.title}\n${i.url}\n\nLeia a descrição completa no link antes de começar.\n${refLine(i)}` });
}

export async function issueToBoard(i: any) {
  const local = i.provider === "github" ? work.findLocal("github", i.repo.split("/")[0], i.repo) : null;
  const c = await kanban.saveCard({ title: i.title, description: issueText(i), labels: (i.labels || []).map((l: any) => l.name).slice(0, 6),
    projects: local ? [local.id] : [], workItem: { number: i.number, title: i.title, url: i.url, provider: i.provider, key: i.key } });
  if (c) ui.toast("Cartão criado no quadro", "ok", { label: "Abrir", run: () => go("/board/c/" + c.id) });
}
