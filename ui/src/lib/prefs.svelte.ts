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
  /** fonte do editor (vazio = JetBrains Mono embutida); qualquer fonte instalada no sistema vale */
  "editor.fontFamily": "" as string,
  "editor.ligatures": false,
  /** 0 = detecta pelo arquivo */
  "editor.tabSize": 0,
  "editor.renderWhitespace": "selection" as "none" | "boundary" | "selection" | "all",
  "editor.cursorStyle": "line" as "line" | "block" | "underline",
  "editor.cursorBlinking": "smooth" as "blink" | "smooth" | "phase" | "expand" | "solid",
  "editor.bracketPairs": true,
  /** dicas inline do servidor de linguagem (nome do parâmetro, tipo): segurando ⌃⌥ (como o VS Code), sempre ou nunca */
  "editor.inlayHints": "offUnlessPressed" as "on" | "off" | "offUnlessPressed" | "onUnlessPressed",
  /** "N referências" em cima de classes, funções e métodos (servidor de linguagem) */
  "editor.codeLens": true,
  "editor.gitGutter": true,
  "editor.formatOnSave": false,
  "editor.autoSave": "off" as "off" | "afterDelay" | "onFocusChange",
  /** tema de cores e de ícones vindos de extensões do VS Code ("" = o do Codeck) */
  "workbench.colorTheme": "" as string,
  "workbench.iconTheme": "" as string,
  /** o tema de cores da extensão pinta o app inteiro (barra lateral, painéis), não só o editor */
  "workbench.themeApp": true,
  /** extensões desligadas no Codeck (snippets e linguagens delas não entram) */
  "ext.disabled": [] as string[],
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
  /** avisos por tipo: aviso do sistema e som (Configurações → Notificações; lib/alerts) */
  "alerts": {} as Record<string, { os?: boolean; sound?: string }>,
  /** volume dos sons dos avisos (0 a 1) e mudo geral */
  "alerts.volume": 0.6,
  "alerts.mute": false,
  /** hub de projetos: ordem e agrupamento lembrados */
  "hub.sort": "recent" as string,
  "hub.group": "none" as string,
  /** cartões ou lista densa; "auto" = lista quando há muitos repositórios */
  "hub.view": "auto" as "auto" | "grid" | "list",
  /** projetos fixados no topo do hub (ids dos repositórios locais) */
  "hub.pinned": [] as string[],
  /** seções recolhidas do hub (chave da seção, por agrupamento) */
  "hub.collapsed": [] as string[],
  /** densidade da interface */
  "ui.density": "comfortable" as "comfortable" | "compact",
  /** abrir o último projeto ao iniciar */
  "work.reopenLast": true,
  /** tela bloqueada/protetor de tela/ocioso: continuar trabalhando, só com algo rodando, ou pausar a automação */
  "power.mode": "keep" as "keep" | "busy" | "pause",
  /** manter os ajustes do editor sincronizados com o settings.json do VS Code/Cursor ("" = não) */
  "vscode.sync": "" as "" | "VS Code" | "Cursor",
  /** assinatura dos ajustes do VS Code na última sincronização (para só importar quando mudarem lá) */
  "vscode.syncSig": "" as string,
  /** atalhos personalizados (Configurações → Atalhos): id do comando → atalhos; lista vazia = sem atalho */
  "keybindings": {} as Record<string, string[]>,
  /** a mesma pessoa com nomes diferentes em cada conta (ex.: "Leonardo" = "Leonardo Thomaz" na Cifal e "leonardo.thomaz"
   *  na Dematec): o filtro de responsável junta todos — nome → nomes, logins ou e-mails */
  "people": {} as Record<string, string[]>,
  /** Issues e tarefas: escopo, estado e responsável escolhidos por último */
  "issues.scope": "mine" as string,
  "issues.state": "open" as string,
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
  private listeners: ((k: PrefKey) => void)[] = [];
  /** Avisa quando uma preferência muda por aqui (ex.: sincronizar com o VS Code). */
  onChange(fn: (k: PrefKey) => void) { this.listeners.push(fn); }
  /** Muda na hora (tela reage) e grava em lote logo depois. */
  set<K extends PrefKey>(k: K, v: PrefValue<K> | null) {
    if (v === null) { const { [k]: _, ...rest } = this.values; this.values = rest; }
    else this.values = { ...this.values, [k]: v };
    this.pending[k] = v;
    for (const fn of this.listeners) { try { fn(k); } catch { /* quem escuta não derruba o ajuste */ } }
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
    try { await post("prefs", { ui }, { quiet: true }); } catch { /* fica valendo na tela; grava na próxima mudança */ }
  }
}

export const prefs = new Prefs();
