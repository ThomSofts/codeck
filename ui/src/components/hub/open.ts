// Projetos abertos na mesma ordem das abas (os de um grupo ficam juntos, onde aparece o 1º deles) e o estado dos
// agentes de cada projeto — compartilhado pelo hub ("Abertos agora") e pelo seletor de projetos abertos.
import type { Project, Provider } from "../../lib/work.svelte";
import { work } from "../../lib/work.svelte";

export function openOrdered(): Project[] {
  const out: Project[] = [], seen = new Set<string>();
  for (const x of work.projects) {
    const g = work.groupOf(x.id);
    if (!g) { out.push(x); continue; }
    if (seen.has(g.id)) continue;
    seen.add(g.id);
    out.push(...work.projects.filter(y => work.groupOf(y.id)?.id === g.id));
  }
  return out;
}

export type AgentsOf = { n: number; working: number; need: number; done: number; list: { id: string; provider?: Provider; status?: string }[] };
const NONE: AgentsOf = { n: 0, working: 0, need: 0, done: 0, list: [] };

/** projeto → agentes abertos nele (contagem por estado). Uma passada só: barato para centenas de linhas. */
export function agentsByProject(): Map<string, AgentsOf> {
  const m = new Map<string, AgentsOf>();
  for (const a of work.agents) {
    let e = m.get(a.project.id);
    if (!e) m.set(a.project.id, (e = { n: 0, working: 0, need: 0, done: 0, list: [] }));
    const st = a.session?.status;
    e.n++;
    if (st === "working") e.working++;
    else if (st === "needs-you") e.need++;
    else if (st === "done") e.done++;
    e.list.push({ id: a.term.id, provider: a.term.meta.provider, status: st });
  }
  return m;
}
export const noAgents = NONE;

/** "precisa de você" > "trabalhando" > "terminou" > nada */
export const tone = (a: AgentsOf) => (a.need ? "warn" : a.working ? "accent" : a.done ? "good" : a.n ? "muted" : "off");
