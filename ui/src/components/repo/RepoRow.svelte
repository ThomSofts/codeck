<script lang="ts">
  // Linha de repositório (catálogo ou local): status do clone, sincronização e ações rápidas.
  import { ArrowDown, ArrowUp, Code2, Download, ExternalLink, Eye, EyeOff, FolderOpen, GitBranch, Lock, Pin, PinOff, Settings2, Terminal, Trash2, Play } from "@lucide/svelte";
  import { work } from "../../lib/work.svelte";
  import { get, post } from "../../lib/api";
  import { ago } from "../../lib/format";
  import { fileManagerName } from "../../lib/native";
  import { repos } from "../../lib/repos.svelte";
  import { go } from "../../lib/router.svelte";
  import type { FavRepo, LocalRepo, RemoteRepo } from "../../lib/types";
  import { ui } from "../../lib/ui.svelte";
  import Menu from "../Menu.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";
  import FavStar from "./FavStar.svelte";
  import TagPicker from "./TagPicker.svelte";

  let { remote = null, local = null, onchanged = () => {}, job = null, onclone = undefined }:
    { remote?: RemoteRepo | FavRepo | null; local?: LocalRepo | null; onchanged?: () => void; job?: any; onclone?: () => void } = $props();
  const favKey = $derived(repos.keyOf((remote || local)!));
  const isFav = $derived(!!repos.fav(favKey));

  const loc = $derived(local || (remote?.local as LocalRepo | null) || null);
  const st = $derived(loc?.status);
  const name = $derived(remote?.name || loc?.name || "");
  const provider = $derived(remote?.provider || loc?.provider || null);
  const web = $derived(remote?.webUrl || loc?.webUrl || null);
  const dirty = $derived(!!st && (st.changes > 0 || st.stashes > 0));
  // acompanhamento (PRs, builds, deploys, issues): o olho liga/desliga este repositório
  const tkey = $derived(((remote as any)?.remoteKey || (remote as any)?.key || loc?.remoteKey || "").toLowerCase());
  const trackable = $derived(/^(github|azure):/.test(tkey));
  const acct = $derived((remote as any)?.accountKey || (loc ? repos.accountOf(loc as any) : null));
  const tr = $derived(repos.track(tkey, acct));
  async function toggleTrack() {
    try { await repos.setTrack(tkey, { track: !tr.on }); ui.toast(tr.on ? `Acompanhando ${name}` : `${name} deixou de ser acompanhado`); }
    catch (e) { ui.error(e); }
  }
  const manage = () => (ui.repoHub = { remote: remote || undefined, localId: loc?.id });
  async function openProject() { try { const id = await work.open(loc!.id); go("/work/" + id, "soft"); } catch (e) { ui.error(e); } }

  async function open(target: "editor" | "files" | "terminal") {
    try { await post("open", { id: loc!.id, target }); } catch (e) { ui.error(e); }
  }
  async function pin() {
    await post("repos/pin", { id: loc!.id, pinned: !loc!.pinned });
    await repos.load();
    onchanged();
  }
  async function clean() {
    const { blockers } = await get<{ blockers: string[] }>("repo/clean-check", { id: loc!.id });
    if (blockers.length) {
      await ui.ask({ title: "Não dá para limpar este repositório", message: "A cópia local tem trabalho que se perderia:", blocked: blockers });
      return;
    }
    const ok = await ui.ask({ title: `Limpar ${name} desta máquina?`, message: `A pasta ${loc!.path} vai para a Lixeira. Tudo já está no servidor — dá para clonar de novo quando quiser.`,
      confirm: "Mandar para a Lixeira", danger: true });
    if (!ok) return;
    try {
      await post("repo/clean", { id: loc!.id });
      ui.toast(`${name} foi para a Lixeira`);
      await repos.load();
      onchanged();
    } catch (e) { ui.error(e); }
  }
  async function forget() {
    if (!(await ui.ask({ title: `Tirar ${name} da lista?`, message: "A pasta continua no disco; só deixa de aparecer no app.", confirm: "Tirar da lista" }))) return;
    await post("repos/remove", { id: loc!.id });
    await repos.load();
    onchanged();
  }
  const items = $derived(loc ? [
    { label: "Abrir projeto", icon: Play, onclick: openProject },
    { label: "Gerenciar repositório…", icon: Settings2, onclick: manage },
    ...(trackable ? [{ label: tr.on ? "Deixar de acompanhar" : "Acompanhar (PRs, builds, deploys, issues)", icon: tr.on ? EyeOff : Eye, onclick: toggleTrack }] : []),
    { separator: true },
    { label: `Abrir no ${fileManagerName()}`, icon: FolderOpen, onclick: () => open("files") },
    { label: "Abrir no terminal", icon: Terminal, onclick: () => open("terminal") },
    ...(web ? [{ label: "Abrir no navegador", icon: ExternalLink, href: web }] : []),
    { separator: true },
    { label: loc.pinned ? "Desafixar do menu" : "Fixar no menu", icon: loc.pinned ? PinOff : Pin, onclick: pin },
    { separator: true },
    { label: "Limpar local (Lixeira)", icon: Trash2, danger: true, onclick: clean, disabled: dirty,
      hint: dirty ? (st!.changes ? `${st!.changes} alteração(ões) sem commit` : `${st!.stashes} stash(es)`) : undefined },
    { label: "Tirar da lista (mantém a pasta)", onclick: forget },
  ] : [
    { label: "Gerenciar repositório…", icon: Settings2, onclick: manage },
    ...(trackable ? [{ label: tr.on ? "Deixar de acompanhar" : "Acompanhar (PRs, builds, deploys, issues)", icon: tr.on ? EyeOff : Eye, onclick: toggleTrack }] : []),
    ...(web ? [{ label: "Abrir no navegador", icon: ExternalLink, href: web }] : []),
  ]);
