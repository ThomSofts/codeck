<script lang="ts">
  // Extensões (como o painel do VS Code): as que esta máquina já tem (VS Code, Cursor…), as instaladas pelo Codeck e o
  // marketplace aberto (Open VSX). Tema de cores e de ícones com prévia ao vivo (setas passam pelos temas, Enter fica,
  // Esc volta), "usar a aparência do VS Code", ligar/desligar snippets e linguagens, instalar e desinstalar.
  import { BadgeCheck, Blocks, Check, Download, Palette, Power, RefreshCw, Search, Shapes, Sparkles, Trash2, Wand2, X } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { extensions, fetchBlob, type Ext, type ExtTheme, type Market } from "../../lib/extensions.svelte";
  import { ui } from "../../lib/ui.svelte";

  let q = $state("");
  let market = $state<Market[] | null>(null);
  let searching = $state(false);
  let installing = $state<string | null>(null);
  let picker = $state<"theme" | "icons" | null>(null);
  let pq = $state("");
  let psel = $state(0);
  let sTimer: ReturnType<typeof setTimeout> | undefined;
  let tab = $state<"installed" | "market">("installed");

  $effect(() => { untrack(() => { if (!extensions.loaded) extensions.load(); }); });

  // ícones das extensões instaladas (arquivo da própria extensão)
  let iconUrls = $state<Record<string, string>>({});
  $effect(() => {
    for (const e of extensions.list) {
      if (!e.icon || iconUrls[e.key] !== undefined) continue;
      iconUrls[e.key] = "";
      fetchBlob(e.key, e.icon).then(b => (iconUrls = { ...iconUrls, [e.key]: URL.createObjectURL(b) })).catch(() => {});
    }
  });

  const filtered = $derived.by(() => {
    const t = q.trim().toLowerCase();
    return extensions.list.filter(e => !t || `${e.displayName} ${e.id} ${e.description} ${e.publisher}`.toLowerCase().includes(t));
  });
  const groups = $derived([
    { key: "themes", label: "Temas de cores", items: filtered.filter(e => e.themes.length && !e.builtin) },
    { key: "icons", label: "Temas de ícones", items: filtered.filter(e => e.iconThemes.length && !e.themes.length && !e.builtin) },
    { key: "contrib", label: "Snippets e linguagens", items: filtered.filter(e => !e.themes.length && !e.iconThemes.length && (e.snippets.length || e.languages.length)) },
    { key: "builtin", label: "Temas que vêm com o VS Code", items: filtered.filter(e => e.builtin) },
    { key: "code", label: "Precisam do VS Code (rodam código)", items: filtered.filter(e => e.code && !e.themes.length && !e.iconThemes.length && !e.snippets.length && !e.languages.length) },
  ].filter(g => g.items.length));
  let shut = $state<Record<string, boolean>>({ code: true, builtin: true });

  function searchMarket() {
    clearTimeout(sTimer);
    sTimer = setTimeout(async () => {
      searching = true;
      try { market = (await extensions.search(q.trim(), q.trim() ? undefined : "Themes")).results; } catch (e) { ui.error(e); market = []; }
      searching = false;
    }, 300);
  }
  $effect(() => { if (tab === "market") untrack(searchMarket); });
  async function install(m: Market) {
    installing = m.id;
    const e = await extensions.install(m);
    installing = null;
    if (market) market = market.map(x => (x.id === m.id ? { ...x, installed: true, installedFrom: "Codeck" } : x));
    if (e && (e.themes.length || e.iconThemes.length)) ui.toast(`${e.displayName}: escolha em “Tema de cores”/“Ícones” no topo`, "info");
  }

  // ------------------------------------------------------------ seletor com prévia ao vivo
  type Opt = { ext: Ext | null; theme: any; label: string; sub: string };
  const opts = $derived.by<Opt[]>(() => {
    const t = pq.trim().toLowerCase();
    const base: Opt[] = picker === "theme"
      ? [{ ext: null, theme: null, label: "Codeck (padrão)", sub: "o tema do app, claro ou escuro" }, ...extensions.themes.map(x => ({ ext: x.ext, theme: x.theme, label: x.theme.label, sub: `${x.ext.displayName} · ${x.ext.source}` }))]
      : [{ ext: null, theme: null, label: "Codeck (padrão)", sub: "ícones embutidos" }, ...extensions.iconThemes.map(x => ({ ext: x.ext, theme: x.theme, label: x.theme.label, sub: `${x.ext.displayName} · ${x.ext.source}` }))];
    return base.filter(o => !t || `${o.label} ${o.sub}`.toLowerCase().includes(t));
  });
  let before: { ext: Ext | null; theme: any } | null = null;
  function openPicker(kind: "theme" | "icons") {
    picker = kind; pq = ""; psel = 0;
    const cur = kind === "theme" ? extensions.activeTheme : extensions.activeIcons;
    const e = cur ? extensions.list.find(x => x.id === cur.ext) || null : null;
    before = { ext: e, theme: e ? (kind === "theme" ? e.themes : e.iconThemes).find(t => t.id === cur!.id) : null };
    requestAnimationFrame(() => { psel = Math.max(0, opts.findIndex(o => o.ext?.id === before?.ext?.id && o.theme?.id === before?.theme?.id)); });
  }
  function preview(i: number) {
    psel = i;
    const o = opts[i];
    if (!o) return;
    if (picker === "theme") extensions.applyTheme(o.ext, o.theme as ExtTheme, false);
    else extensions.applyIcons(o.ext, o.theme, false);
  }
  function commit(i = psel) {
    const o = opts[i];
    if (o) { if (picker === "theme") extensions.applyTheme(o.ext, o.theme); else extensions.applyIcons(o.ext, o.theme); }
    picker = null;
  }
  function cancel() {
    if (before) { if (picker === "theme") extensions.applyTheme(before.ext, before.theme, false); else extensions.applyIcons(before.ext, before.theme, false); }
    picker = null;
  }
  function pkey(e: KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); preview(Math.min(opts.length - 1, psel + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); preview(Math.max(0, psel - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); commit(); }
    else if (e.key === "Escape") { e.preventDefault(); cancel(); }
  }
  const fmtN = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n));
  const kinds = (e: Ext) => [e.themes.length ? `${e.themes.length} tema${e.themes.length > 1 ? "s" : ""}` : "", e.iconThemes.length ? "ícones" : "",
    e.snippets.length ? "snippets" : "", e.languages.length ? `${e.languages.length} linguagem${e.languages.length > 1 ? "ns" : ""}` : ""].filter(Boolean).join(" · ");
