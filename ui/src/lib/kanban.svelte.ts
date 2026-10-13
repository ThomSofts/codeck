import { get, post } from "./api";
import { ui } from "./ui.svelte";
import { work, type Flow } from "./work.svelte";

// Quadro (kanban) editável. Os cartões dizem a que grupo e a quais projetos pertencem; a IA pode planejar e implementar
// um cartão direto daqui (tarefa em worktree no projeto principal, mesma branch nos outros que mudam).
export type Priority = "low" | "normal" | "high" | "urgent";
export interface Column { id: string; name: string; color: string; role: "backlog" | "todo" | "doing" | "review" | "done" | null }
export interface CardLive { repoId: string; taskId: string; title: string; branch: string; status: string; flow: Flow | null; exists: boolean; pr?: any; agents: number }
export interface Card {
  id: string; title: string; description: string; column: string; order: number; priority: Priority; labels: string[]; groupId: string | null;
  projects: string[]; primary: string | null; refs: string[]; workItem: any; due: string | null; tasks: { repoId: string; taskId: string; flow: string; at: string }[];
  createdAt: string; updatedAt: string; live: CardLive | null;
}
export const PRIORITY: Record<Priority, { label: string; tone: string }> = {
  urgent: { label: "Urgente", tone: "bad" }, high: { label: "Alta", tone: "warn" }, normal: { label: "Normal", tone: "neutral" }, low: { label: "Baixa", tone: "muted" },
};

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

class Kanban {
  columns = $state<Column[]>([]);
  cards = $state<Card[]>([]);
  autoMove = $state(true);
  loaded = $state(false);
  private busy = 0;

  async load() {
    if (this.busy) return;
    try {
      const r = await get<{ columns: Column[]; cards: Card[]; autoMove: boolean }>("kanban");
      if (this.busy) return;
      if (!same(this.columns, r.columns)) this.columns = r.columns;
      if (!same(this.cards, r.cards)) this.cards = r.cards;
      this.autoMove = r.autoMove;
      this.loaded = true;
    } catch (e) { ui.error(e); }
  }
  /** Relê enquanto a tela estiver aberta (o estado da IA em cada cartão muda sozinho). */
  watch() {
    this.load();
    const t = setInterval(() => { if (document.visibilityState === "visible") this.load(); }, 4000);
    return () => clearInterval(t);
  }
  private async call<T>(fn: () => Promise<T>, optimistic?: () => void): Promise<T | null> {
    this.busy++;
    const before = { columns: this.columns, cards: this.cards };
    optimistic?.();
    try { const r = await fn(); this.busy--; await this.load(); return r; }
    catch (e) { this.busy--; this.columns = before.columns; this.cards = before.cards; ui.error(e); return null; }
  }
  saveCard(c: Partial<Card>) { return this.call(() => post<Card>("kanban/card", c)); }
  deleteCard(id: string) { return this.call(() => post("kanban/card/delete", { id }), () => (this.cards = this.cards.filter(c => c.id !== id))); }
  move(id: string, column: string, index: number) {
    return this.call(() => post("kanban/move", { id, column, index }), () => {
      const c = this.cards.find(x => x.id === id);
      if (!c) return;
      const rest = this.cards.filter(x => x.column === column && x.id !== id).sort((a, b) => a.order - b.order);
      rest.splice(Math.max(0, Math.min(index, rest.length)), 0, { ...c, column });
      const order = new Map(rest.map((x, i) => [x.id, i + 1]));
      this.cards = this.cards.map(x => (order.has(x.id) ? { ...x, column: x.id === id ? column : x.column, order: order.get(x.id)! } : x));
    });
  }
  saveColumns(columns: Column[], autoMove = this.autoMove) {
    return this.call(() => post("kanban/columns", { columns, autoMove }), () => { this.columns = columns; this.autoMove = autoMove; });
  }

  /** IA no cartão: tarefa no projeto principal, worktree na mesma branch nos projetos que mudam, os de consulta como
   *  pastas extras do agente, e o contexto (cartão, grupo, projetos e pastas) junto do pedido. */
  async run(card: Card, o: { flow: Flow; accountId: string; primary: string; change: string[]; refs: string[] }) {
    const prog = ui.progress(`Preparando “${card.title}”…`);
    try {
      if (card.primary !== o.primary || !same([...card.refs].sort(), [...o.refs].sort())) await post("kanban/card", { id: card.id, primary: o.primary, refs: o.refs });
      const ctx = (await get<{ text: string }>("kanban/context", { id: card.id })).text;
      await work.open(o.primary);
      prog.update("Criando os worktrees e abrindo o agente…");
      const r = await work.askAi({ projectId: o.primary, title: card.title, text: card.description || card.title, flow: o.flow, accountId: o.accountId,
        worktree: true, linked: o.change.filter(x => x !== o.primary), refs: o.refs, context: ctx, card: card.id,
        workItem: card.workItem || null, kind: card.labels.some(l => /bug|fix/i.test(l)) ? "fix" : undefined });
      if (r.taskId) await post("kanban/link", { id: card.id, repoId: o.primary, taskId: r.taskId, flow: o.flow });
      await this.load();
      prog.done(o.flow === "implement" ? "A IA está implementando o cartão" : o.flow === "plan" ? "A IA está planejando o cartão" : "A IA está planejando — aprove o plano no terminal");
      ui.toast(`“${card.title}” em andamento`, "info", { label: "Abrir", run: () => work.focus(o.primary, r.taskId) });
      return r;
    } catch (e) { prog.fail(e); return null; }
  }
}

export const kanban = new Kanban();
