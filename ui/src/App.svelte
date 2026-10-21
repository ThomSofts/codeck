<script lang="ts">
  import { onMount, untrack } from "svelte";
  import CascadeDock from "./components/cascade/CascadeDock.svelte";
  import CommandPalette from "./components/CommandPalette.svelte";
  import DialogHost from "./components/DialogHost.svelte";
  import Sidebar from "./components/Sidebar.svelte";
  import Toaster from "./components/Toaster.svelte";
  import MenuHost from "./components/MenuHost.svelte";
  import CloneDialog from "./components/repo/CloneDialog.svelte";
  import AccountEditor from "./components/repo/AccountEditor.svelte";
  import RepoHub from "./components/repo/RepoHub.svelte";
  import { cascade } from "./lib/cascade.svelte";
  import { applyDensity } from "./lib/density";
  import { prefs } from "./lib/prefs.svelte";
  import { kb, syncKeybindings } from "./lib/keybindings.svelte";
  import { extensions } from "./lib/extensions.svelte";
  import Projects from "./views/Projects.svelte";
  import Kanban from "./views/Kanban.svelte";
  import { ui } from "./lib/ui.svelte";
  import { work } from "./lib/work.svelte";
  import OfflineBanner from "./components/OfflineBanner.svelte";
  import TopProgress from "./components/TopProgress.svelte";
  import UpdateBanner from "./components/UpdateBanner.svelte";
  import { repos } from "./lib/repos.svelte";
  import { go, router } from "./lib/router.svelte";
  import { store } from "./lib/store.svelte";
  import AiUsage from "./views/AiUsage.svelte";
  import Analytics from "./views/Analytics.svelte";
  import Automation from "./views/Automation.svelte";
  import Builds from "./views/Builds.svelte";
  import Deploys from "./views/Deploys.svelte";
  import History from "./views/History.svelte";
  import Inbox from "./views/Inbox.svelte";
  import Issues from "./views/Issues.svelte";
  import PullRequests from "./views/PullRequests.svelte";
  import Repositories from "./views/Repositories.svelte";
  import Settings from "./views/Settings.svelte";
  import Work from "./views/Work.svelte";

  const views: Record<string, any> = {
    inbox: Inbox, prs: PullRequests, builds: Builds, deploys: Deploys, issues: Issues, repos: Repositories,
    automation: Automation, analytics: Analytics, ai: AiUsage, history: History, settings: Settings, work: Work, solo: Work, repo: Work,
    projects: Projects, board: Kanban,
  };
  const View = $derived(views[router.view] || Inbox);

  // Notificação clicada no app nativo: "rota/chave" (formatos antigos continuam valendo).
  window.openTarget = (target: string) => {
    const [t, ...rest] = (target || "").split("/");
    if (t === "term") {   // agente terminou / pediu atenção: abre o projeto dele
      const a = work.agents.find(x => x.term.meta.sid === rest[0] || x.term.id === rest[0]);
      return go("/work/" + (a?.project.id || ""));
    }
    if (t === "cascade") return cascade.show(rest.join("/"));   // passo do "até o deploy": abre a doca naquela PR
    const key = encodeURIComponent(rest.join("/"));
    const map: Record<string, string> = { fila: "/inbox/", minhas: "/prs/mine/", todas: "/prs/all/", builds: "/builds/", historico: "/history", deploys: "/deploys/" };
    go((map[t] ?? `/${t}/`) + (map[t] === "/history" ? "" : key));
  };

  // atalhos personalizados que chegaram de outra janela (pelo /api/state): o editor recebe as regras novas
  $effect(() => { void prefs.get("keybindings"); untrack(() => syncKeybindings()); });
  // densidade da interface (Configurações → Aparência)
  $effect(() => { void prefs.get("ui.density"); applyDensity(); });
  // tema de cores/ícones e snippets das extensões do VS Code: assim que as preferências chegam do backend
  $effect(() => { if (store.s) untrack(() => extensions.restore().catch(() => {})); });
  // ligar/desligar "o tema pinta o app inteiro" reaplica o tema atual
  $effect(() => {
    void prefs.get("workbench.themeApp");
    untrack(() => {
      const a = extensions.activeTheme;
      const e = a && extensions.list.find(x => x.id === a.ext);
      const t = e?.themes.find(x => x.id === a!.id);
      if (e && t) extensions.applyTheme(e, t, false);
    });
  });
  // /work/board (o quadro antigo) agora é a página do Quadro
  $effect(() => { if (router.view === "work" && router.parts[1] === "board") untrack(() => go("/board/agents", "soft")); });
  // abrir o app: volta para o último projeto, se a preferência mandar (Configurações → Projetos)
  let reopened = false;
  $effect(() => {
    if (reopened || !work.loaded || !store.s) return;
    reopened = true;
    if (router.view === "inbox" && !location.hash.replace(/^#\/?/, "") && prefs.get("work.reopenLast") && work.active && work.projects.some(p => p.id === work.active))
      untrack(() => go("/work/" + work.active));
  });

  onMount(() => {
    const stopWork = work.watch();   // projetos abertos e agentes: a barra lateral mostra o estado em qualquer tela
    store.start();
    repos.load();
    const t = setInterval(() => { if (!store.hold) repos.load(); }, 30000);
    return () => { clearInterval(t); stopWork(); };
  });
  // #/repo/<id> (links antigos, barra lateral, ⌘K): repositório é projeto — abre o projeto na aba Git
  $effect(() => { if (router.view === "repo" && router.param) { const id = router.param; untrack(() => work.openRepo(id)); } });

  // 1ª execução sem nenhuma conta: leva para Contas UMA vez, na abertura. Depois o usuário navega livre — na v3 dá
  // para usar só Projetos e IA, sem Azure/GitHub (antes toda navegação voltava para Contas).
  let routedOnce = false;
  $effect(() => {
    if (!store.s || routedOnce) return;
    routedOnce = true;
    if (!store.s.configured && !["settings", "work", "solo", "projects", "board"].includes(router.view) && !work.projects.length) go("/settings/accounts");
  });
</script>

<svelte:window onkeydown={(e) => kb.dispatch(e)} />

<div class="shell">
  {#if router.view !== "solo"}<Sidebar />{/if}
  <main>
    <TopProgress />
    <OfflineBanner />
    <UpdateBanner />
    <div class="page">
      {#key router.view}
        <View />
      {/key}
    </div>
  </main>
</div>

<CommandPalette />
<DialogHost />
<MenuHost />
{#if ui.cloneAsk}<CloneDialog />{/if}
{#if ui.editAccount}<AccountEditor />{/if}
{#if ui.repoHub}<RepoHub />{/if}
<Toaster />
<CascadeDock />

<style>
  .shell { display: flex; height: 100%; }
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; height: 100%; }
  .page { flex: 1; min-height: 0; view-transition-name: page; }
</style>
