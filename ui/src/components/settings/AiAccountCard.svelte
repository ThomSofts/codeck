<script lang="ts">
  // Uma conta de IA por inteiro: limite (5 h / semanal) com a contagem para o reset, o que ela está fazendo agora —
  // em qual projeto/tarefa, se está rodando ou esperando você —, sessões abertas fora do app e as ações da conta.
  import { AlertTriangle, Copy, ExternalLink, LogIn, RefreshCw, Star, Trash2 } from "@lucide/svelte";
  import { ago } from "../../lib/format";
  import { go } from "../../lib/router.svelte";
  import { post } from "../../lib/api";
  import { ui } from "../../lib/ui.svelte";
  import { STATUS, work, type AiAccount } from "../../lib/work.svelte";
  import AgentIcon from "../work/AgentIcon.svelte";
  import Menu from "../Menu.svelte";

  let { a, compact = false, scopes = [], scopeLabel = (s: string) => s, onremove = undefined }:
    { a: AiAccount; compact?: boolean; scopes?: string[]; scopeLabel?: (s: string) => string; onremove?: () => void } = $props();

  const act = $derived(work.activity[a.id]);
  const probing = $derived(!!work.probing[a.id] || !!act?.probing);
  const limits = $derived(a.usage?.rateLimits || []);
  let now = $state(Date.now());
  $effect(() => { const t = setInterval(() => (now = Date.now()), 30000); return () => clearInterval(t); });

  const STATE: Record<string, [string, string]> = {
    "needs-you": ["precisa de você", "warn"], working: ["trabalhando", "accent"], done: ["terminou", "good"], idle: ["sessão aberta", "muted"], free: ["livre", "neutral"],
  };
  const home = (p: string) => p.replace(/^\/Users\/[^/]+|^C:\\Users\\[^\\]+/i, "~");
  function reset(iso: string | null) {
    if (!iso) return "";
    const ms = new Date(iso).getTime() - now;
    if (ms <= 0) return "já resetou";
    const h = Math.floor(ms / 3.6e6), m = Math.round((ms % 3.6e6) / 6e4);
    return h >= 24 ? `reseta em ${Math.floor(h / 24)}d ${h % 24}h` : h ? `reseta em ${h}h${String(m).padStart(2, "0")}` : `reseta em ${m} min`;
  }
  const expired = (iso: string | null) => !!iso && new Date(iso).getTime() <= now;
  const tone = (p: number | null | undefined) => (p == null ? "" : p >= 90 ? "bad" : p >= 70 ? "warn" : "good");
  const src = (s?: string) => (s === "probe" ? "leitura direta" : s === "claude" ? "sessão do app" : s === "codex" ? "log do Codex" : s || "");
  const loginCmd = $derived(a.provider === "claude" ? `CLAUDE_CONFIG_DIR=${a.dir} claude` : a.provider === "codex" ? `CODEX_HOME=${a.dir} codex login` : a.provider === "cursor" ? "cursor-agent login" : a.provider);
  async function copy(t: string) { await navigator.clipboard.writeText(t); ui.toast("Comando copiado"); }
  async function login() {
    try { await post("ai/login", { id: a.id }); ui.toast("Terminal aberto — faça o login lá e depois clique em “Ler agora”", "info"); } catch (e) { ui.error(e); }
  }
  async function setDefault(scope: string) { await post("ai/default", { scope, id: a.id }); await work.loadAi(); ui.toast("Conta padrão salva"); }
  function openSession(repoId: string | null) { if (repoId) go("/work/" + repoId); }
  const sessions = $derived([...(act?.sessions || []).map(s => ({ ...s, ext: false })), ...(act?.external || []).map(s => ({ ...s, ext: true, title: null as string | null, task: null }))]);
  const defaultsOf = $derived(Object.entries(work.defaults).filter(([, id]) => id === a.id).map(([sc]) => sc));
</script>

