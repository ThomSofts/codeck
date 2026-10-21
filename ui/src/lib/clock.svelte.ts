// Relógio da tela: um tique a cada 30 s (e quando a janela volta ao foco) faz os "há 3 min" andarem sozinhos,
// sem cada lista ter o próprio timer.
import { ago } from "./format";

class Clock {
  now = $state(Date.now());
  constructor() {
    if (typeof window === "undefined") return;
    setInterval(() => (this.now = Date.now()), 30_000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) this.now = Date.now(); });
  }
  /** `ago` que se atualiza: lê `now`, então quem chama dentro do template é redesenhado a cada tique */
  ago(iso?: string | null) { void this.now; return ago(iso); }
}

export const clock = new Clock();
