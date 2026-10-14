// .NET como no Visual Studio, por projeto/tarefa aberto: a solução (projetos, configurações), o(s) projeto(s) de
// inicialização escolhido(s), compilar/recompilar/limpar e iniciar (F5) — a compilação roda num terminal e a Lista de
// Erros é lida da saída dela. As escolhas (solução, configuração, inicialização) ficam lembradas por projeto.
import { get, post } from "./api";
import { setBuildProblems, type Problem } from "./editorstate.svelte";
import { ui } from "./ui.svelte";

export type DnProject = { name: string; path: string; dir: string; kind: "web" | "console" | "winexe" | "library" | "test"; sdk: string | null;
  framework: string | null; netfx: boolean; assembly: string; iisUrl: string | null; test: boolean; folder: string | null; missing?: boolean;
  profiles: { name: string; kind: string; url?: string | null }[] };
export type DnSolution = { path: string | null; name: string; configs: string[]; projects: DnProject[] };
type Toolchain = { msbuild: boolean; vs: string | null; iisexpress: boolean; dotnet: boolean; mono: boolean; nuget: boolean; devenv: boolean };
type Choice = { sln: string | null; config: string; startup: string[]; profile?: string | null };
export type BuildState = { termId: string; action: string; target: string; startAfter: boolean; done: boolean; ok: boolean; errors: number; warnings: number; started: number };

const LS = "codeck.dotnet";
function readChoices(): Record<string, Choice> { try { return JSON.parse(localStorage.getItem(LS) || "{}"); } catch { return {}; } }

class Dotnet {
  data = $state<Record<string, { solutions: DnSolution[]; toolchain: Toolchain; platform: string } | null>>({});
  loading = $state<Record<string, boolean>>({});
  choices = $state<Record<string, Choice>>(readChoices());
  build = $state<Record<string, BuildState | null>>({});
  private polls = new Map<string, ReturnType<typeof setInterval>>();

  key = (repoId: string, taskId: string | null | undefined) => `${repoId}|${taskId || ""}`;
  private save() { try { localStorage.setItem(LS, JSON.stringify(this.choices)); } catch { /* sem armazenamento */ } }

  async load(repoId: string, taskId: string | null, refresh = false) {
    const k = this.key(repoId, taskId);
    if (this.loading[k]) return;
    this.loading = { ...this.loading, [k]: true };
    try {
      const r = await get<{ solutions: DnSolution[]; toolchain: Toolchain; platform: string }>("dotnet/solution", { repoId, taskId, refresh: refresh ? 1 : undefined });
      this.data = { ...this.data, [k]: r };
      // primeira vez: escolhe a solução da raiz, Debug e o 1º projeto executável (web primeiro, como o VS costuma estar)
      const ck = repoId;
      const c = this.choices[ck];
      const sln = r.solutions.find(s => s.path === c?.sln) || r.solutions[0];
      if (sln && (!c || !r.solutions.some(s => s.path === c.sln))) {
        const exe = sln.projects.find(p => p.kind === "web") || sln.projects.find(p => p.kind === "console" || p.kind === "winexe");
        this.choices = { ...this.choices, [ck]: { sln: sln.path, config: sln.configs.find(x => /^debug\|/i.test(x)) || sln.configs[0], startup: exe ? [exe.path] : [] } };
        this.save();
      }
    } catch (e) { this.data = { ...this.data, [k]: null }; ui.error(e); }
    finally { this.loading = { ...this.loading, [k]: false }; }
  }
  choice(repoId: string): Choice { return this.choices[repoId] || { sln: null, config: "Debug|Any CPU", startup: [] }; }
  set(repoId: string, patch: Partial<Choice>) { this.choices = { ...this.choices, [repoId]: { ...this.choice(repoId), ...patch } }; this.save(); }
  solution(repoId: string, taskId: string | null): DnSolution | null {
    const d = this.data[this.key(repoId, taskId)];
    if (!d) return null;
    return d.solutions.find(s => s.path === this.choice(repoId).sln) || d.solutions[0] || null;
  }
  toggleStartup(repoId: string, path: string, multi = false) {
    const c = this.choice(repoId);
    const startup = multi ? (c.startup.includes(path) ? c.startup.filter(x => x !== path) : [...c.startup, path]) : [path];
    this.set(repoId, { startup, profile: null });
  }

