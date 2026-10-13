<script lang="ts">
  // Repositórios: os locais registrados, os favoritos (de qualquer conta, com tags) e os catálogos (repositórios de uma
  // org/projeto, clonados ou não — criados sozinhos ao conectar a conta).
  import { Download, Eye, EyeOff, FolderPlus, FolderSearch, Link, Pencil, Plus, RefreshCw, Search, WifiOff, FolderCog, Settings2 } from "@lucide/svelte";
  import { store } from "../lib/store.svelte";
  import Avatar from "../components/Avatar.svelte";
  import { untrack } from "svelte";
  import { get, post } from "../lib/api";
  import { pickFolder } from "../lib/native";
  import { repos } from "../lib/repos.svelte";
  import { go, router, soft } from "../lib/router.svelte";
  import type { CatalogView, FavRepo, RemoteRepo } from "../lib/types";
  import FavStar from "../components/repo/FavStar.svelte";
  import ProviderIcon from "../components/ProviderIcon.svelte";
  import { ui } from "../lib/ui.svelte";
  import Drawer from "../components/Drawer.svelte";
  import Empty from "../components/Empty.svelte";
  import Page from "../components/Page.svelte";
  import CatalogEditor from "../components/repo/CatalogEditor.svelte";
  import RepoRow from "../components/repo/RepoRow.svelte";
  import Segmented from "../components/Segmented.svelte";
  import Skeleton from "../components/Skeleton.svelte";
  import Toolbar from "../components/Toolbar.svelte";

  // catálogo manual ("/repos/catalog/<id>") ou conta inteira ("/repos/account/<provider:conta>") — mesma tela
  const catalogId = $derived(router.parts[1] === "catalog" ? router.parts[2] : router.parts[1] === "account" ? "account:" + router.param.slice(8) : null);
  const isAccount = $derived(!!catalogId?.startsWith("account:"));
  // favoritos ("/repos/favorites") e tag ("/repos/tag/<nome>") listam a coleção pessoal
  const tagName = $derived(router.parts[1] === "tag" ? router.param.slice(4) : null);
  const favMode = $derived(router.parts[1] === "favorites" || !!tagName);
  const tagInfo = $derived(tagName ? repos.tag(tagName) : null);
  const favList = $derived.by(() => {
    const t = q.trim().toLowerCase();
    return repos.favorites.filter(r => (!tagName || r.tags.includes(tagName))
      && (filter === "all" || (filter === "cloned" ? r.cloned : filter === "not" ? !r.cloned : true))
      && (!t || `${r.name} ${r.fullName} ${r.description || ""} ${r.tags.join(" ")}`.toLowerCase().includes(t)));
  });
  const favCounts = $derived.by(() => {
    const base = repos.favorites.filter(r => !tagName || r.tags.includes(tagName));
    return { all: base.length, cloned: base.filter(r => r.cloned).length, notCloned: base.filter(r => !r.cloned).length };
  });

  // busca em TODAS as contas conectadas, para favoritar (e já aplicar a tag aberta)
  let searching = $state(false);
  let sq = $state("");
  let results = $state<(RemoteRepo & { favorite: boolean })[]>([]);
  let sLoading = $state(false);
  let sErrors = $state<Record<string, string>>({});
  let sTimer: ReturnType<typeof setTimeout> | undefined;
  function runSearch() {
    clearTimeout(sTimer);
    sTimer = setTimeout(async () => {
      sLoading = true;
      try { const r = await get("library/search", { q: sq }); results = r.repos; sErrors = r.errors; } catch (e) { ui.error(e); }
      sLoading = false;
    }, 220);
  }
  $effect(() => { if (searching) { void sq; untrack(runSearch); } });

  async function cloneFav(r: FavRepo) {
    const base = await askBase([r.name], `${r.provider}:${r.account}`);
    if (!base) return;
    try { watch(r.key, await post("library/clone", { key: r.key, dest: join(base, r.name) })); } catch (e) { ui.error(e); }
  }
  let view = $state<CatalogView | null>(null);
  let loading = $state(false);
  let q = $state("");
  let filter = $state("all");
  let jobs = $state<Record<string, any>>({});
  let editing = $state<"new" | "edit" | null>(router.parts[1] === "new-catalog" ? "new" : null);
  let adding = $state(router.parts[1] === "add");
  let cloneUrl = $state("");
  let cloneDest = $state("");

  async function loadCatalog(force = false) {
    if (!catalogId) return;
    loading = !view || view.id !== catalogId;
    try {
      view = await get<CatalogView>("catalog", { id: catalogId, force: force ? 1 : 0 });
      const n = view.counts.total, a = repos.accounts.find(x => "account:" + x.key === catalogId), c = repos.catalogs.find(x => x.id === catalogId);
      if (a) a.count = n;
      if (c) c.count = n;
    }
    catch (e) { ui.error(e); }
    loading = false;
  }
  $effect(() => {
    const cid = catalogId;   // só a troca de catálogo dispara a carga (o resto é lido sem rastrear)
    untrack(() => { view = null; if (cid) loadCatalog(); else repos.load(); });
  });

  const trk = (r: RemoteRepo) => repos.track(r.remoteKey || r.key, r.accountKey).on;
  const list = $derived.by(() => {
    const t = q.trim().toLowerCase();
    if (catalogId && view) {
      return view.repos.filter(r => (filter === "all" || (filter === "tracked" ? trk(r) : filter === "untracked" ? !trk(r) : filter === "cloned" ? r.cloned : !r.cloned))
        && (!t || `${r.name} ${r.description} ${r.owner} ${r.language || ""}`.toLowerCase().includes(t)));
    }
    return [];
  });
  const locals = $derived(repos.local.filter(r => (filter === "all" || (filter === "dirty" ? (r.status?.changes || 0) > 0 : filter === "ahead" ? (r.status?.ahead || 0) + (r.status?.behind || 0) > 0 : true))
    && (!q || `${r.name} ${r.path} ${r.slug || ""}`.toLowerCase().includes(q.toLowerCase()))));

  function watch(key: string, job: any) {
    jobs = { ...jobs, [key]: job };
    const tick = async () => {
      try {
        const j = await get("jobs", { id: job.id });
        jobs = { ...jobs, [key]: j };
        if (j.status === "running") return setTimeout(tick, 600);
        if (j.status === "done") { ui.toast(`Clonado em ${j.dest}`); await repos.load(); if (catalogId) await loadCatalog(); }
        else ui.toast(`Falhou ao clonar: ${j.error}`, "error");
      } catch (e) { ui.error(e); }
    };
    setTimeout(tick, 500);
  }
  const join = (base: string, name: string) => base.replace(/[\\/]$/, "") + (base.includes("\\") ? "\\" : "/") + name;
  const accName = (key: string) => repos.accounts.find(a => a.key === key)?.name || key.split(":").pop() || key;
  /** Pergunta a pasta — as pastas base da CONTA do repositório vêm primeiro; pasta nova pode virar pasta da conta. */
  async function askBase(names: string[], account: string) {
    const ch = await ui.chooseCloneDir({ title: names.length === 1 ? `Clonar ${names[0]}` : `Clonar ${names.length} repositórios de ${accName(account)}`, names,
      account, accountName: accName(account) });
    if (!ch) return null;
    if (ch.remember) { await post("accounts/dirs", { key: account, add: ch.base }); repos.load(false); }
    return ch.base;
  }
  async function clone(key: string) {
    const r = view?.repos.find(x => x.key === key);
    if (!r) return;
    const base = await askBase([r.name], r.accountKey || `${r.provider}:${r.account}`);
    if (!base) return;
    try { watch(key, await post("catalogs/clone", { id: catalogId, repoKey: key, dest: join(base, r.name) })); } catch (e) { ui.error(e); }
  }
  async function cloneAll() {
    const pending = view!.repos.filter(r => !r.cloned && !r.archived);
    // catálogo pode misturar contas: pergunta a pasta uma vez por conta
    const bases: Record<string, string> = {};
    for (const acc of [...new Set(pending.map(r => r.accountKey || `${r.provider}:${r.account}`))]) {
      const b = await askBase(pending.filter(r => (r.accountKey || `${r.provider}:${r.account}`) === acc).map(r => r.name), acc);
      if (!b) return;
      bases[acc] = b;
    }
    const prog = ui.progress(`Clonando ${pending.length} repositório(s)…`);
    let n = 0;
    for (const r of pending) {
      const base = bases[r.accountKey || `${r.provider}:${r.account}`];
      prog.update(`Clonando ${r.name} (${++n} de ${pending.length})…`);
      try {
        const job = await post("catalogs/clone", { id: catalogId, repoKey: r.key, dest: join(base, r.name) });
        jobs = { ...jobs, [r.key]: job };
        while (true) {
          await new Promise(res => setTimeout(res, 700));
          const j = await get("jobs", { id: job.id });
          jobs = { ...jobs, [r.key]: j };
          if (j.status !== "running") break;
        }
      } catch (e) { ui.error(e); }
    }
    await repos.load();
    await loadCatalog();
    prog.done("Clones concluídos");
  }
  async function addFolder() {
    const p = await pickFolder("Escolha a pasta de um repositório Git");
    if (!p) return;
    try { const r = await post("repos/add", { path: p }); await repos.load(); adding = false; ui.toast(`${r.name} adicionado`); go("/repo/" + r.id); }
    catch (e) { ui.error(e); }
  }
  async function scanFolder() {
    const p = await pickFolder("Escolha uma pasta para procurar repositórios dentro dela");
    if (!p) return;
    try { const r = await post("repos/scan", { path: p, depth: 3 }); await repos.load(); adding = false; ui.toast(`${r.found} repositório(s) encontrado(s)`); }
    catch (e) { ui.error(e); }
  }
  async function cloneByUrl() {
    if (!cloneUrl.trim()) return;
    let dest = cloneDest.trim();
    if (!dest) {
      const base = await pickFolder("Pasta onde clonar");
      if (!base) return;
      dest = base.replace(/\/$/, "") + "/" + cloneUrl.trim().replace(/\.git$/, "").split(/[/:]/).pop();
    }
    try {
      const job = await post("repos/clone", { url: cloneUrl.trim(), dest });
      adding = false;
      watch(cloneUrl, job);
      ui.toast("Clonando…", "info");
    } catch (e) { ui.error(e); }
  }
  const counts = $derived(view ? { all: view.repos.length, cloned: view.repos.filter(r => r.cloned).length, notCloned: view.repos.filter(r => !r.cloned).length,
    tracked: view.repos.filter(trk).length } : null);
  // conta aberta: cabeçalho com os detalhes dela (o "⚙" abre os ajustes)
  const accKey = $derived(isAccount ? catalogId!.slice(8) : null);
  const accProv = $derived(accKey?.split(":")[0] as "azure" | "github" | undefined);
  const accLogin = $derived(accKey ? accKey.slice((accProv || "").length + 1) : "");
  const accAvatar = $derived(accProv === "github" ? store.s?.githubAccounts.find(a => a.login === accLogin)?.avatar : undefined);
  const accMine = (x: any) => (accProv === "github" ? x.provider === "github" && x.account === accLogin : x.provider !== "github" && x.org === accLogin);
  const accStats = $derived(accKey ? {
    prs: [...(store.s?.prs || []).filter(p => !p.archived), ...(store.s?.myPrs || [])].filter(accMine).length,
    builds: (store.s?.builds || []).filter(b => accMine(b) && b.status !== "completed").length,
    failed: (store.s?.builds || []).filter(b => accMine(b) && b.result === "failed").length,
    deploys: (store.s?.deploys || []).filter(accMine).length,
  } : null);
  const accMode = $derived(accKey ? repos.trackMode(accKey) : "all");
  async function trackVisible(on: boolean) {
    const keys = list.map(r => (r.remoteKey || r.key).toLowerCase());
    if (!keys.length) return;
    try { await repos.setTrackMany(keys, on); store.refreshSoon(2500); ui.toast(on ? `${keys.length} repositório(s) acompanhados` : `${keys.length} repositório(s) deixaram de ser acompanhados`); }
    catch (e) { ui.error(e); }
  }
  let discovering = $state(false);
  async function discoverNow() {
    discovering = true;
    try { const r = await post<{ new: number }>("repos/discover"); await repos.load(); ui.toast(r.new ? `${r.new} repositório(s) novo(s) encontrado(s) nas pastas base` : "Nenhum clone novo nas pastas base", r.new ? "ok" : "info"); }
    catch (e) { ui.error(e); }
    discovering = false;
  }
