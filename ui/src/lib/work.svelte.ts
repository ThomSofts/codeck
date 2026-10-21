// Área de trabalho (v3): projetos abertos em abas, tarefas em worktree, terminais/agentes e contas de IA.
// O estado vem de /api/ws (relido a cada 2,5 s enquanto a tela está aberta — o status dos agentes muda rápido).
import { get, post } from "./api";
import { repos } from "./repos.svelte";
import { go, router } from "./router.svelte";
import { ui } from "./ui.svelte";
import { drop } from "../components/work/Terminal.svelte";

export type Provider = "claude" | "codex" | "cursor" | "gemini" | "opencode";
export interface AiAccount {
  id: string; provider: Provider; dir: string; name: string; email?: string | null; color?: string | null; label: string;
  /** o cliente/contexto da conta (Dematec, Pessoal…): a recomendação de um projeto fica entre as do mesmo grupo */
  group?: string | null;
  installed: boolean; telemetry: "hooks" | "log" | null; bin?: string | null;
  usage?: { rateLimits: { window: string; used: number | null; resetsAt: string | null }[]; updated: string; source: string; plan?: string } | null;
}
/** O que cada conta está fazendo agora: sessões abertas pelo app e fora dele (terminal, IDE). */
export interface AiActivity {
  state: "needs-you" | "working" | "done" | "idle" | "free"; probing: boolean; probeError: { error: string; at: string } | null;
  sessions: { sid: string; project: string | null; repoId: string | null; task: string | null; title: string | null; status: string; model: string | null; context: number | null; since: number | null }[];
  external: { session: string; cwd: string; project: string; repoId: string | null; status: string; updatedAgo: number; external: true }[];
}
export interface TermInfo {
  id: string; title: string; kind: "shell" | "agent" | "setup" | "run"; cwd: string; alive: boolean; exit: number | null; created: number; lastOutput: number;
  meta: { project?: string; task?: string; account?: string; provider?: Provider; sid?: string; run?: string; debug?: string; bypass?: boolean };
}
export interface Session {
  account: string; provider: Provider; status: "starting" | "idle" | "working" | "done" | "needs-you" | "compacting"; started: number;
  model: string | null; cost: number | null; context: { used: number | null; size: number | null; tokens: number | null } | null;
  events: { at: string; event: string; message?: string }[]; title?: string; statusAt?: number;
}
export interface Resumable { sid: string; account: string; provider: Provider; title: string; cliSession: string; updated: string }
export interface Task {
  id: string; title: string; slug: string; branch: string; base: string; path: string; repoId: string; createdAt: string;
  status: string; prompt: string; exists: boolean; terms: TermInfo[]; workItem?: any; pr?: any; copied: string[]; group?: string | null; resumable?: Resumable[];
}
/** Grupo de projetos (como grupo de abas do navegador): nome, cor e os repositórios dele. */
export interface Group { id: string; name: string; color: string; collapsed: boolean; repoIds: string[]; description?: string }
export interface Project {
  id: string; name: string; path: string; provider?: string | null; slug?: string | null; webUrl?: string | null;
  /** bypass = abrir os agentes deste projeto sem pedir permissão; account = a conta de IA do projeto (a última usada) */
  settings: { copy: string[]; setup: string; worktreeRoot: string; shell?: string; addDirs?: string[]; bypass?: boolean; account?: string | null };
  tasks: Task[]; terms: TermInfo[]; resumable?: Resumable[];
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

class Work {
  projects = $state<Project[]>([]);
  groups = $state<Group[]>([]);
  active = $state<string | null>(null);
  sessions = $state<Record<string, Session>>({});
  ai = $state<AiAccount[]>([]);
  providers = $state<Record<string, { label: string; installed: boolean }>>({});
  defaults = $state<Record<string, string>>({});
  activity = $state<Record<string, AiActivity>>({});
  /** contas com a leitura de limite em andamento (botão "Ler agora") */
  probing = $state<Record<string, boolean>>({});
  loaded = $state(false);
  /** "Nova tarefa" já preenchida, pedida de outra tela (PR, build, issue): a tela de trabalho abre o formulário */
  pendingTask = $state<{ projectId: string; preset: any } | null>(null);
  /** "Pedir à IA" pedido de outra tela (issue, PR…): a tela do projeto abre o diálogo já preenchido */
  pendingAsk = $state<{ projectId: string; preset: any } | null>(null);
  /** ⌘⇧I / "Pedir à IA": o painel do agente do projeto põe o cursor no campo de pedido (e consome o pedido) */
  composeFocus = $state<{ projectId: string; at: number } | null>(null);
  /** abrir um projeto já numa aba (ex.: a Git), vindo de um link de repositório */
  focusRequest = $state<{ projectId: string; scope: string | null; tab: "git" | "review" | "code"; termId?: string | null } | null>(null);
  private timer: ReturnType<typeof setInterval> | null = null;
  /** projetos sendo fechados: nem a rota (que muda um quadro depois, na transição) nem o polling os trazem de volta */
  closing = new Set<string>();

