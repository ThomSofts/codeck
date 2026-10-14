<script lang="ts">
  // Versão nova no canal: um aviso flutuante no canto de baixo (não empurra a tela), que abre num cartão com as novidades e o
  // download com progresso. Versão obrigatória (required): bloqueia até atualizar.
  // Antes de instalar, confere o que se perderia ao reabrir: arquivos não salvos, agentes trabalhando, processos
  // rodando e projetos abertos — e pede para salvar tudo (com "Salvar tudo" ali mesmo).
  import { AlertTriangle, Bot, Check, ChevronDown, FileWarning, FolderGit2, Loader2, Play, Rocket, Save, Sparkles, X } from "@lucide/svelte";
  import { get, post } from "../lib/api";
  import { send } from "../lib/native";
  import { store } from "../lib/store.svelte";
  import { ui } from "../lib/ui.svelte";
  import { work } from "../lib/work.svelte";
  import { dirty, docs, saveDoc } from "./work/Editor.svelte";

  let phase = $state<"idle" | "check" | "download" | "install">("idle");
  let open = $state(false);
  let progress = $state<{ done: number; total: number } | null>(null);
  const u = $derived(store.s?.update);
  const SNOOZE = "codeck.update.snooze";
  // "Depois": recolhe para um botão discreto (até a próxima versão ou 6 h)
  let snoozed = $state((() => { try { const x = JSON.parse(localStorage.getItem(SNOOZE) || "null"); return x && Date.now() - x.at < 6 * 36e5 ? x.version : null; } catch { return null; } })());
  const quiet = $derived(!!u?.version && snoozed === u.version);
  function later() {
    open = false;
    snoozed = u?.version || null;
    try { localStorage.setItem(SNOOZE, JSON.stringify({ version: u?.version, at: Date.now() })); } catch { /* sem armazenamento */ }
  }
  const notes = $derived((u?.notes || "").split(/\n|(?:\s+·\s+)|;\s+/).map((x: string) => x.replace(/^[-•*]\s*/, "").trim()).filter((x: string) => x && !/^v?\d+\.\d+(\.\d+)?$/.test(x)).slice(0, 8));
  const mb = (n: number) => (n / 1048576).toFixed(n > 1048576 * 10 ? 0 : 1);
  const pct = $derived(progress?.total ? Math.min(100, Math.round((100 * progress.done) / progress.total)) : null);

  // ------------------------------------------------------------ o que se perde ao reabrir
  const dirtyKeys = $derived(Object.entries(dirty).filter(([, v]) => v).map(([k]) => k));
  const dirtyNames = $derived(dirtyKeys.map(k => k.split(":").slice(2).join(":").split("/").pop() || k));
  const working = $derived(work.agents.filter(a => a.session?.status === "working" || a.session?.status === "needs-you"));
  const running = $derived(work.projects.flatMap(p => [...p.terms, ...p.tasks.flatMap(t => t.terms)]).filter(t => t.alive && t.kind !== "agent"));
  const risky = $derived(work.projects.length > 0 || dirtyKeys.length > 0);
  let saving = $state(false);
  async function saveAll() {
    saving = true;
    let fail = 0;
    for (const k of dirtyKeys) {
      const d = docs.get(k);
      if (!d) continue;
      try { await saveDoc(d); } catch { fail++; }
    }
    saving = false;
    if (fail) ui.toast(`${fail} arquivo(s) não salvaram (o disco mudou?) — abra e salve à mão`, "error");
    else ui.toast("Tudo salvo", "ok");
  }

  async function start() {
    if (risky && phase === "idle") { phase = "check"; open = true; return; }
    await install();
  }
  async function install() {
    phase = "download";
    open = true;
    progress = null;
    const poll = setInterval(async () => { try { const r = await get<{ progress: any }>("update/progress"); if (r.progress) progress = r.progress; } catch { /* */ } }, 400);
    try {
      const r = await post<{ path: string }>("update/download", {}, { quiet: true });
      clearInterval(poll);
      const pr = progress as { done: number; total: number } | null;
      if (pr?.total) progress = { done: pr.total, total: pr.total };
      phase = "install";
      if (!send({ type: "install", path: r.path })) { ui.toast("Instalação automática só no app instalado", "error"); phase = "idle"; }
    } catch (e) { clearInterval(poll); ui.error(e); phase = "idle"; }
  }
  window.checkUpdate = async (manual = false) => {
    try {
      const r = await post("update/check");
      if (manual) ui.toast(r.disabled ? "Atualização automática só no app instalado" : r.available ? `Versão ${r.version} disponível` : r.error ? "Não consegui consultar agora" : "Você está na versão mais nova", r.available ? "info" : "ok");
      if (manual && r.available) { snoozed = null; open = true; }
      store.load();
    } catch (e) { if (manual) ui.error(e); }
  };
  const ago = (iso?: string) => {
    if (!iso) return "";
    const m = Math.round((Date.now() - new Date(iso).getTime()) / 6e4);
    return m < 60 ? `há ${Math.max(1, m)} min` : m < 1440 ? `há ${Math.round(m / 60)} h` : `há ${Math.round(m / 1440)} d`;
  };
