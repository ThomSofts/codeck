<script lang="ts">
  // Repositório (estilo GitKraken): branches | graph | alterações ou commit; diff no centro; sincronização no topo.
  import { ArrowDown, ArrowLeft, ArrowUp, Code2, Copy, ExternalLink, FolderOpen, GitBranch, GitBranchPlus, GitMerge, GitPullRequestCreate, RefreshCw, RotateCcw, Search, Tag as TagIcon, Terminal, Undo2 } from "@lucide/svelte";
  import { onDestroy, untrack } from "svelte";
  import { get, post } from "../lib/api";
  import { fileManagerName } from "../lib/native";
  import { repos } from "../lib/repos.svelte";
  import { go, router } from "../lib/router.svelte";
  import { store } from "../lib/store.svelte";
  import type { Commit, FileChange, Refs, RepoStatus } from "../lib/types";
  import { ui } from "../lib/ui.svelte";
  import Empty from "../components/Empty.svelte";
  import Menu from "../components/Menu.svelte";
  import ProviderIcon from "../components/ProviderIcon.svelte";
  import BranchesPanel from "../components/repo/BranchesPanel.svelte";
  import ChangesPanel from "../components/repo/ChangesPanel.svelte";
  import CommitPanel from "../components/repo/CommitPanel.svelte";
  import CreatePr from "../components/repo/CreatePr.svelte";
  import DiffView from "../components/repo/DiffView.svelte";
  import Graph from "../components/repo/Graph.svelte";

  // Repositório = projeto: esta tela é a aba "Git" do projeto (ou da tarefa, com o worktree dela)
  let { repoId = undefined, embedded = false }: { repoId?: string; embedded?: boolean } = $props();
  const id = $derived(repoId ?? router.parts[1]);
  // repositório recém-registrado (ex.: o worktree de uma tarefa nova) ainda fora da lista carregada: relê uma vez
  let reloaded = "";
  $effect(() => { const i = id; if (i && repos.loaded && !repos.byId(i) && reloaded !== i) { reloaded = i; repos.load(false); } });
  const repo = $derived(repos.byId(id));
  let status = $state<RepoStatus | null>(null);
  let refs = $state<Refs | null>(null);
  let commits = $state<Commit[]>([]);
  let head = $state<string | null>(null);
  let hasMore = $state(false);
  let sel = $state<string | "wip" | null>(null);
  let diff = $state<{ title: string; text: string; binary: boolean; truncated: boolean } | null>(null);
  let focusBranch = $state<string | null>(null);
  let search = $state("");
  let busy = $state<string | null>(null);
  let prFrom = $state<string | null>(null);
  let error = $state<string | null>(null);
  let limit = 400;

  async function loadAll() {
    try {
      const [st, rf, gr] = await Promise.all([
        get<RepoStatus>("repo/status", { id }), get<Refs>("repo/refs", { id }),
        get<{ commits: Commit[]; head: string; hasMore: boolean }>("repo/graph", { id, limit, search: search || undefined }),
      ]);
      status = st; refs = rf; commits = gr.commits; head = gr.head; hasMore = gr.hasMore; error = null;
      if (sel === null) sel = st.dirty ? "wip" : gr.commits[0]?.sha || null;
      if (sel === "wip" && !st.dirty) sel = gr.commits[0]?.sha || null;
    } catch (e: any) { error = e.message; }
  }
  async function refreshStatus() {
    if (store.hold || busy) return;
    try {
      const st = await get<RepoStatus>("repo/status", { id });
      const changed = JSON.stringify([st.head, st.branch, st.ahead, st.behind]) !== JSON.stringify([status?.head, status?.branch, status?.ahead, status?.behind]);
      status = st;
      if (changed) loadAll();
    } catch { /* repositório pode estar ocupado */ }
  }
  $effect(() => {
    void id;   // só a troca de repositório recarrega tudo
    untrack(() => { status = null; refs = null; commits = []; sel = null; diff = null; loadAll(); if (!repos.loaded) repos.load(false); });
  });
  const timer = setInterval(refreshStatus, 5000);
  onDestroy(() => clearInterval(timer));

  async function run(label: string, path: string, payload: Record<string, unknown> = {}, ok?: string) {
    busy = label;
    try {
      await post("repo/" + path, { id, ...payload });
      if (ok) ui.toast(ok);
      await loadAll();
      repos.load();
    } catch (e) { ui.error(e); }
    busy = null;
  }
  async function openFile(f: FileChange, staged: boolean) {
    try {
      const d = await get("repo/diff", { id, path: f.path, staged: staged ? 1 : 0 });
      diff = { title: f.path, text: d.diff, binary: d.binary, truncated: d.truncated };
    } catch (e) { ui.error(e); }
  }
  async function openCommitFile(f: FileChange) {
    try {
      const d = await get("repo/diff", { id, path: f.path, sha: sel as string });
      diff = { title: f.path, text: d.diff, binary: d.binary, truncated: d.truncated };
    } catch (e) { ui.error(e); }
  }
  // veio da PR ("Commits da branch"): destaca a branch dela no graph assim que as refs chegam
  $effect(() => {
    const bi = repos.branchIntent;
    if (bi && bi.repoId === id && refs) untrack(() => {
      const has = refs!.local.some(b => b.name === bi.branch) || refs!.remote.some(b => b.name.split("/").slice(1).join("/") === bi.branch);
      if (has) focusBranch = bi.branch;
      else ui.toast(`${bi.branch} ainda não está nesta cópia — faça um fetch`, "info");
      repos.branchIntent = null;
    });
  });
  // veio de uma tarefa com "Criar PR": abre o formulário assim que souber a branch
  $effect(() => {
    if (repos.prIntent === id && status?.branch) { prFrom = status.branch; repos.prIntent = null; }
  });
  async function newBranch(start?: string, from?: string) {
    const name = await ui.ask({ title: from ? `Nova branch a partir de ${from}` : start ? "Criar branch a partir deste commit" : "Nova branch", input: { label: "Nome da branch", placeholder: "feature/minha-mudanca", required: true }, confirm: "Criar e fazer checkout" });
    if (name) run("branch", "branch-create", { name: name.trim(), start }, `Branch ${name} criada`);
  }
  async function commitAction(a: string, sha: string) {
    if (a === "branch") return newBranch(sha);
    const label = a === "cherry-pick" ? "Cherry-pick" : "Revert";
    if (await ui.ask({ title: `${label} de ${sha.slice(0, 8)} em ${status?.branch}?`, confirm: label })) run(a, a, { sha }, `${label} feito`);
  }
  async function branchAction(a: string, name: any) {
    if (a === "checkout") return run("checkout", "checkout", { ref: name }, `Agora em ${name}`);
    if (a === "track") return run("checkout", "checkout", { track: name }, `Branch ${name.split("/").slice(1).join("/")} criada`);
    if (a === "merge") { if (await ui.ask({ title: `Merge de ${name} em ${status?.branch}?`, confirm: "Fazer merge" })) run("merge", "merge", { ref: name }, "Merge feito"); return; }
    if (a === "pr") { prFrom = name; return; }
    if (a === "update") return run("update", "branch-update", { name }, name === status?.branch ? "Branch atualizada" : `${name} atualizada sem checkout`);
    if (a === "push-branch") return run("push", "branch-push", { name }, `${name} enviada`);
    if (a === "branch-from") return newBranch(name, name);
    if (a === "rebase") {
      if (await ui.ask({ title: `Rebase de ${status?.branch} sobre ${name}?`, message: "Reescreve os commits da branch atual por cima de " + name + ". Se ela já foi enviada, o próximo push precisa ser forçado.", confirm: "Fazer rebase" }))
        run("rebase", "rebase", { onto: name }, "Rebase feito");
      return;
    }
    if (a === "tag-push") return run("tag", "tag-push", { name }, `Tag ${name} enviada`);
    if (a === "tag-delete" || a === "tag-delete-remote") {
      const remote = a === "tag-delete-remote";
      if (await ui.ask({ title: remote ? `Apagar a tag ${name} no servidor?` : `Apagar a tag local ${name}?`, confirm: "Apagar", danger: true }))
        run("tag", "tag-delete", { name, remote }, `Tag ${name} apagada${remote ? " no servidor" : ""}`);
      return;
    }
    if (a === "rename") { const n = await ui.ask({ title: `Renomear ${name}`, input: { label: "Novo nome", value: name, required: true }, confirm: "Renomear" }); if (n) run("rename", "branch-rename", { old: name, new: n }); return; }
    if (a === "delete") {
      if (!(await ui.ask({ title: `Apagar a branch local ${name}?`, message: "Se ela tiver commits que não estão em outra branch, o Git avisa antes.", confirm: "Apagar", danger: true }))) return;
      try { await post("repo/branch-delete", { id, name }); ui.toast(`${name} apagada`); }
      catch (e: any) {
        if (!/not fully merged|não.*mesclad/i.test(e.message || "")) return ui.error(e);
        if (!(await ui.ask({ title: `${name} tem commits que não estão em nenhuma outra branch`, message: "Apagar mesmo assim perde esses commits (a não ser que estejam no servidor).", confirm: "Apagar mesmo assim", danger: true }))) return;
        try { await post("repo/branch-delete", { id, name, force: true }); ui.toast(`${name} apagada`); } catch (e2) { ui.error(e2); }
      }
      return loadAll();
    }
    if (a === "delete-remote") {
      if (await ui.ask({ title: `Apagar ${name} no servidor?`, message: "Isso remove a branch para todo mundo.", confirm: "Apagar no servidor", danger: true }))
        run("delete", "branch-delete", { name, remote: true }, `${name} apagada no servidor`);
      return;
    }
    if (a.startsWith("stash-")) return run("stash", "stash", { action: a.slice(6), ref: name }, "Stash aplicado");
    if (a === "tidy") { repos.load(); return loadAll(); }   // a limpeza (BranchCleanup) já apagou: só relê
  }
  function contextCommit(c: Commit, e: MouseEvent) {
    sel = c.sha;
    const short = c.sha.slice(0, 8);
    ui.contextMenu(e, [
      { heading: `${short} · ${c.subject.slice(0, 40)}` },
      { label: "Nova branch a partir daqui…", icon: GitBranchPlus, onclick: () => newBranch(c.sha) },
      { label: "Criar tag aqui…", icon: TagIcon, onclick: async () => { const n = await ui.ask({ title: `Tag em ${short}`, input: { label: "Nome da tag", placeholder: "v1.2.0", required: true }, confirm: "Criar tag" }); if (n) run("tag", "tag", { name: n.trim(), sha: c.sha }, `Tag ${n} criada`); } },
      { label: "Checkout deste commit (detached)", icon: GitBranch, onclick: () => run("checkout", "checkout", { ref: c.sha }, `Agora em ${short}`) },
      { separator: true },
      { label: `Cherry-pick em ${status?.branch}`, icon: GitMerge, onclick: () => commitAction("cherry-pick", c.sha), disabled: !status?.branch },
      { label: "Reverter (revert)", icon: Undo2, onclick: () => commitAction("revert", c.sha), disabled: !status?.branch },
      { label: `Mover ${status?.branch} para cá (reset)…`, icon: RotateCcw, danger: true, onclick: () => resetTo(c.sha), disabled: !status?.branch },
      { separator: true },
      { label: "Copiar SHA", icon: Copy, onclick: async () => { await navigator.clipboard.writeText(c.sha); ui.toast("SHA copiado"); } },
      { label: "Copiar mensagem", icon: Copy, onclick: async () => { await navigator.clipboard.writeText(c.subject); ui.toast("Mensagem copiada"); } },
    ]);
  }
  async function resetTo(sha: string) {
    const mode = await ui.ask({ title: `Mover ${status?.branch} para ${sha.slice(0, 8)}?`, message: "soft = mantém tudo preparado · mixed = mantém as alterações · hard = descarta tudo",
      input: { label: "Modo (soft, mixed ou hard)", value: "mixed", required: true }, confirm: "Mover", danger: true });
    if (mode && ["soft", "mixed", "hard"].includes(mode.trim())) run("reset", "reset", { sha, mode: mode.trim() }, "Branch movida");
  }
  async function open(target: string) { try { await post("open", { id, target }); } catch (e) { ui.error(e); } }
  async function sync(kind: "fetch" | "pull" | "push") {
    const labels = { fetch: ["Buscando…", "Atualizado com o servidor"], pull: ["Recebendo…", "Branch atualizada"], push: ["Enviando…", "Enviado"] };
    run(kind, kind, {}, labels[kind][1]);
  }
  const switchItems = $derived(refs ? [
    { heading: "Trocar de branch" },
    ...refs.local.slice(0, 14).map(b => ({ label: b.name, icon: GitBranch, onclick: () => branchAction("checkout", b.name), disabled: b.name === refs!.current })),
    { separator: true },
    { label: "Nova branch…", icon: GitBranchPlus, onclick: () => newBranch() },
  ] : []);
