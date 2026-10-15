<script lang="ts">
  // Branches locais (↑/↓, sem remota), remotas, tags e stashes. Nomes com "/" viram pastas recolhíveis (feature/, fix/…),
  // como no GitKraken. Cada linha tem as ações no "⋯" e no clique direito; duplo clique faz checkout. "Limpar" abre a
  // análise pela principal (mergeadas, squash, remoto apagado) — ver BranchCleanup.
  import { ArrowDown, ArrowUp, Archive, ChevronRight, Cloud, CloudOff, Copy, Download, Folder, FolderOpen, GitBranch, GitBranchPlus, GitMerge,
    GitPullRequestCreate, Pencil, Search, Sparkles, Tag, Trash2, Upload, Shuffle, X } from "@lucide/svelte";
  import { ago } from "../../lib/format";
  import type { Refs } from "../../lib/types";
  import { ui } from "../../lib/ui.svelte";
  import Menu, { type MenuItem } from "../Menu.svelte";
  import BranchCleanup from "./BranchCleanup.svelte";

  let { refs, onaction, onfocus, focused = null, canPr = true, repoId = undefined }:
    { refs: Refs; onaction: (action: string, arg: any) => void; onfocus: (name: string | null) => void; focused?: string | null; canPr?: boolean; repoId?: string } = $props();
  let cleaning = $state(false);
  let sec = $state<Record<string, boolean>>({ local: true, remote: false, tags: false, stashes: true });
  let shut = $state<Record<string, boolean>>({});   // pastas fechadas à mão (chave = seção:caminho)
  let q = $state("");
  const f = (n: string) => !q || n.toLowerCase().includes(q.trim().toLowerCase());

  type Leaf = { kind: "leaf"; name: string; label: string; data: any };
  type Dir = { kind: "dir"; path: string; label: string; kids: Node[]; count: number; hasCurrent: boolean };
  type Node = Leaf | Dir;
  function tree(items: { name: string }[], strip = 0): Node[] {
    const root: Dir = { kind: "dir", path: "", label: "", kids: [], count: 0, hasCurrent: false };
    for (const it of items) {
      const parts = it.name.split("/").slice(strip);
      let d = root;
      parts.slice(0, -1).forEach((p, i) => {
        const path = parts.slice(0, i + 1).join("/");
        let nx = d.kids.find(k => k.kind === "dir" && k.path === path) as Dir | undefined;
        if (!nx) { nx = { kind: "dir", path, label: p, kids: [], count: 0, hasCurrent: false }; d.kids.push(nx); }
        d = nx;
      });
      d.kids.push({ kind: "leaf", name: it.name, label: parts[parts.length - 1], data: it });
    }
    const fin = (d: Dir): number => {
      d.kids.sort((a, b) => (a.kind === b.kind ? a.label.localeCompare(b.label) : a.kind === "dir" ? -1 : 1));
      d.count = d.kids.reduce((n, k) => n + (k.kind === "dir" ? fin(k) : 1), 0);
      d.hasCurrent = d.kids.some(k => (k.kind === "leaf" ? k.name === refs.current : k.hasCurrent));
      return d.count;
    };
    fin(root);
    return root.kids;
  }
  const local = $derived(tree(refs.local.filter(b => f(b.name))));
  // remotas: uma pasta por remoto (origin, upstream…), e dentro dela as pastas da branch
  const remotes = $derived.by(() => {
    const by = new Map<string, any[]>();
    for (const b of refs.remote.filter(b => f(b.name) && !b.name.endsWith("/HEAD"))) {
      const r = b.name.split("/")[0];
      by.set(r, [...(by.get(r) || []), b]);
    }
    return [...by.entries()].map(([r, list]) => ({ remote: r, nodes: tree(list, 1), count: list.length }));
  });
  const tags = $derived(refs.tags.filter(t => f(t.name)).slice(0, 150));
  const gone = $derived(refs.local.filter(b => b.gone && b.name !== refs.current));
  const isOpen = (key: string, hasCurrent: boolean) => (q ? true : shut[key] === undefined ? hasCurrent : !shut[key]);
  const flip = (key: string, hasCurrent: boolean) => (shut = { ...shut, [key]: isOpen(key, hasCurrent) });
  const localOf = (remote: string) => remote.split("/").slice(1).join("/");
  const copy = async (t: string) => { await navigator.clipboard.writeText(t); ui.toast(`Copiado: ${t}`); };

  function localItems(b: Refs["local"][number]): MenuItem[] {
    const cur = b.name === refs.current;
    return [
      { label: "Fazer checkout", icon: GitBranch, onclick: () => onaction("checkout", b.name), disabled: cur, kbd: "2× clique" },
      { label: cur ? "Receber (pull)" : "Atualizar do servidor (sem checkout)", icon: Download, onclick: () => onaction("update", b.name), disabled: !b.upstream || b.gone,
        hint: !b.upstream ? "sem branch remota" : undefined },
      { label: b.upstream && !b.gone ? "Enviar (push)" : "Publicar no servidor", icon: Upload, onclick: () => onaction("push-branch", b.name) },
      { separator: true },
      { label: `Merge em ${refs.current}`, icon: GitMerge, onclick: () => onaction("merge", b.name), disabled: cur || !refs.current },
      { label: `Rebase de ${refs.current} sobre ${b.name}`, icon: Shuffle, onclick: () => onaction("rebase", b.name), disabled: cur || !refs.current },
      ...(canPr ? [{ label: "Criar PR desta branch", icon: GitPullRequestCreate, onclick: () => onaction("pr", b.name), disabled: b.name === refs.default }] : []),
      { label: "Nova branch a partir desta…", icon: GitBranchPlus, onclick: () => onaction("branch-from", b.name) },
      { separator: true },
      { label: "Copiar nome", icon: Copy, onclick: () => copy(b.name) },
      { label: "Renomear…", icon: Pencil, onclick: () => onaction("rename", b.name) },
      { label: "Apagar branch local", icon: Trash2, danger: true, onclick: () => onaction("delete", b.name), disabled: cur, hint: cur ? "é a branch atual" : undefined },
    ];
  }
  function remoteItems(b: Refs["remote"][number]): MenuItem[] {
    const has = refs.local.some(l => l.name === localOf(b.name));
    return [
      { label: has ? `Checkout de ${localOf(b.name)}` : "Checkout (cria a local)", icon: GitBranch, onclick: () => onaction(has ? "checkout" : "track", has ? localOf(b.name) : b.name), kbd: "2× clique" },
      { label: `Merge em ${refs.current}`, icon: GitMerge, onclick: () => onaction("merge", b.name), disabled: !refs.current },
      { label: `Rebase de ${refs.current} sobre ${b.name}`, icon: Shuffle, onclick: () => onaction("rebase", b.name), disabled: !refs.current },
      ...(canPr ? [{ label: "Criar PR desta branch", icon: GitPullRequestCreate, onclick: () => onaction("pr", localOf(b.name)), disabled: localOf(b.name) === refs.default }] : []),
      { label: "Nova branch a partir desta…", icon: GitBranchPlus, onclick: () => onaction("branch-from", b.name) },
      { separator: true },
      { label: "Copiar nome", icon: Copy, onclick: () => copy(localOf(b.name)) },
      { label: "Apagar no servidor", icon: Trash2, danger: true, onclick: () => onaction("delete-remote", b.name), disabled: localOf(b.name) === refs.default },
    ];
  }
  const tagItems = (t: Refs["tags"][number]): MenuItem[] => [
    { label: "Checkout desta tag", icon: GitBranch, onclick: () => onaction("checkout", t.name) },
    { label: "Nova branch a partir desta tag…", icon: GitBranchPlus, onclick: () => onaction("branch-from", t.name) },
    { label: "Enviar para o servidor", icon: Upload, onclick: () => onaction("tag-push", t.name) },
    { separator: true },
    { label: "Copiar nome", icon: Copy, onclick: () => copy(t.name) },
    { label: "Apagar tag local", icon: Trash2, danger: true, onclick: () => onaction("tag-delete", t.name) },
    { label: "Apagar tag no servidor", icon: Trash2, danger: true, onclick: () => onaction("tag-delete-remote", t.name) },
  ];
  const stashItems = (s: Refs["stashes"][number]): MenuItem[] => [
    { label: "Aplicar e remover (pop)", icon: Download, onclick: () => onaction("stash-pop", s.ref) },
    { label: "Aplicar e manter", icon: Copy, onclick: () => onaction("stash-apply", s.ref) },
    { separator: true },
    { label: "Descartar stash", icon: Trash2, danger: true, onclick: () => onaction("stash-drop", s.ref) },
  ];