</script>

<div class="xv">
  <div class="top">
    <span class="ttl">Extensões</span>
    <button class="ib" title="Procurar de novo" onclick={() => extensions.load(true)}><RefreshCw size={13} class={extensions.loading ? "spin" : ""} /></button>
  </div>
  <div class="look">
    <button class="pick" onclick={() => openPicker("theme")}><Palette size={14} /><span class="ell"><span class="tiny muted">Tema de cores</span><b>{extensions.activeTheme?.label || "Codeck"}</b></span></button>
    <button class="pick" onclick={() => openPicker("icons")}><Shapes size={14} /><span class="ell"><span class="tiny muted">Ícones</span><b>{extensions.activeIcons?.label || "Codeck"}</b></span></button>
  </div>
  {#if extensions.vscodeSettings.length}
    <div class="imp">
      {#each extensions.vscodeSettings as v (v.app)}
        <button class="btn sm" title={Object.entries(v.settings).map(([k, x]) => `${k}: ${x}`).join("\n")} onclick={() => extensions.importVscode(v.settings)}><Wand2 size={13} /> Usar a aparência do {v.app}</button>
      {/each}
    </div>
  {/if}
  <div class="tabs">
    <button class:on={tab === "installed"} onclick={() => (tab = "installed")}>Nesta máquina <span class="n">{extensions.list.length}</span></button>
    <button class:on={tab === "market"} onclick={() => (tab = "market")}>Marketplace</button>
  </div>
  <label class="flt"><Search size={13} /><input bind:value={q} oninput={() => tab === "market" && searchMarket()} placeholder={tab === "market" ? "Buscar no Open VSX (temas, ícones, snippets…)" : "Filtrar extensões…"} />
    {#if q}<button class="x" onclick={() => { q = ""; if (tab === "market") searchMarket(); }}><X size={11} /></button>{/if}</label>

  <div class="list">
    {#if tab === "installed"}
      {#if !extensions.loaded}<div class="none">Procurando extensões…</div>{/if}
      {#each groups as g (g.key)}
        <button class="gh" onclick={() => (shut = { ...shut, [g.key]: !shut[g.key] })}><span class="ell">{g.label}</span><span class="n">{g.items.length}</span></button>
        {#if !shut[g.key]}
          {#each g.items as e (e.key)}
            {@const on = extensions.enabled(e)}
            <div class="ex" class:off={!on && !e.themes.length && !e.iconThemes.length}>
              <span class="ic">{#if iconUrls[e.key]}<img src={iconUrls[e.key]} alt="" />{:else}<Blocks size={18} />{/if}</span>
              <div class="mid">
                <div class="nm"><b class="ell">{e.displayName}</b><span class="tiny muted">{e.version}</span></div>
                <div class="ds ell">{e.description}</div>
                <div class="meta tiny"><span class="src">{e.source}</span>{#if kinds(e)}<span class="muted">{kinds(e)}</span>{/if}{#if e.grammars && !e.themes.length}<span class="muted" title="Gramáticas TextMate ainda não são usadas — o realce vem do Monaco">gramática: não usada</span>{/if}</div>
                <div class="acts">
                  {#if e.themes.length}
                    <button class="btn sm" onclick={(ev) => ui.contextMenu(ev, e.themes.map(t => ({ label: (extensions.activeTheme?.ext === e.id && extensions.activeTheme.id === t.id ? "● " : "") + t.label, onclick: () => extensions.applyTheme(e, t) })))}><Palette size={12} /> Aplicar tema</button>
                  {/if}
                  {#if e.iconThemes.length}
                    <button class="btn sm" onclick={(ev) => ui.contextMenu(ev, e.iconThemes.map(t => ({ label: (extensions.activeIcons?.ext === e.id && extensions.activeIcons.id === t.id ? "● " : "") + t.label, onclick: () => extensions.applyIcons(e, t) })))}><Shapes size={12} /> Usar ícones</button>
                  {/if}
                  {#if e.snippets.length || e.languages.length}
                    <button class="btn sm ghost" title={on ? "Desligar snippets/linguagens desta extensão" : "Ligar"} onclick={() => extensions.toggle(e)}><Power size={12} /> {on ? "Ligada" : "Desligada"}</button>
                  {/if}
                  {#if e.code && !e.themes.length && !e.iconThemes.length && !e.snippets.length && !e.languages.length}
                    <span class="tiny muted">roda código — só no VS Code</span>
                  {/if}
                  {#if e.removable}<button class="btn sm ghost danger" title="Desinstalar" onclick={() => extensions.uninstall(e)}><Trash2 size={12} /></button>{/if}
                </div>
              </div>
            </div>
          {/each}
        {/if}
      {:else}
        {#if extensions.loaded}<div class="none">Nenhuma extensão {q ? "com esse filtro" : "encontrada"}. Instale temas e ícones pelo Marketplace.</div>{/if}
      {/each}
    {:else}
      {#if searching && !market}<div class="none">Buscando no Open VSX…</div>{/if}
      {#if !q.trim() && market?.length}<div class="hint tiny muted"><Sparkles size={12} /> Temas mais baixados</div>{/if}
      {#each market || [] as m (m.id)}
        <div class="ex">
          <span class="ic">{#if m.icon}<img src={m.icon} alt="" loading="lazy" />{:else}<Blocks size={18} />{/if}</span>
          <div class="mid">
            <div class="nm"><b class="ell">{m.displayName}</b>{#if m.verified}<BadgeCheck size={12} class="ver" />{/if}<span class="tiny muted">{m.version}</span></div>
            <div class="ds ell">{m.description}</div>
            <div class="meta tiny"><span class="muted">{m.namespace}</span><span class="muted"><Download size={10} /> {fmtN(m.downloads)}</span>{#if m.rating}<span class="muted">★ {m.rating.toFixed(1)}</span>{/if}</div>
            <div class="acts">
              {#if m.installed}<span class="tiny inst"><Check size={12} /> {m.installedFrom === "Codeck" ? "instalada" : `no ${m.installedFrom}`}</span>
              {:else}<button class="btn sm primary" disabled={installing === m.id} onclick={() => install(m)}><Download size={12} /> {installing === m.id ? "Instalando…" : "Instalar"}</button>{/if}
            </div>
          </div>
        </div>
      {:else}
        {#if market && !searching}<div class="none">Nada encontrado no Open VSX.</div>{/if}
      {/each}
    {/if}
  </div>
</div>

{#if picker}
  <div class="pk-back" role="presentation" onclick={cancel}>
    <div class="pk" role="dialog" aria-label="Escolher tema" tabindex="-1" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
      <!-- svelte-ignore a11y_autofocus -->
      <input autofocus bind:value={pq} onkeydown={pkey} oninput={() => (psel = 0)} placeholder={picker === "theme" ? "Tema de cores (↑↓ mostra na hora · Enter fica · Esc volta)" : "Tema de ícones (↑↓ mostra na hora · Enter fica · Esc volta)"} />
      <div class="pl">
        {#each opts as o, i (i)}
          <button class:on={i === psel} onmouseenter={() => preview(i)} onclick={() => commit(i)}><span class="ell"><b>{o.label}</b></span><span class="tiny muted ell">{o.sub}</span></button>
        {:else}<div class="none">Nenhum tema. Instale pelo Marketplace (aba ao lado).</div>{/each}
      </div>
    </div>
  </div>
{/if}

<style>
  .xv { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .top { display: flex; align-items: center; gap: 2px; padding: 8px 8px 4px 12px; }
  .ttl { flex: 1; min-width: 0; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ib { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--muted); cursor: pointer; }
  .ib:hover { background: var(--surface-3); color: var(--text); }
  .look { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; padding: 2px 8px 6px; }
  .pick { display: flex; align-items: center; gap: 8px; padding: 7px 9px; border-radius: 9px; border: 1px solid var(--line-2); background: var(--surface-2); color: var(--text);
    font: 12px var(--font); cursor: pointer; text-align: left; transition: border-color var(--t), transform var(--t) var(--spring); min-width: 0; }
  .pick:hover { border-color: var(--accent); transform: translateY(-1px); }
  .pick :global(svg) { color: var(--accent); flex: none; }
  .pick .ell { display: grid; min-width: 0; }
  .pick b { font-weight: 650; overflow: hidden; text-overflow: ellipsis; }
  .imp { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 8px 6px; }
  .tabs { display: flex; gap: 2px; margin: 0 8px 6px; padding: 2px; border-radius: 8px; background: var(--bg-2); border: 1px solid var(--line); }
  .tabs button { flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 5px; height: 24px; border: 0; border-radius: 6px; background: none;
    color: var(--muted); font: 600 11.5px var(--font); cursor: pointer; }
  .tabs button.on { background: var(--surface-3); color: var(--text); }
  .n { font: 650 10px/1 var(--font); padding: 2px 6px; border-radius: 99px; background: var(--surface-3); color: var(--text-2); }
  .flt { display: flex; align-items: center; gap: 6px; height: 28px; margin: 0 8px 6px; padding: 0 8px; border-radius: 7px; border: 1px solid var(--line-2); background: var(--bg-2); color: var(--muted); }
  .flt:focus-within { border-color: var(--accent); }
  .flt input { flex: 1; min-width: 0; border: 0; outline: none; background: none; color: var(--text); font: 12.5px var(--font); }
  .x { display: grid; place-items: center; width: 16px; height: 16px; border: 0; border-radius: 50%; background: var(--surface-3); color: var(--text-2); cursor: pointer; }
  .list { flex: 1; overflow: auto; padding: 0 6px 12px; }
  .gh { display: flex; align-items: center; gap: 6px; width: 100%; padding: 8px 6px 4px; border: 0; background: none; color: var(--muted); cursor: pointer;
    font: 650 10.5px var(--font); text-transform: uppercase; letter-spacing: 0.06em; text-align: left; }
  .gh .ell { flex: 1; }
  .ex { display: flex; gap: 10px; padding: 8px 6px; border-radius: 9px; animation: rise 0.2s var(--ease-out) both; }
  .ex:hover { background: var(--surface-2); }
  .ex.off { opacity: 0.55; }
  .ic { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 9px; background: var(--surface-3); color: var(--muted); flex: none; overflow: hidden; }
  .ic img { width: 100%; height: 100%; object-fit: contain; }
  .mid { flex: 1; min-width: 0; display: grid; gap: 2px; }
  .nm { display: flex; align-items: baseline; gap: 6px; min-width: 0; font-size: 13px; }
  .nm b { font-weight: 650; }
  .nm :global(.ver) { color: var(--accent); flex: none; align-self: center; }
  .ds { font-size: 12px; color: var(--text-2); }
  .meta { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; }
  .meta span { display: inline-flex; align-items: center; gap: 3px; }
  .src { padding: 0 6px; border-radius: 99px; background: var(--accent-soft); color: var(--accent); font-weight: 600; }
  .acts { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; align-items: center; }
  .inst { display: inline-flex; align-items: center; gap: 4px; color: var(--good); font-weight: 600; }
  .danger { color: var(--bad); }
  .none { padding: 12px 6px; font-size: 12px; color: var(--muted); }
  .hint { display: flex; align-items: center; gap: 5px; padding: 4px 6px; }
  .pk-back { position: fixed; inset: 0; z-index: 80; background: rgba(0, 0, 0, 0.12); }
  .pk { position: absolute; top: 64px; left: 50%; transform: translateX(-50%); width: min(560px, calc(100vw - 32px)); border-radius: 12px; overflow: hidden;
    background: var(--elevated); border: 1px solid var(--line-2); box-shadow: var(--shadow-3); animation: rise 0.16s var(--ease-out); }
  .pk input { width: 100%; height: 40px; border: 0; border-bottom: 1px solid var(--line); outline: none; background: none; color: var(--text); font: 13.5px var(--font); padding: 0 14px; }
  .pl { max-height: min(420px, 60vh); overflow: auto; padding: 4px; }
  .pl button { display: flex; align-items: baseline; gap: 10px; width: 100%; padding: 6px 10px; border: 0; border-radius: 7px; background: none; color: var(--text); font: 13px var(--font); cursor: pointer; text-align: left; }
  .pl button.on { background: var(--accent-soft); }
  .pl .ell { min-width: 0; }
</style>
