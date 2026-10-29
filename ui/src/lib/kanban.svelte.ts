import { get, post } from "./api";
import { ui } from "./ui.svelte";
import { work, type Flow } from "./work.svelte";

// Quadro (kanban) editável. Os cartões são seus (título basta; descrição, checklist, anexos, prazo e etiquetas são
// opcionais). A IA é uma automação: com projetos no cartão ela planeja/implementa (tarefa em worktree) e, com o
// "mover sozinho" ligado, move o cartão — cada movimento fica no histórico do cartão e aparece num aviso.
export type Priority = "low" | "normal" | "high" | "urgent";
export type LiveStatus = "working" | "needs-you" | "done" | "idle" | "stopped" | "gone" | "missing";
export interface Column { id: string; name: string; color: string; role: "backlog" | "todo" | "doing" | "review" | "done" | null }
export interface CardLive { repoId: string; taskId: string; title: string; branch: string; status: LiveStatus; flow: Flow | null; exists: boolean; pr?: any; agents: number; since: number | null }
export interface CardFile { id: string; name: string; size: number; type: string; at: string }
export interface CardMove { at: string; from: string; to: string; by: "ia" | "você"; why?: string }
export interface Card {
  id: string; title: string; description: string; column: string; order: number; priority: Priority; labels: string[]; groupId: string | null;
  projects: string[]; primary: string | null; refs: string[]; workItem: any; due: string | null; tasks: { repoId: string; taskId: string; flow: string; at: string }[];
  files: CardFile[]; history: CardMove[]; createdAt: string; updatedAt: string; live: CardLive | null;
}
export const PRIORITY: Record<Priority, { label: string; tone: string }> = {
  urgent: { label: "Urgente", tone: "bad" }, high: { label: "Alta", tone: "warn" }, normal: { label: "Normal", tone: "neutral" }, low: { label: "Baixa", tone: "muted" },
};
/** Estado da tarefa ligada, em palavras: [rótulo, tom]. */
export const LIVE: Record<LiveStatus, [string, string]> = {
  working: ["IA trabalhando", "accent"], "needs-you": ["Precisa de você", "warn"], done: ["IA em espera", "muted"], idle: ["Agente aberto, parado", "muted"],
  stopped: ["Agente fechado", "muted"], gone: ["Worktree apagado", "bad"], missing: ["Tarefa removida", "bad"],
};
export const MAX_FILE = 25 * 1024 * 1024;

/** "- [ ]" / "- [x]" da descrição: feitos/total (null sem checklist). */
export function checklist(text: string) {
  const all = text.match(/^\s*[-*]\s*\[[ xX]\]/gm) || [];
  return all.length ? { done: all.filter(x => /\[[xX]\]/.test(x)).length, total: all.length } : null;
}
/** Cor estável da etiqueta (pelo nome): sem cadastro de cores, a mesma etiqueta tem sempre a mesma cor. */
const LABEL_COLORS = ["#6F8CFF", "#3CCF91", "#F5B84F", "#FF6B7D", "#B07CFF", "#4FC3F7", "#FF8A50", "#E879F9"];
export function labelColor(l: string) {
  let h = 0;
  for (const ch of l.toLowerCase()) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return LABEL_COLORS[h % LABEL_COLORS.length];
}
export const isImage = (f: CardFile) => /^image\/(png|jpe?g|gif|webp|avif|bmp|svg\+xml)$/i.test(f.type);
export function fmtSize(n: number) {
  return n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${Math.round(n / 1024)} KB` : `${(n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}
export function ago(at: string | number | null | undefined, now = Date.now()) {
  if (!at) return "";
  const s = Math.max(0, (now - (typeof at === "number" ? at * 1000 : new Date(at).getTime())) / 1000);
  return s < 60 ? "agora" : s < 3600 ? `há ${Math.floor(s / 60)} min` : s < 86400 ? `há ${Math.floor(s / 3600)} h` : `há ${Math.floor(s / 86400)} d`;
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const headers = () => ({ "X-Codeck-Token": window.CODECK_TOKEN || "" });
function toBase64(f: Blob): Promise<string> {
  return new Promise((ok, fail) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).replace(/^data:[^,]*,/, ""));
    r.onerror = () => fail(r.error || new Error("Não deu para ler o arquivo"));
    r.readAsDataURL(f);
  });
}