</script>

<div class="list-row repo" class:cloned={!!loc} class:untracked={trackable && !tr.on} onclick={manage} role="button" tabindex="-1" onkeydown={(e) => e.key === "Enter" && e.target === e.currentTarget && manage()}>
  <span class="ic"><ProviderIcon {provider} size={16} /></span>
  <div class="grow">
    <div class="t">
      <span class="title ell">{name}</span>
      <FavStar repo={(remote || local)!} size={13} />
      {#if remote?.private}<Lock size={11} class="muted" />{/if}
      {#if remote?.archived}<span class="pill neutral">arquivado</span>{/if}
      {#if remote?.fork}<span class="pill neutral">fork</span>{/if}
      {#if loc?.pinned}<Pin size={11} class="muted" />{/if}
    </div>
    <div class="meta">
      {#if remote}<span>{remote.owner}</span>{/if}
      {#if remote?.description}<span class="ell desc">{remote.description}</span>{/if}
      {#if remote?.language}<span class="lang">{remote.language}</span>{/if}
      {#if loc}<span class="path ell" title={loc.path}>{loc.path.replace(/^\/Users\/[^/]+/, "~")}</span>{/if}
      {#if loc?.lastCommit}<span>último commit {ago(loc.lastCommit.date)}</span>{:else if remote?.updated}<span>atualizado {ago(remote.updated)}</span>{/if}
    </div>
    {#if isFav}<div class="tagline"><TagPicker key={favKey} /></div>{/if}
    {#if job && job.status === "running"}
      <div class="progress"><span style="width:{Math.max(4, job.percent)}%"></span></div>
      <div class="tiny muted">{job.progress || "Clonando…"}</div>
    {/if}
  </div>
  <div class="acts" onclick={(e) => e.stopPropagation()} role="presentation">
    {#if trackable}
      <button class="btn sm ghost icon eye" class:on={tr.on} title={tr.on ? `Acompanhando${tr.explicit ? "" : " (padrão da conta)"} — clique para deixar de acompanhar` : "Não acompanhado — clique para acompanhar PRs, builds, deploys e issues"} onclick={toggleTrack}>
        {#if tr.on}<Eye size={14} />{:else}<EyeOff size={14} />{/if}</button>
    {/if}
    {#if loc && st}
      <span class="branch"><GitBranch size={11} /><b>{st.detached ? "detached" : st.branch}</b></span>
      {#if st.ahead}<span class="pill accent" title="commits para enviar"><ArrowUp size={10} />{st.ahead}</span>{/if}
      {#if st.behind}<span class="pill info" title="commits para receber"><ArrowDown size={10} />{st.behind}</span>{/if}
      {#if st.changes}<span class="pill warn" title="alterações não commitadas">{st.changes} alteração(ões)</span>{/if}
      {#if st.operation}<span class="pill bad">{st.operation} em andamento</span>{/if}
      <button class="btn sm" onclick={openProject} title="Abrir como projeto (agentes, terminais, arquivos)"><Play size={13} /> Abrir</button>
      <button class="btn sm ghost" onclick={() => open("editor")} title="Abrir no editor externo"><Code2 size={13} /></button>
    {:else if loc && !loc.exists}
      <span class="pill bad">pasta não existe</span>
    {:else if remote && !loc}
      {#if job?.status === "error"}<span class="pill bad" title={job.error}>falhou</span>{/if}
      <button class="btn sm primary" disabled={job?.status === "running"} onclick={onclone}><Download size={13} /> {job?.status === "running" ? `${job.percent}%` : "Clonar"}</button>
    {/if}
    {#if items.length}<Menu {items} />{/if}
  </div>
</div>

<style>
  .tagline { margin-top: 6px; animation: rise 0.25s var(--ease-out); }
  .eye { color: var(--faint); }
  .eye.on { color: var(--good); }
  .untracked .title { color: var(--text-2); }
  .t :global(.star) { width: 22px; height: 22px; margin-left: -2px; }
  .ic { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; background: var(--surface-2); border: 1px solid var(--line); }
  .cloned .ic { background: var(--surface-3); }
  .t { display: flex; align-items: center; gap: 7px; min-width: 0; }
  .title { font-weight: 600; }
  .desc { max-width: 380px; color: var(--muted); }
  .lang { color: var(--accent); }
  .path { font: 11.5px var(--mono); color: var(--muted); max-width: 320px; }
  .acts { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
  .progress { height: 4px; border-radius: 99px; background: var(--surface-3); overflow: hidden; margin-top: 8px; }
  .progress span { display: block; height: 100%; background: var(--brand-grad); border-radius: 99px; transition: width 0.4s var(--ease); }
</style>
