import { post } from "./api";

// Preferências da tela (editor, terminal, barra lateral, Markdown, IA…). Ficam no config.json do backend (chave "ui"),
// então sobrevivem a reinstalar o app e valem para todas as janelas. Chegam junto com o /api/state; enquanto não
// chegam, valem os padrões abaixo.
export const PREF_DEFAULTS = {
  /** barra lateral só com ícones (menus viram popover) */
  "sidebar.collapsed": false,
  /** projetos abertos listados na barra lateral (além do hub) */
  "sidebar.openProjects": true,
  /** Markdown abre em: pré-visualização, código ou lado a lado */
  "md.mode": "preview" as "preview" | "code" | "split",
  "editor.fontSize": 13,
  "editor.minimap": true,
  "editor.wordWrap": false,
  "editor.lineNumbers": true,
  "editor.stickyScroll": true,
  "terminal.fontSize": 13,
  "terminal.scrollback": 10000,
  "terminal.cursorBlink": true,
  /** lê o limite das contas do Claude sem abrir sessão (sonda mínima no Haiku), de tempos em tempos */
  "ai.autoLimits": true,
  "ai.autoLimitsMinutes": 60,
  /** modo padrão do agente ao pedir para a IA: planejar, planejar e implementar, implementar direto */
  "ai.defaultFlow": "plan-implement" as "plan" | "plan-implement" | "implement",
  /** avisos do agente */
  "notify.agentDone": true,
  "notify.agentNeedsYou": true,
  /** hub de projetos: ordem e agrupamento lembrados */
  "hub.sort": "recent" as string,
  "hub.group": "none" as string,
  "hub.view": "grid" as "grid" | "list",
  /** densidade da interface */
  "ui.density": "comfortable" as "comfortable" | "compact",
  /** abrir o último projeto ao iniciar */
  "work.reopenLast": true,
};
export type PrefKey = keyof typeof PREF_DEFAULTS;
type PrefValue<K extends PrefKey> = (typeof PREF_DEFAULTS)[K];

class Prefs {
  values = $state<Record<string, any>>({});
  private pending: Record<string, any> = {};
  private timer: ReturnType<typeof setTimeout> | null = null;

  get<K extends PrefKey>(k: K): PrefValue<K> {
    const v = this.values[k];
    return (v === undefined ? PREF_DEFAULTS[k] : v) as PrefValue<K>;
  }
  /** Muda na hora (tela reage) e grava em lote logo depois. */
  set<K extends PrefKey>(k: K, v: PrefValue<K> | null) {
    if (v === null) { const { [k]: _, ...rest } = this.values; this.values = rest; }
    else this.values = { ...this.values, [k]: v };
    this.pending[k] = v;
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), 300);
  }
  /** O /api/state trouxe as preferências gravadas: só aplica as que não estão para ser gravadas agora. */
  sync(ui: Record<string, any> | undefined) {
    if (!ui) return;
    const next = { ...ui };
    for (const k of Object.keys(this.pending)) { if (this.pending[k] === null) delete next[k]; else next[k] = this.pending[k]; }
    if (JSON.stringify(next) !== JSON.stringify(this.values)) this.values = next;
  }
  private async flush() {
    const ui = this.pending;
    this.pending = {};
    try { await post("prefs", { ui }); } catch { /* fica valendo na tela; grava na próxima mudança */ }
  }
}

export const prefs = new Prefs();
