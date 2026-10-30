<script lang="ts">
  // Gestão de um repositório: o que acompanhar (PRs, builds, deploys, issues e notificações), o que está acontecendo
  // nele agora, a pasta local (abrir, mover para outra pasta, clonar, limpar) e a organização (grupo, favorito, tags).
  import { ArrowDown, ArrowUp, Bell, BellOff, CircleDot, Code2, Download, Eye, EyeOff, ExternalLink, FolderInput, FolderOpen, GitBranch, GitPullRequest,
    Hammer, Layers, Lock, Pin, PinOff, Play, Rocket, Bot, Terminal, Trash2 } from "@lucide/svelte";
  import { get, post } from "../../lib/api";
  import { ago } from "../../lib/format";
  import { fileManagerName, pickFolder } from "../../lib/native";
  import { repos, type TrackCat } from "../../lib/repos.svelte";
  import { go } from "../../lib/router.svelte";
  import { store } from "../../lib/store.svelte";
  import type { LocalRepo, RemoteRepo } from "../../lib/types";
  import { ui } from "../../lib/ui.svelte";
  import { work } from "../../lib/work.svelte";
  import { buildState } from "../build/status";
  import Drawer from "../Drawer.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import Switch from "../Switch.svelte";
  import FavStar from "./FavStar.svelte";
  import TagPicker from "./TagPicker.svelte";

  const req = $derived(ui.repoHub!);
  const local = $derived<LocalRepo | null>(req.localId ? repos.byId(req.localId) || null : (req.remote?.local?.id ? repos.byId(req.remote.local.id) || null : null));
  const remote = $derived<RemoteRepo | null>(req.remote || null);
  const key = $derived(((remote?.remoteKey || remote?.key || local?.remoteKey || "") as string).toLowerCase() || null);
  const trackable = $derived(!!key && /^(github|azure):/.test(key));
  const accountKey = $derived(remote?.accountKey || (local ? repos.accountOf(local) : null));
  const t = $derived(repos.track(key, accountKey));
  const name = $derived(remote?.name || local?.name || "repositório");
  const provider = $derived((remote?.provider || local?.provider || null) as any);
  const web = $derived(remote?.webUrl || local?.webUrl || null);
  const favKey = $derived(repos.keyOf((remote || local)!));
  const isFav = $derived(!!repos.fav(favKey));
  const st = $derived(local?.status);
  const home = (p: string) => p.replace(/^\/Users\/[^/]+|^C:\\Users\\[^\\]+/i, "~");

  // o que está acontecendo no repositório (das listas que o app já lê)
  const mine = <T extends { repoKey?: string | null }>(xs: T[] | undefined) => (key ? (xs || []).filter(x => (x.repoKey || "").toLowerCase() === key) : []);
  const prs = $derived(mine([...(store.s?.myPrs || []), ...(store.s?.prs || []).filter(p => !p.archived)]));
  const builds = $derived(mine(store.s?.builds).slice(0, 6));
  const deploys = $derived(mine(store.s?.deploys));
  // work item do Azure não tem repositório: vale o projeto ("azure:org/projeto") — desligar aqui não mexe no resto
  const projKey = $derived(provider === "azure" && key ? key.split("/").slice(0, -1).join("/") : null);
  const projIssues = $derived(projKey ? repos.tracking.repos[projKey]?.issues !== false : true);
  const issues = $derived(projKey ? (store.s?.issues || []).filter(i => (i.scopeKey || "").toLowerCase() === projKey) : mine(store.s?.issues));
  const CATS: { id: TrackCat; label: string; icon: any; n: () => number; route: string }[] = $derived([
    { id: "prs", label: "PRs", icon: GitPullRequest, n: () => prs.length, route: "/prs/all" },
    { id: "builds", label: "Builds", icon: Hammer, n: () => builds.filter(b => b.status !== "completed").length, route: "/builds" },
    { id: "deploys", label: "Deploys", icon: Rocket, n: () => deploys.length, route: "/deploys" },
    { id: "issues", label: provider === "azure" ? "Work items" : "Issues", icon: CircleDot, n: () => issues.length, route: "/issues" },
  ]);
  /** Azure: "Work items" liga/desliga os do PROJETO (independe de acompanhar o repositório). */
  const catOn = (id: TrackCat) => (id === "issues" && projKey ? projIssues : t.on && t[id]);
  async function toggleCat(id: TrackCat) {
    if (id === "issues" && projKey) {
      try { await repos.setTrack(projKey, { issues: !projIssues }); store.refreshSource("issues"); } catch (e) { ui.error(e); }
      return;
    }
    return t.on ? setTrack({ [id]: !t[id] }) : setTrack({ track: true, [id]: true });
  }
  async function setTrack(patch: Record<string, any>) {
    try { await repos.setTrack(key!, patch); store.refreshSoon(2500); } catch (e) { ui.error(e); }
  }
  let note = $state("");
  $effect(() => { note = t.note; });

  async function openProject() {
    if (!local) return;
    try { const id = await work.open(local.id); ui.repoHub = null; go("/work/" + id, "soft"); } catch (e) { ui.error(e); }
  }
  async function openIn(target: "editor" | "files" | "terminal") { try { await post("open", { id: local!.id, target }); } catch (e) { ui.error(e); } }
  async function move() {
    if (!local) return;
    const ch = await ui.chooseCloneDir({ title: `Mover ${name} para…`, names: [name], account: accountKey, accountName: accountKey?.split(":").pop() });
    const base = ch?.base;
    if (!base) return;
    if (!(await ui.ask({ title: `Mover ${name}?`, message: `De ${home(local.path)} para ${home(base.replace(/[\\/]$/, ""))}/${local.path.split(/[\\/]/).pop()}. Os worktrees das tarefas continuam ligados.`, confirm: "Mover" }))) return;
    const prog = ui.progress("Movendo a pasta…");
    try {
      const r = await post<{ path: string }>("repos/move", { id: local.id, dest: base });
      if (ch?.remember && accountKey) await post("accounts/dirs", { key: accountKey, add: base });
      await repos.load();
      prog.done(`Agora em ${home(r.path)}`);
    } catch (e) { prog.fail(e); }
  }
  async function clone() {
    const url = remote?.cloneUrl || remote?.sshUrl;
    if (!url) return ui.toast("Este repositório não tem URL de clone", "info");
    const ch = await ui.chooseCloneDir({ title: `Clonar ${name}`, names: [name], account: accountKey, accountName: accountKey?.split(":").pop() });
    if (!ch) return;
    if (ch.remember && accountKey) await post("accounts/dirs", { key: accountKey, add: ch.base });
    const dest = ch.base.replace(/[\\/]$/, "") + (ch.base.includes("\\") ? "\\" : "/") + name;
    const prog = ui.progress(`Clonando ${name}…`);
    try {
      const job = await post<any>("repos/clone", { url: url.replace(/^https:\/\/[^@/]+@/, "https://"), dest });
      for (;;) {
        await new Promise(r => setTimeout(r, 700));
        const j = await get<any>("jobs", { id: job.id });
        if (j.status === "running") { prog.update(j.progress || `Clonando ${name}… ${j.percent || 0}%`); continue; }
        if (j.status === "done") { await repos.load(); prog.done(`Clonado em ${home(j.dest)}`); } else prog.fail(j.error || "Falhou ao clonar");
        break;
      }
    } catch (e) { prog.fail(e); }
  }
  async function pin() { await post("repos/pin", { id: local!.id, pinned: !local!.pinned }); await repos.load(); }
  async function forget() {
    if (!(await ui.ask({ title: `Tirar ${name} da lista?`, message: "A pasta continua no disco; só deixa de aparecer no app.", confirm: "Tirar da lista" }))) return;
    await post("repos/remove", { id: local!.id }); await repos.load(); ui.repoHub = null;
  }
  const group = $derived(local ? work.groupOf(local.id) : null);
  async function setGroup(v: string) {
    if (!local) return;
    if (v === "__new") { await work.newGroup([local.id]); return; }
    await work.assignGroup(local.id, v || null);
  }
  const prRoute = (k: string) => "/prs/all/" + encodeURIComponent(k);