  get project() { return this.projects.find(p => p.id === this.active) || null; }
  account(id?: string | null) { return this.ai.find(a => a.id === id) || null; }
  session(t: TermInfo | null | undefined) { return t?.meta.sid ? this.sessions[t.meta.sid] || null : null; }

  /** Todos os terminais de agente abertos, com a sessão — para a barra lateral e o quadro. */
  get agents() {
    const out: { project: Project; task: Task | null; term: TermInfo; session: Session | null }[] = [];
    for (const p of this.projects) {
      for (const t of p.terms.filter(x => x.kind === "agent")) out.push({ project: p, task: null, term: t, session: this.session(t) });
      for (const k of p.tasks) for (const t of k.terms.filter(x => x.kind === "agent")) out.push({ project: p, task: k, term: t, session: this.session(t) });
    }
    return out;
  }
  get needsYou() { return this.agents.filter(a => a.session?.status === "needs-you").length; }

  async load() {
    try {
      const s = await get<{ projects: Project[]; active: string | null; sessions: Record<string, Session>; groups: Group[] }>("ws");
      if (!this.groupBusy && !same(this.groups, s.groups || [])) this.groups = s.groups || [];
      // reaproveita os projetos que não mudaram: trocar o objeto a cada 2,5 s fazia a tela inteira do projeto reagir
      // (árvore de arquivos fechando, diff relido…) mesmo sem nada novo
      const old = new Map(this.projects.map(p => [p.id, p]));
      const next = s.projects.filter(p => !this.closing.has(p.id)).map(p => { const o = old.get(p.id); return o && same(o, p) ? o : p; });
      if (next.length !== this.projects.length || next.some((p, i) => p !== this.projects[i])) this.projects = next;
      this.active = this.projects.some(p => p.id === this.active) ? this.active : s.active;
      if (!same(this.sessions, s.sessions)) this.sessions = s.sessions;
      this.loaded = true;
    } catch (e) { ui.error(e); }
  }
  async loadAi(rescan = false) {
    const r = await get<{ accounts: AiAccount[]; providers: any; defaults: Record<string, string> }>("ai", rescan ? { rescan: 1 } : undefined);
    if (!same(this.ai, r.accounts)) this.ai = r.accounts;
    if (!same(this.providers, r.providers)) this.providers = r.providers;
    if (!same(this.defaults, r.defaults)) this.defaults = r.defaults;
  }
  async loadActivity() {
    try {
      const r = await get<{ activity: Record<string, AiActivity> }>("ai/activity");
      if (!same(this.activity, r.activity)) this.activity = r.activity;
    } catch { /* backend ocupado: tenta no próximo ciclo */ }
  }
  /** Lê o limite agora (sonda mínima pela própria CLI). Sem id: todas as contas do Claude. */
  async probe(id?: string) {
    const ids = id ? [id] : this.ai.filter(a => a.provider === "claude").map(a => a.id);
    for (const x of ids) this.probing = { ...this.probing, [x]: true };
    try {
      if (id) await post("ai/probe", { id });
      else {
        const r = await post<{ ok: number; errors: Record<string, string> }>("ai/probe", { all: true });
        const n = Object.keys(r.errors).length;
        ui.toast(n ? `${r.ok} conta(s) lidas · ${n} com problema` : `Limites de ${r.ok} conta(s) atualizados`, n ? "info" : "ok");
      }
      await Promise.all([this.loadAi(), this.loadActivity()]);
    } catch (e) { ui.error(e); await this.loadActivity(); }
    finally { const p = { ...this.probing }; for (const x of ids) delete p[x]; this.probing = p; }
  }
  watch() {
    if (this.timer) return () => {};
    this.load();
    this.loadAi();
    this.loadActivity();
    this.timer = setInterval(() => this.load(), 2500);
    const aiT = setInterval(() => this.loadAi(), 30000);
    const actT = setInterval(() => { if (document.visibilityState === "visible") this.loadActivity(); }, 15000);
    return () => { clearInterval(this.timer!); clearInterval(aiT); clearInterval(actT); this.timer = null; };
  }

