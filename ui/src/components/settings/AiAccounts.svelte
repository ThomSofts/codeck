<script lang="ts">
  // Contas de IA: cada conta é uma pasta de configuração da CLI (Claude: CLAUDE_CONFIG_DIR; Codex: CODEX_HOME).
  // O login é o da própria CLI — o app nunca lê nem guarda token de IA. Por conta: limite, o que está fazendo agora
  // (projeto, tarefa, rodando/esperando você) e as sessões abertas fora do app.
  import { Check, FolderOpen, Gauge, Plus, RefreshCw, Search, TerminalSquare } from "@lucide/svelte";
  import { get, post } from "../../lib/api";
  import { pickFolder } from "../../lib/native";
  import { go } from "../../lib/router.svelte";
  import { store } from "../../lib/store.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { work, type AiAccount } from "../../lib/work.svelte";
  import AgentIcon from "../work/AgentIcon.svelte";
  import AiAccountCard from "./AiAccountCard.svelte";

  let found = $state<{ provider: string; dir: string; name: string; email?: string }[]>([]);
  let adding = $state<{ provider: string; name: string; dir: string } | null>(null);
  let rescanning = $state(false);
  $effect(() => { work.loadAi(); work.loadActivity(); });
  const home = (p: string) => p.replace(/^\/Users\/[^/]+|^C:\\Users\\[^\\]+/i, "~");
  const scopes = $derived(["*", ...(store.s?.orgs || []).map(o => `azure:${o}`), ...(store.s?.githubAccounts || []).map(a => `github:${a.login}`)]);
  const scopeLabel = (s: string) => (s === "*" ? "Geral" : s.replace(/^azure:/, "Azure · ").replace(/^github:/, "GitHub · "));

  async function detect() {
    found = (await get<any>("ai/detect")).found.filter((f: any) => !work.ai.some(a => a.dir === f.dir));
    if (!found.length) ui.toast("Nenhuma conta nova encontrada", "info");
  }
  async function rescan() {
    rescanning = true;
    try {
      await work.loadAi(true);
      const n = Object.values(work.providers).filter(p => p.installed).length;
      ui.toast(n ? `${n} CLI(s) de IA encontrada(s)` : "Nenhuma CLI de IA encontrada no PATH do seu terminal", n ? "ok" : "info");
    } catch (e) { ui.error(e); }
    rescanning = false;
  }
  async function add(f: { provider: string; name: string; dir: string }) {
    try { await post("ai/save", f); await work.loadAi(); found = found.filter(x => x.dir !== f.dir); adding = null; ui.toast("Conta adicionada"); } catch (e) { ui.error(e); }
  }
  async function remove(a: AiAccount) {
    if (!(await ui.ask({ title: `Tirar ${a.label} · ${a.name} do app?`, message: "A pasta e o login continuam na máquina; só some daqui.", confirm: "Tirar", danger: true }))) return;
    await post("ai/delete", { id: a.id }); await work.loadAi();
  }
  const loginCmd = (p: string, dir: string) => p === "claude" ? `CLAUDE_CONFIG_DIR=${dir} claude` : p === "codex" ? `CODEX_HOME=${dir} codex login` : p === "cursor" ? "cursor-agent login" : p;
  const grouped = $derived(Object.entries(work.providers).map(([k, v]) => ({ key: k, ...v, accounts: work.ai.filter(a => a.provider === k) })).filter(g => g.accounts.length || g.installed));
  // ordem: quem está trabalhando/precisa de você primeiro, depois quem tem limite lido
  const rank = (a: AiAccount) => ({ "needs-you": 0, working: 1, done: 2, idle: 3 } as Record<string, number>)[work.activity[a.id]?.state || ""] ?? (a.usage?.rateLimits?.length ? 4 : 5);
  const summary = $derived.by(() => {
    const acts = Object.values(work.activity);
    return { working: acts.filter(x => x.state === "working").length, need: acts.filter(x => x.state === "needs-you").length,
      sessions: acts.reduce((n, x) => n + x.sessions.length + x.external.length, 0) };
  });
</script>

<div class="head"><div class="ht"><h2>Contas de IA</h2><p class="muted small">Claude Code, Codex, Cursor e outras CLIs. Cada conta é uma pasta de configuração — o login é o da própria CLI; o app nunca lê token.</p></div>
  <div class="hb">
    <button class="btn sm ghost" onclick={rescan} disabled={rescanning} title="Procura as CLIs de novo no PATH do seu terminal (.zshrc incluso)"><Search size={14} class={rescanning ? "spin" : ""} /> Procurar CLIs</button>
    <button class="btn sm ghost" onclick={detect}><RefreshCw size={14} /> Procurar contas</button>
    <button class="btn sm" onclick={() => (adding = { provider: "claude", name: "", dir: "" })}><Plus size={14} /> Conta</button>
  </div></div>

