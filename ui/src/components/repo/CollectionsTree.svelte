<script lang="ts">
  // Coleções de repositórios, cada seção recolhível (estado guardado por tela: painel de Repositórios × barra lateral):
  //   Contas    — cada conta conectada lista TODOS os repositórios dela (logo do provedor + quantidade)
  //   Favoritos — de qualquer conta;  Tags — coleções pelas tags dos favoritos;  Catálogos — categorias manuais
  // Os contadores vêm do cache do backend; "…" enquanto a lista da conta/catálogo ainda não foi lida.
  import { ChevronRight, FolderCog, FolderKanban, FolderOpen, Palette, Pencil, Plus, Star, Tags, Trash2, Users } from "@lucide/svelte";
  import { post } from "../../lib/api";
  import { repos } from "../../lib/repos.svelte";
  import { go, router } from "../../lib/router.svelte";
    import { ui } from "../../lib/ui.svelte";
  import Menu from "../Menu.svelte";
  import ProviderIcon from "../ProviderIcon.svelte";

  let { compact = false, onnew = undefined }: { compact?: boolean; onnew?: () => void } = $props();

  const scope = () => (compact ? "side" : "page");
  const STORE = "codeck.collapsed";
  let closed = $state<Record<string, boolean>>(read());
  function read() {
    try { return JSON.parse(localStorage.getItem(STORE) || "{}")[scope()] || {}; } catch { return {}; }
  }
  function toggle(k: string) {
    closed = { ...closed, [k]: !isClosed(k) };
    try { const all = JSON.parse(localStorage.getItem(STORE) || "{}"); all[scope()] = closed; localStorage.setItem(STORE, JSON.stringify(all)); } catch { /* sem armazenamento */ }
  }
  // na barra lateral as seções começam recolhidas (menos Contas); no painel, abertas
  const isClosed = (k: string) => closed[k] ?? (compact && k !== "accounts");
  const num = (n: number | null | undefined) => (n === null || n === undefined ? "…" : n);

  const at = (path: string) => router.view === "repos" && router.param === path;
  const enc = encodeURIComponent;

  async function editTag(name: string, patch: Record<string, unknown>) {
    try { await post("library/tag", { name, ...patch }); await repos.loadLibrary(); } catch (e) { ui.error(e); }
  }
  async function rename(name: string) {
    const v = await ui.ask({ title: "Renomear tag", input: { label: "Nome", value: name, required: true }, confirm: "Renomear" });
    if (v && v !== name) { await editTag(name, { rename: v }); if (at("tag/" + name)) go("/repos/tag/" + enc(v), "soft"); }
  }
  const PALETTE = ["#6F8CFF", "#3CCF91", "#F5B84F", "#FF6B7D", "#B07CFF", "#4FC3F7", "#FF8A50", "#9AA4B2", "#E879F9", "#A3E635"];
  async function remove(name: string) {
    if (!(await ui.ask({ title: `Apagar a tag ${name}?`, message: "Os repositórios continuam nos favoritos; só perdem esta tag.", confirm: "Apagar", danger: true }))) return;
    try { await post("library/tag/delete", { name }); await repos.loadLibrary(); if (at("tag/" + name)) go("/repos/favorites", "soft"); } catch (e) { ui.error(e); }
  }
  const tagMenu = (name: string, color: string) => [
    { label: "Renomear", icon: Pencil, onclick: () => rename(name) },
    { label: "Trocar a cor", icon: Palette, onclick: () => editTag(name, { color: PALETTE[(PALETTE.indexOf(color) + 1) % PALETTE.length] }) },
    { separator: true },
    { label: "Apagar tag", icon: Trash2, danger: true, onclick: () => remove(name) },
  ];
</script>