</script>

<section class="repo" class:embedded>
  {#if !repo && repos.loaded}
    <Empty title="Repositório não encontrado" text="Ele pode ter sido removido da lista."><button class="btn" onclick={() => go("/repos")}>Ver repositórios</button></Empty>
  {:else}
    <header class="rh">
      {#if !embedded}<button class="btn ghost icon" title="Voltar" onclick={() => history.length > 1 ? history.back() : go("/repos")}><ArrowLeft size={17} /></button>{/if}
      <div class="title">
        <div class="row" style="gap:8px"><ProviderIcon provider={repo?.provider} size={15} /><h1 class="ell">{repo?.name || "…"}</h1></div>
        <div class="path ell" title={repo?.path}>{repo?.path?.replace(/^\/Users\/[^/]+/, "~")}</div>
      </div>
      {#if status}
        <Menu items={switchItems} align="left">
          {#snippet trigger()}<span class="btn branch-btn"><GitBranch size={14} /><b>{status!.detached ? "detached" : status!.branch}</b></span>{/snippet}
        </Menu>
      {/if}
      <span class="spacer"></span>
      <div class="sync">
        <button class="btn sm" disabled={!!busy} onclick={() => sync("fetch")} title="Buscar novidades do servidor"><RefreshCw size={13} class={busy === "fetch" ? "spin" : ""} /> Fetch</button>
        <button class="btn sm" disabled={!!busy || !status?.upstream} onclick={() => sync("pull")} title="Receber commits"><ArrowDown size={13} /> Pull{#if status?.behind}<span class="n">{status.behind}</span>{/if}</button>
        <button class="btn sm" class:primary={!!status?.ahead || (!!status && !status.upstream && !!status.branch)} disabled={!!busy || !status?.branch} onclick={() => sync("push")} title="Enviar commits">
          <ArrowUp size={13} /> Push{#if status?.ahead}<span class="n">{status.ahead}</span>{/if}</button>
      </div>
      <div class="opens">
        <button class="btn sm" onclick={() => open("editor")} title="Abrir no editor"><Code2 size={14} /> {store.s?.editor === "cursor" ? "Cursor" : "VS Code"}</button>
        <button class="btn sm ghost icon" onclick={() => open("files")} title={`Abrir no ${fileManagerName()}`}><FolderOpen size={15} /></button>
        <button class="btn sm ghost icon" onclick={() => open("terminal")} title="Abrir no terminal"><Terminal size={15} /></button>
        {#if repo?.webUrl}<a class="btn sm ghost icon" href={repo.webUrl} target="_blank" rel="noopener" title="Abrir no navegador"><ExternalLink size={15} /></a>{/if}
        {#if refs && status?.branch && status.branch !== refs.default && repo?.provider}
          <button class="btn sm brand" onclick={() => (prFrom = status!.branch)}><GitPullRequestCreate size={14} /> Criar PR</button>
        {/if}
      </div>
    </header>

    {#if status?.operation}
      <div class="op">⚠ <b>{status.operation}</b> em andamento{#if status.conflicts.length} — {status.conflicts.length} arquivo(s) com conflito: resolva no editor, prepare e continue{/if}.
        <span class="spacer"></span>
        <button class="btn sm" onclick={() => open("editor")}>Abrir no editor</button>
        <button class="btn sm" disabled={!!status.conflicts.length} onclick={() => run("continue", "continue", {}, "Continuado")}>Continuar</button>
        <button class="btn sm danger" onclick={() => run("abort", "abort", {}, "Operação cancelada")}>Abortar</button></div>
    {/if}
    {#if error}<div class="err">{error}</div>{/if}

    <div class="cols">
      <aside class="card side">{#if refs}<BranchesPanel {refs} repoId={id} canPr={!!repo?.provider} onaction={branchAction} onfocus={(n) => (focusBranch = n)} focused={focusBranch} />{:else}<div class="sk"><i class="shim"></i><i class="shim"></i><i class="shim"></i></div>{/if}</aside>

      <div class="card center">
        {#if diff}
          <div class="dh"><button class="btn sm ghost" onclick={() => (diff = null)}><ArrowLeft size={14} /> Graph</button><span class="mono ell">{diff.title}</span></div>
          <div class="dscroll"><DiffView diff={diff.text} binary={diff.binary} truncated={diff.truncated} /></div>
        {:else}
          <div class="gh"><span class="gtitle">Histórico</span>
            <label class="gsearch"><Search size={13} /><input bind:value={search} placeholder="Buscar mensagem…" onkeydown={(e) => e.key === "Enter" && loadAll()} /></label>
            {#if focusBranch}<button class="pill accent" onclick={() => (focusBranch = null)}>destacando {focusBranch} ✕</button>{/if}
          </div>
          <div class="gscroll">
            {#if !commits.length && !error}<div class="sk"><i class="shim"></i><i class="shim"></i><i class="shim"></i><i class="shim"></i></div>
            {:else}
              <Graph {commits} {head} selected={sel} wip={status?.dirty ? status.staged.length + status.unstaged.length + status.untracked.length + status.conflicts.length : 0}
                onselect={(s) => { sel = s; diff = null; }} oncontext={contextCommit} highlight={focusBranch} />
              {#if hasMore}<div class="more"><button class="btn sm" onclick={() => { limit += 400; loadAll(); }}>Carregar mais commits</button></div>{/if}
            {/if}
          </div>
        {/if}
      </div>

      <aside class="card right">
        {#if sel === "wip" && status}
          <ChangesPanel repoId={id} {status} onopen={openFile} onchanged={loadAll} />
        {:else if sel}
          {#key sel}<CommitPanel repoId={id} sha={sel} onopen={openCommitFile} onaction={commitAction} />{/key}
          <div class="extra"><button class="btn sm ghost" onclick={() => resetTo(sel as string)}>Mover {status?.branch} para cá…</button></div>
        {:else}<Empty title="Selecione um commit" />{/if}
      </aside>
    </div>
  {/if}
</section>

{#if prFrom && repo && refs}
  <CreatePr {repo} {refs} source={prFrom} onclose={() => (prFrom = null)} ondone={loadAll} />
{/if}

<style>
  .repo { height: 100%; display: flex; flex-direction: column; padding: 14px 18px 18px; gap: 12px; }
  .repo.embedded { padding: 10px 10px 10px; }
  .embedded h1 { font-size: 15px; }
  .rh { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; flex: none; }
  .title { min-width: 0; max-width: 360px; }
  h1 { margin: 0; font-size: 19px; letter-spacing: -0.025em; }
  .path { font: 11.5px var(--mono); color: var(--muted); }
  .branch-btn { height: 30px; font: 12.5px var(--mono); }
  .branch-btn :global(svg) { color: var(--good); }
  .sync, .opens { display: flex; gap: 6px; align-items: center; }
  .n { font: 700 10.5px/1 var(--font); padding: 2px 5px; border-radius: 99px; background: rgba(255, 255, 255, 0.2); }
  .op { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 9px 12px; border-radius: 10px; background: var(--warn-soft); color: var(--warn); font-size: 13px; flex: none; }
  .op b { color: var(--text); }
  .err { padding: 9px 12px; border-radius: 10px; background: var(--bad-soft); color: var(--bad); font-size: 13px; flex: none; }
  .cols { flex: 1; min-height: 0; display: grid; grid-template-columns: 220px minmax(0, 1fr) 360px; gap: 12px; }
  .card { min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
  .center { min-width: 0; }
  .gh, .dh { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-bottom: 1px solid var(--line); flex: none; }
  .gtitle { font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
  .gsearch { display: flex; align-items: center; gap: 6px; height: 27px; padding: 0 9px; border-radius: 7px; border: 1px solid var(--line); background: var(--bg-2); color: var(--muted); margin-left: auto; }
  .gsearch input { border: 0; outline: none; background: none; color: var(--text); font: 12.5px var(--font); width: 170px; }
  .gscroll, .dscroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; }
  .dscroll { padding: 12px; }
  .more { padding: 12px; text-align: center; }
  .extra { padding: 8px 14px; border-top: 1px solid var(--line); }
  .sk { display: grid; gap: 10px; padding: 14px; }
  .sk i { height: 22px; }
  @media (max-width: 1280px) { .cols { grid-template-columns: 200px minmax(0, 1fr) 330px; } }
  @media (max-width: 1080px) { .cols { grid-template-columns: minmax(0, 1fr) 320px; } .side { display: none; } }
</style>
