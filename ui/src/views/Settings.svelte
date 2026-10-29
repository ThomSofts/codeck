<script lang="ts">
  // Configurações: contas (Azure DevOps, GitHub, IA) e as preferências do app — aparência, editor, terminal, projetos,
  // agentes, notificações, leitura, atalhos e dados. A busca do menu filtra os ajustes de todas as seções.
  // Segredos (PAT/token) só vão para o servidor local, que os guarda no cofre do sistema — nunca voltam para a tela.
  // Preferências da tela (lib/prefs) gravam na hora; as do backend (tema, editor, intervalo, avisos) também.
  import { Bell, Bot, Check, ClipboardCopy, Code2, Database, ExternalLink, FolderGit2, FolderOpen, Info, Keyboard, KeyRound, LogIn, Monitor,
    Moon, Palette, Plus, RefreshCw, Search, Shield, Sparkles, SquareTerminal, Sun, Terminal, Trash2, Wifi, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { get, post } from "../lib/api";
  import { applyDensity, type Density } from "../lib/density";
  import { dateTime } from "../lib/format";
  import { isMac, kbd } from "../lib/keys";
  import Keybindings from "../components/settings/Keybindings.svelte";
  import Alerts from "../components/settings/Alerts.svelte";
  import { ALERT_DEFS } from "../lib/alerts.svelte";
  import People from "../components/settings/People.svelte";
  import { PREF_DEFAULTS, prefs, type PrefKey } from "../lib/prefs.svelte";
  import { go, router } from "../lib/router.svelte";
  import { store } from "../lib/store.svelte";
  import type { Source } from "../lib/types";
  import { ui } from "../lib/ui.svelte";
  import Avatar from "../components/Avatar.svelte";
  import Page from "../components/Page.svelte";
  import ProviderIcon from "../components/ProviderIcon.svelte";
  import Skeleton from "../components/Skeleton.svelte";
  import Switch from "../components/Switch.svelte";
  import Segmented from "../components/Segmented.svelte";
  import AiAccounts from "../components/settings/AiAccounts.svelte";
  import { extensions } from "../lib/extensions.svelte";
  import { repos } from "../lib/repos.svelte";
  import TestResult from "../components/TestResult.svelte";
  import { chooseTheme, type ThemePref } from "../lib/theme";
  import { send } from "../lib/native";

  type OrgForm = { name: string; url: string; pat: string; enabled: boolean; originalName?: string; hasPat?: boolean; patStore?: string; me?: any; test?: any };
  type SecId = "accounts" | "github" | "ai" | "appearance" | "editor" | "terminal" | "projects" | "agents" | "notifications" | "network" | "shortcuts" | "data" | "about";
  type Sec = { id: SecId; label: string; icon?: any; provider?: "azure" | "github"; title: string; desc: string };

  const OS = isMac() ? "macOS" : "Windows";
  const GROUPS: { label: string; items: Sec[] }[] = [
    { label: "Contas", items: [
      { id: "accounts", label: "Azure DevOps", provider: "azure", title: "Organizações do Azure DevOps", desc: "PRs, builds, releases, aprovações de deploy e work items." },
      { id: "github", label: "GitHub", provider: "github", title: "Contas do GitHub", desc: "Pessoais, organizações e repositórios de terceiros a que o perfil tem acesso — PRs, Actions, issues e deploys." },
      { id: "ai", label: "IA", icon: Bot, title: "Contas de IA", desc: "" },
    ] },
    { label: "Aplicativo", items: [
      { id: "appearance", label: "Aparência", icon: Palette, title: "Aparência", desc: "Tema, densidade e barra lateral." },
      { id: "editor", label: "Editor", icon: Code2, title: "Editor", desc: "O editor de código dos projetos (o mesmo do VS Code) e o editor externo." },
      { id: "terminal", label: "Terminal", icon: SquareTerminal, title: "Terminal", desc: "Terminais e agentes dos projetos. Vale também para os que já estão abertos." },
      { id: "projects", label: "Projetos", icon: FolderGit2, title: "Projetos", desc: "Como os projetos abrem." },
      { id: "agents", label: "IA e agentes", icon: Sparkles, title: "IA e agentes", desc: "Limites das contas e o que a IA faz quando você pede uma tarefa." },
    ] },
    { label: "Sistema", items: [
      { id: "notifications", label: "Notificações e sons", icon: Bell, title: "Notificações e sons", desc: `Escolha, para cada tipo de aviso, se ele aparece na Central de Notificações do ${OS} e qual som toca.` },
      { id: "network", label: "Leitura e automação", icon: Wifi, title: "Leitura e automação", desc: "Com que frequência o app consulta Azure e GitHub e se as regras agem sozinhas." },
      { id: "shortcuts", label: "Atalhos", icon: Keyboard, title: "Atalhos de teclado", desc: `Mostrados no formato do ${OS} — ${isMac() ? "⌘ ⇧ ⌥" : "Ctrl, Shift, Alt"}. No ${isMac() ? "Windows" : "macOS"} o app mostra ${isMac() ? "Ctrl" : "⌘"} automaticamente.` },
      { id: "data", label: "Dados e privacidade", icon: Database, title: "Dados e privacidade", desc: "Onde o app guarda tudo e como protege suas credenciais." },
      { id: "about", label: "Sobre", icon: Info, title: store.s?.app.product || "Codeck", desc: "" },
    ] },
  ];
  const SECS = GROUPS.flatMap(g => g.items);
  const ALIAS: Record<string, SecId> = { prefs: "appearance" };   // links antigos (#/settings/prefs)
  const tab = $derived<SecId>(ALIAS[router.param] || (SECS.some(s => s.id === router.param) ? router.param as SecId : "accounts"));
  const sec = $derived(SECS.find(s => s.id === tab)!);

  // ------------------------------------------------------------ linhas de ajuste (também o índice da busca)
  type Opt = { value: string; label: string; icon?: any };
  type Row = { sec: SecId; id: string; label: string; desc?: string; kw?: string;
    kind: "pref-switch" | "pref-select" | "pref-seg" | "pref-text" | "rule-switch" | "auto" | "theme" | "ext-theme" | "ext-icons" | "vscode-import" | "vscode-sync" | "ext-editor" | "poll" | "poll-adaptive" | "live" | "note" | "data-dir" | "diag" | "security" | "link";
    key?: string; options?: Opt[]; when?: () => boolean };
  const sizes = (a: number, b: number) => Array.from({ length: b - a + 1 }, (_, i) => ({ value: String(a + i), label: `${a + i} px` }));
  const ROWS: Row[] = [
    // aparência
    { sec: "appearance", id: "theme", kind: "theme", label: "Tema", desc: `“Sistema” acompanha o claro/escuro do ${OS} e troca sozinho.`, kw: "escuro claro dark light cor" },
    { sec: "appearance", id: "colorTheme", kind: "ext-theme", label: "Tema de cores", desc: "Os temas do VS Code desta máquina (os seus e os que vêm com ele) e os instalados pelo Codeck. Pinta o editor, o terminal e — se ligado abaixo — o app inteiro.", kw: "vscode extensão tema cor dark+ monokai dracula one dark ayu" },
    { sec: "appearance", id: "themeApp", kind: "pref-switch", key: "workbench.themeApp", label: "O tema de cores pinta o app inteiro", desc: "Desligado, o tema vale só no editor e no terminal; o resto segue Sistema/Escuro/Claro.", kw: "vscode tema app" },
    { sec: "appearance", id: "iconTheme", kind: "ext-icons", label: "Tema de ícones", desc: "Ícones de arquivo e pasta do explorador, das abas e do ⌘P (Material Icon Theme, vscode-icons, Seti…).", kw: "vscode extensão ícone material seti" },
    { sec: "appearance", id: "vscodeImport", kind: "vscode-import", label: "Usar a aparência do VS Code", desc: "Lê as configurações do VS Code/Cursor desta máquina: tema, ícones, fonte, tamanho, ligaduras, tabulação, salvar automático.", kw: "vscode cursor importar configurações" },
    { sec: "appearance", id: "vscodeSync", kind: "vscode-sync", label: "Manter sincronizado com o VS Code", desc: "Fonte, tamanho, tabulação, salvar automático, tema e ícones: o que mudar no VS Code vem para cá ao abrir o app; o que mudar aqui vai para o settings.json dele. As configurações de execução (launch.json) sincronizam por projeto, em Executar e depurar.", kw: "vscode cursor sincronizar levar exportar settings.json" },
    { sec: "appearance", id: "extLink", kind: "note", label: "Extensões", desc: "Instale temas, ícones e snippets do marketplace aberto (Open VSX) no painel Extensões do projeto (ícone de blocos na barra da esquerda).", kw: "extensão marketplace open vsx instalar" },
    { sec: "appearance", id: "density", kind: "pref-seg", key: "ui.density", label: "Densidade", desc: "Compacta diminui alturas e espaçamentos — cabe mais na tela.",
      options: [{ value: "comfortable", label: "Confortável" }, { value: "compact", label: "Compacta" }], kw: "tamanho espaço compacto" },
    { sec: "appearance", id: "sidebar", kind: "pref-switch", key: "sidebar.collapsed", label: "Barra lateral recolhida", desc: `Só os ícones; os menus abrem por cima. Atalho: ${kbd("mod+\\")}.`, kw: "menu aside retrair" },
    { sec: "appearance", id: "openProjects", kind: "pref-switch", key: "sidebar.openProjects", label: "Projetos abertos na barra lateral", desc: "Lista os projetos abertos abaixo de “Projetos”, para trocar rápido.", kw: "abas menu" },
    // editor
    { sec: "editor", id: "edFont", kind: "pref-select", key: "editor.fontSize", label: "Tamanho da fonte", options: sizes(11, 20), kw: "letra zoom" },
    { sec: "editor", id: "edFamily", kind: "pref-text", key: "editor.fontFamily", label: "Fonte", desc: "Qualquer fonte instalada no sistema (Fira Code, Cascadia Code, JetBrains Mono, SF Mono, Consolas…). Vazio = JetBrains Mono.", kw: "fonte font family letra" },
    { sec: "editor", id: "ligatures", kind: "pref-switch", key: "editor.ligatures", label: "Ligaduras", desc: "=> != === viram um símbolo só (precisa de uma fonte com ligaduras, como Fira Code ou Cascadia Code).", kw: "ligatures fira" },
    { sec: "editor", id: "tabSize", kind: "pref-select", key: "editor.tabSize", label: "Tabulação",
      options: [{ value: "0", label: "Detectar pelo arquivo" }, { value: "2", label: "2 espaços" }, { value: "4", label: "4 espaços" }, { value: "8", label: "8 espaços" }], kw: "tab indentação espaços" },
    { sec: "editor", id: "cursor", kind: "pref-seg", key: "editor.cursorStyle", label: "Cursor", options: [{ value: "line", label: "Linha" }, { value: "block", label: "Bloco" }, { value: "underline", label: "Sublinhado" }], kw: "cursor caret" },
    { sec: "editor", id: "blinking", kind: "pref-select", key: "editor.cursorBlinking", label: "Animação do cursor",
      options: [{ value: "smooth", label: "Suave" }, { value: "blink", label: "Piscar" }, { value: "phase", label: "Fase" }, { value: "expand", label: "Expandir" }, { value: "solid", label: "Fixo" }], kw: "cursor piscar" },
    { sec: "editor", id: "whitespace", kind: "pref-select", key: "editor.renderWhitespace", label: "Mostrar espaços",
      options: [{ value: "none", label: "Nunca" }, { value: "boundary", label: "Nas bordas" }, { value: "selection", label: "Na seleção" }, { value: "all", label: "Sempre" }], kw: "whitespace espaço tab" },
    { sec: "editor", id: "inlay", kind: "pref-seg", key: "editor.inlayHints", label: "Dicas inline", desc: `Nome do parâmetro e tipo inferido, do servidor de linguagem. "Segurando" = aparecem com ${isMac() ? "⌃⌥" : "Ctrl+Alt"} pressionados, como no VS Code.`,
      options: [{ value: "offUnlessPressed", label: "Segurando" }, { value: "on", label: "Sempre" }, { value: "off", label: "Nunca" }], kw: "inlay hints parametro tipo" },
    { sec: "editor", id: "codeLens", kind: "pref-switch", key: "editor.codeLens", label: "Contagem de referências", desc: "\"N referências\" em cima de classes, funções e métodos; clicar lista onde são usados.", kw: "codelens referências references" },
    { sec: "editor", id: "brackets", kind: "pref-switch", key: "editor.bracketPairs", label: "Colchetes coloridos", desc: "Cada par de ( ) [ ] { } numa cor, como no VS Code.", kw: "bracket pair colorization" },
    { sec: "editor", id: "gutter", kind: "pref-switch", key: "editor.gitGutter", label: "Alterações do Git na margem", desc: "Faixa verde (novo), azul (alterado) e o triângulo vermelho (apagado) ao lado dos números de linha.", kw: "git gutter diff margem" },
    { sec: "editor", id: "formatSave", kind: "pref-switch", key: "editor.formatOnSave", label: "Formatar ao salvar", desc: "Usa o formatador do servidor de linguagem (ou do Monaco) a cada ⌘S.", kw: "format prettier salvar" },
    { sec: "editor", id: "autoSave", kind: "pref-select", key: "editor.autoSave", label: "Salvar automaticamente",
      options: [{ value: "off", label: "Não" }, { value: "afterDelay", label: "1 s depois de parar de digitar" }, { value: "onFocusChange", label: "Ao sair do editor" }], kw: "auto save salvar" },
    { sec: "editor", id: "minimap", kind: "pref-switch", key: "editor.minimap", label: "Minimapa", desc: "A miniatura do arquivo à direita do editor." },
    { sec: "editor", id: "wrap", kind: "pref-switch", key: "editor.wordWrap", label: "Quebra de linha", desc: "Linhas longas continuam na linha de baixo em vez de rolar para o lado.", kw: "word wrap" },
    { sec: "editor", id: "lineNumbers", kind: "pref-switch", key: "editor.lineNumbers", label: "Números de linha" },
    { sec: "editor", id: "sticky", kind: "pref-switch", key: "editor.stickyScroll", label: "Cabeçalho fixo ao rolar", desc: "Mostra a classe/função em que você está no topo do editor (sticky scroll).", kw: "sticky scroll" },
    { sec: "editor", id: "md", kind: "pref-seg", key: "md.mode", label: "Markdown abre em", desc: `Arquivos .md (roteiros de teste, README…). Na pré-visualização dá para marcar os checkboxes. Alterne com ${kbd("mod+shift+v")}.`,
      options: [{ value: "preview", label: "Visualização" }, { value: "code", label: "Código" }, { value: "split", label: "Lado a lado" }], kw: "md markdown renderizado preview checkbox" },
    { sec: "editor", id: "extEditor", kind: "ext-editor", label: "Editor externo", desc: "Usado em “Abrir no editor” nos repositórios.", kw: "vscode cursor rider" },
    // terminal
    { sec: "terminal", id: "termFont", kind: "pref-select", key: "terminal.fontSize", label: "Tamanho da fonte", options: sizes(10, 20), kw: "letra zoom" },
    { sec: "terminal", id: "scrollback", kind: "pref-select", key: "terminal.scrollback", label: "Linhas de histórico", desc: "Quanto dá para rolar para cima em cada terminal.",
      options: [1000, 5000, 10000, 50000].map(n => ({ value: String(n), label: `${n.toLocaleString("pt-BR")} linhas` })), kw: "scrollback buffer" },
    { sec: "terminal", id: "blink", kind: "pref-switch", key: "terminal.cursorBlink", label: "Cursor piscando" },
    // projetos
    { sec: "projects", id: "reopen", kind: "pref-switch", key: "work.reopenLast", label: "Reabrir o último projeto ao iniciar", desc: "Ao abrir o app, já entra no projeto em que você estava." },
    { sec: "projects", id: "projNote", kind: "note", label: "Ajustes de cada projeto",
      desc: "Arquivos copiados para os worktrees (workspace.local.json, .env…), script de preparação, pasta dos worktrees, pastas extras e shell ficam na engrenagem do projeto (aba do projeto → clique direito → Ajustes do projeto).", kw: "worktree copiar preparação shell" },
    { sec: "projects", id: "dirsNote", kind: "note", label: "Pastas dos clones", desc: "Ficam em cada conta: Repositórios → Contas → “⋯” → Pastas base.", kw: "clonar pasta base" },
    // agentes
    { sec: "agents", id: "autoLimits", kind: "pref-switch", key: "ai.autoLimits", label: "Ler os limites das contas automaticamente",
      desc: "Para contas do Claude sem leitura recente, o app manda um pedido mínimo ao Haiku (cerca de US$ 0,002, um tiquinho do limite) e lê o uso de 5 h e semanal da resposta. Nunca lê token: quem fala com a Anthropic é a própria CLI.", kw: "limite uso 5h semanal claude" },
    { sec: "agents", id: "autoLimitsMin", kind: "pref-select", key: "ai.autoLimitsMinutes", label: "A cada", when: () => !!prefs.get("ai.autoLimits"),
      options: [30, 60, 120, 240].map(n => ({ value: String(n), label: n < 60 ? `${n} min` : `${n / 60} h` })), kw: "intervalo limite" },
    { sec: "agents", id: "flow", kind: "pref-select", key: "ai.defaultFlow", label: "Ao pedir uma tarefa para a IA",
      desc: "O padrão de “Pedir à IA” no projeto, nas issues e no quadro — dá para trocar em cada pedido.",
      options: [{ value: "plan", label: "Só planejar" }, { value: "plan-implement", label: "Planejar → você aprova → implementa" }, { value: "implement", label: "Implementar direto" }],
      kw: "planejar implementar plano modo" },
    { sec: "agents", id: "aiAccounts", kind: "link", label: "Contas de IA", desc: "Claude Code, Codex, Cursor… e a conta padrão de cada organização.", key: "ai", kw: "claude codex cursor gemini conta" },
    // notificações
    // notificações: a tela própria (components/settings/Alerts) — estas linhas só servem para a busca achar
    ...ALERT_DEFS.map(d => ({ sec: "notifications" as SecId, id: "a-" + d.kind, kind: "link" as const, key: "notifications", label: d.label, desc: d.desc,
      kw: "notificação som aviso alerta volume " + d.kind })),
    { sec: "notifications", id: "aSounds", kind: "link", key: "notifications", label: "Sons dos avisos", desc: "Volume, mudo e o som de cada tipo de aviso.", kw: "som volume mudo silenciar áudio" },
    // leitura e automação
    { sec: "network", id: "live", kind: "live", label: "Tempo real (local)", desc: "Vigia os repositórios ativos (projetos abertos, suas PRs, revisões pedidas e PRs acompanhadas até o deploy) a cada poucos segundos e relê só o que mudou. Roda inteiro nesta máquina, com o seu PAT/login do GitHub: nada vai para outro servidor além do próprio GitHub e Azure DevOps. No GitHub usa ETag — “nada mudou” não gasta a cota. Espaça com a janela escondida ou na economia de bateria e para com a tela bloqueada.", kw: "tempo real live realtime vigiar etag local webhook rápido" },
    { sec: "network", id: "poll", kind: "poll", label: "Intervalo de leitura", desc: "De quanto em quanto tempo o piloto consulta Azure e GitHub — cada tipo no seu ritmo (as regras automáticas rodam junto com PRs e deploys). Sem internet, tenta a cada 10 s; com o limite de chamadas no fim, espera a conta liberar.", kw: "polling atualizar intervalo prs builds deploys issues tarefas tempo real" },
    { sec: "network", id: "pollAdaptive", kind: "poll-adaptive", label: "Ritmo automático", desc: "Com build rodando ou deploy em andamento, lê mais rápido (20–30 s); com a janela escondida ou a tela bloqueada, espaça (até 3×) e, ao voltar, relê na hora o que ficou velho. Contas do GitHub também avisam mudanças pelas notificações (sem gastar cota).", kw: "adaptativo foco economia tempo real notificações" },
    { sec: "network", id: "cascade", kind: "rule-switch", key: "cascadeOnApprove", label: "Ao aprovar uma PR, acompanhar até o deploy", desc: "Segue a PR em poucos segundos: merge → build do commit integrado → deploy (environments do GitHub, estágios do YAML ou releases do Azure). Vale para a sua aprovação e a das regras. Em qualquer PR dá para começar à mão.", kw: "cascata seguir merge build deploy tempo real acompanhar" },
    { sec: "network", id: "auto", kind: "auto", label: "Automação ativa", desc: "Desligada, nenhuma regra aprova ou arquiva nada sozinha — a tela continua igual.", kw: "pausar regras piloto" },
    { sec: "network", id: "power", kind: "pref-select", key: "power.mode", label: "Com a tela bloqueada, protetor de tela ou o computador ocioso",
      desc: `Continuar: o ${OS} não suspende por ociosidade enquanto o app estiver aberto (o monitor apaga normalmente) — agentes, execuções, regras e o quadro seguem. Só com algo rodando: o mesmo, enquanto houver agente trabalhando, projeto executando ou regra ativa. Pausar: deixa o computador dormir e retoma ao desbloquear. Ao acordar, tudo é relido na hora.${isMac() ? " Com a tampa fechada na bateria, o Mac dorme de qualquer jeito." : ""}`,
      options: [{ value: "keep", label: "Continuar trabalhando" }, { value: "busy", label: "Continuar só com algo rodando" }, { value: "pause", label: "Pausar a automação" }],
      kw: "suspender dormir sleep protetor tela bloqueio ocioso energia app nap acordado" },
    { sec: "network", id: "resurface", kind: "rule-switch", key: "resurfaceOnPush", label: "PR arquivada volta com push novo", desc: "Se a PR que você arquivou receber commits, ela volta para a fila.", kw: "arquivar" },
    // dados
    { sec: "data", id: "dataDir", kind: "data-dir", label: "Pasta de dados", kw: "config json pasta" },
    { sec: "data", id: "security", kind: "security", label: "Segurança",
      desc: `O servidor local só escuta em 127.0.0.1 e exige um token por execução. PATs e tokens ficam no ${isMac() ? "Keychain do macOS" : "cofre do Windows (DPAPI)"}; a tela nunca os recebe de volta. Terminais e agentes não herdam a chave do app.`, kw: "pat token cofre keychain" },
    { sec: "data", id: "diag", kind: "diag", label: "Diagnóstico", desc: "Versão, plataforma e contagens — sem nomes, tokens ou conteúdo. Útil para relatar um problema.", kw: "suporte bug versão" },
    // atalhos para as seções de contas (a busca leva até elas)
    { sec: "accounts", id: "azLink", kind: "link", key: "accounts", label: "Organizações do Azure DevOps", desc: "PAT por organização, com teste de cada permissão.", kw: "azure pat organização" },
    { sec: "github", id: "ghLink", kind: "link", key: "github", label: "Contas do GitHub", desc: "Entrar com GitHub, gh CLI ou token.", kw: "github token gh login" },
    { sec: "shortcuts", id: "keysLink", kind: "link", key: "shortcuts", label: "Atalhos de teclado", desc: "Todos os atalhos do app e do editor (os do VS Code) — troque qualquer um.", kw: "teclado atalho kbd keybinding vscode" },
    { sec: "about", id: "updLink", kind: "link", key: "about", label: "Versão e atualizações", desc: "Procurar atualização agora.", kw: "atualizar versão update sobre thomsoft licença open-source código aberto" },
  ];

  let query = $state("");
  const norm = (s: string) => s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const results = $derived.by(() => {
    const words = norm(query).split(/\s+/).filter(Boolean);
    if (!words.length) return null;
    const hits = ROWS.filter(r => {
      const hay = norm(`${r.label} ${r.desc || ""} ${r.kw || ""} ${SECS.find(s => s.id === r.sec)?.label}`);
      return words.every(w => hay.includes(w));
    });
    return SECS.map(s => ({ sec: s, rows: hits.filter(r => r.sec === s.id) })).filter(g => g.rows.length);
  });
  const secRows = $derived(ROWS.filter(r => r.sec === tab && r.kind !== "link" || (r.sec === tab && r.kind === "link" && r.key !== tab)));

  // ------------------------------------------------------------ "Salvo" discreto (sem toast a cada clique)
  let saved = $state(false);
  let savedT: ReturnType<typeof setTimeout> | undefined;
  function flashSaved() { saved = true; clearTimeout(savedT); savedT = setTimeout(() => (saved = false), 1600); }

  function setPref(key: string, raw: string | boolean) {
    const k = key as PrefKey;
    const def = PREF_DEFAULTS[k];
    const v = typeof def === "number" ? Number(raw) : raw;
    prefs.set(k, v as any);
    if (k === "ui.density") applyDensity(v as Density);
    if (k === "power.mode") setTimeout(() => send({ type: "power" }), 800);   // o app nativo relê o modo depois de gravado
    flashSaved();
  }
  async function setRule(key: string, v: boolean) {
    const r = store.s?.rules;
    if (!r) return;
    const settings = { ...r.settings, [key]: v };
    r.settings = settings;   // otimista: o switch não volta enquanto grava
    try { await post("rules", { ...r, settings }); flashSaved(); store.load(); } catch (e) { ui.error(e); store.load(); }
  }

  // ------------------------------------------------------------ contas (Azure, GitHub)
  let cfg = $state<any>(null);
  let orgs = $state<OrgForm[]>([]);
  let saving = $state(false);
  let ghTests = $state<Record<string, any>>({});
  let token = $state("");
  let device = $state<any>(null);
  let busy = $state("");

  async function load() {
    const c = await get("config");
    cfg = c;
    orgs = c.orgs.map((o: any) => ({ name: o.name, url: o.url, pat: "", enabled: o.enabled, originalName: o.name, hasPat: o.hasPat, patStore: o.patStore, me: o.me }));
    if (!orgs.length && !c.github.length) orgs = [blankOrg()];
  }
  $effect(() => { untrack(() => load().catch(ui.error)); });
  $effect(() => { untrack(() => { if (!extensions.loaded) extensions.load(); }); });

  const blankOrg = (): OrgForm => ({ name: "", url: "https://dev.azure.com/", pat: "", enabled: true });

  async function testOrg(o: OrgForm) {
    o.test = { running: true };
    try { o.test = await post("config/test", { name: o.name, url: o.url, pat: o.pat, originalName: o.originalName }); }
    catch (e: any) { o.test = { error: e.message }; }
  }
  async function saveOrgs() {
    saving = true;
    try {
      await post("config", { orgs: orgs.map(o => ({ name: o.name, url: o.url, pat: o.pat, enabled: o.enabled, originalName: o.originalName })), pollSeconds: cfg.pollSeconds });
      ui.toast("Organizações salvas — PATs no cofre do sistema");
      await load(); store.refreshSoon();
    } catch (e) { ui.error(e); } finally { saving = false; }
  }
  async function removeOrg(i: number) {
    const o = orgs[i];
    if (o.originalName && !(await ui.ask({ title: `Remover ${o.name}?`, message: "O PAT sai do cofre ao salvar.", confirm: "Remover", danger: true }))) return;
    orgs = orgs.filter((_, k) => k !== i);
  }

  async function addAccount(kind: "token" | "cli") {
    busy = kind;
    try {
      const a = kind === "cli" ? await post("github/cli") : await post("github/token", { token });
      token = "";
      ui.toast(`Conectado como @${a.login}`);
      await load(); store.refreshSoon();
    } catch (e) { ui.error(e); } finally { busy = ""; }
  }
  async function startDevice() {
    busy = "device";
    try {
      device = await post("github/device/start");
      window.open(device.verificationUri, "_blank");
      const id = device.id;
      while (device?.id === id && device.status === "pending") {
        await new Promise(r => setTimeout(r, 2500));
        if (device?.id !== id) return;
        device = await get("github/device", { id });
      }
      if (device?.status === "done") { ui.toast(`Conectado como @${device.account.login}`); device = null; await load(); store.refreshSoon(); }
    } catch (e) { ui.error(e); device = null; } finally { busy = ""; }
  }
  async function testGh(id: string) {
    ghTests[id] = { running: true };
    try { ghTests[id] = await post("github/test", { id }); } catch (e: any) { ghTests[id] = { error: e.message }; }
  }
  async function removeGh(a: any) {
    if (!(await ui.ask({ title: `Desconectar @${a.login}?`, message: "O token é apagado do cofre do sistema.", confirm: "Desconectar", danger: true }))) return;
    try { await post("github/remove", { id: a.id }); await load(); store.refreshSoon(); } catch (e) { ui.error(e); }
  }

  // intervalo de cada fonte (backend: engine.POLL_KINDS). O valor atual entra na lista mesmo fora das opções (migrado).
  const POLL_SRC: [Source, string][] = [["prs", "Pull requests"], ["builds", "Builds e Actions"], ["deploys", "Deploys"], ["issues", "Issues e tarefas"]];
  const POLL_OPTS: Record<Source, number[]> = { prs: [15, 30, 60, 120, 300, 600], builds: [15, 30, 60, 120, 300, 600],
    deploys: [15, 30, 60, 120, 300, 600], issues: [30, 60, 180, 300, 600, 900, 1800] };
  const pollOpts = (k: Source) => [...new Set([...POLL_OPTS[k], Number(cfg?.pollIntervals?.[k]) || 0])].filter(Boolean).sort((a, b) => a - b);
  const secs = (s: number) => (s < 60 ? `${s} s` : s % 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s / 60} min`);

  const live = $derived(store.s?.schedule?.live);
  async function saveLive(patch: { liveWatch?: boolean; liveSeconds?: number }) {
    await savePrefs(patch);
    cfg = { ...cfg, live: { on: patch.liveWatch ?? cfg?.live?.on ?? true, seconds: patch.liveSeconds ?? cfg?.live?.seconds ?? 10 } };
  }

  async function savePrefs(patch: Record<string, unknown>) {
    try { await post("prefs", patch); cfg = { ...cfg, ...patch }; flashSaved(); } catch (e) { ui.error(e); }
  }
  async function copy(t: string, msg = "Código copiado") { await navigator.clipboard.writeText(t); ui.toast(msg); }

  async function openData() {
    try { await post("open", { path: cfg.dataDir, target: "files" }); } catch (e) { ui.error(e); }
  }
  function diagnostic() {
    const s = store.s, a = s?.app;
    const lines = [
      `${a?.product || "Codeck"} ${a?.version || "?"} (build ${a?.build ?? "?"}, ${a?.platform || "?"})`,
      `Sistema: ${navigator.userAgent}`,
      `Contas: Azure ${s?.orgs.length ?? 0} · GitHub ${s?.githubAccounts.length ?? 0}`,
      `Itens: PRs ${(s?.prs.length ?? 0) + (s?.myPrs.length ?? 0)} · builds ${s?.builds.length ?? 0} · deploys ${s?.deploys.length ?? 0} · issues ${s?.issues.length ?? 0}`,
      `Leitura: ${POLL_SRC.map(([k, l]) => `${l} ${s?.pollIntervals?.[k] ?? "?"} s`).join(" · ")}${cfg?.pollAdaptive === false ? "" : " (automático)"}${s?.schedule?.live?.on ? ` · tempo real ${s.schedule.live.every} s em ${s.schedule.live.repos} repo(s)` : ""} · última ${s?.lastPoll || "nunca"} · ${s?.pollMs ?? "?"} ms${s?.offline ? ` · offline desde ${s.offline}` : ""}`,
      `Erros de leitura: ${Object.keys({ ...(s?.errors || {}), ...(s?.buildErrors || {}), ...(s?.deployErrors || {}), ...(s?.issueErrors || {}) }).length}`,
      `Automação: ${s?.rules.settings.paused ? "pausada" : "ativa"} · ${s?.rules.rules.length ?? 0} regra(s) de PR · ${s?.rules.deployRules.length ?? 0} de deploy`,
      `Tela: ${window.innerWidth}×${window.innerHeight} · densidade ${prefs.get("ui.density")} · tema ${s?.theme || "?"}`,
    ];
    copy(lines.join("\n"), "Diagnóstico copiado");
  }
</script>

{#snippet control(r: Row)}
  {#if r.kind === "pref-switch"}
    <Switch checked={!!prefs.get(r.key as PrefKey)} onchange={(v) => setPref(r.key!, v)} />
  {:else if r.kind === "pref-select"}
    <select class="input" value={String(prefs.get(r.key as PrefKey))} onchange={(e) => setPref(r.key!, (e.target as HTMLSelectElement).value)}>
      {#each r.options || [] as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
    </select>
  {:else if r.kind === "pref-text"}
    <input class="input" list="cd-fonts" value={String(prefs.get(r.key as PrefKey) || "")} placeholder="JetBrains Mono" onchange={(e) => setPref(r.key!, (e.target as HTMLInputElement).value.trim())} />
    <datalist id="cd-fonts">{#each ["JetBrains Mono", "Fira Code", "Cascadia Code", "Cascadia Mono", "SF Mono", "Menlo", "Monaco", "Consolas", "Source Code Pro", "Hack", "Iosevka", "Monaspace Neon", "Ubuntu Mono", "Roboto Mono", "IBM Plex Mono", "Geist Mono"] as f (f)}<option value={f}></option>{/each}</datalist>
  {:else if r.kind === "ext-theme"}
    <select class="input" value={extensions.activeTheme ? `${extensions.activeTheme.ext}|${extensions.activeTheme.id}` : ""} onchange={(e) => {
      const v = (e.target as HTMLSelectElement).value; const hit = extensions.themes.find(x => `${x.ext.id}|${x.theme.id}` === v);
      extensions.applyTheme(hit?.ext || null, hit?.theme); flashSaved(); }}>
      <option value="">Codeck (padrão)</option>
      {#each extensions.themes as x (x.ext.id + x.theme.id)}<option value={`${x.ext.id}|${x.theme.id}`}>{x.theme.label} — {x.ext.displayName}</option>{/each}
    </select>
  {:else if r.kind === "ext-icons"}
    <select class="input" value={extensions.activeIcons ? `${extensions.activeIcons.ext}|${extensions.activeIcons.id}` : ""} onchange={(e) => {
      const v = (e.target as HTMLSelectElement).value; const hit = extensions.iconThemes.find(x => `${x.ext.id}|${x.theme.id}` === v);
      extensions.applyIcons(hit?.ext || null, hit?.theme); flashSaved(); }}>
      <option value="">Codeck (padrão)</option>
      {#each extensions.iconThemes as x (x.ext.id + x.theme.id)}<option value={`${x.ext.id}|${x.theme.id}`}>{x.theme.label} — {x.ext.displayName}</option>{/each}
    </select>
  {:else if r.kind === "vscode-import"}
    <div class="row" style="gap:6px;flex-wrap:wrap;justify-content:flex-end">
      {#each extensions.vscodeSettings as x (x.app)}
        <button class="btn sm" title={`Traz tema, ícones e ajustes do editor do ${x.app}`} onclick={() => extensions.importVscode(x.settings)}>Trazer do {x.app}</button>
        <button class="btn sm ghost" title={`Grava os ajustes do editor do Codeck no settings.json do ${x.app}`} onclick={() => extensions.exportVscode(x.app)}>Levar para o {x.app}</button>
      {:else}<span class="small muted">configurações do VS Code não encontradas</span>{/each}
    </div>
  {:else if r.kind === "vscode-sync"}
    <select class="input" style="width:auto" value={prefs.get("vscode.sync")} onchange={(e) => { const v = (e.target as HTMLSelectElement).value as any; setPref("vscode.sync", v); if (v) { extensions.exportVscode(v, true); ui.toast(`Sincronizando com o ${v}: o que mudar lá vem para cá ao abrir o app, e o que mudar aqui vai para lá`); } }}>
      <option value="">Não sincronizar</option>
      {#each extensions.vscodeSettings as x (x.app)}<option value={x.app}>Com o {x.app}</option>{/each}
    </select>
  {:else if r.kind === "pref-seg"}
    <Segmented size="sm" value={String(prefs.get(r.key as PrefKey))} options={r.options || []} onchange={(v) => setPref(r.key!, v)} />
  {:else if r.kind === "rule-switch"}
    <Switch checked={!!(store.s?.rules.settings as any)?.[r.key!]} disabled={!store.s} onchange={(v) => setRule(r.key!, v)} />
  {:else if r.kind === "auto"}
    <Switch checked={!store.s?.rules.settings.paused} disabled={!store.s} onchange={(v) => setRule("paused", !v)} />
  {:else if r.kind === "theme"}
    <Segmented size="sm" value={cfg?.theme || "system"} onchange={(v) => { chooseTheme(v as ThemePref); savePrefs({ theme: v }); }}
      options={[{ value: "system", label: "Sistema", icon: Monitor }, { value: "dark", label: "Escuro", icon: Moon }, { value: "light", label: "Claro", icon: Sun }]} />
  {:else if r.kind === "ext-editor"}
    <select class="input" value={cfg?.editor} onchange={(e) => savePrefs({ editor: (e.target as HTMLSelectElement).value })}>
      {#each cfg?.editors || [] as ed (ed.id)}<option value={ed.id}>{ed.name}</option>{:else}<option value="">nenhum editor encontrado</option>{/each}
    </select>
  {:else if r.kind === "poll"}
    <div class="polls">
      {#each POLL_SRC as [k, l] (k)}
        {@const sch = store.s?.schedule?.[k]}
        <label><span>{l}</span>
          <select class="input" value={String(cfg?.pollIntervals?.[k])} onchange={(e) => savePrefs({ pollIntervals: { ...cfg.pollIntervals, [k]: Number((e.target as HTMLSelectElement).value) } })}>
            {#each pollOpts(k) as s (s)}<option value={String(s)}>{secs(s)}</option>{/each}
          </select>
          {#if live?.on}<em title={`Tempo real (local): ${live.repos} repositório(s) ativo(s) · ${live.callsMin} consultas no último minuto, ${live.freeMin} sem gastar cota (304). A leitura completa segue como reserva.`}>tempo real · {live.every} s{#if live.why !== "tempo real"} ({live.why}){/if}</em>
          {:else if sch && sch.why !== "intervalo"}<em title="Ritmo desta leitura agora">agora {secs(sch.every)} · {sch.why}</em>{/if}
        </label>
      {/each}
    </div>
  {:else if r.kind === "live"}
    <div class="row" style="gap:8px">
      {#if cfg?.live?.on}
        <select class="input sm-sel" value={String(cfg.live.seconds)} title="De quanto em quanto tempo olhar (Azure: no mínimo 15 s)"
          onchange={(e) => saveLive({ liveSeconds: Number((e.target as HTMLSelectElement).value) })}>
          {#each [5, 10, 15, 20, 30, 60] as v (v)}<option value={String(v)}>a cada {v} s</option>{/each}
        </select>
      {/if}
      <Switch checked={cfg?.live?.on !== false} onchange={(v) => saveLive({ liveWatch: v })} />
    </div>
  {:else if r.kind === "poll-adaptive"}
    <Switch checked={cfg?.pollAdaptive !== false} onchange={(v) => savePrefs({ pollAdaptive: v })} />
  {:else if r.kind === "data-dir"}
    <button class="btn sm" onclick={openData} disabled={!cfg?.dataDir}><FolderOpen size={14} /> Abrir pasta</button>
  {:else if r.kind === "diag"}
    <button class="btn sm" onclick={diagnostic}><ClipboardCopy size={14} /> Copiar diagnóstico</button>
  {:else if r.kind === "security"}
    <Shield size={18} class="shield" />
  {:else if r.kind === "link"}
    <button class="btn sm ghost" onclick={() => { query = ""; go(`/settings/${r.key}`, "soft"); }}>Abrir →</button>
  {/if}
{/snippet}

{#snippet row(r: Row)}
  <div class="pref" class:off={r.when && !r.when()} class:note={r.kind === "note"}>
    <div class="pt">
      <b>{r.label}</b>
      {#if r.kind === "data-dir"}<div class="small muted mono sel">{cfg?.dataDir || "…"}</div>{/if}
      {#if r.desc}<div class="small muted">{r.desc}</div>{/if}
    </div>
    {#if r.kind !== "note"}<div class="pc">{@render control(r)}</div>{/if}
  </div>
{/snippet}

{#snippet trackRow(key: string, name: string)}
  {@const mode = repos.trackMode(key)}
  <div class="trackrow">
    <Switch checked={mode === "all"} onchange={async (v) => { try { await repos.setTrackMode(key, v ? "all" : "selected"); store.refreshSoon(2500); } catch (e) { ui.error(e); } }}
      label="Acompanhar todos os repositórios desta conta"
      hint={mode === "all" ? "PRs, builds, deploys e issues de todos os repositórios — em Repositórios dá para desligar um a um" : "Só os repositórios que você marcar (o olho em Repositórios)"} />
    <button class="btn sm ghost" onclick={() => (ui.editAccount = key)}>Detalhes da conta →</button>
  </div>
{/snippet}

<Page title="Configurações" sub="Contas, preferências e segurança">
  {#snippet actions()}
    <span class="saved" class:on={saved} aria-live="polite"><Check size={13} /> Salvo</span>
  {/snippet}
  <div class="layout">
    <nav class="tabs">
      <label class="find">
        <Search size={14} />
        <input bind:value={query} placeholder="Buscar ajuste…" aria-label="Buscar ajuste" onkeydown={(e) => e.key === "Escape" && (query = "")} />
        {#if query}<button class="clr" title="Limpar" aria-label="Limpar busca" onclick={() => (query = "")}><X size={11} /></button>{/if}
      </label>
      {#each GROUPS as g (g.label)}
        <div class="ng">{g.label}</div>
        {#each g.items as t (t.id)}
          <button class:on={tab === t.id && !results} onclick={() => { query = ""; go(`/settings/${t.id}`, "soft"); }}>
            {#if t.provider}<ProviderIcon provider={t.provider} size={15} />{:else if t.icon}<t.icon size={15} />{/if} {t.label}
          </button>
        {/each}
      {/each}
      <div class="sec-note"><Shield size={14} /><span>Credenciais ficam criptografadas no {cfg?.orgs?.[0]?.patStore || cfg?.github?.[0]?.store || "cofre do sistema"}; a tela nunca as recebe de volta.</span></div>
    </nav>

    <div class="body">
      {#if !cfg}<Skeleton rows={4} />
      {:else if results}
        <div class="head"><div><h2>Resultados para “{query}”</h2><p class="muted small">{results.reduce((n, g) => n + g.rows.length, 0)} ajuste(s)</p></div></div>
        {#each results as g (g.sec.id)}
          <button class="rh" onclick={() => { query = ""; go(`/settings/${g.sec.id}`, "soft"); }}>
            {#if g.sec.provider}<ProviderIcon provider={g.sec.provider} size={13} />{:else if g.sec.icon}<g.sec.icon size={13} />{/if} {g.sec.label} <span class="muted">→</span>
          </button>
          <div class="card org">{#each g.rows as r (r.id)}{@render row(r)}{/each}</div>
        {:else}
          <div class="none card"><Search size={18} /><b>Nenhum ajuste com “{query}”</b><span class="small muted">Tente outra palavra — por exemplo “tema”, “fonte”, “limite” ou “notificação”.</span></div>
        {/each}

      {:else if tab === "accounts"}
        <div class="head"><div><h2>{sec.title}</h2><p class="muted small">{sec.desc}</p></div>
          <span class="spacer"></span><button class="btn sm ghost" onclick={() => (orgs = [...orgs, blankOrg()])}><Plus size={14} /> Organização</button></div>
        {#each orgs as o, i (i)}
          <div class="card org">
            <div class="row" style="gap:10px">
              <Switch bind:checked={o.enabled} />
              <b>{o.name || "Nova organização"}</b>
              {#if o.me}<span class="pill good"><Check size={11} /> {o.me.displayName || o.me.name || "conectado"}</span>{/if}
              <span class="spacer"></span>
              <button class="btn sm ghost danger" onclick={() => removeOrg(i)}><Trash2 size={14} /></button>
            </div>
            <div class="fields">
              <label><span>Nome</span><input class="input" bind:value={o.name} placeholder="Cifal" /></label>
              <label><span>URL da organização</span><input class="input" bind:value={o.url} placeholder="https://dev.azure.com/minha-org" /></label>
              <label class="full"><span>Personal Access Token {#if o.hasPat}<em class="good">· salvo no {o.patStore || "cofre"} — deixe vazio para manter</em>{/if}</span>
                <input class="input mono" type="password" autocomplete="off" bind:value={o.pat} placeholder={o.hasPat ? "••••••••••••••••" : "cole o PAT"} /></label>
            </div>
            <div class="row" style="gap:8px">
              <button class="btn sm" onclick={() => testOrg(o)} disabled={!o.url || (!o.pat && !o.hasPat)}><KeyRound size={14} /> Testar</button>
              <span class="tiny muted">Escopos: Code (Read & Write), Build (Read & Execute), Release (Read, Write & Execute), Work Items (Read), Project (Read).</span>
            </div>
            {#if o.test}<div class="test"><TestResult test={o.test} /></div>{/if}
            {#if o.originalName}{@render trackRow("azure:" + o.originalName, o.originalName)}{/if}
          </div>
        {/each}
        <div class="foot"><button class="btn primary" onclick={saveOrgs} disabled={saving}>{saving ? "Salvando…" : "Salvar organizações"}</button></div>
        <People />

      {:else if tab === "github"}
        <div class="head"><div><h2>{sec.title}</h2><p class="muted small">{sec.desc}</p></div></div>
        {#each cfg.github as a (a.id)}
          <div class="card org">
            <div class="row" style="gap:10px">
              <Avatar name={a.login} src={a.avatar} size={30} />
              <div><b>{a.name || a.login}</b><div class="tiny muted">@{a.login} · {a.store || "cofre"} · conectado {dateTime(a.connectedAt)}{a.renewedAt ? ` · renovado ${dateTime(a.renewedAt)}` : ""}</div></div>
              <span class="spacer"></span>
              {#if a.rate}<span class="tiny muted">API {a.rate.remaining}/{a.rate.limit}</span>{/if}
              <button class="btn sm" title="Entra de novo nesta conta (mantém os ajustes e o que você acompanha)" onclick={() => (a.source === "gh-cli" ? addAccount("cli") : startDevice())} disabled={!!busy}><LogIn size={14} /> Entrar de novo</button>
              <button class="btn sm" onclick={() => testGh(a.id)}><KeyRound size={14} /> Testar</button>
              <button class="btn sm ghost danger" onclick={() => removeGh(a)}><Trash2 size={14} /></button>
            </div>
            {#if a.authError}
              <div class="autherr small"><b>O GitHub recusou o token</b> ({dateTime(a.authError.at)}) e o app não conseguiu renovar sozinho. Use <b>Entrar de novo</b> — a conta, os ajustes e o que você acompanha continuam.</div>
            {/if}
            <div class="tiny muted">{a.expiresAt ? `Token que expira (${dateTime(new Date(a.expiresAt * 1000).toISOString())})${a.autoRenew ? " — renovado sozinho antes de vencer" : ""}` : a.source === "gh-cli" ? "Token do gh CLI — se ele mudar, o app relê sozinho" : "Token sem validade — só para de funcionar se for revogado no GitHub"}</div>
            {#if a.scopes?.length}<div class="scopes">{#each a.scopes as s (s)}<span class="pill neutral">{s}</span>{/each}</div>{/if}
            {#if ghTests[a.id]}<div class="test"><TestResult test={ghTests[a.id]} /></div>{/if}
            {@render trackRow("github:" + a.login, a.login)}
          </div>
        {/each}

        <div class="connect">
          <div class="card opt">
            <LogIn size={20} /><h4>Entrar com GitHub</h4>
            <p class="small muted">Abre o navegador, você digita um código e pronto. Sem copiar token.</p>
            {#if device}
              <div class="code"><button class="mono" onclick={() => copy(device.userCode)} title="Copiar">{device.userCode}</button>
                <a href={device.verificationUri} target="_blank" rel="noopener" class="small">{device.verificationUri} <ExternalLink size={11} /></a>
                <span class="small muted">{device.status === "error" ? device.error : "aguardando você autorizar…"}</span></div>
            {:else}
              <button class="btn primary sm" onclick={startDevice} disabled={!cfg.githubLogin || !!busy} title={cfg.githubLogin ? "" : "Este build ainda não tem o client id do OAuth App"}>Entrar</button>
              {#if !cfg.githubLogin}<span class="tiny muted">indisponível neste build — use o gh CLI ou um token</span>{/if}
            {/if}
          </div>
          <div class="card opt">
            <Terminal size={20} /><h4>Usar o login do gh CLI</h4>
            <p class="small muted">Reaproveita o <code>gh auth login</code> já feito nesta máquina.</p>
            <button class="btn sm" onclick={() => addAccount("cli")} disabled={!cfg.ghCli || !!busy}>{busy === "cli" ? "Conectando…" : "Importar"}</button>
            {#if !cfg.ghCli}<span class="tiny muted">gh CLI não encontrado</span>{/if}
          </div>
          <div class="card opt">
            <KeyRound size={20} /><h4>Colar um token</h4>
            <p class="small muted">Classic com <code>repo</code>, <code>workflow</code>, <code>read:org</code> — ou fine-grained.</p>
            <input class="input mono" type="password" autocomplete="off" bind:value={token} placeholder="ghp_… ou github_pat_…" />
            <button class="btn sm" onclick={() => addAccount("token")} disabled={!token.trim() || !!busy}>{busy === "token" ? "Conectando…" : "Conectar"}</button>
          </div>
        </div>

      {:else if tab === "ai"}
        <AiAccounts />

      {:else if tab === "notifications"}
        <div class="head"><div><h2>{sec.title}</h2><p class="muted small">{sec.desc}</p></div></div>
        <Alerts />

      {:else if tab === "shortcuts"}
        <div class="head"><div><h2>{sec.title}</h2><p class="muted small">{sec.desc}</p></div></div>
        <Keybindings />

      {:else if tab === "about"}
        <div class="head"><div><h2>{store.s?.app.product || "Codeck"}</h2><p class="muted small">Versão {store.s?.app.version} · build {store.s?.app.build} · {store.s?.app.platform}</p></div></div>
        <div class="card org">
          <div class="pref"><div><b>Atualizações</b><div class="small muted">
            {#if store.s?.update.available}Versão {store.s.update.version} disponível{:else if store.s?.update.checkedAt}Em dia — verificado {dateTime(store.s.update.checkedAt)}{:else}Ainda não verificado{/if}</div></div>
            <button class="btn sm" onclick={() => (window as any).checkUpdate?.(true)}><RefreshCw size={14} /> Procurar agora</button></div>
          <div class="pref"><div><b>Segurança</b><div class="small muted">O servidor local só escuta em 127.0.0.1 e exige um token por execução. PATs e tokens ficam no Keychain (macOS) ou DPAPI (Windows).</div></div></div>
          <div class="pref"><div><b>Diagnóstico</b><div class="small muted">Versão, plataforma e contagens, para relatar um problema.</div></div>
            <button class="btn sm" onclick={diagnostic}><ClipboardCopy size={14} /> Copiar</button></div>
        </div>
        <div class="card org">
          <div class="pref"><div><b>Desenvolvido pela ThomSoft</b><div class="small muted">
            <a href="https://thomsoft.com.br" target="_blank" rel="noopener">thomsoft.com.br <ExternalLink size={11} /></a></div></div></div>
          <div class="pref"><div><b>Código aberto</b><div class="small muted">Projeto open-source da ThomSoft, de uso gratuito sob a licença MIT.
            <a href="https://github.com/ThomSofts/codeck" target="_blank" rel="noopener">github.com/ThomSofts/codeck <ExternalLink size={11} /></a></div></div></div>
        </div>

      {:else}
        <div class="head"><div><h2>{sec.title}</h2>{#if sec.desc}<p class="muted small">{sec.desc}</p>{/if}</div></div>
        <div class="card org">{#each secRows as r (r.id)}{@render row(r)}{/each}</div>
      {/if}
    </div>
  </div>
</Page>

<style>
  .layout { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 22px; flex: 1; min-height: 0; }
  .tabs { display: flex; flex-direction: column; gap: 2px; overflow: auto; min-height: 0; padding-bottom: 12px; }
  .tabs button { display: flex; align-items: center; gap: 9px; height: 32px; padding: 0 11px; border: 0; border-radius: 9px; background: none; color: var(--text-2);
    font: 550 13px var(--font); cursor: pointer; text-align: left; transition: background var(--t-fast), color var(--t-fast); flex: none; }
  .tabs button:hover { background: var(--surface-2); color: var(--text); }
  .tabs button.on { background: var(--accent-soft); color: var(--text); }
  .ng { font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.08em; color: var(--faint); padding: 14px 11px 6px; }
  .find { display: flex; align-items: center; gap: 7px; height: 32px; padding: 0 9px; margin-bottom: 2px; border-radius: 9px; border: 1px solid var(--line-2);
    background: var(--bg-2); color: var(--muted); flex: none; }
  .find:focus-within { border-color: var(--accent); box-shadow: var(--ring); }
  .find input { flex: 1; min-width: 0; border: 0; outline: none; background: none; color: var(--text); font: 13px var(--font); }
  .tabs .clr { display: grid; place-items: center; width: 18px; height: 18px; flex: none; padding: 0; border-radius: 50%; background: var(--surface-3); color: var(--text-2); }
  .sec-note { margin-top: 14px; display: flex; gap: 8px; font-size: 11.5px; color: var(--muted); line-height: 1.45; padding: 0 6px; }
  .sec-note :global(svg) { flex: none; color: var(--good); margin-top: 1px; }
  .body { overflow: auto; min-height: 0; overscroll-behavior: contain; padding-right: 4px; max-width: 920px; }
  .head { display: flex; align-items: flex-end; gap: 10px; margin-bottom: 12px; }
  .head h2 { margin: 0 0 3px; font-size: 16px; }
  .head p { margin: 0; }
  .org { padding: 14px 16px; margin-bottom: 12px; display: grid; gap: 12px; }
  .fields { display: grid; grid-template-columns: 1fr 2fr; gap: 10px; }
  .fields label { display: grid; gap: 5px; font-size: 12px; color: var(--text-2); }
  .fields .full { grid-column: 1 / -1; }
  .fields em { font-style: normal; }
  .good { color: var(--good); }
  .danger:hover { color: var(--bad); }
  .foot { display: flex; justify-content: flex-end; padding-bottom: 20px; }
  .scopes { display: flex; flex-wrap: wrap; gap: 5px; }
  .trackrow { display: flex; align-items: center; gap: 10px; justify-content: space-between; border-top: 1px solid var(--line); padding-top: 10px; }
  .connect { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 6px; }
  .opt { padding: 16px; display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
  .opt h4 { margin: 2px 0 0; font-size: 14px; }
  .opt p { margin: 0; flex: 1; }
  .opt :global(svg:first-child) { color: var(--accent); }
  .opt .input { width: 100%; }
  .code { display: grid; gap: 6px; }
  .code button { font-size: 22px; letter-spacing: 0.12em; border: 1px dashed var(--line-2); background: var(--surface-2); color: var(--text); border-radius: 9px; padding: 6px 12px; cursor: copy; }
  .pref { display: flex; align-items: center; gap: 16px; justify-content: space-between; transition: opacity var(--t); }
  .pref + .pref { border-top: 1px solid var(--line); padding-top: 12px; }
  .pref.off { opacity: 0.45; pointer-events: none; }
  .pt { display: grid; gap: 3px; min-width: 0; }
  .pt .small { line-height: 1.45; max-width: 560px; }
  .pc { flex: none; display: flex; align-items: center; }
  .pc select { width: 220px; }
  .pref select { width: 220px; }
  .pref select.sm-sel { width: 130px; }
  .polls { display: grid; grid-template-columns: repeat(2, minmax(150px, 1fr)); gap: 8px 10px; }
  .polls label { display: grid; gap: 3px; font-size: 11.5px; color: var(--muted); }
  .polls select { width: 100%; }
  .polls em { font-style: normal; font-size: 11px; color: var(--accent); }
  .sel { user-select: text; word-break: break-all; }
  .pc :global(.shield) { color: var(--good); }
  .test { border-top: 1px solid var(--line); padding-top: 10px; }
  .saved { display: inline-flex; align-items: center; gap: 5px; font: 600 12px var(--font); color: var(--good); opacity: 0; transform: translateY(2px);
    transition: opacity var(--t), transform var(--t) var(--ease-out); }
  .saved.on { opacity: 1; transform: none; }
  .rh { display: inline-flex; align-items: center; gap: 7px; margin: 4px 0 8px; padding: 0; border: 0; background: none; color: var(--text-2);
    font: 650 11px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; cursor: pointer; }
  .rh:hover { color: var(--accent); }
  .none { display: grid; justify-items: center; gap: 6px; padding: 36px 16px; text-align: center; color: var(--text-2); }
  .none :global(svg) { color: var(--muted); }
  @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } .tabs { flex-direction: row; flex-wrap: wrap; } .ng, .find, .sec-note { display: none; } .fields { grid-template-columns: 1fr; } }
  .autherr { padding: 8px 11px; border-radius: 9px; background: var(--bad-soft); color: var(--text-2); }
  .autherr b { color: var(--bad); }
</style>
