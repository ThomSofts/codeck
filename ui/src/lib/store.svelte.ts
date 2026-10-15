import { get, post } from "./api";
import { prefs } from "./prefs.svelte";
import { syncTheme } from "./theme";
import type { AppState, PR, Source } from "./types";

// Estado global: o /api/state inteiro, relido a cada poucos segundos (mais rápido enquanto alguma fonte está lendo).
// Cada fonte (PRs, builds, deploys, issues) tem o próprio ciclo no backend; a tela mostra o "lendo/atualizado há"
// de cada uma no lugar dela, e "↻" relê só aquela.
class Store {
  s = $state<AppState | null>(null);
  error = $state<string | null>(null);
  /** contador de "não redesenhe agora" (menu aberto, paleta de comandos) — vale por pouco tempo: ver `held` */
  hold = $state(0);
  private heldSince = 0;
  /** segura a releitura enquanto houver menu aberto, mas nunca mais que 20 s: a lista não pode congelar */
  private get held() {
    if (!this.hold) { this.heldSince = 0; return false; }
    if (!this.heldSince) this.heldSince = Date.now();
    return Date.now() - this.heldSince < 20000;
  }
  /** "Atualizar" pedido à mão: fica true até o backend terminar a leitura que o pedido disparou */
  refreshing = $state(false);
  /** fase de cada voto em andamento, por PR: enviando → feito → saindo (a linha anima em cada uma) */
  votes = $state<Record<string, { vote: number; phase: "sending" | "done" | "leaving" | "error" }>>({});
  private timer: ReturnType<typeof setTimeout> | null = null;

  /** o sistema diz que não há rede (resposta imediata) — o backend confirma por `s.offline` na leitura seguinte */
  netDown = $state(typeof navigator !== "undefined" && navigator.onLine === false);
  get offline() { return this.netDown || !!this.s?.offline; }

  get ready() { return !!this.s; }
  /** o backend está lendo Azure/GitHub agora (ou o usuário acabou de pedir) */
  get fetching() { return this.refreshing || !!this.s?.polling; }
  /** fontes pedidas à mão (↻ de uma tela) ainda sem resposta */
  pending = $state<Partial<Record<Source, boolean>>>({});
  loadingOf(src: Source) { return !!this.s?.loading?.[src] || !!this.pending[src]; }
  updatedOf(src: Source) { return this.s?.updated?.[src] || null; }
  get anyLoading() { return (["prs", "builds", "deploys", "issues"] as Source[]).some(k => this.loadingOf(k)); }
  /** Relê uma fonte só (as outras seguem o próprio ciclo) e acompanha até terminar. */
  async refreshSource(src: Source) {
    if (this.pending[src]) return;
    const before = this.updatedOf(src);
    this.pending = { ...this.pending, [src]: true };
    try {
      await post("refresh", { source: src }, { quiet: true });
      for (let i = 0; i < 90; i++) {
        await new Promise(r => setTimeout(r, 1000));
        await this.load();
        if (!this.s?.loading?.[src] && this.updatedOf(src) !== before) break;
      }
    } finally { const p = { ...this.pending }; delete p[src]; this.pending = p; }
  }
  get prsReady() { return !!this.s?.lastPoll; }
  get buildsReady() { return !!this.s?.lastBuildPoll; }
  get deploysReady() { return !!this.s?.lastDeployPoll; }

  /** PRs que esperam o MEU voto (no GitHub, só as que pediram minha revisão) */
  get inbox(): PR[] {
    return (this.s?.prs || []).filter(p => !p.archived && p.myVote === 0 && (p.provider !== "github" || p.reviewRequested));
  }
  get deploysForMe() { return (this.s?.deploys || []); }
  get open(): PR[] { return (this.s?.prs || []).filter(p => !p.archived); }
  get archived(): PR[] { return (this.s?.prs || []).filter(p => p.archived); }

  async load() {
    try {
      // uma resposta presa não pode parar o ciclo da tela: desiste em 20 s e tenta de novo no próximo
      const s = await Promise.race([get<AppState>("state"),
        new Promise<never>((_, rej) => setTimeout(() => rej(new Error("o backend demorou para responder")), 20000))]);
      this.s = s;
      this.error = null;
      syncTheme(s.theme);
      prefs.sync(s.ui);
    } catch (e: any) {
      this.error = e.message || "backend fora do ar";
    }
  }

  start() {
    // rede caiu/voltou: o banner reage na hora; ao voltar, lê tudo sem esperar o próximo ciclo
    window.addEventListener("offline", () => (this.netDown = true));
    window.addEventListener("online", () => { this.netDown = false; this.refresh(); });
    const tick = async () => {
      if (!this.held) await this.load();
      // relê rápido até chegar o 1º dado e enquanto o backend estiver no meio de uma leitura (o indicador some na hora certa)
      // lendo alguma fonte: relê rápido (os dados de cada uma aparecem assim que ela termina); parado: a cada 6 s
      const fast = !this.s || !this.s.lastPoll || !this.s.lastBuildPoll || !this.s.lastDeployPoll || this.anyLoading;
      this.timer = setTimeout(tick, fast ? 1500 : 6000);
    };
    tick();
  }

  /** Lê tudo agora e acompanha até o backend terminar. Devolve false se demorar mais de 2 min. */
  async refresh() {
    if (this.refreshing) return true;
    this.refreshing = true;
    const since = { ...(this.s?.updated || {}) };
    try {
      await post("refresh");
      for (let i = 0; i < 120; i++) {
        await new Promise(r => setTimeout(r, 1000));
        await this.load();
        const u = this.s?.updated || {};
        if (this.s && !this.anyLoading && (["prs", "builds", "deploys"] as Source[]).every(k => u[k] !== since[k])) return true;
      }
      return false;
    } finally {
      this.refreshing = false;
    }
  }

  refreshSoon(ms = 400) {
    setTimeout(() => this.load(), ms);
  }
}

export const store = new Store();