</script>

{#snippet guard()}
  <div class="guard">
    <div class="gh"><AlertTriangle size={18} /><b>Salve tudo antes de atualizar</b></div>
    <p class="small">O Codeck fecha e reabre na versão nova. Terminais e processos abertos são encerrados; as conversas dos agentes dá para retomar depois.</p>
    <ul>
      {#if dirtyKeys.length}
        <li class="bad"><FileWarning size={14} /><span><b>{dirtyKeys.length} arquivo{dirtyKeys.length === 1 ? "" : "s"} sem salvar</b> — {dirtyNames.slice(0, 4).join(", ")}{dirtyNames.length > 4 ? "…" : ""}</span>
          <button class="btn sm" disabled={saving} onclick={saveAll}><Save size={12} /> {saving ? "Salvando…" : "Salvar tudo"}</button></li>
      {:else}
        <li class="ok"><Check size={14} /><span>Nenhum arquivo sem salvar</span></li>
      {/if}
      {#if working.length}<li class="warn"><Bot size={14} /><span><b>{working.length} agente{working.length === 1 ? "" : "s"} trabalhando</b> — {working.slice(0, 3).map(a => a.project.name).join(", ")}</span></li>{/if}
      {#if running.length}<li class="warn"><Play size={13} /><span><b>{running.length} processo{running.length === 1 ? "" : "s"} rodando</b> — {running.slice(0, 3).map(t => t.title).join(", ")}</span></li>{/if}
      {#if work.projects.length}<li><FolderGit2 size={14} /><span>{work.projects.length} projeto{work.projects.length === 1 ? "" : "s"} aberto{work.projects.length === 1 ? "" : "s"} — reabrem sozinhos</span></li>{/if}
    </ul>
    <div class="acts">
      <button class="btn sm ghost" onclick={() => { phase = "idle"; if (!u?.required) open = false; }}>Agora não</button>
      {#if dirtyKeys.length}<button class="btn sm danger-text" onclick={install}>Atualizar sem salvar</button>
        <button class="btn sm primary" disabled={saving} onclick={async () => { await saveAll(); if (!Object.values(dirty).some(Boolean)) install(); }}><Save size={13} /> Salvar tudo e atualizar</button>
      {:else}<button class="btn sm primary" onclick={install}><Rocket size={13} /> Atualizar agora</button>{/if}
    </div>
  </div>
{/snippet}

{#snippet progressView()}
  <div class="prog">
    <div class="ph">
      {#if phase === "install"}<Loader2 size={16} class="spin" /><b>Instalando — o app reabre sozinho</b>
      {:else}<Loader2 size={16} class="spin" /><b>Baixando a versão {u?.version}</b>{/if}
      <span class="spacer"></span>
      {#if pct !== null && phase === "download"}<span class="num">{pct}%</span>{/if}
    </div>
    <div class="track" class:indet={pct === null || phase === "install"}><span style="width:{phase === 'install' ? 100 : pct ?? 30}%"></span></div>
    <div class="tiny muted">{#if progress?.total && phase === "download"}{mb(progress.done)} de {mb(progress.total)} MB · o instalador é conferido (SHA-256) antes de abrir{:else if phase === "install"}conferido e aberto o instalador{:else}conectando…{/if}</div>
  </div>
{/snippet}

{#if u?.available && u.required}
  <div class="block">
    <div class="card box">
      <div class="burst"><Rocket size={34} /></div>
      <h2>Atualização obrigatória</h2>
      <p>A versão {u.version} (build {u.build}) é necessária para continuar.</p>
      {#if notes.length}<ul class="notes left">{#each notes as n (n)}<li><Sparkles size={12} />{n}</li>{/each}</ul>{/if}
      {#if phase === "check"}{@render guard()}
      {:else if phase !== "idle"}{@render progressView()}
      {:else}<button class="btn primary lg" onclick={start}><Rocket size={16} /> Atualizar agora</button>{/if}
    </div>
  </div>
{:else if u?.available}
  <div class="upd" class:open class:quiet={quiet && !open && phase === "idle"} class:busy={phase !== "idle"}>
    {#if !open}
      <button class="pill" onclick={() => (open = true)} title={`Versão ${u.version} disponível`}>
        <span class="ring"></span>
        <span class="rk"><Rocket size={14} /></span>
        {#if !quiet}<span class="pt"><b>Versão {u.version}</b> disponível</span>{/if}
        {#if phase === "download" && pct !== null}<span class="num">{pct}%</span>{/if}
      </button>
    {:else}
      <div class="card2">
        <div class="hd">
          <span class="rk big"><Rocket size={18} /></span>
          <div class="ttl"><b>Codeck {u.version}</b><span class="tiny muted">build {u.build}{u.publishedAt ? " · publicado " + ago(u.publishedAt) : ""}</span></div>
          {#if phase === "idle"}<button class="ib" title="Recolher" onclick={() => (open = false)}><ChevronDown size={15} /></button>{/if}
        </div>
        {#if phase === "check"}{@render guard()}
        {:else if phase !== "idle"}{@render progressView()}
        {:else}
          {#if notes.length}<ul class="notes">{#each notes as n, i (n)}<li style="--i:{i}"><Sparkles size={12} />{n}</li>{/each}</ul>
          {:else}<p class="small muted">Correções e melhorias. O app baixa, confere a assinatura e reabre sozinho.</p>{/if}
          <div class="acts">
            <button class="btn sm ghost" onclick={later}><X size={13} /> Depois</button>
            <button class="btn sm primary go" onclick={start}><Rocket size={13} /> Atualizar agora</button>
          </div>
        {/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  /* ---------- aviso flutuante no canto (não empurra a tela) */
  .upd { position: fixed; right: 18px; bottom: 46px; z-index: 60; display: flex; justify-content: flex-end; }
  .pill { position: relative; display: inline-flex; align-items: center; gap: 8px; height: 32px; padding: 0 14px 0 5px; border: 0; border-radius: 99px; cursor: pointer;
    background: var(--elevated); color: var(--text); font: 500 12.5px var(--font); box-shadow: var(--shadow-2); isolation: isolate;
    animation: drop-in 0.6s var(--spring) both; transition: transform var(--t) var(--spring); }
  .pill:hover { transform: translateY(-1px) scale(1.02); }
  /* borda em gradiente girando */
  .ring { position: absolute; inset: -1.5px; z-index: -1; border-radius: inherit; overflow: hidden; }
  .ring::before { content: ""; position: absolute; inset: -60%; background: conic-gradient(from 0deg, var(--accent), var(--accent-2, #8b6cf0), #3ccf91, var(--accent));
    animation: spin-slow 3.2s linear infinite; }
  .ring::after { content: ""; position: absolute; inset: 1.5px; border-radius: inherit; background: var(--elevated); }
  .rk { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 50%; color: #fff; background: var(--brand-grad, var(--accent)); flex: none;
    animation: bob 2.4s var(--ease) infinite; box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 50%, transparent); }
  .rk.big { width: 34px; height: 34px; border-radius: 10px; animation: bob 2.4s var(--ease) infinite, glow 2.4s var(--ease) infinite; }
  .pt b { font-weight: 650; }
  .num { font: 650 11.5px var(--mono); color: var(--accent); }
  .quiet .pill { padding: 0 3px; height: 30px; }
  .quiet .ring::before { animation-duration: 8s; opacity: 0.55; }
  .card2 { position: relative; width: 370px; max-width: calc(100vw - 36px); transform-origin: bottom right; padding: 14px; border-radius: 16px; background: var(--elevated); border: 1px solid var(--line-2);
    box-shadow: var(--shadow-3); animation: card-in 0.42s var(--spring) both; overflow: hidden; }
  .card2::before { content: ""; position: absolute; inset: 0 0 auto; height: 70px; pointer-events: none;
    background: radial-gradient(120% 90% at 20% -20%, color-mix(in srgb, var(--accent) 26%, transparent), transparent 70%); }
  .hd { position: relative; display: flex; align-items: center; gap: 10px; }
  .ttl { flex: 1; display: grid; min-width: 0; }
  .ttl b { font-size: 14.5px; letter-spacing: -0.01em; }
  .ib { display: grid; place-items: center; width: 26px; height: 26px; border: 0; border-radius: 7px; background: none; color: var(--muted); cursor: pointer; }
  .ib:hover { background: var(--surface-3); color: var(--text); }
  .notes { list-style: none; margin: 12px 0 0; padding: 0; display: grid; gap: 6px; }
  .notes li { display: flex; gap: 7px; align-items: flex-start; font-size: 12.5px; color: var(--text-2); animation: note-in 0.4s var(--ease-out) both; animation-delay: calc(var(--i, 0) * 60ms + 120ms); }
  .notes li :global(svg) { color: var(--accent); flex: none; margin-top: 3px; }
  .notes.left { text-align: left; margin: 0 0 16px; }
  .acts { display: flex; justify-content: flex-end; gap: 6px; margin-top: 14px; flex-wrap: wrap; }
  .go { position: relative; overflow: hidden; }
  .go::after { content: ""; position: absolute; inset: 0; background: linear-gradient(100deg, transparent 30%, rgba(255, 255, 255, 0.35) 50%, transparent 70%);
    transform: translateX(-100%); animation: shine 2.6s var(--ease) infinite 0.8s; }
  /* ---------- progresso */
  .prog { display: grid; gap: 8px; margin-top: 12px; }
  .ph { display: flex; align-items: center; gap: 8px; font-size: 13px; }
  .ph :global(svg) { color: var(--accent); }
  .spacer { flex: 1; }
  .track { position: relative; height: 8px; border-radius: 99px; background: var(--surface-3); overflow: hidden; }
  .track span { position: absolute; inset: 0 auto 0 0; border-radius: inherit; background: linear-gradient(90deg, var(--accent), var(--accent-2, #8b6cf0), #3ccf91);
    background-size: 200% 100%; transition: width 0.35s var(--ease-out); animation: flow 1.6s linear infinite; }
  .track.indet span { width: 40% !important; animation: flow 1.6s linear infinite, indet 1.3s var(--ease) infinite; }
  /* ---------- trava antes de atualizar */
  .guard { display: grid; gap: 8px; margin-top: 12px; padding: 12px; border-radius: 12px; background: var(--warn-soft); border: 1px solid color-mix(in srgb, var(--warn) 40%, transparent);
    text-align: left; animation: card-in 0.35s var(--spring) both; }
  .gh { display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
  .gh :global(svg) { color: var(--warn); animation: nudge 1.4s var(--ease) 2; }
  .guard p { margin: 0; color: var(--text-2); }
  .guard ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 5px; }
  .guard li { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-2); }
  .guard li > span { flex: 1; min-width: 0; }
  .guard li.bad :global(svg) { color: var(--bad); } .guard li.warn :global(svg) { color: var(--warn); } .guard li.ok :global(svg) { color: var(--good); }
  .guard .acts { margin-top: 4px; }
  .danger-text { color: var(--bad); }
  /* ---------- obrigatória */
  .block { position: fixed; inset: 0; z-index: 95; display: grid; place-items: center; background: rgba(5, 7, 12, 0.75); backdrop-filter: blur(6px); animation: fade 0.2s both; }
  .box { width: min(460px, 90vw); padding: 28px; text-align: center; animation: card-in 0.5s var(--spring) both; }
  .burst { display: inline-grid; place-items: center; width: 64px; height: 64px; border-radius: 18px; color: #fff; background: var(--brand-grad, var(--accent));
    animation: bob 2.4s var(--ease) infinite, glow 2.4s var(--ease) infinite; }
  h2 { margin: 14px 0 6px; }
  .box p { color: var(--text-2); margin: 0 0 16px; }
  @keyframes spin-slow { to { transform: rotate(360deg); } }
  @keyframes bob { 0%, 100% { transform: translateY(0) rotate(0); } 50% { transform: translateY(-2px) rotate(-8deg); } }
  @keyframes glow { 50% { box-shadow: 0 0 0 6px color-mix(in srgb, var(--accent) 18%, transparent); } }
  @keyframes drop-in { from { opacity: 0; transform: translateY(16px) scale(0.9); } }
  @keyframes card-in { from { opacity: 0; transform: translateY(10px) scale(0.96); } }
  @keyframes note-in { from { opacity: 0; transform: translateX(-6px); } }
  @keyframes shine { to { transform: translateX(100%); } }
  @keyframes flow { to { background-position: -200% 0; } }
  @keyframes indet { from { left: -40%; } to { left: 100%; } }
  @keyframes nudge { 25% { transform: rotate(-12deg); } 75% { transform: rotate(12deg); } }
  @media (prefers-reduced-motion: reduce) {
    .ring::before, .rk, .rk.big, .burst, .go::after, .track span, .gh :global(svg) { animation: none !important; }
  }
</style>
