<script lang="ts">
  // Contas de IA: cada conta é uma pasta de configuração da CLI (Claude: CLAUDE_CONFIG_DIR; Codex: CODEX_HOME).
  // O login é o da própria CLI — o app nunca lê nem guarda token de IA. Aqui é a gestão: apelido e grupo (o cliente),
  // a padrão de cada organização, login; no topo, qual usar agora. O uso em detalhe fica em Uso de IA.
  import { AlertTriangle, ArrowRight, Check, FolderOpen, Gauge, Plus, RefreshCw, Search, Sparkles, TerminalSquare, X } from "@lucide/svelte";
  import { get, post } from "../../lib/api";
  import { pickFolder } from "../../lib/native";
  import { go } from "../../lib/router.svelte";
  import { store } from "../../lib/store.svelte";
  import { ui } from "../../lib/ui.svelte";
  import { work, type AiAccount } from "../../lib/work.svelte";
  import AgentIcon from "../work/AgentIcon.svelte";
  import AiAccountItem from "./AiAccountItem.svelte";
  import AccountAvatar from "../ai/AccountAvatar.svelte";
  import { clock, home, rank } from "../ai/limits.svelte";

  let found = $state<{ provider: string; dir: string; name: string; email?: string }[]>([]);
  let adding = $state<{ provider: string; name: string; dir: string; group?: string } | null>(null);
  let rescanning = $state(false);
  $effect(() => { work.loadAi(); work.loadActivity(); });
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
  async function add(f: { provider: string; name: string; dir: string; group?: string }) {
    try { await post("ai/save", f); await work.loadAi(); found = found.filter(x => x.dir !== f.dir); adding = null; ui.toast("Conta adicionada"); } catch (e) { ui.error(e); }
  }
  async function remove(a: AiAccount) {
    if (!(await ui.ask({ title: `Tirar ${a.label} · ${a.name} do app?`, message: "A pasta e o login continuam na máquina; só some daqui.", confirm: "Tirar", danger: true }))) return;
    await post("ai/delete", { id: a.id }); await work.loadAi();
  }
  const loginCmd = (p: string, dir: string) => p === "claude" ? `CLAUDE_CONFIG_DIR=${dir} claude` : p === "codex" ? `CODEX_HOME=${dir} codex login` : p === "cursor" ? "cursor-agent login" : p;
  const grouped = $derived(Object.entries(work.providers).map(([k, v]) => ({ key: k, ...v, accounts: work.ai.filter(a => a.provider === k) })).filter(g => g.accounts.length || g.installed));
  // ordem estável dentro da CLI: por grupo e apelido (a ordem por fôlego é a de Uso de IA)
  const order = (list: AiAccount[]) => [...list].sort((x, y) => (x.group || "~").localeCompare(y.group || "~") || x.name.localeCompare(y.name));
  // a conta com mais fôlego agora (onde abrir o próximo agente)
  const best = $derived(rank(work.ai.filter(a => a.installed), clock.now).find(r => r.free != null && !r.blocked) || null);
  const probingAny = $derived(Object.keys(work.probing).length > 0);
</script>

<div class="head"><div class="ht"><h2>Contas de IA</h2><p class="muted small">Claude Code, Codex, Cursor e outras CLIs. Cada conta é uma pasta de configuração — o login é o da própria CLI; o app nunca lê token.</p></div>
  <div class="hb">
    <button class="btn sm ghost" onclick={rescan} disabled={rescanning} title="Procura as CLIs de novo no PATH do seu terminal (.zshrc incluso)"><Search size={14} class={rescanning ? "spin" : ""} /> Procurar CLIs</button>
    <button class="btn sm ghost" onclick={detect}><RefreshCw size={14} /> Procurar contas</button>
    <button class="btn sm primary" onclick={() => (adding = { provider: "claude", name: "", dir: "", group: "" })}><Plus size={14} /> Conta</button>
  </div></div>