<div class="tree" class:compact>
  {#snippet head(key: string, label: string, Icon: any, count: number | string)}
    <button class="gh" onclick={() => toggle(key)} aria-expanded={!isClosed(key)}>
      <ChevronRight size={12} class="chev {isClosed(key) ? '' : 'open'}" /><Icon size={12} /><span class="grow ell">{label}</span><span class="n">{count}</span>
    </button>
  {/snippet}

  {#if repos.accounts.length}
    {@render head("accounts", "Contas", Users, repos.accounts.length)}
    <div class="kids" class:closed={isClosed("accounts")}><div>
      {#each repos.accounts as a (a.key)}
        <div class="row">
          <button class="it sub" class:on={at("account/" + a.key)} onclick={() => go("/repos/account/" + enc(a.key), "soft")}
            title={`${a.provider === "azure" ? "Azure DevOps" : "GitHub"} · todos os repositórios de ${a.name}${a.dirs.length ? "\nPastas: " + a.dirs.join(", ") : ""}`}>
            <ProviderIcon provider={a.provider} size={13} /><span class="grow ell">{a.name}</span><span class="n">{num(a.count)}</span>
          </button>
          <span class="more"><Menu items={[
            { label: "Ver todos os repositórios", icon: FolderOpen, onclick: () => go("/repos/account/" + enc(a.key), "soft") },
            { label: "Detalhes e ajustes da conta…", icon: FolderCog, onclick: () => (ui.editAccount = a.key) },
          ]} /></span>
        </div>
      {/each}
    </div></div>
  {/if}

  <button class="it top" class:on={at("favorites")} onclick={() => go("/repos/favorites", "soft")}>
    <Star size={compact ? 12 : 14} class="star" /><span class="grow ell">Favoritos</span><span class="n">{repos.favorites.length}</span>
  </button>

  {#if repos.tags.length}
    {@render head("tags", "Tags", Tags, repos.tags.length)}
    <div class="kids" class:closed={isClosed("tags")}><div>
      {#each repos.tags as t (t.name)}
        <div class="row">
          <button class="it sub" class:on={at("tag/" + t.name)} onclick={() => go("/repos/tag/" + enc(t.name), "soft")}>
            <span class="dot" style="background:{t.color}"></span><span class="grow ell">{t.name}</span><span class="n">{t.count}</span>
          </button>
          <span class="more"><Menu items={tagMenu(t.name, t.color)} /></span>
        </div>
      {/each}
    </div></div>
  {/if}

  {#if repos.catalogs.length || onnew}
    {@render head("catalogs", "Catálogos", FolderKanban, repos.catalogs.length)}
    <div class="kids" class:closed={isClosed("catalogs")}><div>
      {#each repos.catalogs as c (c.id)}
        <button class="it sub" class:on={at("catalog/" + c.id)} onclick={() => go("/repos/catalog/" + c.id, "soft")}>
          <span class="dot sq" style="background:{c.color}"></span><span class="grow ell">{c.name}</span><span class="n">{num(c.count)}</span>
        </button>
      {/each}
      {#if onnew}<button class="it sub add" onclick={onnew}><Plus size={13} /> Novo catálogo</button>{/if}
    </div></div>
  {/if}
</div>

<style>
  .tree { display: flex; flex-direction: column; gap: 1px; }
  .it, .gh { display: flex; align-items: center; gap: 8px; width: 100%; height: 30px; padding: 0 10px; border: 0; border-radius: 8px; background: none;
    color: var(--text-2); font: 500 13px var(--font); cursor: pointer; text-align: left; transition: background var(--t), color var(--t), padding var(--t) var(--ease); }
  .it:hover, .gh:hover { background: color-mix(in srgb, var(--surface-2) 70%, transparent); color: var(--text); }
  .it.on { background: var(--accent-soft); color: var(--text); font-weight: 600; }
  .it :global(.star) { color: var(--warn); flex: none; }
  .gh { height: 28px; margin-top: 6px; font: 600 12px var(--font); color: var(--muted); }
  .gh :global(.chev) { flex: none; transition: transform var(--t) var(--ease); }
  .gh :global(.chev.open) { transform: rotate(90deg); }
  .sub { padding-left: 30px; height: 28px; font-size: 12.5px; }
  .row { position: relative; }
  .more { position: absolute; right: 4px; top: 50%; transform: translateY(-50%); opacity: 0; transition: opacity var(--t-fast); }
  .row:hover .more, .row:focus-within .more, .more:has(:global(.menu.open)) { opacity: 1; }
  .row:hover .n { opacity: 0; }
  .compact .more :global(.btn) { width: 22px; height: 22px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .dot.sq { border-radius: 3px; }
  .n { font-size: 11px; color: var(--faint); font-variant-numeric: tabular-nums; transition: opacity var(--t-fast); }
  .add { color: var(--accent); }
  .top { margin-top: 6px; }
  /* recolher com grid-rows 1fr→0fr: anima a altura real sem medir nada */
  .kids { display: grid; grid-template-rows: 1fr; transition: grid-template-rows 0.3s var(--ease-out), opacity 0.25s var(--ease); }
  .kids > div { overflow: hidden; min-height: 0; display: flex; flex-direction: column; gap: 1px; }
  .kids.closed { grid-template-rows: 0fr; opacity: 0; }

  /* versão da barra lateral do app: mais compacta, alinhada aos subitens de lá */
  .compact .it, .compact .gh { height: 26px; font-size: 12.5px; padding-left: 36px; }
  .compact .gh { margin-top: 2px; font-size: 12px; padding-left: 22px; }
  .compact .sub { padding-left: 48px; }
</style>
