// Avisos (toasts) e diálogos do próprio app — consistentes no macOS e no Windows.
export interface Toast { id: number; text: string; kind: "ok" | "error" | "info" | "loading"; action?: { label: string; run: () => void } }
export interface Dialog {
  title: string; message?: string; detail?: string[]; confirm?: string; cancel?: string; danger?: boolean;
  /** terceiro botão (ex.: "Minimizar"): o diálogo devolve "alt" */
  alt?: string;
  input?: { label: string; value?: string; placeholder?: string; multiline?: boolean; required?: boolean };
  blocked?: string[]; resolve: (v: string | boolean | null) => void;
}
/** Menu aberto: um só por vez, desenhado pelo MenuHost por cima de tudo (nunca recortado por painel com rolagem). */
export interface OpenMenu {
  items: import("../components/Menu.svelte").MenuItem[];
  /** retângulo do botão que abriu (menu ancorado) ou ponto do clique direito */
  anchor: { left: number; top: number; right: number; bottom: number };
  align: "left" | "right";
  owner: symbol | null;
}
/** Pergunta onde clonar: devolve a pasta BASE escolhida (o repositório vai para base/<nome>) e se é para lembrar. */
export interface CloneAsk { title: string; names: string[]; account?: string | null; accountName?: string; resolve: (v: { base: string; remember: boolean } | null) => void }
/** Aviso de uma ação em andamento: nasce girando e vira sucesso ou erro no mesmo lugar. */
export interface Progress { done: (text: string) => void; fail: (e: unknown) => void; update: (text: string) => void }

const message = (e: unknown) => (e as any)?.message || String(e);

class UI {
  toasts = $state<Toast[]>([]);
  dialog = $state<Dialog | null>(null);
  palette = $state(false);
  menu = $state<OpenMenu | null>(null);
  cloneAsk = $state<CloneAsk | null>(null);
  /** conta aberta no painel de detalhes e ajustes ("provider:conta") */
  editAccount = $state<string | null>(null);
  /** repositório aberto no painel de gestão (acompanhamento, PRs/builds/deploys/issues, pasta local) */
  repoHub = $state<{ localId?: string; remote?: any } | null>(null);
  /** quantos envios (POST) estão em andamento — alimenta a barra de progresso do topo */
  inflight = $state(0);
  private seq = 0;

  private expire(id: number, kind: Toast["kind"]) {
    setTimeout(() => (this.toasts = this.toasts.filter(t => t.id !== id)), kind === "error" ? 6000 : 3200);
  }
  private patch(id: number, p: Partial<Toast>) {
    this.toasts = this.toasts.map(t => (t.id === id ? { ...t, ...p } : t));
  }

  toast(text: string, kind: Toast["kind"] = "ok", action?: Toast["action"]) {
    const id = ++this.seq;
    this.toasts = [...this.toasts.slice(-3), { id, text, kind, action }];
    if (kind !== "loading") this.expire(id, kind);
    return id;
  }
  error(e: unknown) { this.toast(message(e), "error"); }

  progress(text: string): Progress {
    const id = this.toast(text, "loading");
    return {
      update: t => this.patch(id, { text: t }),
      done: t => { this.patch(id, { text: t, kind: "ok" }); this.expire(id, "ok"); },
      fail: e => { this.patch(id, { text: message(e), kind: "error" }); this.expire(id, "error"); },
    };
  }

  openMenu(m: OpenMenu) { this.menu = m; }
  chooseCloneDir(a: Omit<CloneAsk, "resolve">): Promise<{ base: string; remember: boolean } | null> {
    return new Promise(resolve => (this.cloneAsk = { ...a, resolve: v => { this.cloneAsk = null; resolve(v); } }));
  }
  closeMenu() { this.menu = null; }
  /** Clique direito: abre `items` no ponto do cursor. */
  contextMenu(e: MouseEvent, items: OpenMenu["items"]) {
    e.preventDefault();
    e.stopPropagation();
    this.menu = { items, anchor: { left: e.clientX, right: e.clientX, top: e.clientY, bottom: e.clientY }, align: "left", owner: null };
  }

  /** Confirmação. Com `input`, devolve o texto (ou null se cancelou). Com `blocked`, só informa e não deixa confirmar. */
  ask(d: Omit<Dialog, "resolve">): Promise<any> {
    return new Promise(resolve => (this.dialog = { ...d, resolve }));
  }
  close(v: string | boolean | null) {
    this.dialog?.resolve(v);
    this.dialog = null;
  }
}

export const ui = new UI();