  async open(repoId?: string, path?: string) {
    const r = await post<{ id: string }>("ws/open", { repoId, path });
    this.closing.delete(r.id);   // reabrir de propósito vence o "fechando"
    this.active = r.id;
    await this.load();
    return r.id;
  }
  async close(repoId: string) {
    const p = this.projects.find(x => x.id === repoId);
    const running = p ? [...p.terms, ...p.tasks.flatMap(t => t.terms)].filter(t => t.alive).length : 0;
    if (running && !(await ui.ask({ title: `Fechar ${p!.name}?`, message: `${running} terminal(is)/agente(s) deste projeto serão encerrados e as sessões de IA limpas (não ficam para retomar). As tarefas e os worktrees continuam.`, confirm: "Fechar", danger: true }))) return;
    // sai da rota do projeto ANTES de fechar: a tela reabre o projeto que está na rota (por isso ele "voltava").
    // A rota só muda no quadro seguinte (transição de tela) — até lá o "closing" impede a reabertura.
    this.closing.add(repoId);
    const rest = this.projects.filter(x => x.id !== repoId);
    if (router.view === "work" && (router.parts[1] === repoId || (!router.parts[1] && this.active === repoId)))
      go(rest.length ? "/work/" + rest[rest.length - 1].id : "/work/", "soft");
    this.projects = rest;
    if (this.active === repoId) this.active = rest.length ? rest[rest.length - 1].id : null;
    try { await post("ws/close", { repoId }); }
    finally { setTimeout(() => this.closing.delete(repoId), 1500); }
    // os terminais do projeto saem da tela também (xterm + conexão): antes ficavam vivos na memória, reconectando
    if (p) for (const t of [...p.terms, ...p.tasks.flatMap(k => k.terms)]) drop(t.id);
    await this.load();
  }
  async activate(repoId: string) {
    this.active = repoId;
    post("ws/activate", { repoId }).catch(() => {});
  }

  /** Acha o clone local de um repositório remoto. GitHub: "dono/repo"; Azure: org + nome do repo. */
  findLocal(provider: string, org: string, repo: string) {
    const n = (s?: string | null) => (s || "").toLowerCase();
    return repos.local.find(r => r.provider === provider && r.exists && r.slug && (provider === "github"
      ? n(r.slug) === n(repo.includes("/") ? repo : `${org}/${repo}`)
      : n(r.slug.split("/")[0]) === n(org) && n(r.slug.split("/").pop()) === n(repo))) || null;
  }

  /** Abre o projeto certo e a "Nova tarefa" preenchida. Sem clone local, avisa; sem repo (work item do Azure), usa o projeto ativo. */
  async startTask(target: { provider: string; org: string; repo?: string | null } | null, preset: any) {
    if (!repos.loaded) await repos.load(false);
    let local = target?.repo ? this.findLocal(target.provider, target.org, target.repo) : null;
    if (!local && target?.repo) {
      return ui.toast(`${target.repo} não está clonado nesta máquina — clone em Repositórios e tente de novo`, "info");
    }
    const projectId = local ? await this.open(local.id) : this.active;
    if (!projectId) return ui.toast("Abra um projeto em Projetos primeiro", "info");
    this.pendingTask = { projectId, preset };
    go("/work/" + projectId);
  }

  /** Abre o projeto certo e o "Pedir à IA" preenchido (issue/work item). Sem clone, usa o projeto ativo. */
  async askFrom(target: { provider: string; org: string; repo?: string | null } | null, preset: any) {
    if (!repos.loaded) await repos.load(false);
    const local = target?.repo ? this.findLocal(target.provider, target.org, target.repo) : null;
    if (!local && target?.repo) return ui.toast(`${target.repo} não está clonado nesta máquina — clone em Repositórios e tente de novo`, "info");
    const projectId = local ? await this.open(local.id) : this.active;
    if (!projectId) return ui.toast("Abra um projeto em Projetos primeiro", "info");
    this.pendingAsk = { projectId, preset };
    go("/work/" + projectId);
  }