<div class="acc" class:compact class:busy={act?.state === "working"} class:need={act?.state === "needs-you"}>
  <div class="head">
    <span class="ic"><AgentIcon provider={a.provider} size={18} /></span>
    <div class="who">
      <b class="ell">{a.name}</b>
      <span class="tiny muted ell">{a.email || a.label}{compact ? "" : " · " + home(a.dir)}</span>
    </div>
    {#if act}<span class="pill {STATE[act.state]?.[1]}" class:pulse={act.state === "working"}>{STATE[act.state]?.[0]}</span>{/if}
    {#each defaultsOf as sc (sc)}<span class="pill accent" title="Conta padrão"><Star size={10} /> {scopeLabel(sc)}</span>{/each}
    {#if !compact}
      <Menu items={[
        ...(a.provider === "claude" ? [{ label: "Ler o limite agora", icon: RefreshCw, onclick: () => work.probe(a.id), disabled: probing }] : []),
        { label: "Entrar (login da CLI)", icon: LogIn, onclick: login },
        { label: "Copiar comando de login", icon: Copy, onclick: () => copy(loginCmd) },
        ...(scopes.length ? [{ separator: true }, { heading: "Padrão para…" }, ...scopes.map(sc => ({ label: scopeLabel(sc), icon: Star, onclick: () => setDefault(sc) }))] : []),
        ...(onremove ? [{ separator: true }, { label: "Tirar do app", icon: Trash2, danger: true, onclick: onremove }] : []),
      ]} />
    {/if}
  </div>

  {#if act?.probeError}
    <div class="err small"><AlertTriangle size={13} /><span class="grow">{act.probeError.error}</span>
      <button class="btn sm" onclick={login}><LogIn size={12} /> Entrar</button></div>
  {/if}

  <div class="limits">
    {#each limits as w (w.window)}
      {@const used = expired(w.resetsAt) ? 0 : w.used || 0}
      <div class="lim">
        <div class="lt"><span>{w.window}</span><b class={tone(used)}>{Math.round(used)}%</b></div>
        <div class="bar"><span class={tone(used)} style="width:{Math.min(100, used)}%"></span></div>
        <span class="tiny muted">{reset(w.resetsAt)}</span>
      </div>
    {:else}
      <div class="nolim small muted">
        {#if a.provider === "claude"}Limite ainda não lido.{:else if a.provider === "codex"}O limite aparece depois da primeira sessão do Codex.{:else}Esta CLI não informa limite.{/if}
      </div>
    {/each}
    {#if a.provider === "claude"}
      <button class="btn sm ghost read" disabled={probing || !a.installed} title="Manda um “ok” mínimo pelo Haiku na própria CLI e lê o limite que ela devolve (custa frações de centavo)"
        onclick={() => work.probe(a.id)}><RefreshCw size={12} class={probing ? "spin" : ""} /> {probing ? "Lendo…" : "Ler agora"}</button>
    {/if}
  </div>
  {#if a.usage?.updated && limits.length}<div class="tiny muted upd">lido há {ago(a.usage.updated)} · {src(a.usage.source)}</div>{/if}

  {#if sessions.length}
    <div class="sess">
      {#each sessions.slice(0, compact ? 3 : 8) as s (s.ext ? "x" + (s as any).session : (s as any).sid)}
        {@const st = STATUS[s.status] || STATE[s.status] || [s.status, "muted"]}
        <button class="ses" class:clickable={!!s.repoId} onclick={() => openSession(s.repoId)} title={s.ext ? `Sessão aberta fora do app · ${(s as any).cwd}` : s.title || ""}>
          <span class="sdot {st[1]}" class:pulse={s.status === "working"}></span>
          <span class="grow ell"><b>{s.project || "—"}</b>{#if s.title && !s.ext}<span class="muted"> · {s.title.replace(/^.*· /, "")}</span>{/if}</span>
          {#if s.ext}<span class="pill neutral tiny-pill">fora do app</span>{/if}
          <span class="tiny muted">{st[0]}</span>
          {#if !s.ext && (s as any).context != null}<span class="tiny muted">{Math.round((s as any).context)}% ctx</span>{/if}
          {#if s.repoId}<ExternalLink size={11} class="muted" />{/if}
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .acc { display: grid; gap: 10px; padding: 12px 14px; border-radius: 12px; background: var(--surface-2); border: 1px solid var(--line);
    animation: rise 0.25s var(--ease-out) both; transition: border-color var(--t); }
  .acc.busy { border-color: var(--accent-line); }
  .acc.need { border-color: color-mix(in srgb, var(--warn) 55%, transparent); }
  .head { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .ic { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 9px; background: var(--surface-3); flex: none; }
  .who { display: grid; min-width: 0; flex: 1; }
  .err { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 9px; background: var(--bad-soft); color: var(--bad); }
  .err .grow { flex: 1; min-width: 0; }
  .limits { display: flex; align-items: flex-end; gap: 14px; flex-wrap: wrap; }
  .lim { display: grid; gap: 4px; flex: 1; min-width: 120px; }
  .lt { display: flex; justify-content: space-between; font-size: 12px; color: var(--text-2); }
  .lt b.good { color: var(--good); } .lt b.warn { color: var(--warn); } .lt b.bad { color: var(--bad); }
  .bar { height: 6px; border-radius: 99px; background: var(--surface-3); overflow: hidden; }
  .bar span { display: block; height: 100%; border-radius: 99px; background: var(--accent); transition: width 0.5s var(--ease-out); }
  .bar span.good { background: var(--good); } .bar span.warn { background: var(--warn); } .bar span.bad { background: var(--bad); }
  .nolim { flex: 1; }
  .read { flex: none; }
  .upd { margin-top: -4px; }
  .sess { display: grid; gap: 2px; border-top: 1px solid var(--line); padding-top: 8px; }
  .ses { display: flex; align-items: center; gap: 8px; padding: 5px 6px; border: 0; border-radius: 7px; background: none; color: var(--text-2);
    font: 12.5px var(--font); text-align: left; cursor: default; min-width: 0; }
  .ses.clickable { cursor: pointer; }
  .ses.clickable:hover { background: var(--surface-3); color: var(--text); }
  .ses .grow { flex: 1; min-width: 0; }
  .ses b { color: var(--text); font-weight: 600; }
  .sdot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); flex: none; }
  .sdot.accent { background: var(--accent); } .sdot.good { background: var(--good); } .sdot.warn { background: var(--warn); } .sdot.info { background: var(--info); }
  .pulse { animation: ping 1.2s var(--ease) infinite; }
  @keyframes ping { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 60%, transparent); } 80%, 100% { box-shadow: 0 0 0 6px transparent; } }
  .tiny-pill { font-size: 10px; padding: 1px 6px; }
  .compact { padding: 10px 12px; gap: 8px; }
</style>
