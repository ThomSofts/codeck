// Atalhos de histórico de uma PR: o do app (votos, piloto, comentários) e os commits da branch no clone local.
import { repos } from "../../lib/repos.svelte";
import { go } from "../../lib/router.svelte";
import { store } from "../../lib/store.svelte";
import type { LocalRepo, PR } from "../../lib/types";
import { ui } from "../../lib/ui.svelte";
import { work } from "../../lib/work.svelte";

/** Clone local do repositório da PR — o do projeto, não o worktree de uma tarefa. */
export function localClone(repoKey: string | null | undefined): LocalRepo | null {
  const k = (repoKey || "").toLowerCase();
  if (!k) return null;
  const taskRepos = new Set(work.projects.flatMap(p => p.tasks.map(t => t.repoId)));
  const all = repos.local.filter(r => (r.remoteKey || "").toLowerCase() === k && r.exists !== false);
  return all.find(r => !taskRepos.has(r.id)) || all[0] || null;
}

export const prHistoryPath = (key: string) => "/history/pr/" + encodeURIComponent(key);

/** Aba Git do clone com a branch da PR destacada no graph. */
export function openPrCommits(pr: { repo: string; repoKey?: string | null; source: string }) {
  const local = localClone(pr.repoKey);
  if (!local) return ui.toast(`${pr.repo} não está clonado nesta máquina — clone em Repositórios para ver os commits`, "info");
  repos.branchIntent = { repoId: local.id, branch: pr.source };
  work.openRepo(local.id, "git");
}

/** A PR (das listas que o app já tem) e a aba de PRs em que ela aparece. */
export function findPr(key: string): { pr: PR; tab: string } | null {
  const s = store.s;
  if (!s) return null;
  const mine = s.myPrs.find(p => p.key === key);
  if (mine) return { pr: mine, tab: "mine" };
  const inbox = store.inbox.find(p => p.key === key);
  if (inbox) return { pr: inbox, tab: "review" };
  const arch = store.archived.find(p => p.key === key);
  if (arch) return { pr: arch, tab: "archived" };
  const open = store.open.find(p => p.key === key) || s.prs.find(p => p.key === key);
  return open ? { pr: open, tab: "all" } : null;
}

export const openPr = (key: string) => { const f = findPr(key); go(`/prs/${f?.tab || "all"}/${encodeURIComponent(key)}`); };