class Kanban {
  columns = $state<Column[]>([]);
  cards = $state<Card[]>([]);
  autoMove = $state(true);
  loaded = $state(false);
  /** cartões que a IA acabou de mover (brilham por alguns segundos) */
  flashed = $state<Record<string, true>>({});
  /** arrastando um cartão: o polling não troca a lista embaixo do arraste */
  dragging = false;
  private busy = 0;
  /** muda a cada ação sua: uma leitura que saiu ANTES da ação e chega DEPOIS é descartada (o cartão não "volta") */
  private gen = 0;
  /** movimentos da IA já vistos (o 1º carregamento só anota; os novos viram aviso) */
  private seen: Set<string> | null = null;
  private blobs = new Map<string, Promise<string>>();

  async load() {
    if (this.busy || this.dragging) return;
    const g = this.gen;
    try {
      const r = await get<{ columns: Column[]; cards: Card[]; autoMove: boolean }>("kanban");
      if (this.busy || this.dragging || g !== this.gen) return;
      if (!same(this.columns, r.columns)) this.columns = r.columns;
      if (!same(this.cards, r.cards)) this.cards = r.cards;
      this.autoMove = r.autoMove;
      this.loaded = true;
      this.notice(r.cards, r.columns);
    } catch (e) { ui.error(e); }
  }
  /** A IA moveu um cartão desde a última leitura: avisa (com "Abrir") e faz o cartão brilhar — nada se move calado. */
  private notice(cards: Card[], columns: Column[]) {
    const fresh: { c: Card; m: CardMove }[] = [];
    const keys = new Set<string>();
    for (const c of cards) for (const m of c.history || []) {
      if (m.by !== "ia") continue;
      const k = `${c.id}|${m.at}|${m.to}`;
      keys.add(k);
      if (this.seen && !this.seen.has(k)) fresh.push({ c, m });
    }
    this.seen = keys;
    for (const { c, m } of fresh.slice(-3)) {
      const to = columns.find(x => x.id === m.to)?.name || m.to;
      // "a IA começou" foi você que pediu (o próprio pedido já avisa): só brilha
      if (m.why !== "a IA começou") ui.toast(`IA moveu “${c.title}” para ${to}${m.why ? ` — ${m.why}` : ""}`, "info", c.live ? { label: "Abrir", run: () => this.openTask(c) } : undefined);
      this.flashed = { ...this.flashed, [c.id]: true };
      setTimeout(() => { const f = { ...this.flashed }; delete f[c.id]; this.flashed = f; }, 2600);
    }
  }
  /** Relê enquanto a tela estiver aberta (o estado da IA em cada cartão muda sozinho). */
  watch() {
    this.load();
    const t = setInterval(() => { if (document.visibilityState === "visible") this.load(); }, 4000);
    return () => clearInterval(t);
  }
  private async call<T>(fn: () => Promise<T>, optimistic?: () => void): Promise<T | null> {
    this.busy++;
    this.gen++;
    const before = { columns: this.columns, cards: this.cards };
    optimistic?.();
    try { const r = await fn(); this.busy--; this.gen++; await this.load(); return r; }
    catch (e) { this.busy--; this.gen++; if (!this.busy) { this.columns = before.columns; this.cards = before.cards; } ui.error(e); await this.load(); return null; }
  }
  saveCard(c: Partial<Card>) { return this.call(() => post<Card>("kanban/card", c)); }
  /** Cartão só com título (o "+ Cartão" da coluna): aparece na hora, no fim da coluna. */
  quickAdd(column: string, title: string) {
    const tmp: Card = { id: "tmp-" + Math.random().toString(36).slice(2, 8), title, description: "", column, priority: "normal", labels: [], groupId: null,
      projects: [], primary: null, refs: [], workItem: null, due: null, tasks: [], files: [], history: [], createdAt: "", updatedAt: "", live: null,
      order: Math.max(0, ...this.cards.filter(c => c.column === column).map(c => c.order)) + 1 };
    return this.call(() => post<Card>("kanban/card", { title, column }), () => (this.cards = [...this.cards, tmp]));
  }
  rename(id: string, title: string) {
    return this.call(() => post<Card>("kanban/card", { id, title }), () => (this.cards = this.cards.map(c => (c.id === id ? { ...c, title } : c))));
  }
  setDescription(id: string, description: string) {
    return this.call(() => post<Card>("kanban/card", { id, description }), () => (this.cards = this.cards.map(c => (c.id === id ? { ...c, description } : c))));
  }
  deleteCard(id: string) {
    for (const k of [...this.blobs.keys()]) if (k.startsWith(id + "/")) this.forget(k);
    return this.call(() => post("kanban/card/delete", { id }), () => (this.cards = this.cards.filter(c => c.id !== id)));
  }
  move(id: string, column: string, index: number) {
    return this.call(() => post("kanban/move", { id, column, index }), () => {
      const c = this.cards.find(x => x.id === id);
      if (!c) return;
      const rest = this.cards.filter(x => x.column === column && x.id !== id).sort((a, b) => a.order - b.order);
      rest.splice(Math.max(0, Math.min(index, rest.length)), 0, { ...c, column });
      const order = new Map(rest.map((x, i) => [x.id, i + 1]));
      const hist = c.column !== column ? [...(c.history || []), { at: new Date().toISOString(), from: c.column, to: column, by: "você" as const }] : c.history;
      this.cards = this.cards.map(x => (order.has(x.id) ? { ...x, column: x.id === id ? column : x.column, order: order.get(x.id)!, history: x.id === id ? hist : x.history } : x));
    });
  }
  saveColumns(columns: Column[], autoMove = this.autoMove) {
    return this.call(() => post("kanban/columns", { columns, autoMove }), () => { this.columns = columns; this.autoMove = autoMove; });
  }
  unlink(card: Card, taskId?: string) {
    return this.call(() => post<Card>("kanban/unlink", { id: card.id, taskId: taskId || card.live?.taskId || null }));
  }