</script>

<Page title={catalogId ? view?.name || (isAccount ? catalogId.split(":").pop() || "" : "Catálogo") : tagName ? tagName : favMode ? "Favoritos" : "Repositórios"}
  sub={catalogId ? (view ? `${view.counts.cloned} de ${view.counts.total} clonados${isAccount && view.dirs?.length ? " · " + view.dirs.map(d => d.replace(/^\/Users\/[^/]+/, "~")).join(", ") : ""}` : "carregando…")
    : favMode ? `${favCounts.cloned} de ${favCounts.all} clonados · GitHub e Azure DevOps juntos`
    : "Seus repositórios locais, favoritos e catálogos de GitHub e Azure DevOps"}>
  {#snippet actions()}
    {#if favMode}
      <button class="btn sm" onclick={() => (editing = "new")}><Plus size={14} /> Novo catálogo</button>
      <button class="btn sm primary" onclick={() => { searching = true; sq = ""; }}><Search size={14} /> Adicionar repositório</button>
    {:else if catalogId && view}
      <button class="btn sm ghost" onclick={() => loadCatalog(true)} title="Ler a lista de novo"><RefreshCw size={14} /></button>
      {#if counts?.notCloned}<button class="btn sm" onclick={cloneAll}><Download size={14} /> Clonar todos ({counts.notCloned})</button>{/if}
      {#if isAccount}<button class="btn sm" onclick={() => (ui.editAccount = catalogId!.slice(8))}><Settings2 size={14} /> Detalhes e ajustes</button>
      {:else}<button class="btn sm" onclick={() => (editing = "edit")}><Pencil size={14} /> Editar</button>{/if}
      <button class="btn sm" onclick={() => (editing = "new")}><Plus size={14} /> Novo catálogo</button>
    {:else}
      <button class="btn sm ghost" onclick={discoverNow} disabled={discovering} title="Vasculha de novo as pastas base das contas"><FolderSearch size={14} class={discovering ? "spin" : ""} /> Procurar clones</button>
      <button class="btn sm" onclick={() => (adding = true)}><FolderPlus size={14} /> Adicionar local</button>
      <button class="btn sm primary" onclick={() => (editing = "new")}><Plus size={14} /> Novo catálogo</button>
    {/if}
  {/snippet}

  <div class="layout">
    <div class="main">
      <Toolbar bind:query={q} placeholder={catalogId ? "Buscar no catálogo…" : favMode ? "Buscar nos favoritos (nome, tag)…" : "Buscar repositório local…"}>
        {#snippet left()}
          {#if favMode}
            <Segmented bind:value={filter} options={[{ value: "all", label: "Todos", count: favCounts.all }, { value: "cloned", label: "Clonados", count: favCounts.cloned },
              { value: "not", label: "Não clonados", count: favCounts.notCloned }]} />
          {:else if catalogId}
            <Segmented bind:value={filter} options={[{ value: "all", label: "Todos", count: counts?.all ?? "…" }, { value: "tracked", label: "Acompanhados", count: counts?.tracked ?? "…" },
              { value: "untracked", label: "Não acompanhados", count: counts ? counts.all - counts.tracked : "…" },
              { value: "cloned", label: "Clonados", count: counts?.cloned ?? "…" }, { value: "not", label: "Não clonados", count: counts?.notCloned ?? "…" }]} onchange={() => soft(() => {})} />
          {:else}
            <Segmented bind:value={filter} options={[{ value: "all", label: "Todos", count: repos.local.length },
              { value: "dirty", label: "Com alterações", count: repos.local.filter(r => (r.status?.changes || 0) > 0).length },
              { value: "ahead", label: "Para sincronizar", count: repos.local.filter(r => (r.status?.ahead || 0) + (r.status?.behind || 0) > 0).length }]} />
          {/if}
        {/snippet}
      </Toolbar>
      {#if accKey && accStats}
        <div class="acchead card">
          {#if accAvatar}<Avatar name={accLogin} src={accAvatar} size={38} />{:else}<span class="aic"><ProviderIcon provider={accProv || null} size={20} /></span>{/if}
          <button class="who" onclick={() => (ui.editAccount = accKey)} title="Detalhes e ajustes da conta">
            <b>{accLogin}</b><span class="tiny muted">{accProv === "azure" ? "Azure DevOps" : "GitHub"} · {view?.dirs?.length ? view.dirs.map(d => d.replace(/^\/Users\/[^/]+/, "~")).join(", ") : "sem pasta base"}</span>
          </button>
          <div class="st"><b>{accStats.prs}</b><span>PRs</span></div>
          <div class="st" class:hot={accStats.builds}><b>{accStats.builds}</b><span>rodando</span></div>
          <div class="st" class:bad={accStats.failed}><b>{accStats.failed}</b><span>falhos</span></div>
          <div class="st"><b>{accStats.deploys}</b><span>deploys</span></div>
          <div class="mode">
            <span class="tiny muted">Acompanhar</span>
            <Segmented size="sm" value={accMode} onchange={async (m) => { await repos.setTrackMode(accKey!, m as any); store.refreshSoon(2500); }}
              options={[{ value: "all", label: "Todos" }, { value: "selected", label: "Escolhidos" }]} />
          </div>
          <button class="btn sm" onclick={() => (ui.editAccount = accKey)}><Settings2 size={13} /> Ajustes</button>
        </div>
        {#if list.length}
          <div class="bulk small muted">
            <span>{counts?.tracked ?? 0} de {counts?.all ?? 0} acompanhados{accMode === "selected" ? " (só os escolhidos)" : ""}</span>
            <span class="grow"></span>
            <button class="btn sm ghost" onclick={() => trackVisible(true)}><Eye size={13} /> Acompanhar os {list.length} listados</button>
            <button class="btn sm ghost" onclick={() => trackVisible(false)}><EyeOff size={13} /> Deixar de acompanhar os listados</button>
          </div>
        {/if}
      {/if}
      <div class="card scroll">
        {#if favMode}
          {#if !repos.loaded}<Skeleton rows={6} />
          {:else}
            {#each favList as r (r.key)}<RepoRow remote={r} job={jobs[r.key]} onclone={() => cloneFav(r)} />
            {:else}
              <Empty title={q || filter !== "all" ? "Nada com esses filtros" : tagName ? `Nenhum favorito com a tag ${tagName}` : "Nenhum favorito ainda"}
                text={q || filter !== "all" ? "" : "Favorite repositórios de qualquer conta — GitHub e Azure DevOps juntos — e organize com tags."}>
                {#if !q && filter === "all"}<button class="btn primary" onclick={() => { searching = true; sq = ""; }}><Search size={14} /> Buscar nas contas</button>{/if}
              </Empty>
            {/each}
          {/if}
        {:else if catalogId}
          {#if loading || !view}<Skeleton rows={9} />
          {:else}
            {#if view.staleSince}<div class="stale"><WifiOff size={14} /> Sem conexão — mostrando a lista lida às {new Date(view.staleSince * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}.</div>{/if}
            {#each Object.entries(view.errors) as [k, e] (k)}<div class="err">{k}: {e}</div>{/each}
            {#each list as r (r.key)}<RepoRow remote={r} job={jobs[r.key]} onclone={() => clone(r.key)} onchanged={() => loadCatalog()} />
            {:else}<Empty title={q ? "Nada encontrado" : filter === "not" ? "Tudo clonado" : "Catálogo vazio"} done={filter === "not" && !q} text={view.sources.length ? "" : "Edite o catálogo e escolha as origens."} />{/each}
          {/if}
        {:else if !repos.loaded}<Skeleton rows={8} />
        {:else}
          {#each locals as r (r.id)}<RepoRow local={r} />
          {:else}
            <Empty title={q || filter !== "all" ? "Nada com esses filtros" : "Nenhum repositório local ainda"} text="Adicione uma pasta, procure repositórios dentro de uma pasta ou crie um catálogo para clonar.">
              <button class="btn" onclick={addFolder}><FolderPlus size={14} /> Adicionar pasta</button>
              <button class="btn primary" onclick={() => (editing = "new")}><Plus size={14} /> Novo catálogo</button>
            </Empty>
          {/each}
        {/if}
      </div>
    </div>
  </div>
</Page>

{#if editing}
  <CatalogEditor catalog={editing === "edit" ? view : null} onclose={() => { editing = null; if (router.parts[1] === "new-catalog") go("/repos", "soft"); loadCatalog(); setTimeout(() => repos.load(false), 2500); }} />
{/if}

{#if searching}
  <Drawer title={tagName ? `Adicionar a ${tagName}` : "Adicionar aos favoritos"} subtitle="Busca em todas as contas conectadas — GitHub e Azure DevOps" onclose={() => (searching = false)} width={560}>
    <!-- svelte-ignore a11y_autofocus -->
    <label class="sbox"><Search size={15} /><input bind:value={sq} placeholder="nome do repositório, dono ou projeto…" autofocus />{#if sLoading}<RefreshCw size={13} class="spin" />{/if}</label>
    {#each Object.entries(sErrors) as [k, e] (k)}<div class="err">{k}: {e}</div>{/each}
    <div class="results">
      {#each results as r (r.key)}
        <div class="res" class:fav={!!repos.fav(r.remoteKey || r.key)}>
          <ProviderIcon provider={r.provider} size={15} />
          <div class="grow"><div class="ell"><b>{r.name}</b> <span class="muted small">{r.owner}</span></div>{#if r.description}<div class="small muted ell">{r.description}</div>{/if}</div>
          <FavStar repo={r} tags={tagName ? [tagName] : []} />
        </div>
      {:else}
        {#if !sLoading}<div class="small muted pad">{sq ? "Nada encontrado." : "Digite para buscar."}</div>{/if}
      {/each}
    </div>
    {#if tagName}<p class="small muted">Ao favoritar daqui, o repositório já entra com a tag <b>{tagName}</b>.</p>{/if}
  </Drawer>
{/if}

{#if adding}
  <Drawer title="Adicionar repositório local" subtitle="Registre clones que já existem ou clone um novo" onclose={() => { adding = false; if (router.parts[1] === "add") go("/repos", "soft"); }} width={520}>
    <div class="opts">
      <button class="opt" onclick={addFolder}><FolderPlus size={20} /><div><b>Uma pasta</b><small>Escolha a pasta de um repositório Git que já existe.</small></div></button>
      <button class="opt" onclick={scanFolder}><FolderSearch size={20} /><div><b>Procurar numa pasta</b><small>Encontra todos os repositórios dentro de uma pasta (até 3 níveis).</small></div></button>
      <div class="opt static"><Link size={20} /><div class="grow"><b>Clonar por URL</b><small>https ou ssh. A credencial vem das contas conectadas no app.</small>
        <input class="input mono" bind:value={cloneUrl} placeholder="https://github.com/dono/repo.git" />
        <input class="input mono" bind:value={cloneDest} placeholder="pasta de destino (vazio = escolher)" />
        <button class="btn primary sm" disabled={!cloneUrl.trim()} onclick={cloneByUrl}><Download size={13} /> Clonar</button></div></div>
    </div>
  </Drawer>
{/if}

<style>
  .acchead { display: flex; align-items: center; gap: 14px; padding: 12px 14px; margin-bottom: 10px; flex-wrap: wrap; }
  .aic { width: 38px; height: 38px; border-radius: 11px; display: grid; place-items: center; background: var(--surface-2); border: 1px solid var(--line-2); }
  .acchead .who { display: grid; text-align: left; border: 0; background: none; color: var(--text); font: 14px var(--font); cursor: pointer; min-width: 0; flex: 1; padding: 0; }
  .acchead .who:hover b { color: var(--accent); }
  .acchead .st { display: grid; justify-items: center; min-width: 54px; }
  .acchead .st b { font-size: 17px; font-variant-numeric: tabular-nums; }
  .acchead .st span { font-size: 11px; color: var(--muted); }
  .acchead .st.hot b { color: var(--accent); } .acchead .st.bad b { color: var(--bad); }
  .acchead .mode { display: grid; gap: 3px; }
  .bulk { display: flex; align-items: center; gap: 6px; margin: -2px 2px 8px; flex-wrap: wrap; }
  .bulk .grow { flex: 1; }
  .sbox { display: flex; align-items: center; gap: 9px; height: 38px; padding: 0 12px; margin-top: 12px; border-radius: 10px; border: 1px solid var(--line-2);
    background: var(--bg-2); color: var(--muted); }
  .sbox:focus-within { border-color: var(--accent); box-shadow: var(--ring); }
  .sbox input { flex: 1; border: 0; outline: none; background: none; color: var(--text); font: 14px var(--font); }
  .results { display: grid; gap: 2px; margin-top: 10px; }
  .res { display: flex; align-items: center; gap: 11px; padding: 8px 10px; border-radius: 9px; transition: background var(--t); animation: rise 0.25s var(--ease-out) both; }
  .res:hover { background: var(--surface-2); }
  .res.fav { background: color-mix(in srgb, var(--warn-soft) 60%, transparent); }
  .res .grow { min-width: 0; flex: 1; }
  .pad { padding: 14px 4px; }
  .layout { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .main { min-height: 0; display: flex; flex-direction: column; }
  .scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; }
  .stale { display: flex; align-items: center; gap: 8px; margin: 10px 16px 0; padding: 8px 12px; border-radius: 9px; background: var(--warn-soft); color: var(--warn); font-size: 12.5px; }
  .err { margin: 10px 16px 0; padding: 8px 12px; border-radius: 9px; background: var(--bad-soft); color: var(--bad); font-size: 12.5px; }
  .opts { display: grid; gap: 10px; padding-top: 14px; }
  .opt { display: flex; gap: 14px; align-items: flex-start; text-align: left; padding: 14px; border-radius: 12px; border: 1px solid var(--line-2); background: var(--surface-2);
    color: var(--text); font: 13px var(--font); cursor: pointer; transition: border-color var(--t), transform var(--t-fast); }
  .opt:not(.static):hover { border-color: var(--accent); transform: translateY(-1px); }
  .opt.static { cursor: default; }
  .opt :global(svg) { color: var(--accent); flex-shrink: 0; margin-top: 2px; }
  .opt b { display: block; margin-bottom: 2px; }
  .opt small { display: block; color: var(--muted); margin-bottom: 8px; }
  .opt .grow { display: grid; gap: 8px; }
  .opt .grow small { margin-bottom: 0; }
</style>