  /** Repositório = projeto. Um link de repositório (lista, barra lateral, ⌘K) abre o projeto na aba Git; se o
   *  repositório é o worktree de uma tarefa, abre a tarefa (o Git dela é o do worktree). */
  async openRepo(repoId: string, tab: "git" | "review" = "git") {
    if (!this.loaded) await this.load();
    const owner = this.projects.find(p => p.tasks.some(t => t.repoId === repoId));
    const task = owner?.tasks.find(t => t.repoId === repoId);
    const projectId = owner ? owner.id : repoId;
    this.focusRequest = { projectId, scope: task?.id || null, tab };
    go("/work/" + projectId);
  }

  // ---------------------------------------------------------------- grupos
  private groupBusy = 0;
  groupOf(repoId?: string | null) { return repoId ? this.groups.find(g => g.repoIds.includes(repoId)) || null : null; }
  private async groupCall(path: string, body: any, optimistic?: () => void) {
    this.groupBusy++;
    const before = this.groups;
    optimistic?.();
    try { const r = await post(path, body); await this.load(); return r; }
    catch (e) { this.groups = before; ui.error(e); return null; }
    finally { this.groupBusy--; }
  }
  /** Cria (sem id) ou altera um grupo. Devolve o grupo salvo. */
  saveGroup(g: Partial<Group> & { name?: string }) {
    return this.groupCall("ws/groups/save", g, () => {
      if (g.id) this.groups = this.groups.map(x => (x.id === g.id ? { ...x, ...g } as Group : g.repoIds ? { ...x, repoIds: x.repoIds.filter(r => !g.repoIds!.includes(r)) } : x));
    }) as Promise<Group | null>;
  }
  deleteGroup(id: string) { return this.groupCall("ws/groups/delete", { id }, () => (this.groups = this.groups.filter(g => g.id !== id))); }
  assignGroup(repoId: string, groupId: string | null) {
    return this.groupCall("ws/groups/assign", { repoId, groupId }, () => {
      this.groups = this.groups.map(g => ({ ...g, repoIds: g.id === groupId ? [...g.repoIds.filter(x => x !== repoId), repoId] : g.repoIds.filter(x => x !== repoId) }));
    });
  }
  toggleGroup(id: string) { const g = this.groups.find(x => x.id === id); if (g) this.saveGroup({ id, collapsed: !g.collapsed }); }
  async openGroup(id: string) { const r = await this.groupCall("ws/groups/open", { id }); return r; }
  /** Pergunta o nome e cria um grupo novo (já com os projetos indicados). */
  async newGroup(repoIds: string[] = []) {
    const name = await ui.ask({ title: "Novo grupo de projetos", message: "Como um grupo de abas do navegador: junta projetos (ex.: “Cifal 2” com as APIs) com nome e cor. Recolhe e expande nas abas.",
      input: { label: "Nome do grupo", placeholder: "Cifal 2", required: true }, confirm: "Criar grupo" });
    if (!name) return null;
    return this.saveGroup({ name: String(name).trim(), repoIds });
  }

