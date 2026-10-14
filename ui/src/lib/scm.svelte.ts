// Controle de código-fonte do projeto aberto (como o do VS Code): o `git status` do escopo (checkout principal ou
// worktree da tarefa) relido a cada poucos segundos enquanto a tela está à vista. Dele saem as cores e letras do
// explorador e das abas (M alterado, U novo, D apagado, A adicionado, R renomeado, ! conflito) e a contagem da
// barra de atividades.
import { get } from "./api";
import type { FileChange, RepoStatus } from "./types";

export type Decor = { letter: string; tone: "mod" | "add" | "del" | "ren" | "conf" | "ign"; label: string; staged: boolean };

const TONE: Record<string, [string, Decor["tone"], string]> = {
  M: ["M", "mod", "alterado"], T: ["M", "mod", "tipo alterado"], A: ["A", "add", "adicionado"], "?": ["U", "add", "novo (não rastreado)"],
  D: ["D", "del", "apagado"], R: ["R", "ren", "renomeado"], C: ["C", "ren", "copiado"], U: ["!", "conf", "conflito"],
};
const RANK: Record<Decor["tone"], number> = { conf: 5, del: 4, mod: 3, add: 2, ren: 2, ign: 0 };

class Scm {
  /** id do repositório do escopo (projeto ou worktree da tarefa) → status */
  status = $state<Record<string, RepoStatus | null>>({});
  error = $state<Record<string, string | null>>({});
  private timers = new Map<string, { n: number; t: ReturnType<typeof setInterval> }>();
  private inflight = new Set<string>();

  async load(repoId: string) {
    if (!repoId || this.inflight.has(repoId)) return;
    this.inflight.add(repoId);
    try {
      const s = await get<RepoStatus>("repo/status", { id: repoId });
      if (JSON.stringify(s) !== JSON.stringify(this.status[repoId])) this.status = { ...this.status, [repoId]: s };
      if (this.error[repoId]) this.error = { ...this.error, [repoId]: null };
    } catch (e: any) { this.error = { ...this.error, [repoId]: e.message || String(e) }; }
    finally { this.inflight.delete(repoId); }
  }
  /** Acompanha o escopo enquanto alguém o mostra (contagem de referências). Devolve a função que para. */
  watch(repoId: string) {
    const cur = this.timers.get(repoId);
    if (cur) cur.n++;
    else {
      this.load(repoId);
      this.timers.set(repoId, { n: 1, t: setInterval(() => { if (document.visibilityState === "visible") this.load(repoId); }, 4000) });
    }
    return () => {
      const x = this.timers.get(repoId);
      if (!x) return;
      if (--x.n <= 0) { clearInterval(x.t); this.timers.delete(repoId); }
    };
  }
  /** Alguém mudou algo (salvou, stage, commit): relê já. */
  touch(repoId: string | null | undefined) { if (repoId) setTimeout(() => this.load(repoId), 150); }

  /** path → decoração (o estado mais "forte" entre preparado e não preparado). */
  map(repoId: string | null | undefined): Map<string, Decor> {
    const s = repoId ? this.status[repoId] : null;
    const out = new Map<string, Decor>();
    if (!s) return out;
    const put = (f: FileChange, staged: boolean) => {
      const t = TONE[f.status] || ["M", "mod", f.status];
      const d: Decor = { letter: t[0], tone: t[1], label: t[2] + (staged ? " · preparado" : ""), staged };
      const prev = out.get(f.path);
      if (!prev || RANK[d.tone] > RANK[prev.tone] || (!staged && prev.staged && RANK[d.tone] === RANK[prev.tone])) out.set(f.path, d);
    };
    for (const f of s.staged) put(f, true);
    for (const f of s.unstaged) put(f, false);
    for (const f of s.untracked) put(f, false);
    for (const f of s.conflicts) put(f, false);
    return out;
  }
  count(repoId: string | null | undefined) {
    const s = repoId ? this.status[repoId] : null;
    return s ? new Set([...s.staged, ...s.unstaged, ...s.untracked, ...s.conflicts].map(f => f.path)).size : 0;
  }
}

/** Pasta → a decoração mais forte entre os arquivos dela (o explorador pinta a pasta como o VS Code). */
export function folderDecor(map: Map<string, Decor>): Map<string, Decor["tone"]> {
  const out = new Map<string, Decor["tone"]>();
  for (const [p, d] of map) {
    const parts = p.split("/");
    let acc = "";
    for (let i = 0; i < parts.length - 1; i++) {
      acc += parts[i] + "/";
      const prev = out.get(acc);
      if (!prev || RANK[d.tone] > RANK[prev]) out.set(acc, d.tone === "del" ? "mod" : d.tone);
    }
  }
  return out;
}

export const scm = new Scm();