<div class="stats">
  <span><b>{work.ai.length}</b> contas</span>
  <span class:hot={summary.working}><b>{summary.working}</b> trabalhando</span>
  <span class:warn={summary.need}><b>{summary.need}</b> esperando você</span>
  <span><b>{summary.sessions}</b> sessões abertas</span>
  <span class="spacer"></span>
  {#if work.ai.some(a => a.provider === "claude" && a.installed)}
    <button class="btn sm" disabled={Object.keys(work.probing).length > 0} onclick={() => work.probe()}><Gauge size={13} /> Ler limite de todas</button>
  {/if}
</div>

{#if found.length}
  <div class="card org found"><b>Encontradas nesta máquina</b>
    {#each found as f (f.dir)}<div class="row"><AgentIcon provider={f.provider} size={18} /><div class="grow"><b>{f.name}</b><span class="tiny muted mono">{home(f.dir)}{f.email ? " · " + f.email : ""}</span></div><button class="btn sm" onclick={() => add(f)}><Plus size={13} /> Adicionar</button></div>{/each}
  </div>
{/if}

{#if adding}
  <div class="card org">
    <b>Nova conta</b>
    <div class="row3">
      <select class="input" bind:value={adding.provider}>{#each Object.entries(work.providers) as [k, p] (k)}<option value={k}>{p.label}</option>{/each}</select>
      <input class="input" bind:value={adding.name} placeholder="nome (ex.: dematec)" />
    </div>
    <div class="row3"><input class="input mono" bind:value={adding.dir} placeholder={adding.provider === "claude" ? "~/.claude-minha-conta" : adding.provider === "codex" ? "~/.codex-minha-conta" : "pasta de configuração"} />
      <button class="btn" onclick={async () => { const p = await pickFolder("Pasta de configuração da conta"); if (p && adding) adding.dir = p; }}><FolderOpen size={14} /></button></div>
    {#if adding.dir}<div class="small muted">Depois de salvar, use <b>Entrar</b> no menu da conta para fazer o login (<span class="mono">{loginCmd(adding.provider, adding.dir)}</span>).</div>{/if}
    <div class="row3 end"><button class="btn sm" onclick={() => (adding = null)}>Cancelar</button><button class="btn sm primary" disabled={!adding.dir} onclick={() => add(adding!)}><Check size={13} /> Salvar</button></div>
  </div>
{/if}

{#each grouped as g (g.key)}
  <div class="card org">
    <div class="gh"><AgentIcon provider={g.key} size={18} /><b>{g.label}</b>
      {#if g.installed}<span class="tiny muted mono ell" title="CLI usada pelo app">{home((g as any).bin || "")}</span>
      {:else}<span class="pill warn">CLI não encontrada</span>
        <button class="btn sm ghost" onclick={rescan} disabled={rescanning}><TerminalSquare size={13} /> Procurar de novo</button>{/if}
    </div>
    {#if !g.installed}<p class="small muted">O app procura a CLI no PATH do seu terminal (lendo o .zprofile e o .zshrc) e nas pastas de instalação comuns (~/.local/bin, npm, Homebrew, nvm…). Se ela está instalada e mesmo assim não aparece, abra um terminal e rode <span class="mono">command -v {g.key === "cursor" ? "cursor-agent" : g.key}</span>.</p>{/if}
    <div class="grid">
      {#each [...g.accounts].sort((x, y) => rank(x) - rank(y)) as a (a.id)}
        <AiAccountCard {a} {scopes} {scopeLabel} onremove={() => remove(a)} />
      {:else}<div class="small muted">Nenhuma conta. “Procurar contas” acha as pastas existentes; “Conta” cria uma nova.</div>{/each}
    </div>
  </div>
{/each}

<div class="card org usage">
  <div class="gh"><b>Uso</b><span class="muted small">custo, tempo e limites por projeto</span><span class="spacer"></span>
    <button class="btn sm" onclick={() => go("/ai")}>Abrir Uso de IA →</button></div>
</div>

<style>
  .head { display: flex; align-items: flex-start; gap: 8px 16px; flex-wrap: wrap; }
  .ht { flex: 1 1 360px; min-width: 0; }
  .hb { display: flex; gap: 6px; flex: none; }
  .head h2 { margin: 0 0 4px; }
  .spacer { flex: 1; }
  .stats { display: flex; align-items: center; gap: 16px; margin-top: 12px; padding: 10px 14px; border-radius: 12px; background: var(--surface); border: 1px solid var(--line);
    font-size: 12.5px; color: var(--muted); flex-wrap: wrap; }
  .stats b { color: var(--text); font-variant-numeric: tabular-nums; }
  .stats .hot b { color: var(--accent); } .stats .warn b { color: var(--warn); }
  .card { display: grid; gap: 10px; padding: 14px; margin-top: 12px; }
  .gh { display: flex; align-items: center; gap: 9px; min-width: 0; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 10px; }
  .row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--line); }
  .row .grow { flex: 1; min-width: 0; display: grid; }
  .row3 { display: flex; gap: 8px; }
  .row3 .input { flex: 1; }
  .row3.end { justify-content: flex-end; }
  .found { border-color: var(--accent-line); }
  p { margin: 0; }
</style>
