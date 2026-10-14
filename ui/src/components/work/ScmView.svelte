<script lang="ts">
  // Controle de código-fonte do escopo (como o painel do VS Code): mensagem de commit, alterações preparadas e não
  // preparadas, conflitos — em lista ou árvore —, com abrir as alterações (diff), preparar/despreparar, descartar e
  // sincronizar (pull/push). Clique no arquivo abre o diff; o ícone de arquivo abre o arquivo em si.
  import { ArrowDown, ArrowUp, Check, ChevronDown, ChevronRight, FileText, FolderTree, List, Minus, MoreHorizontal, Plus, RefreshCw, RotateCcw, Undo2 } from "@lucide/svelte";
  import { post } from "../../lib/api";
  import { kbd } from "../../lib/keys";
  import { scm } from "../../lib/scm.svelte";
  import type { FileChange } from "../../lib/types";
  import { ui } from "../../lib/ui.svelte";
  import FileIcon from "./FileIcon.svelte";

  let { gitRepo, ondiff, onopen }: { gitRepo: string; ondiff: (path: string, staged: boolean) => void; onopen: (path: string) => void } = $props();
  $effect(() => { const g = gitRepo; return scm.watch(g); });
  const st = $derived(scm.status[gitRepo] || null);
  let message = $state("");
  let busy = $state("");
  let asTree = $state((() => { try { return localStorage.getItem("codeck.scm.tree") === "1"; } catch { return false; } })());
  let shut = $state<Record<string, boolean>>({});
  $effect(() => { try { localStorage.setItem("codeck.scm.tree", asTree ? "1" : "0"); } catch { /* */ } });

  const LETTER: Record<string, [string, string, string]> = { M: ["M", "mod", "Alterado"], T: ["M", "mod", "Tipo alterado"], A: ["A", "add", "Adicionado"],
    "?": ["U", "add", "Novo"], D: ["D", "del", "Apagado"], R: ["R", "ren", "Renomeado"], C: ["C", "ren", "Copiado"], U: ["!", "conf", "Conflito"] };
  const staged = $derived(st?.staged || []);
  const changes = $derived([...(st?.unstaged || []), ...(st?.untracked || [])]);
  const conflicts = $derived(st?.conflicts || []);

  async function act(path: string, payload: Record<string, unknown>, msg?: string) {
    try { await post("repo/" + path, { id: gitRepo, ...payload }); if (msg) ui.toast(msg); } catch (e) { ui.error(e); }
    scm.touch(gitRepo);
  }
  async function discard(files: FileChange[]) {
    if (!files.length) return;
    const ok = await ui.ask({ title: files.length === 1 ? `Descartar as alterações em ${files[0].path.split("/").pop()}?` : `Descartar ${files.length} alterações?`,
      message: "Voltam ao último commit. Arquivos novos vão para a Lixeira.", confirm: "Descartar", danger: true, detail: files.slice(0, 8).map(f => f.path) });
    if (ok) act("discard", { paths: files.map(f => f.path) }, "Alterações descartadas");
  }
  async function commit(mode: "commit" | "push" | "amend" = "commit") {
    const msg = message.trim();
    if (!msg && mode !== "amend") return ui.toast("Escreva a mensagem do commit", "error");
    if (!staged.length && !changes.length && mode !== "amend") return ui.toast("Nada para commitar", "info");
    busy = mode;
    try {
      // como o VS Code com "smart commit": sem nada preparado, commita tudo
      await post("repo/commit", { id: gitRepo, message: msg, amend: mode === "amend", stageAll: !staged.length && mode !== "amend" });
      message = "";
      if (mode === "push") { await post("repo/push", { id: gitRepo }); ui.toast("Commit enviado"); }
      else ui.toast(mode === "amend" ? "Último commit corrigido" : "Commit feito");
    } catch (e) { ui.error(e); }
    busy = "";
    scm.touch(gitRepo);
  }
  async function sync() {
    if (!st) return;
    busy = "sync";
    try {
      if (st.behind) await post("repo/pull", { id: gitRepo });
      if (st.ahead || !st.upstream) await post("repo/push", { id: gitRepo });
      if (!st.ahead && !st.behind && st.upstream) await post("repo/fetch", { id: gitRepo });
      ui.toast(st.ahead || st.behind ? "Sincronizado" : "Atualizado do servidor");
    } catch (e) { ui.error(e); }
    busy = "";
    scm.touch(gitRepo);
  }
  const moreItems = $derived([
    { label: "Buscar do servidor (fetch)", icon: RefreshCw, onclick: () => act("fetch", {}, "Atualizado do servidor") },
    { label: "Puxar (pull)", icon: ArrowDown, onclick: () => act("pull", {}, "Atualizado") },
    { label: "Puxar com rebase", icon: ArrowDown, onclick: () => act("pull", { rebase: true }, "Atualizado (rebase)") },
    { label: "Enviar (push)", icon: ArrowUp, onclick: () => act("push", {}, "Enviado") },
    { separator: true },
    { label: "Corrigir o último commit (amend)", icon: Undo2, onclick: () => commit("amend") },
    { label: "Guardar alterações (stash)", onclick: () => act("stash", { action: "push" }, "Alterações guardadas no stash") },
    { label: "Recuperar o último stash", onclick: () => act("stash", { action: "pop" }, "Stash aplicado") },
    { separator: true },
    { label: "Preparar tudo", icon: Plus, onclick: () => act("stage-all", {}) },
    { label: "Despreparar tudo", icon: Minus, onclick: () => act("unstage", { paths: staged.map(f => f.path) }) },
    { label: "Descartar tudo", icon: RotateCcw, danger: true, onclick: () => discard(changes) },
  ]);

  // árvore: pastas (como o VS Code em "Exibir como árvore")
  type TNode = { name: string; path: string; files: FileChange[]; dirs: TNode[] };
  function tree(files: FileChange[]): TNode {
    const rootN: TNode = { name: "", path: "", files: [], dirs: [] };
    for (const f of files) {
      const parts = f.path.split("/");
      let cur = rootN;
      for (let i = 0; i < parts.length - 1; i++) {
        const p = parts.slice(0, i + 1).join("/") + "/";
        let n = cur.dirs.find(d => d.path === p);
        if (!n) { n = { name: parts[i], path: p, files: [], dirs: [] }; cur.dirs.push(n); }
        cur = n;
      }
      cur.files.push(f);
    }
    const squash = (n: TNode): TNode => {
      n.dirs = n.dirs.map(squash);
      if (n.path && !n.files.length && n.dirs.length === 1) { const c = n.dirs[0]; return { ...c, name: n.name + "/" + c.name }; }
      return n;
    };
    return squash(rootN);
  }