  /** Pede para a IA planejar e/ou implementar. Em worktree (tarefa nova: branch + worktree + agente) ou no checkout
   *  atual/na tarefa aberta. `linked` = outros projetos que a tarefa atravessa (um worktree em cada, mesma branch).
   *  `raw` = o pedido vai do jeito que foi escrito (sem a instrução do fluxo na frente) — o "Pedir à IA" do painel.
   *  Pular permissões é do projeto (ajustes): o servidor põe a flag em todo agente aberto nele. */
  async askAi(o: { projectId: string; title: string; text: string; flow: Flow; accountId: string | null; worktree: boolean; linked?: string[];
    refs?: string[]; workItem?: any; context?: string; kind?: string; taskId?: string | null; card?: string | null; raw?: boolean }) {
    const f = FLOWS[o.flow];
    const prompt = (o.raw ? "" : f.prefix) + o.text.trim() + (o.context ? "\n\n" + o.context.trim() : "");
    if (!o.accountId) throw new Error("Escolha a conta de IA");
    if (o.worktree) {
      const t = await post<Task>("ws/task", { repoId: o.projectId, title: o.title.trim() || o.text.trim().split("\n")[0].slice(0, 70), kind: o.kind || (o.flow === "plan" ? "plan" : "feature"), prompt,
        agents: [o.accountId], mode: f.mode, linked: o.linked || [], refs: o.refs || [], workItem: o.workItem || null, card: o.card || null });
      await this.load();
      return { projectId: o.projectId, taskId: t.id };
    }
    const t = await post<TermInfo>("ws/agent", { repoId: o.projectId, taskId: o.taskId || null, accountId: o.accountId, prompt, mode: f.mode, title: o.title.slice(0, 40) || undefined, card: o.card || null });
    this.rememberAccount(o.projectId, o.accountId);
    await this.load();
    return { projectId: o.projectId, taskId: o.taskId || null, termId: t.id };
  }
  /** Abre um agente sem pedido (só a sessão), na conta indicada ou na do projeto. */
  async openAgent(projectId: string, taskId: string | null, accountId?: string | null) {
    const p = this.projects.find(x => x.id === projectId);
    const acc = accountId || this.defaultAccount(p);
    if (!acc) throw new Error("Nenhuma conta de IA — configure em Contas e ajustes → IA");
    const t = await post<TermInfo>("ws/agent", { repoId: projectId, taskId, accountId: acc });
    this.rememberAccount(projectId, acc);
    await this.load();
    return { projectId, taskId, termId: t.id };
  }
  /** Manda um pedido para um agente já aberto (como se fosse colado no terminal dele e Enter). */
  sendToAgent(termId: string, text: string) { return post("ws/agent/input", { termId, text }); }
  /** A conta de IA do projeto: o servidor já grava a última usada ao abrir um agente; trocar no chip grava na hora. */
  rememberAccount(projectId: string, accountId: string) {
    const p = this.projects.find(x => x.id === projectId);
    if (p && p.settings.account !== accountId) this.projects = this.projects.map(x => (x === p ? { ...x, settings: { ...x.settings, account: accountId } } : x));
  }
  /** Apelido, grupo e cor da conta (o que vier). */
  async updateAccount(id: string, patch: { name?: string; group?: string | null; color?: string | null }) {
    await post("ai/update", { id, ...patch });
    this.ai = this.ai.map(a => (a.id === id ? { ...a, ...patch } : a));
  }
  async setAccount(projectId: string, accountId: string) {
    this.rememberAccount(projectId, accountId);
    try { await post("ws/settings", { repoId: projectId, account: accountId }); } catch (e) { ui.error(e); }
  }
  focusComposer(projectId?: string | null) {
    const id = projectId || this.active;
    if (id) this.composeFocus = { projectId: id, at: Date.now() };
  }
  /** Abre o projeto já numa tarefa/aba (vindo do quadro, das issues…). */
  focus(projectId: string, scope: string | null, termId?: string | null) {
    this.focusRequest = { projectId, scope, tab: "code", termId: termId || null };
    go("/work/" + projectId);
  }

  /** Conta sugerida para um projeto: a dele (a última usada nele), senão a padrão do dono (org) do repositório, senão a
   *  geral, senão a 1ª instalada. */
  defaultAccount(p?: Project | null) {
    const own = p?.settings?.account;
    if (own && this.ai.some(a => a.id === own && a.installed)) return own;
    const scope = p?.provider && p.slug ? `${p.provider}:${p.slug.split("/")[0]}` : "";
    return this.defaults[scope] || this.defaults["*"] || this.ai.find(a => a.installed && a.provider === "claude")?.id || this.ai.find(a => a.installed)?.id || null;
  }
}

export const work = new Work();

/** Como a IA trabalha num pedido: o modo do agente e a instrução que vai antes do pedido. */
export type Flow = "plan" | "plan-implement" | "implement";
export const FLOWS: Record<Flow, { label: string; short: string; hint: string; mode: string; prefix: string }> = {
  plan: { label: "Só planejar", short: "Planejar", hint: "Investiga o código e devolve um plano — não altera nada",
    mode: "plan", prefix: "Planeje esta tarefa: investigue o código, liste os arquivos que mudam, os passos e os riscos. NÃO implemente nada ainda.\n\n" },
  "plan-implement": { label: "Planejar → você aprova → implementar", short: "Planejar e implementar", hint: "Mostra o plano, espera você aprovar no terminal e então implementa",
    mode: "plan", prefix: "Primeiro apresente um plano (arquivos, passos, riscos) para eu aprovar. Depois de aprovado, implemente, rode o build/os testes e resuma o que mudou.\n\n" },
  implement: { label: "Implementar direto", short: "Implementar", hint: "Já implementa, aceitando as edições — você revisa no fim",
    mode: "acceptEdits", prefix: "Implemente esta tarefa. Ao final rode o build/os testes e resuma o que mudou.\n\n" },
};

export const STATUS: Record<string, [string, string]> = {
  starting: ["abrindo…", "muted"], idle: ["pronto", "muted"], working: ["trabalhando", "accent"], done: ["terminou", "good"],
  "needs-you": ["precisa de você", "warn"], compacting: ["compactando", "info"],
};