<div class="rec">
  {#if best}
    <AccountAvatar a={best.a} size={30} />
    <span class="grow"><span class="k"><Sparkles size={12} /> Mais fôlego agora</span><b>{best.a.name}</b> · <span class="free">{Math.round(best.free!)}% livre</span><span class="why">&nbsp;— {best.why}</span></span>
  {:else}<span class="grow muted small">Nenhum limite lido ainda.</span>{/if}
  {#if work.ai.some(a => a.provider === "claude" && a.installed)}
    <button class="btn sm ghost" disabled={probingAny} onclick={() => work.probe()}><Gauge size={13} class={probingAny ? "spin" : ""} /> {probingAny ? "Lendo…" : "Ler limites"}</button>
  {/if}
  <button class="btn sm ghost" onclick={() => go("/ai")}>IA <ArrowRight size={13} /></button>
</div>

{#if found.length}
  <div class="card org found"><div class="fh"><b>Encontradas nesta máquina</b><span class="tiny muted">{found.length} pasta(s) de configuração ainda fora do app</span><span class="grow"></span><button class="btn sm ghost icon" title="Fechar" onclick={() => (found = [])}><X size={13} /></button></div>
    {#each found as f (f.dir)}<div class="frow"><AgentIcon provider={f.provider} size={18} /><div class="grow"><b>{f.name}</b><span class="tiny muted mono">{home(f.dir)}{f.email ? " · " + f.email : ""}</span></div><button class="btn sm" onclick={() => add(f)}><Plus size={13} /> Adicionar</button></div>{/each}
  </div>
{/if}

{#if adding}
  <div class="card org add">
    <b>Nova conta</b>
    <div class="row3">
      <select class="input" bind:value={adding.provider}>{#each Object.entries(work.providers) as [k, p] (k)}<option value={k}>{p.label}</option>{/each}</select>
      <input class="input" bind:value={adding.name} placeholder="apelido (ex.: Ademar)" />
      <input class="input" bind:value={adding.group} placeholder="grupo (ex.: Dematec)" />
    </div>
    <div class="row3"><input class="input mono" bind:value={adding.dir} placeholder={adding.provider === "claude" ? "~/.claude-minha-conta" : adding.provider === "codex" ? "~/.codex-minha-conta" : "pasta de configuração"} />
      <button class="btn" title="Escolher pasta" onclick={async () => { const p = await pickFolder("Pasta de configuração da conta"); if (p && adding) adding.dir = p; }}><FolderOpen size={14} /></button></div>
    {#if adding.dir}<div class="small muted">Depois de salvar, use <b>Entrar</b> no menu da conta para fazer o login (<span class="mono">{loginCmd(adding.provider, adding.dir)}</span>).</div>{/if}
    <div class="row3 end"><button class="btn sm" onclick={() => (adding = null)}>Cancelar</button><button class="btn sm primary" disabled={!adding.dir} onclick={() => add(adding!)}><Check size={13} /> Salvar</button></div>
  </div>
{/if}

{#each grouped as g (g.key)}
  <section class="prov">
    <div class="gh">
      <span class="pic"><AgentIcon provider={g.key} size={18} /></span>
      <b>{g.label}</b>
      <span class="cnt">{g.accounts.length} conta{g.accounts.length === 1 ? "" : "s"}</span>
      {#if g.installed}<span class="bin mono ell" title="CLI usada pelo app">{home((g as any).bin || "")}</span>{/if}
    </div>
    {#if !g.installed}
      <div class="miss">
        <AlertTriangle size={16} />
        <div class="grow"><b>CLI do {g.label} não encontrada</b>
          <p class="small muted">O app procura no PATH do seu terminal (lendo o .zprofile e o .zshrc) e nas pastas de instalação comuns (~/.local/bin, npm, Homebrew, nvm…). Se ela está instalada, rode <span class="mono">command -v {g.key === "cursor" ? "cursor-agent" : g.key}</span> num terminal para conferir.</p></div>
        <button class="btn sm" onclick={rescan} disabled={rescanning}><TerminalSquare size={13} /> Procurar de novo</button>
      </div>
    {/if}
    <div class="list" role="list">
      {#each order(g.accounts) as a, i (a.id)}
        <AiAccountItem {a} {scopes} {scopeLabel} index={i} onremove={() => remove(a)} />
      {:else}<div class="small muted none">Nenhuma conta. “Procurar contas” acha as pastas existentes; “Conta” cria uma nova.</div>{/each}
    </div>
  </section>
{/each}

<style>
  .head { display: flex; align-items: flex-start; gap: 8px 16px; flex-wrap: wrap; }
  .ht { flex: 1 1 360px; min-width: 0; }
  .hb { display: flex; gap: 6px; flex: none; }
  .head h2 { margin: 0 0 4px; }
  .grow { flex: 1; min-width: 0; }
  .rec { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 14px; padding: 10px 12px 10px 14px; border-radius: var(--r);
    background: color-mix(in srgb, var(--good) 6%, var(--surface)); border: 1px solid color-mix(in srgb, var(--good) 22%, var(--line)); font-size: 13px; }
  .rec .k { display: inline-flex; align-items: center; gap: 5px; margin-right: 8px; font-size: 12px; font-weight: 600; color: var(--good); }
  .rec .free { color: var(--good); font-weight: 650; font-variant-numeric: tabular-nums; }
  .rec .why { color: var(--muted); }
  .list { border-radius: var(--r); border: 1px solid var(--line); background: var(--surface); overflow: hidden; }
  .card { display: grid; gap: 10px; padding: 14px; margin-top: 12px; }
  .fh { display: flex; align-items: center; gap: 10px; }
  .frow { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--line); }
  .frow .grow { display: grid; }
  .row3 { display: flex; gap: 8px; }
  .row3 .input { flex: 1; }
  .row3.end { justify-content: flex-end; }
  .found { border-color: var(--accent-line); animation: rise 0.25s var(--ease-out); }
  .add { animation: rise 0.25s var(--ease-out); }
  .prov { display: grid; gap: 10px; margin-top: 22px; }
  .gh { display: flex; align-items: center; gap: 9px; min-width: 0; padding: 0 2px; }
  .gh b { font-size: 14px; }
  .pic { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 8px; background: var(--surface-2); border: 1px solid var(--line); flex: none; }
  .cnt { font: 600 11px/1 var(--font); padding: 4px 8px; border-radius: 99px; background: var(--surface-2); color: var(--text-2); }
  .bin { margin-left: auto; font-size: 11px; color: var(--faint); max-width: 45%; }
  .miss { display: flex; align-items: flex-start; gap: 10px; padding: 12px 14px; border-radius: 12px; background: var(--warn-soft);
    border: 1px solid color-mix(in srgb, var(--warn) 35%, transparent); color: var(--text); }
  .miss > :global(svg) { color: var(--warn); flex: none; margin-top: 2px; }
  .miss p { margin: 3px 0 0; }
  .none { padding: 6px 2px; }
  p { margin: 0; }
</style>