</script>

{#snippet nodes(list: Node[], key: string, depth: number, kind: "local" | "remote")}
  {#each list as n (n.kind === "dir" ? "d:" + n.path : n.name)}
    {#if n.kind === "dir"}
      {@const k = `${key}:${n.path}`}
      {@const op = isOpen(k, n.hasCurrent)}
      <button class="b dir" style="--d:{depth}" onclick={() => flip(k, n.hasCurrent)} aria-expanded={op}>
        <ChevronRight size={12} class="chev {op ? 'rot' : ''}" />
        {#if op}<FolderOpen size={13} />{:else}<Folder size={13} />{/if}
        <span class="name ell">{n.label}</span><span class="cnt">{n.count}</span>
      </button>
      {#if op}{@render nodes(n.kids, key, depth + 1, kind)}{/if}
    {:else if kind === "local"}
      {@const b = n.data as Refs["local"][number]}
      <div class="b" style="--d:{depth}" class:cur={b.name === refs.current} class:foc={focused === b.name} role="button" tabindex="-1" title={`${b.name}\n${b.subject} — ${b.author}, ${ago(b.date)}`}
        onclick={() => onfocus(focused === b.name ? null : b.name)} ondblclick={() => b.name !== refs.current && onaction("checkout", b.name)}
        oncontextmenu={(e) => ui.contextMenu(e, localItems(b))} onkeydown={(e) => e.key === "Enter" && b.name !== refs.current && onaction("checkout", b.name)}>
        <GitBranch size={13} />
        <span class="name ell">{n.label}</span>
        {#if b.name === refs.current}<span class="now">atual</span>{/if}
        {#if b.gone}<span class="gone" title="A branch no servidor foi apagada (normalmente já mesclada)"><CloudOff size={12} /></span>
        {:else if !b.upstream}<span class="gone" title="Só existe nesta máquina — ainda não foi enviada"><Upload size={11} /></span>{/if}
        {#if b.ahead}<span class="ab up" title="commits para enviar"><ArrowUp size={10} />{b.ahead}</span>{/if}
        {#if b.behind}<span class="ab down" title="commits para receber"><ArrowDown size={10} />{b.behind}</span>{/if}
        <span onclick={(e) => e.stopPropagation()} ondblclick={(e) => e.stopPropagation()} role="presentation" class="m"><Menu items={localItems(b)} /></span>
      </div>
    {:else}
      {@const b = n.data as Refs["remote"][number]}
      {@const has = refs.local.some(l => l.name === localOf(b.name))}
      <div class="b" style="--d:{depth}" class:foc={focused === b.name} class:dim={has} role="button" tabindex="-1" title={`${b.name}\n${b.subject} — ${b.author}, ${ago(b.date)}`}
        onclick={() => onfocus(focused === b.name ? null : b.name)} ondblclick={() => onaction(has ? "checkout" : "track", has ? localOf(b.name) : b.name)}
        oncontextmenu={(e) => ui.contextMenu(e, remoteItems(b))} onkeydown={() => {}}>
        <Cloud size={13} /><span class="name ell">{n.label}</span><span class="tiny when">{ago(b.date)}</span>
        <span onclick={(e) => e.stopPropagation()} ondblclick={(e) => e.stopPropagation()} role="presentation" class="m"><Menu items={remoteItems(b)} /></span>
      </div>
    {/if}
  {/each}
{/snippet}

<div class="panel">
  <div class="filter">
    <Search size={13} />
    <input bind:value={q} placeholder="Filtrar branches, tags…" />
    {#if q}<button class="x" onclick={() => (q = "")} aria-label="Limpar"><X size={12} /></button>{/if}
  </div>
  <div class="scroll">
    <div class="sech">
      <button class="sec" onclick={() => (sec.local = !sec.local)}><ChevronRight size={13} class="chev {sec.local ? 'rot' : ''}" /> Locais <em>{refs.local.length}</em></button>
      {#if repoId && refs.local.length > 1}
        <button class="tidy" class:has={gone.length > 0} title={`Recomenda o que apagar comparando com ${refs.default ? "origin/" + refs.default : "a principal"}: mergeadas, squash e remoto apagado${gone.length ? ` · ${gone.length} com o remoto apagado` : ""}`}
          onclick={() => (cleaning = true)}><Sparkles size={12} /> Limpar{#if gone.length}<em>{gone.length}</em>{/if}</button>
      {/if}
    </div>
    {#if sec.local}{@render nodes(local, "local", 0, "local")}{#if !local.length}<div class="none">{q ? "Nada com esse filtro." : "Nenhuma branch local."}</div>{/if}{/if}

    <button class="sec" onclick={() => (sec.remote = !sec.remote)}><ChevronRight size={13} class="chev {sec.remote ? 'rot' : ''}" /> Remotas <em>{refs.remote.filter(b => !b.name.endsWith("/HEAD")).length}</em></button>
    {#if sec.remote || q}
      {#each remotes as r (r.remote)}
        {@const k = "remote:" + r.remote}
        {@const op = q ? true : !shut[k]}
        <button class="b dir" style="--d:0" onclick={() => (shut = { ...shut, [k]: op })} aria-expanded={op}>
          <ChevronRight size={12} class="chev {op ? 'rot' : ''}" /><Cloud size={13} /><span class="name ell">{r.remote}</span><span class="cnt">{r.count}</span>
        </button>
        {#if op}{@render nodes(r.nodes, "r:" + r.remote, 1, "remote")}{/if}
      {/each}
    {/if}

    <button class="sec" onclick={() => (sec.tags = !sec.tags)}><ChevronRight size={13} class="chev {sec.tags ? 'rot' : ''}" /> Tags <em>{refs.tags.length}</em></button>
    {#if sec.tags || (q && tags.length)}
      {#each tags as t (t.name)}
        <div class="b" style="--d:0" role="button" tabindex="-1" onclick={() => onfocus("tag: " + t.name)} oncontextmenu={(e) => ui.contextMenu(e, tagItems(t))} onkeydown={() => {}}>
          <Tag size={13} /><span class="name ell">{t.name}</span><span class="tiny when">{ago(t.date)}</span>
          <span onclick={(e) => e.stopPropagation()} role="presentation" class="m"><Menu items={tagItems(t)} /></span>
        </div>
      {/each}
    {/if}

    <button class="sec" onclick={() => (sec.stashes = !sec.stashes)}><ChevronRight size={13} class="chev {sec.stashes ? 'rot' : ''}" /> Stashes <em>{refs.stashes.length}</em></button>
    {#if sec.stashes}
      {#each refs.stashes as s (s.ref)}
        <div class="b" style="--d:0" title={s.message} role="button" tabindex="-1" oncontextmenu={(e) => ui.contextMenu(e, stashItems(s))} onkeydown={() => {}}>
          <Archive size={13} /><span class="name ell">{s.message.replace(/^On [^:]+: /, "").replace(/^WIP on [^:]+: /, "")}</span><span class="tiny when">{ago(s.date)}</span>
          <span class="m"><Menu items={stashItems(s)} /></span>
        </div>
      {:else}<div class="none">Nenhum stash.</div>{/each}
    {/if}
  </div>
</div>
{#if cleaning && repoId}<BranchCleanup {repoId} onclose={() => (cleaning = false)} ondone={() => onaction("tidy", null)} />{/if}

<style>
  .panel { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .filter { display: flex; align-items: center; gap: 7px; margin: 10px; padding: 0 8px; height: 30px; border-radius: 8px; border: 1px solid var(--line-2);
    background: var(--bg-2); color: var(--muted); transition: border-color var(--t), box-shadow var(--t); }
  .filter:focus-within { border-color: var(--accent); box-shadow: var(--ring); }
  .filter input { flex: 1; min-width: 0; border: 0; outline: none; background: none; color: var(--text); font: 12.5px var(--font); }
  .x { display: grid; place-items: center; width: 18px; height: 18px; border: 0; border-radius: 50%; background: var(--surface-3); color: var(--text-2); cursor: pointer; }
  .scroll { flex: 1; overflow: auto; padding: 0 0 10px; border-top: 1px solid var(--line); }
  .sec { display: flex; align-items: center; gap: 6px; width: 100%; padding: 10px 12px 5px; border: 0; background: none; cursor: pointer;
    font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
  .sec em { font-style: normal; color: var(--text-2); }
  :global(.chev) { transition: transform var(--t) var(--ease); flex: none; }
  :global(.chev.rot) { transform: rotate(90deg); }
  .b { --d: 0; display: flex; align-items: center; gap: 7px; width: 100%; height: 28px; padding: 0 6px 0 calc(14px + var(--d) * 14px); border: 0; background: none;
    cursor: pointer; font: 12.5px var(--font); color: var(--text-2); text-align: left; outline: none; transition: background var(--t-fast), color var(--t-fast); }
  .b:hover, .b:focus-visible { background: var(--surface-2); color: var(--text); }
  .b.dir { color: var(--muted); font-weight: 550; }
  .b.dir :global(svg:not(.chev)) { color: var(--faint); }
  .b.dir:hover { color: var(--text-2); }
  .b.cur { color: var(--text); font-weight: 650; }
  .b.cur > :global(svg:first-child) { color: var(--good); }
  .b.foc { background: var(--accent-soft); color: var(--text); }
  .b.dim { opacity: 0.6; }
  .name { flex: 1; min-width: 0; }
  .cnt { font: 600 10.5px/1 var(--font); color: var(--faint); }
  .now { font: 650 9.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.05em; padding: 3px 5px; border-radius: 5px; background: var(--good-soft); color: var(--good); }
  .when { color: var(--faint); white-space: nowrap; }
  .sech { display: flex; align-items: center; padding-right: 8px; }
  .tidy { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; border: 0; background: none; color: var(--muted);
    font: 600 11px/1 var(--font); padding: 4px 7px; border-radius: 6px; cursor: pointer; white-space: nowrap; transition: background var(--t-fast), color var(--t-fast); }
  .tidy:hover { background: var(--surface-2); color: var(--text); }
  .tidy.has { background: var(--accent-soft); color: var(--accent); }
  .tidy em { font-style: normal; font-variant-numeric: tabular-nums; }
  .gone { color: var(--faint); display: inline-grid; }
  .ab { display: inline-flex; align-items: center; gap: 2px; font: 650 10.5px/1 var(--font); }
  .ab.up { color: var(--accent); }
  .ab.down { color: var(--info); }
  /* "⋯" aparece no hover — e continua visível enquanto o menu dele estiver aberto */
  .m { opacity: 0; transition: opacity var(--t-fast); display: inline-flex; }
  .b:hover .m, .b:focus-within .m, .m:has(:global(.menu.open)) { opacity: 1; }
  .b:hover .when { display: none; }
  .none { padding: 4px 16px; font-size: 12px; color: var(--muted); }
</style>