  /** Compila (Build/Rebuild/Clean/Restore) a solução ou um projeto; com startAfter, inicia os projetos se der certo (F5). */
  async run(repoId: string, taskId: string | null, action: "Build" | "Rebuild" | "Clean" | "Restore", opts: { target?: string; startAfter?: boolean; onterm?: (id: string) => void } = {}) {
    const k = this.key(repoId, taskId);
    const c = this.choice(repoId), sln = this.solution(repoId, taskId);
    const target = opts.target || sln?.path || c.startup[0];
    if (!target) return ui.toast("Nenhuma solução ou projeto .NET aqui", "info");
    if (opts.startAfter && !c.startup.length) return ui.toast("Escolha o projeto de inicialização (clique direito no projeto → Definir como inicialização)", "info");
    try {
      const r = await post<{ term: { id: string } }>("dotnet/build", { repoId, taskId, target, config: c.config, action });
      this.build = { ...this.build, [k]: { termId: r.term.id, action, target, startAfter: !!opts.startAfter, done: false, ok: false, errors: 0, warnings: 0, started: Date.now() } };
      opts.onterm?.(r.term.id);
      this.watch(repoId, taskId, opts.onterm);
    } catch (e) { ui.error(e); }
  }
  private watch(repoId: string, taskId: string | null, onterm?: (id: string) => void) {
    const k = this.key(repoId, taskId);
    clearInterval(this.polls.get(k));
    const tick = async () => {
      const b = this.build[k];
      if (!b) return clearInterval(this.polls.get(k));
      try {
        const r = await get<{ done: boolean; ok: boolean; exitCode: number | null; problems: Problem[]; errors: number; warnings: number }>("dotnet/problems", { termId: b.termId });
        setBuildProblems(r.problems.map(p => ({ ...p, scope: k })));
        this.build = { ...this.build, [k]: { ...b, done: r.done, ok: r.ok, errors: r.errors, warnings: r.warnings } };
        if (!r.done) return;
        clearInterval(this.polls.get(k));
        const secs = Math.round((Date.now() - b.started) / 1000);
        const verb = { Build: "Compilação", Rebuild: "Recompilação", Clean: "Limpeza", Restore: "Restauração" }[b.action] || "Compilação";
        if (r.ok) {
          ui.toast(`${verb} concluída em ${secs} s${r.warnings ? ` · ${r.warnings} aviso(s)` : ""}`, "ok");
          if (b.startAfter) await this.start(repoId, taskId, onterm);
        } else ui.toast(`${verb} falhou: ${r.errors || "?"} erro(s)${r.warnings ? `, ${r.warnings} aviso(s)` : ""} — veja Problemas`, "error");
      } catch { clearInterval(this.polls.get(k)); }   // terminal fechado
    };
    this.polls.set(k, setInterval(tick, 1000));
  }
  /** Inicia sem compilar (os binários precisam existir). */
  async start(repoId: string, taskId: string | null, onterm?: (id: string) => void) {
    const c = this.choice(repoId);
    if (!c.startup.length) return ui.toast("Escolha o projeto de inicialização", "info");
    try {
      const r = await post<{ terms: { id: string }[]; urls: string[] }>("dotnet/start", { repoId, taskId, projects: c.startup, config: c.config, profile: c.profile });
      if (r.terms[0]) onterm?.(r.terms[0].id);
      for (const u of r.urls) setTimeout(() => window.open(u, "_blank"), 2500);   // o site leva uns segundos para subir
      ui.toast(r.terms.length > 1 ? `${r.terms.length} projetos iniciados` : "Iniciado", "ok");
    } catch (e) { ui.error(e); }
  }
  /** Para os projetos iniciados (Shift+F5) — fecha os terminais "▶" deste escopo. */
  async stop(terms: { id: string; meta: any }[]) {
    const running = terms.filter(t => String(t.meta?.dotnet || "").startsWith("start:"));
    for (const t of running) await post("terms/close", { id: t.id }).catch(() => {});
    if (running.length) ui.toast(running.length > 1 ? `${running.length} projetos parados` : "Parado");
    return running.map(t => t.id);
  }
}

export const dotnet = new Dotnet();
export const KIND_LABEL: Record<string, string> = { web: "Web", console: "Console", winexe: "Windows", library: "Biblioteca", test: "Testes" };
