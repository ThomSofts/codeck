<script lang="ts">
  // Uma conta de IA nas Configurações: quem é (apelido, grupo, e-mail, pasta), de que organização é a padrão, o fôlego
  // resumido e as ações (renomear, ler o limite, entrar, padrão para…, tirar). Os detalhes de uso ficam em Uso de IA.
  import { AlertTriangle, Copy, LogIn, Pencil, RefreshCw, Star, Trash2 } from "@lucide/svelte";
  import { post } from "../../lib/api";
  import { ui } from "../../lib/ui.svelte";
  import { work, type AiAccount } from "../../lib/work.svelte";
  import Menu from "../Menu.svelte";
  import AccountAvatar from "../ai/AccountAvatar.svelte";
  import AccountEdit from "../ai/AccountEdit.svelte";
  import Fuel from "../ai/Fuel.svelte";
  import { home } from "../ai/limits.svelte";

  let { a, scopes = [], scopeLabel = (s: string) => s, onremove, index = 0 }:
    { a: AiAccount; scopes?: string[]; scopeLabel?: (s: string) => string; onremove: () => void; index?: number } = $props();
  let editing = $state(false);
  const act = $derived(work.activity[a.id]);
  const probing = $derived(!!work.probing[a.id] || !!act?.probing);
  const defaultsOf = $derived(Object.entries(work.defaults).filter(([, id]) => id === a.id).map(([sc]) => sc));
  const loginCmd = $derived(a.provider === "claude" ? `CLAUDE_CONFIG_DIR=${a.dir} claude` : a.provider === "codex" ? `CODEX_HOME=${a.dir} codex login` : a.provider === "cursor" ? "cursor-agent login" : a.provider);
  async function login() {
    try { await post("ai/login", { id: a.id }); ui.toast("Terminal aberto — faça o login lá e depois leia o limite", "info"); } catch (e) { ui.error(e); }
  }
  async function setDefault(scope: string) { await post("ai/default", { scope, id: a.id }); await work.loadAi(); ui.toast(`${a.name} é a padrão para ${scopeLabel(scope)}`); }
  const items = $derived([
    { label: "Renomear, grupo e cor…", icon: Pencil, onclick: () => (editing = true) },
    ...(a.provider === "claude" ? [{ label: "Ler o limite agora", icon: RefreshCw, onclick: () => work.probe(a.id), disabled: probing || !a.installed }] : []),
    { separator: true },
    { label: "Entrar (login da CLI)", icon: LogIn, onclick: login },
    { label: "Copiar comando de login", icon: Copy, onclick: () => navigator.clipboard.writeText(loginCmd).then(() => ui.toast("Comando copiado")) },
    ...(scopes.length ? [{ separator: true }, { heading: "Padrão para novos agentes em…" }, ...scopes.map(sc => ({ label: (defaultsOf.includes(sc) ? "★ " : "") + scopeLabel(sc), icon: Star, onclick: () => setDefault(sc) }))] : []),
    { separator: true }, { label: "Tirar do app", icon: Trash2, danger: true, onclick: onremove },
  ]);
</script>

{#if editing}
  <div class="it ed"><AccountEdit {a} ondone={() => (editing = false)} /></div>
{:else}
  <div class="it" style="--i:{index}" data-menu-row oncontextmenu={(e) => ui.contextMenu(e, items)} role="listitem">
    <AccountAvatar {a} state={act?.state} size={36} />
    <div class="who">
      <div class="nm">
        <button class="name" title="Renomear, grupo e cor" onclick={() => (editing = true)}><b class="ell">{a.name}</b><Pencil size={11} /></button>
        {#if a.group}<span class="gchip">{a.group}</span>{/if}
        {#each defaultsOf as sc (sc)}<span class="def" title="Conta padrão para novos agentes"><Star size={10} /> {scopeLabel(sc)}</span>{/each}
      </div>
      <span class="sub ell" title={a.dir}>{a.email ? a.email + " · " : ""}<span class="mono">{home(a.dir)}</span></span>
    </div>
    <div class="fu">
      {#if a.usage?.rateLimits?.length}<Fuel {a} compact />
      {:else}<span class="nol">{a.provider === "claude" ? (a.installed ? "limite ainda não lido" : "CLI não encontrada") : a.provider === "codex" ? "limite aparece depois da 1ª sessão" : "não informa limite"}</span>{/if}
    </div>
    <Menu {items} />
    {#if act?.probeError}
      <div class="perr"><AlertTriangle size={13} /><span class="grow">{act.probeError.error}</span><button class="btn sm" onclick={login}><LogIn size={12} /> Entrar</button></div>
    {/if}
  </div>
{/if}

<style>
  .it { display: grid; grid-template-columns: auto minmax(0, 1fr) minmax(180px, 260px) 28px; align-items: center; gap: 14px; padding: 12px 12px 12px 16px;
    border-top: 1px solid var(--line); transition: background var(--t-fast); animation: fade 0.3s var(--ease-out) both; animation-delay: calc(min(var(--i), 10) * 25ms); }
  .it:first-child { border-top: 0; }
  .it:hover { background: color-mix(in srgb, var(--surface-2) 70%, transparent); }
  .it.ed { display: block; padding: 8px; animation: none; }
  .who { display: grid; gap: 3px; min-width: 0; }
  .nm { display: flex; align-items: center; gap: 7px; min-width: 0; flex-wrap: wrap; }
  .name { display: inline-flex; align-items: center; gap: 6px; min-width: 0; max-width: 100%; padding: 0; border: 0; background: none; color: var(--text); cursor: pointer; font: inherit; }
  .name b { font-size: 14px; font-weight: 650; }
  .name :global(svg) { color: var(--muted); opacity: 0; transition: opacity var(--t-fast); flex: none; }
  .it:hover .name :global(svg), .name:focus-visible :global(svg) { opacity: 1; }
  .gchip { height: 18px; padding: 0 7px; border-radius: 99px; font: 600 10.5px/18px var(--font); color: var(--text-2); background: var(--surface-3); white-space: nowrap; }
  .def { display: inline-flex; align-items: center; gap: 4px; height: 18px; padding: 0 7px; border-radius: 99px; font: 600 10.5px/1 var(--font); white-space: nowrap;
    color: var(--accent); background: var(--accent-soft); }
  .sub { font-size: 11.5px; color: var(--muted); }
  .sub .mono { font-size: 11px; }
  .fu { min-width: 0; }
  .nol { font-size: 12px; color: var(--faint); }
  .perr { grid-column: 1 / -1; display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 9px; background: var(--bad-soft); color: var(--bad); font-size: 12px; }
  .grow { flex: 1; }
  .ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  @media (max-width: 1000px) { .it { grid-template-columns: auto minmax(0, 1fr) 28px; } .fu { grid-column: 2 / -1; grid-row: 2; } }
  @media (prefers-reduced-motion: reduce) { .it { animation: none; } }
</style>
