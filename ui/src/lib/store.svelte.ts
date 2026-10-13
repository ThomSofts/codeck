import { get, post } from "./api";
import { prefs } from "./prefs.svelte";
import { syncTheme } from "./theme";
import type { AppState, PR } from "./types";

// Estado global: o /api/state inteiro, relido a cada 15 s (mais rápido até chegar o 1º dado do Azure/GitHub).
class Store {
  s = $state<AppState | null>(null);
  error = $state<string | null>(null);
  /** contador de "não redesenhe agora" (menu aberto, diálogo, edição) */
  hold = $state(0);
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
      const s = await get<AppState>("state");
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
      if (!this.hold) await this.load();
      // relê rápido até chegar o 1º dado e enquanto o backend estiver no meio de uma leitura (o indicador some na hora certa)
      const fast = !this.s || !this.s.lastPoll || !this.s.lastBuildPoll || !this.s.lastDeployPoll || !!this.s.polling;
      this.timer = setTimeout(tick, fast ? 1500 : 15000);
    };
    tick();
  }

  /** Lê tudo agora e acompanha até o backend terminar. Devolve false se demorar mais de 2 min. */
  async refresh() {
    if (this.refreshing) return true;
    this.refreshing = true;
    const since = this.s?.lastPoll;
    try {
      await post("refresh");
      for (let i = 0; i < 120; i++) {
        await new Promise(r => setTimeout(r, 1000));
        await this.load();
        if (this.s && !this.s.polling && this.s.lastPoll !== since) return true;
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