</script>

<Drawer title={name} subtitle={remote?.fullName || local?.slug || (local ? home(local.path) : "")} onclose={() => (ui.repoHub = null)} width={660}>
  <div class="hub">
    <!-- cabeçalho -->
    <div class="hero">
      <span class="ic"><ProviderIcon {provider} size={22} /></span>
      <div class="grow">
        <div class="t"><b>{name}</b><FavStar repo={(remote || local)!} size={14} />{#if remote?.private}<Lock size={12} class="muted" />{/if}
          {#if remote?.archived}<span class="pill neutral">arquivado</span>{/if}{#if remote?.fork}<span class="pill neutral">fork</span>{/if}
          {#if remote?.language}<span class="pill neutral">{remote.language}</span>{/if}</div>
        {#if remote?.description}<p class="small muted">{remote.description}</p>{/if}
        <div class="tiny muted">{provider === "azure" ? "Azure DevOps" : provider === "github" ? "GitHub" : "sem remoto"}{accountKey ? " · conta " + accountKey.split(":").pop() : ""}{remote?.defaultBranch ? " · padrão " + remote.defaultBranch : ""}{remote?.updated ? " · atualizado há " + ago(remote.updated) : ""}</div>
        {#if isFav}<div class="tags"><TagPicker key={favKey} /></div>{/if}
      </div>
      {#if web}<a class="btn sm ghost" href={web} target="_blank" rel="noopener"><ExternalLink size={13} /> Abrir</a>{/if}
    </div>

    <!-- acompanhamento -->
    {#if trackable}
      <section class="card track" class:off={!t.on}>
        <div class="th">
          {#if t.on}<Eye size={18} class="on" />{:else}<EyeOff size={18} />{/if}
          <div class="grow"><b>{t.on ? "Acompanhando" : "Não acompanhado"}</b>
            <span class="tiny muted">{t.explicit ? "escolhido aqui" : t.mode === "all" ? "a conta acompanha todos os repositórios" : "a conta acompanha só os escolhidos"}</span></div>
          <Switch checked={t.on} onchange={(v) => setTrack({ track: v })} />
        </div>
        <div class="cats">
          {#each CATS as c (c.id)}
            {@const on = catOn(c.id)}
            <button class="cat" class:on onclick={() => toggleCat(c.id)} title={c.id === "issues" && projKey ? `${on ? "Parar de acompanhar" : "Acompanhar"} os work items do projeto ${projKey.split("/").pop()} (vale para o projeto todo, não só este repositório)` : on ? `Parar de acompanhar ${c.label.toLowerCase()}` : `Acompanhar ${c.label.toLowerCase()}`}>
              <c.icon size={16} /><span class="cl">{c.label}</span><b class="cn">{on ? c.n() : "—"}</b>
              <span class="cs tiny">{on ? "acompanhando" : "desligado"}</span>
            </button>
          {/each}
        </div>
        <div class="trow">
          <button class="btn sm ghost" disabled={!t.on} onclick={() => setTrack({ notify: !t.notify })}>{#if t.notify}<Bell size={13} /> Notificações ligadas{:else}<BellOff size={13} /> Sem notificações{/if}</button>
          {#if t.explicit}<button class="btn sm ghost" onclick={() => setTrack({ reset: true })} title="Volta a seguir o padrão da conta">Usar o padrão da conta</button>{/if}
          <span class="grow"></span>
          {#if accountKey}<button class="btn sm ghost" onclick={() => { ui.repoHub = null; ui.editAccount = accountKey; }}>Conta {accountKey.split(":").pop()} →</button>{/if}
        </div>
        <textarea class="input note" rows="2" placeholder="Observação (ex.: “deploy só às sextas”, “quem revisa: Ana”)…" bind:value={note} onblur={() => note !== t.note && setTrack({ note })}></textarea>
      </section>
    {/if}

    <!-- agora -->
    {#if trackable && t.on}
      <section class="now">
        {#if t.prs}
          <div class="blk"><h4><GitPullRequest size={13} /> Pull requests abertas <span class="n">{prs.length}</span></h4>
            {#each prs.slice(0, 4) as p (p.key)}
              <button class="li" onclick={() => { ui.repoHub = null; go(prRoute(p.key)); }}><b>#{p.prId}</b><span class="ell">{p.title}</span><span class="tiny muted">{p.creatorName} · {p.source} → {p.target}</span></button>
            {:else}<div class="none">Nenhuma PR aberta.</div>{/each}</div>
        {/if}
        {#if t.builds}
          <div class="blk"><h4><Hammer size={13} /> Builds recentes <span class="n">{builds.length}</span></h4>
            {#each builds as b (b.key)}
              {@const bs = buildState(b)}
              <button class="li" onclick={() => { ui.repoHub = null; go("/builds/" + encodeURIComponent(b.key)); }}><span class="pill {bs.cls}">{bs.icon} {bs.label}</span><span class="ell">{b.pipeline} · {b.branch}</span><span class="tiny muted">{ago(b.finished || b.queued)}</span></button>
            {:else}<div class="none">Nenhum build lido ainda.</div>{/each}</div>
        {/if}
        {#if t.deploys && deploys.length}
          <div class="blk"><h4><Rocket size={13} /> Deploys esperando <span class="n">{deploys.length}</span></h4>
            {#each deploys.slice(0, 4) as d (d.key)}
              <button class="li" onclick={() => { ui.repoHub = null; go("/deploys/" + encodeURIComponent(d.key)); }}><span class="pill warn">{d.stage || d.kind}</span><span class="ell">{d.pipeline}</span><span class="tiny muted">{ago(d.created)}</span></button>
            {/each}</div>
        {/if}
        {#if t.issues}
          <div class="blk"><h4><CircleDot size={13} /> Issues e tarefas <span class="n">{issues.length}</span></h4>
            {#each issues.slice(0, 4) as i (i.key)}
              <a class="li" href={i.url} target="_blank" rel="noopener"><b>#{i.number}</b><span class="ell">{i.title}</span><span class="tiny muted">{i.state}</span></a>
            {:else}<div class="none">Nada atribuído a você aqui.</div>{/each}</div>
        {/if}
      </section>
    {/if}

    <!-- pasta local -->
    <section class="card loc">
      <h4><FolderOpen size={13} /> Pasta local</h4>
      {#if local && local.exists}
        <div class="path mono" title={local.path}>{home(local.path)}</div>
        <div class="stat">
          {#if st}<span class="pill neutral"><GitBranch size={11} /> {st.detached ? "detached" : st.branch}</span>
            {#if st.ahead}<span class="pill accent"><ArrowUp size={10} /> {st.ahead} para enviar</span>{/if}
            {#if st.behind}<span class="pill info"><ArrowDown size={10} /> {st.behind} para receber</span>{/if}
            {#if st.changes}<span class="pill warn">{st.changes} alteraç{st.changes === 1 ? "ão" : "ões"}</span>{/if}
            {#if st.operation}<span class="pill bad">{st.operation} em andamento</span>{/if}{/if}
          {#if local.lastCommit}<span class="tiny muted ell">último commit há {ago(local.lastCommit.date)}: {local.lastCommit.subject}</span>{/if}
        </div>
        <div class="btns">
          <button class="btn sm primary" onclick={openProject}><Play size={13} /> Abrir projeto</button>
          <button class="btn sm" onclick={async () => { const id = await work.open(local!.id); ui.repoHub = null; work.launch(id); }}><Bot size={13} /> Abrir agente</button>
          <button class="btn sm" onclick={() => openIn("editor")}><Code2 size={13} /> Editor</button>
          <button class="btn sm" onclick={() => openIn("files")}><FolderOpen size={13} /> {fileManagerName()}</button>
          <button class="btn sm" onclick={() => openIn("terminal")}><Terminal size={13} /> Terminal</button>
          <button class="btn sm" onclick={move}><FolderInput size={13} /> Mover para…</button>
          <button class="btn sm ghost" onclick={pin}>{#if local.pinned}<PinOff size={13} /> Desafixar{:else}<Pin size={13} /> Fixar no menu{/if}</button>
          <button class="btn sm ghost" onclick={forget}><Trash2 size={13} /> Tirar da lista</button>
        </div>
        <label class="grp"><Layers size={13} /> Grupo de projetos
          <select class="input sm" value={group?.id || ""} onchange={(e) => setGroup((e.target as HTMLSelectElement).value)}>
            <option value="">Sem grupo</option>{#each work.groups as g (g.id)}<option value={g.id}>{g.name}</option>{/each}<option value="__new">+ Novo grupo…</option>
          </select>
          {#if group}<span class="dot" style="background:{group.color}"></span>{/if}
        </label>
      {:else if local && !local.exists}
        <div class="small muted">A pasta <span class="mono">{home(local.path)}</span> não existe mais.</div>
        <div class="btns"><button class="btn sm" onclick={async () => { const p = await pickFolder(`Onde está ${name}?`); if (p) { await post("repos/add", { path: p }); await post("repos/remove", { id: local!.id }); await repos.load(); } }}><FolderInput size={13} /> Apontar a pasta nova</button>
          <button class="btn sm ghost" onclick={forget}><Trash2 size={13} /> Tirar da lista</button></div>
      {:else}
        <div class="small muted">Não está clonado nesta máquina.</div>
        <div class="btns"><button class="btn sm primary" onclick={clone}><Download size={13} /> Clonar</button>
          <button class="btn sm" onclick={async () => { const p = await pickFolder(`Pasta de ${name} (clone que já existe)`); if (p) { try { await post("repos/add", { path: p }); await repos.load(); } catch (e) { ui.error(e); } } }}><FolderInput size={13} /> Já tenho clonado…</button></div>
      {/if}
    </section>
  </div>
</Drawer>

<style>
  .hub { display: grid; gap: 14px; padding-top: 12px; }
  .hero { display: flex; gap: 14px; align-items: flex-start; }
  .hero .ic { width: 46px; height: 46px; border-radius: 13px; display: grid; place-items: center; background: var(--surface-2); border: 1px solid var(--line-2); flex: none; }
  .hero .grow { flex: 1; min-width: 0; display: grid; gap: 4px; }
  .hero p { margin: 0; }
  .t { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 16px; }
  .tags { margin-top: 4px; }
  .card { padding: 14px; display: grid; gap: 12px; }
  .track { border-color: color-mix(in srgb, var(--good) 35%, var(--line)); background: linear-gradient(180deg, color-mix(in srgb, var(--good) 6%, transparent), transparent 60%), var(--surface); }
  .track.off { border-color: var(--line); background: var(--surface); }
  .th { display: flex; align-items: center; gap: 12px; }
  .th .grow { flex: 1; display: grid; }
  .th :global(.on) { color: var(--good); }
  .cats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
  .cat { display: grid; grid-template-columns: auto 1fr; grid-template-rows: auto auto; gap: 2px 8px; align-items: center; padding: 10px; border-radius: 10px;
    border: 1px solid var(--line); background: var(--surface-2); color: var(--muted); font: 12.5px var(--font); text-align: left; cursor: pointer;
    transition: border-color var(--t), background var(--t), color var(--t), transform var(--t-fast); }
  .cat:hover { border-color: var(--line-3); }
  .cat:active { transform: scale(0.98); }
  .cat.on { color: var(--text); border-color: color-mix(in srgb, var(--good) 45%, transparent); background: color-mix(in srgb, var(--good) 8%, var(--surface-2)); }
  .cat.on :global(svg) { color: var(--good); }
  .cl { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cn { grid-column: 1; font-size: 18px; font-variant-numeric: tabular-nums; }
  .cs { color: var(--muted); }
  .trow { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .grow { flex: 1; }
  .note { resize: vertical; height: auto; min-height: 44px; font: 12.5px/1.45 var(--font); padding: 7px 10px; }
  .now { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .blk { display: grid; gap: 2px; align-content: start; padding: 10px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface); min-width: 0; }
  h4 { display: flex; align-items: center; gap: 6px; margin: 0 0 4px; font-size: 12px; color: var(--text-2); text-transform: uppercase; letter-spacing: 0.05em; }
  h4 .n { margin-left: auto; color: var(--faint); }
  .li { display: grid; grid-template-columns: auto 1fr; gap: 0 8px; padding: 6px; border: 0; border-radius: 8px; background: none; color: var(--text-2); font: 12.5px var(--font);
    text-align: left; cursor: pointer; text-decoration: none; min-width: 0; }
  .li .tiny { grid-column: 2; }
  .li:hover { background: var(--surface-2); color: var(--text); }
  .none { font-size: 12px; color: var(--faint); padding: 4px 6px; }
  .path { font-size: 12px; color: var(--text-2); word-break: break-all; }
  .stat { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .btns { display: flex; gap: 6px; flex-wrap: wrap; }
  .grp { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-2); }
  .grp .input { width: auto; height: 30px; font-size: 12.5px; }
  .dot { width: 10px; height: 10px; border-radius: 3px; }
  @media (max-width: 700px) { .cats { grid-template-columns: 1fr 1fr; } .now { grid-template-columns: 1fr; } }
</style>