</script>

{#snippet frow(f: FileChange, sec: "staged" | "changes" | "conflicts", depth: number)}
  {@const l = LETTER[f.status] || [f.status, "mod", f.status]}
  {@const name = f.path.split("/").pop() || f.path}
  <div class="f {l[1]}" style="--d:{depth}" role="button" tabindex="0" title={`${f.path} · ${l[2]}${f.from ? " (de " + f.from + ")" : ""}`}
    onclick={() => (f.status === "D" ? onopen(f.path) : ondiff(f.path, sec === "staged"))} onkeydown={(e) => e.key === "Enter" && ondiff(f.path, sec === "staged")}
    oncontextmenu={(e) => ui.contextMenu(e, [
      { label: "Abrir alterações", onclick: () => ondiff(f.path, sec === "staged") },
      ...(f.status !== "D" ? [{ label: "Abrir arquivo", icon: FileText, onclick: () => onopen(f.path) }] : []),
      { separator: true },
      ...(sec === "staged" ? [{ label: "Despreparar", icon: Minus, onclick: () => act("unstage", { paths: [f.path] }) }]
        : [{ label: "Preparar", icon: Plus, onclick: () => act("stage", { paths: [f.path] }) }]),
      ...(sec === "changes" ? [{ label: "Descartar alterações", icon: RotateCcw, danger: true, onclick: () => discard([f])}] : []),
    ])}>
    <FileIcon {name} size={15} />
    <span class="nm ell"><span class:strike={f.status === "D"}>{name}</span>{#if !asTree}<i>{f.path.split("/").slice(0, -1).join("/")}</i>{/if}</span>
    <span class="fa" role="presentation" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
      {#if f.status !== "D"}<button title="Abrir arquivo" onclick={() => onopen(f.path)}><FileText size={13} /></button>{/if}
      {#if sec === "changes"}<button title="Descartar alterações" onclick={() => discard([f])}><RotateCcw size={13} /></button>
        <button title="Preparar (stage)" onclick={() => act("stage", { paths: [f.path] })}><Plus size={14} /></button>
      {:else if sec === "staged"}<button title="Despreparar" onclick={() => act("unstage", { paths: [f.path] })}><Minus size={14} /></button>
      {:else}<button title="Marcar como resolvido (preparar)" onclick={() => act("stage", { paths: [f.path] })}><Check size={13} /></button>{/if}
    </span>
    <span class="sl">{l[0]}</span>
  </div>
{/snippet}

{#snippet tnode(n: TNode, sec: "staged" | "changes" | "conflicts", depth: number)}
  {#each n.dirs as d (d.path)}
    {@const k = sec + ":" + d.path}
    <button class="dir" style="--d:{depth}" onclick={() => (shut = { ...shut, [k]: !shut[k] })}>
      <ChevronRight size={12} class="chev {shut[k] ? '' : 'rot'}" /><FileIcon name={d.name.split("/").pop() || d.name} dir open={!shut[k]} size={15} /><span class="ell">{d.name}</span></button>
    {#if !shut[k]}{@render tnode(d, sec, depth + 1)}{/if}
  {/each}
  {#each n.files as f (f.path)}{@render frow(f, sec, depth)}{/each}
{/snippet}

{#snippet section(key: "staged" | "changes" | "conflicts", title: string, files: FileChange[])}
  {#if files.length}
    <div class="sec">
      <button class="sh" onclick={() => (shut = { ...shut, [key]: !shut[key] })}>
        <ChevronDown size={13} class="chev {shut[key] ? 'shut' : ''}" /><span class="ell">{title}</span>
        <span class="sa" role="presentation" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
          {#if key === "staged"}<span role="button" tabindex="0" title="Despreparar tudo" onclick={() => act("unstage", { paths: files.map(f => f.path) })} onkeydown={() => {}}><Minus size={14} /></span>
          {:else if key === "changes"}
            <span role="button" tabindex="0" title="Descartar tudo" onclick={() => discard(files)} onkeydown={() => {}}><RotateCcw size={13} /></span>
            <span role="button" tabindex="0" title="Preparar tudo" onclick={() => act("stage-all", {})} onkeydown={() => {}}><Plus size={14} /></span>{/if}
        </span>
        <span class="cnt">{files.length}</span>
      </button>
      {#if !shut[key]}
        {#if asTree}{@render tnode(tree(files), key, 0)}{:else}{#each files as f (f.path + f.status)}{@render frow(f, key, 0)}{/each}{/if}
      {/if}
    </div>
  {/if}
{/snippet}

<div class="scm">
  <div class="top">
    <span class="ttl">Controle de código-fonte</span>
    <button class="ib" title={asTree ? "Ver como lista" : "Ver como árvore"} onclick={() => (asTree = !asTree)}>{#if asTree}<List size={14} />{:else}<FolderTree size={14} />{/if}</button>
    <button class="ib" title="Recarregar" onclick={() => scm.load(gitRepo)}><RefreshCw size={13} /></button>
    <button class="ib" title="Mais ações" onclick={(e) => ui.contextMenu(e, moreItems)}><MoreHorizontal size={15} /></button>
  </div>
  {#if !st}
    <div class="none">{scm.error[gitRepo] || "Lendo o status do Git…"}</div>
  {:else}
    {#if st.operation}<div class="op small"><b>{st.operation}</b> em andamento — resolva os conflitos e prepare os arquivos.
      <span class="opb"><button class="btn sm" onclick={() => act("continue", {}, "Continuando")}>Continuar</button><button class="btn sm ghost" onclick={() => act("abort", {}, "Cancelado")}>Cancelar</button></span></div>{/if}
    <div class="msg">
      <textarea class="input" rows="2" bind:value={message} placeholder={`Mensagem (${kbd("mod+enter")} para commitar em “${st.branch || "HEAD"}”)`}
        onkeydown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); commit(e.shiftKey ? "push" : "commit"); } }}></textarea>
      <div class="cb">
        <button class="btn sm primary grow" disabled={!!busy || (!staged.length && !changes.length)} onclick={() => commit()}>
          <Check size={14} /> {busy === "commit" ? "Commitando…" : staged.length ? `Commit (${staged.length})` : "Commit de tudo"}</button>
        <button class="btn sm primary caret" disabled={!!busy} title="Mais opções de commit" onclick={(e) => ui.contextMenu(e, [
          { label: "Commit e enviar (push)", icon: ArrowUp, kbd: kbd("mod+shift+enter"), onclick: () => commit("push") },
          { label: "Corrigir o último commit (amend)", icon: Undo2, onclick: () => commit("amend") },
        ])}><ChevronDown size={13} /></button>
      </div>
      {#if st.ahead || st.behind || !st.upstream}
        <button class="btn sm sync" disabled={!!busy} onclick={sync}><RefreshCw size={13} class={busy === "sync" ? "spin" : ""} />
          {#if !st.upstream}Publicar a branch{:else}Sincronizar{#if st.behind} <ArrowDown size={12} />{st.behind}{/if}{#if st.ahead} <ArrowUp size={12} />{st.ahead}{/if}{/if}</button>
      {/if}
    </div>
    <div class="files">
      {@render section("conflicts", "Conflitos de mesclagem", conflicts)}
      {@render section("staged", "Alterações preparadas", staged)}
      {@render section("changes", "Alterações", changes)}
      {#if !staged.length && !changes.length && !conflicts.length}
        <div class="clean"><Check size={18} /><b>Tudo commitado</b><span class="tiny muted">{st.branch || "HEAD"}{st.upstream ? ` · em dia com ${st.upstream}` : ""}</span></div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .scm { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .top { display: flex; align-items: center; gap: 2px; padding: 8px 8px 4px 12px; }
  .ttl { flex: 1; min-width: 0; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ib { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; }
  .ib:hover { background: var(--surface-3); color: var(--text); }
  .none { padding: 12px; font-size: 12px; color: var(--muted); }
  .op { margin: 4px 8px; padding: 8px 10px; border-radius: 8px; background: var(--warn-soft); color: var(--text-2); display: grid; gap: 6px; }
  .opb { display: flex; gap: 6px; }
  .msg { display: grid; gap: 6px; padding: 4px 8px 8px; }
  .msg textarea { width: 100%; resize: vertical; min-height: 52px; font: 12.5px/1.45 var(--font); padding: 7px 9px; height: auto; }
  .cb { display: flex; }
  .cb .grow { flex: 1; border-radius: 8px 0 0 8px; justify-content: center; }
  .cb .caret { border-radius: 0 8px 8px 0; margin-left: 1px; padding: 0 7px; }
  .sync { justify-content: center; }
  .files { flex: 1; overflow: auto; padding: 0 4px 12px; }
  .sec { margin-top: 2px; }
  .sh { display: flex; align-items: center; gap: 5px; width: 100%; height: 24px; padding: 0 6px 0 4px; border: 0; border-radius: 5px; background: none; color: var(--text-2);
    font: 650 11px var(--font); text-transform: uppercase; letter-spacing: 0.04em; cursor: pointer; text-align: left; }
  .sh:hover { background: var(--surface-2); }
  .sh .ell { flex: 1; min-width: 0; }
  .sh :global(.chev) { transition: transform var(--t) var(--ease); flex: none; }
  .sh :global(.chev.shut) { transform: rotate(-90deg); }
  .sa { display: none; align-items: center; gap: 2px; }
  .sh:hover .sa { display: inline-flex; }
  .sa span { display: grid; place-items: center; width: 22px; height: 20px; border-radius: 5px; color: var(--muted); }
  .sa span:hover { background: var(--surface-3); color: var(--text); }
  .cnt { font: 650 10.5px/1 var(--font); padding: 3px 7px; border-radius: 99px; background: var(--surface-3); color: var(--text-2); }
  .f, .dir { --d: 0; display: flex; align-items: center; gap: 6px; width: 100%; height: 23px; padding: 0 6px 0 calc(18px + var(--d) * 12px); border: 0; border-radius: 5px;
    background: none; color: var(--text-2); font: 12.5px var(--font); text-align: left; cursor: pointer; }
  .f:hover, .dir:hover { background: var(--surface-2); }
  .dir :global(.chev) { color: var(--faint); transition: transform var(--t) var(--ease); flex: none; margin-left: -14px; }
  .dir :global(.chev.rot) { transform: rotate(90deg); }
  .nm { flex: 1; min-width: 0; color: var(--text); }
  .nm i { font-style: normal; color: var(--muted); font-size: 11.5px; margin-left: 6px; }
  .strike { text-decoration: line-through; }
  .fa { display: none; align-items: center; gap: 1px; }
  .f:hover .fa, .f:focus-visible .fa { display: inline-flex; }
  .fa button { display: grid; place-items: center; width: 22px; height: 20px; border: 0; border-radius: 5px; background: none; color: var(--muted); cursor: pointer; }
  .fa button:hover { background: var(--surface-3); color: var(--text); }
  .sl { width: 14px; text-align: center; font: 650 11px/1 var(--mono); flex: none; }
  .f.mod .sl, .f.mod .nm { color: #e2c08d; } .f.add .sl, .f.add .nm { color: #73c991; } .f.del .sl, .f.del .nm { color: #e5717d; }
  .f.ren .sl, .f.ren .nm { color: #73c991; } .f.conf .sl, .f.conf .nm { color: #e5717d; }
  :global([data-theme="light"]) .f.mod .sl, :global([data-theme="light"]) .f.mod .nm { color: #a26a00; }
  :global([data-theme="light"]) .f.add .sl, :global([data-theme="light"]) .f.add .nm, :global([data-theme="light"]) .f.ren .nm { color: #2f8a4a; }
  :global([data-theme="light"]) .f.del .sl, :global([data-theme="light"]) .f.del .nm, :global([data-theme="light"]) .f.conf .nm { color: #c4314b; }
  .clean { display: grid; justify-items: center; gap: 4px; padding: 28px 12px; color: var(--good); text-align: center; animation: fade 0.3s; }
  .clean b { color: var(--text); }
</style>
