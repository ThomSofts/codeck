import { post } from "./api";
import { store } from "./store.svelte";
import { ui } from "./ui.svelte";
import type { CascadeItem, CascadeStatus, PR } from "./types";

// Acompanhar em cascata: as PRs seguidas até o deploy vêm no /api/state (s.cascade). Aqui ficam as ações e o estado
// da doca (o painel flutuante que mostra os acompanhamentos em qualquer tela).
class Cascade {
  /** doca aberta e o item em destaque (notificação clicada, clique na barra lateral) */
  open = $state(false);
  focus = $state<string | null>(null);

  get items(): CascadeItem[] { return store.s?.cascade || []; }
  get active(): CascadeItem[] { return this.items.filter(i => i.stage !== "finished"); }
  /** em execução de verdade: build/deploy, ou o merge já andando. PR aprovada esperando o autor completar não conta —
   *  com aprovação automática, dezenas ficam dias nessa espera e o contador dizia "31" com 1 rodando */
  get running(): CascadeItem[] { return this.active.filter(i => i.stage !== "merge" || i.steps?.merge?.status === "running"); }
  get waiting(): CascadeItem[] { return this.active.filter(i => !this.running.includes(i)); }
  of(key: string) { return this.items.find(i => i.key === key) || null; }

  show(key?: string | null) { this.open = true; this.focus = key || null; }

  async follow(pr: PR) {
    try {
      await post("cascade/follow", { key: pr.key });
      ui.toast("Acompanhando até o deploy — merge, build e deploy aparecem aqui e nas notificações");
      await store.load();
      this.show(pr.key);
    } catch (e) { ui.error(e); }
  }

  async stop(key: string) {
    try { await post("cascade/stop", { key }); await store.load(); } catch (e) { ui.error(e); }
  }
}

export const cascade = new Cascade();

export const STEP_LABEL: Record<string, string> = { approved: "Aprovada", merge: "Merge", build: "Build", deploy: "Deploy" };
export const STATUS_TEXT: Record<CascadeStatus, string> = {
  pending: "a seguir", waiting: "aguardando", running: "em andamento", done: "feito", failed: "falhou", skipped: "pulado",
};
export const RESULT_TEXT: Record<string, string> = {
  succeeded: "Concluído", failed: "Falhou", abandoned: "PR fechada sem merge", timeout: "Encerrado por tempo",
};