  // ------------------------------------------------------------ anexos
  /** Sobe arquivos para o cartão (colar imagem, soltar arquivo, escolher). Mais de 25 MB: recusa com aviso. */
  async attach(cardId: string, files: File[] | FileList) {
    const list = [...files];
    const big = list.filter(f => f.size > MAX_FILE);
    if (big.length) ui.toast(`${big.map(f => f.name).join(", ")} passa${big.length > 1 ? "m" : ""} de 25 MB — não anexado`, "error");
    const ok = list.filter(f => f.size <= MAX_FILE && f.size > 0);
    if (!ok.length) return [];
    const prog = ui.progress(ok.length > 1 ? `Anexando ${ok.length} arquivos…` : `Anexando ${ok[0].name}…`);
    const out: CardFile[] = [];
    this.busy++;
    this.gen++;
    try {
      for (const f of ok) {
        const name = f.name && f.name !== "image.png" ? f.name : `imagem-${new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-")}.${(f.type.split("/")[1] || "png").replace("jpeg", "jpg").replace("svg+xml", "svg")}`;
        out.push(await post<CardFile>("kanban/file", { id: cardId, name, type: f.type || null, data: await toBase64(f) }));
      }
      prog.done(out.length > 1 ? `${out.length} anexos adicionados` : `${out[0].name} anexado`);
    } catch (e) { prog.fail(e); }
    finally { this.busy--; this.gen++; await this.load(); }
    return out;
  }
  async removeFile(cardId: string, fid: string) {
    this.forget(`${cardId}/${fid}`);
    return this.call(() => post("kanban/file/delete", { id: cardId, f: fid }),
      () => (this.cards = this.cards.map(c => (c.id === cardId ? { ...c, files: c.files.filter(f => f.id !== fid) } : c))));
  }
  openFile(cardId: string, fid: string, reveal = false) { return post("kanban/file/open", { id: cardId, f: fid, reveal }).catch(e => ui.error(e)); }
  /** URL local (blob) do anexo: a rota pede a chave no cabeçalho, que um <img src> não manda. Fica em cache. */
  fileUrl(cardId: string, fid: string) {
    const k = `${cardId}/${fid}`;
    let p = this.blobs.get(k);
    if (!p) {
      p = fetch(`/api/kanban/file?${new URLSearchParams({ id: cardId, f: fid })}`, { headers: headers() })
        .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.blob(); }).then(b => URL.createObjectURL(b));
      p.catch(() => this.blobs.delete(k));
      this.blobs.set(k, p);
    }
    return p;
  }
  private forget(k: string) {
    const p = this.blobs.get(k);
    this.blobs.delete(k);
    p?.then(u => URL.revokeObjectURL(u)).catch(() => {});
  }

  // ------------------------------------------------------------ tarefa da IA
  /** Abre a tarefa do cartão: abre o projeto se preciso, entra na tarefa e foca o terminal do agente. Tarefa que não
   *  existe mais: diz isso e oferece desvincular (em vez de abrir o projeto num lugar qualquer). */
  async openTask(card: Card) {
    const lv = card.live || (card.tasks.length ? { repoId: card.tasks[card.tasks.length - 1].repoId, taskId: card.tasks[card.tasks.length - 1].taskId, status: "stopped" } as CardLive : null);
    if (!lv) return ui.toast("Este cartão não tem tarefa da IA", "info");
    const gone = async (why: string) => {
      if (await ui.ask({ title: why, message: `O cartão “${card.title}” continua no quadro. Desvincular tira a ligação com a tarefa (você pode pedir à IA de novo).`, confirm: "Desvincular", cancel: "Manter" }))
        await this.unlink(card, lv.taskId);
    };
    if (lv.status === "missing") return gone("A tarefa deste cartão foi removida do projeto");
    try {
      if (!work.loaded) await work.load();
      if (!work.projects.some(p => p.id === lv.repoId)) await work.open(lv.repoId);
      const p = work.projects.find(x => x.id === lv.repoId);
      if (!p) return ui.toast("Não deu para abrir o projeto da tarefa — ele ainda está nesta máquina?", "error");
      const t = p.tasks.find(x => x.id === lv.taskId);
      if (!t) return gone("A tarefa deste cartão não existe mais no projeto");
      // o agente vivo mais recente; sem vivo, o último (mostra a saída e o "retomar")
      const agents = t.terms.filter(x => x.kind === "agent").sort((a, b) => a.created - b.created);
      const term = [...agents].reverse().find(x => x.alive) || agents[agents.length - 1] || null;
      work.focus(p.id, t.id, term?.id || null);
      if (!t.exists) ui.toast("A pasta do worktree desta tarefa foi apagada", "info", { label: "Desvincular", run: () => this.unlink(card, t.id) });
      else if (!term) ui.toast("Nenhum agente aberto nesta tarefa — retome a conversa ou abra um agente nela", "info");
    } catch (e) { ui.error(e); }
  }

  /** IA no cartão: tarefa no projeto principal, worktree na mesma branch nos projetos que mudam, os de consulta como
   *  pastas extras do agente, e o contexto (cartão, grupo, projetos, anexos e pastas) junto do pedido. */
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
      const fresh = this.cards.find(c => c.id === card.id) || card;
      ui.toast(`“${card.title}” em andamento`, "info", { label: "Abrir", run: () => this.openTask(fresh) });
      return r;
    } catch (e) { prog.fail(e); return null; }
  }
}

export const kanban = new Kanban();
