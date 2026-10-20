<script lang="ts">
  // "Executar e depurar" (⌘/Ctrl+Shift+D), como no VS Code e nas janelas do Visual Studio: o que iniciar, as sessões
  // com a pilha de chamadas, as variáveis do quadro escolhido, a inspeção (expressões vigiadas) e os breakpoints, com
  // as exceções em que parar. Com um app Flutter rodando, as ferramentas dele: DevTools e as chaves do app.
  import { Bug, ChevronRight, CircleDot, Download, ExternalLink, Eye, Gauge, Layers, ListTree, Play, Plus, RefreshCw, Settings2, Square, Trash2, X, Zap } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { debug, KIND_LABEL, type Frame, type Session, type Variable } from "../../lib/debug.svelte";
  import { darkOf, DEVTOOLS_PAGES, DUMPS, dump, flipBrightness, flipPlatform, has, isOn, openInBrowser, platformOf, toggle, TOGGLES } from "../../lib/flutter";
  import { ui } from "../../lib/ui.svelte";
  import FileIcon from "./FileIcon.svelte";
  import VarTree from "./VarTree.svelte";

  let { repoId, taskId = null, onopen, onconfigs }:
    { repoId: string; taskId?: string | null; onopen: (path: string, line: number) => void; onconfigs: () => void } = $props();
  const k = $derived(debug.key(repoId, taskId));
  $effect(() => { const kk = k; untrack(() => { if (debug.lists[kk] === undefined) debug.load(repoId, taskId); debug.loadBps(repoId); if (!debug.adapters) debug.loadAdapters(); }); });
  const list = $derived(debug.lists[k]?.configs || []);
  const sel = $derived(debug.selected(repoId, taskId));
  const groups = $derived.by(() => {
    const m = new Map<string, typeof list>();
    for (const c of list) m.set(c.group, [...(m.get(c.group) || []), c]);
    return [...m.entries()];
  });
  const sessions = $derived(debug.scopeSessions(repoId, taskId).filter(s => s.status !== "ended" || Date.now() / 1000 - (s.ended || 0) < 600));
  const roots = $derived(sessions.filter(s => !s.parent));
  const kidsOf = (s: Session) => sessions.filter(x => x.parent === s.id);
  const need = $derived.by(() => {
    if (!sel || !debug.adapters || !sel.debug) return null;
    const kind = ["dotnet"].includes(sel.kind) ? "dotnet" : ["flutter", "dart"].includes(sel.kind) ? "dart" : ["coreclr"].includes(sel.type) ? "dotnet"
      : sel.type === "compound" || sel.type.startsWith("codeck") ? null : "js";
    return kind && !debug.adapters[kind as "js"].ok ? kind as "dotnet" | "js" | "dart" : null;
  });

  let shut = $state<Record<string, boolean>>({ });
  const sec = (id: string) => !shut[id];
  const tog = (id: string) => (shut = { ...shut, [id]: !shut[id] });

  // ------------------------------------------------------------ pilha de chamadas
  let openThreads = $state<Record<string, boolean>>({});
  $effect(() => {
    // thread parada abre sozinha (e carrega a pilha)
    for (const s of sessions) if (s.status === "stopped" && s.stopped?.threadId != null) {
      const key = `${s.id}:${s.stopped.threadId}`;
      if (openThreads[key] === undefined) untrack(() => { openThreads = { ...openThreads, [key]: true }; if (!debug.stackOf(s.id, s.stopped!.threadId)) debug.loadStack(s.id, s.stopped!.threadId); });
    }
  });
  function toggleThread(s: Session, tid: number) {
    const key = `${s.id}:${tid}`;
    openThreads = { ...openThreads, [key]: !openThreads[key] };
    if (openThreads[key] && s.status === "stopped") debug.loadStack(s.id, tid);
  }
  /** Como o "Só meu código" do Visual Studio: quadros fora do projeto em sequência viram uma linha "[Código externo]". */
  let openExt = $state<Record<string, boolean>>({});
  function chunks(frames: Frame[]) {
    const out: ({ f: Frame } | { ext: Frame[]; key: string })[] = [];
    for (const f of frames) {
      const last = out[out.length - 1];
      if (!f.path && last && "ext" in last) last.ext.push(f);
      else if (!f.path) out.push({ ext: [f], key: String(f.id) });
      else out.push({ f });
    }
    return out;
  }
  let moreThreads = $state<Record<string, boolean>>({});
  const frameLabel = (f: Frame) => f.path ? `${f.path.split("/").pop()}:${f.line}` : f.source ? `${f.source}:${f.line}` : "";
  const statusText = (s: Session) => ({ booting: `ligando ${s.boot || "o emulador"}`, building: "compilando", starting: "iniciando", running: s.kind === "run" ? "executando" : "rodando", stopped: s.stopped?.reason === "exception" ? "parado · exceção" : s.stopped?.reason === "breakpoint" ? "parado · breakpoint" : s.stopped?.reason === "step" ? "parado · passo" : "pausado",
    ended: s.error ? "falhou" : s.exitCode != null ? `terminou (${s.exitCode})` : "terminou" } as Record<string, string>)[s.status];

  // ------------------------------------------------------------ Flutter
  const fl = $derived(debug.flutterSession(repoId, taskId));

  // ------------------------------------------------------------ variáveis do quadro em foco
  const focusS = $derived(debug.sessions.find(s => s.id === debug.focus.sid && s.status === "stopped") || null);
  let scopes = $state<{ name: string; ref: number; expensive: boolean; vars: Variable[] | null; open: boolean }[]>([]);
  $effect(() => {
    const s = focusS, fid = debug.focus.frameId;
    if (!s || fid == null) { scopes = []; return; }
    untrack(async () => {
      const sc = await debug.scopes(s.id, fid);
      if (debug.focus.frameId !== fid) return;
      scopes = sc.map((x, i) => ({ ...x, vars: null, open: i === 0 && !x.expensive }));
      for (const x of scopes) if (x.open) x.vars = await debug.variables(s.id, x.ref);
    });
  });
  async function openScope(i: number) {
    const x = scopes[i];
    x.open = !x.open;
    if (x.open && !x.vars && focusS) x.vars = await debug.variables(focusS.id, x.ref);
  }

  // ------------------------------------------------------------ inspeção
  let novo = $state("");
  const watches = $derived(debug.watches(repoId));
  function addWatch() { const t = novo.trim(); if (t && !watches.includes(t)) debug.setWatches(repoId, [...watches, t]); novo = ""; }

  // ------------------------------------------------------------ breakpoints e exceções
  const bpList = $derived(Object.entries(debug.bps[repoId] || {}).flatMap(([path, l]) => l.map(b => ({ path, ...b }))).sort((a, b) => a.path.localeCompare(b.path) || a.line - b.line));
  const excKind = $derived(sessions.find(s => s.kind === "debug" && s.caps.exceptionFilters?.length)?.adapter || null);
  const excFilters = $derived(sessions.find(s => s.adapter === excKind && s.caps.exceptionFilters?.length)?.caps.exceptionFilters || []);
  const excOn = $derived.by(() => {
    const saved = debug.exc[repoId]?.[excKind || ""];
    return saved ?? excFilters.filter(f => f.default).map(f => f.filter);
  });
  function toggleExc(f: string) {
    if (!excKind) return;
    debug.setExceptions(repoId, excKind, excOn.includes(f) ? excOn.filter(x => x !== f) : [...excOn, f]);
  }
</script>

<div class="dv">
  <div class="hd">
    <span class="tt">Executar e depurar</span>
    <button class="ib" title="Configurações de execução" onclick={onconfigs}><Settings2 size={14} /></button>
    <button class="ib" title="Detectar de novo" onclick={() => debug.load(repoId, taskId)}><RefreshCw size={13} /></button>
  </div>
  <div class="launch">
    <select class="input sel" value={sel?.id || ""} onchange={(e) => debug.select(repoId, (e.target as HTMLSelectElement).value)} title="O que iniciar">
      {#if !list.length}<option value="">{debug.loadingList[k] ? "Procurando…" : "Nada detectado"}</option>{/if}
      {#each groups as [g, items] (g)}
        <optgroup label={g}>{#each items as c (c.id)}<option value={c.id}>{c.name}{c.debug ? "" : " (sem depurador)"}</option>{/each}</optgroup>
      {/each}
    </select>
    <button class="go" title="Depurar (F5)" disabled={!sel} onclick={() => debug.start(repoId, taskId, sel?.id)}><Play size={13} fill="currentColor" /></button>
    <button class="ib alt" title="Sem depurar (Ctrl+F5)" disabled={!sel} onclick={() => debug.start(repoId, taskId, sel?.id, { noDebug: true })}><Zap size={13} /></button>
  </div>
  {#if sel}
    <div class="meta tiny muted">
      <span class="chip">{KIND_LABEL[sel.kind] || sel.kind}</span>
      <span class="chip">{sel.source === "detected" ? "detectada" : sel.source === "vscode" ? "launch.json" : "salva no app"}</span>
      {#if sel.profile}<span class="chip">perfil {sel.profile}</span>{/if}
      {#if sel.url}<span class="chip mono">{sel.url.replace(/^https?:\/\//, "")}</span>{/if}
      {#if sel.envFile}<span class="chip">{sel.envFile}</span>{/if}
    </div>
  {/if}
  {#if need && debug.adapters}
    <div class="need">
      <Bug size={14} /><span class="grow">{debug.adapters[need].installable ? `Para depurar falta o ${debug.adapters[need].name}.` : debug.adapters[need].note}</span>
      {#if debug.adapters[need].installable}<button class="btn sm" onclick={() => debug.offerInstall(need!)}><Download size={12} /> Instalar</button>{/if}
    </div>
  {/if}

  <div class="secs">
    <!-- pilha de chamadas -->
    <section>
      <button class="sh" onclick={() => tog("stack")}><ChevronRight size={12} class={sec("stack") ? "rot" : ""} /> Pilha de chamadas
        {#if roots.some(s => s.status !== "ended")}<span class="n">{roots.filter(s => s.status !== "ended").length}</span>{/if}</button>
      {#if sec("stack")}
        {#each roots as s (s.id)}
          {@render sessionRow(s, 0)}
        {:else}
          <div class="none">Nada rodando. <b>F5</b> depura o escolhido acima; <b>Ctrl+F5</b> executa sem depurar.</div>
        {/each}
      {/if}
    </section>

    <!-- Flutter: DevTools e as chaves do app -->
    {#if fl}
      <section>
        <button class="sh" onclick={() => tog("flutter")}><ChevronRight size={12} class={sec("flutter") ? "rot" : ""} /> Flutter</button>
        {#if sec("flutter")}
          <div class="dt">
            <button class="btn sm" disabled={!fl.flutter?.vmUri} onclick={() => debug.devtoolsOpen?.(repoId, taskId, "")}><Gauge size={12} /> DevTools</button>
            {#each DEVTOOLS_PAGES.slice(0, 6) as pg (pg.page)}
              <button class="pg" disabled={!fl.flutter?.vmUri} onclick={() => debug.devtoolsOpen?.(repoId, taskId, pg.page)}>{pg.label}</button>
            {/each}
            <button class="ib" title="Abrir o DevTools no navegador" disabled={!fl.flutter?.vmUri} onclick={() => openInBrowser(fl)}><ExternalLink size={12} /></button>
          </div>
          {#if !fl.flutter?.vmUri}<div class="none">O DevTools conecta quando o app terminar de subir.</div>{/if}
          {#each TOGGLES.filter(t => has(fl, t.ext)) as t (t.ext)}
            <label class="exc"><input type="checkbox" checked={isOn(fl, t)} onchange={() => toggle(fl, t)} /> {t.label}</label>
          {/each}
          {#if has(fl, "ext.flutter.brightnessOverride")}
            <div class="plat"><span>Tema do app: <b>{darkOf(fl) ? "escuro" : "claro"}</b></span><button class="pg" onclick={() => flipBrightness(fl)}>trocar para {darkOf(fl) ? "claro" : "escuro"}</button></div>
          {/if}
          {#if has(fl, "ext.flutter.platformOverride")}
            <div class="plat"><span>Plataforma: <b>{platformOf(fl) || "?"}</b></span><button class="pg" onclick={() => flipPlatform(fl)}>trocar para {platformOf(fl) === "iOS" ? "Android" : "iOS"}</button></div>
          {/if}
          {#if DUMPS.some(d => has(fl, d.ext))}
            <div class="dt">
              <ListTree size={12} class="muted" />
              {#each DUMPS.filter(d => has(fl, d.ext)) as d (d.ext)}<button class="pg" title="Imprime no console de depuração" onclick={() => dump(fl, d.ext)}>{d.label}</button>{/each}
            </div>
          {/if}
          {#if !fl.flutter?.tools && fl.flutter?.vmUri}
            <div class="none">{fl.noDebug || fl.flutter?.mode === "profile" || fl.flutter?.mode === "release" ? "As chaves do app (debug paint, overlay…) precisam de F5 — depurando, no modo debug. O DevTools funciona assim mesmo." : "As chaves aparecem quando o app terminar de subir."}</div>
          {/if}
        {/if}
      </section>
    {/if}

    <!-- variáveis -->
    <section>
      <button class="sh" onclick={() => tog("vars")}><ChevronRight size={12} class={sec("vars") ? "rot" : ""} /> Variáveis</button>
      {#if sec("vars")}
        {#if focusS}
          {#each scopes as x, i (x.ref + ":" + i)}
            <button class="scope" onclick={() => openScope(i)}><ChevronRight size={12} class={x.open ? "rot" : ""} /> {x.name}</button>
            {#if x.open && x.vars}
              {#each x.vars as v, j (v.name + j)}<VarTree sid={focusS.id} {v} parentRef={x.ref} depth={1} editable={!!focusS.caps.setVariable} />{/each}
              {#if !x.vars.length}<div class="none">vazio</div>{/if}
            {/if}
          {/each}
        {:else}
          <div class="none">Aparecem quando a execução para num breakpoint.</div>
        {/if}
      {/if}
    </section>

    <!-- inspeção -->
    <section>
      <button class="sh" onclick={() => tog("watch")}><ChevronRight size={12} class={sec("watch") ? "rot" : ""} /> Inspeção {#if watches.length}<span class="n">{watches.length}</span>{/if}</button>
      {#if sec("watch")}
        {#each watches as w (w)}
          {@const r = debug.watchValues[w]}
          <div class="w">
            {#if r?.ref && focusS}
              <VarTree sid={focusS.id} v={{ name: w, value: r.value || "", type: r.type, ref: r.ref }} />
            {:else}
              <div class="wrow" title={r?.error || r?.value || ""}><Eye size={11} /><span class="n">{w}</span><span class="eq">:</span>
                <span class="val" class:err={!!r?.error}>{r ? (r.error ? r.error.replace(/^error:\s*/, "") : r.value) : focusS ? "…" : "não disponível"}</span></div>
            {/if}
            <button class="x" title="Tirar" onclick={() => debug.setWatches(repoId, watches.filter(x => x !== w))}><X size={11} /></button>
          </div>
        {/each}
        <form class="add" onsubmit={(e) => { e.preventDefault(); addWatch(); }}>
          <Plus size={12} /><input bind:value={novo} placeholder="Adicionar expressão…" spellcheck="false" />
        </form>
      {/if}
    </section>

    <!-- breakpoints -->
    <section>
      <div class="sh">
        <button class="shb" onclick={() => tog("bps")}><ChevronRight size={12} class={sec("bps") ? "rot" : ""} /> Breakpoints {#if bpList.length}<span class="n">{bpList.length}</span>{/if}</button>
        {#if bpList.length}
          <button class="ib" title={bpList.some(b => b.enabled !== false) ? "Desativar todos" : "Ativar todos"} onclick={() => debug.enableAll(repoId, !bpList.some(b => b.enabled !== false))}><CircleDot size={12} /></button>
          <button class="ib" title="Remover todos" onclick={async () => { if (await ui.ask({ title: "Remover todos os breakpoints?", confirm: "Remover", danger: true })) debug.clearBps(repoId); }}><Trash2 size={12} /></button>
        {/if}
      </div>
      {#if sec("bps")}
        {#each excFilters as f (f.filter)}
          <label class="exc" title={f.description || ""}><input type="checkbox" checked={excOn.includes(f.filter)} onchange={() => toggleExc(f.filter)} /> {f.label}</label>
        {/each}
        {#each bpList as b (b.path + ":" + b.line)}
          {@const st = debug.bpState(repoId, b.path, b.line)}
          <div class="bp" class:off={b.enabled === false}>
            <input type="checkbox" checked={b.enabled !== false} title="Ativo" onchange={() => debug.setBp(repoId, b.path, b.line, { enabled: b.enabled === false })} />
            <span class="dot" class:pending={st === "pending"} class:cond={!!(b.condition || b.hitCondition || b.logMessage)}></span>
            <button class="bpm" onclick={() => onopen(b.path, b.line)} title={b.path}>
              <FileIcon name={b.path.split("/").pop() || ""} size={13} /><span class="ell">{b.path.split("/").pop()}</span>
              <span class="tiny muted ell">{b.logMessage ? `log: ${b.logMessage}` : b.condition ? `se ${b.condition}` : b.hitCondition ? `contador ${b.hitCondition}` : b.path.split("/").slice(0, -1).join("/")}</span>
              <span class="ln">{b.line}</span>
            </button>
            <button class="x" title="Remover" onclick={() => debug.setBp(repoId, b.path, b.line, null)}><X size={11} /></button>
          </div>
        {:else}
          <div class="none">Clique na margem do editor (ou <b>F9</b>) para pôr um breakpoint. Clique direito: condicional ou logpoint.</div>
        {/each}
      {/if}
    </section>
  </div>
</div>

{#snippet sessionRow(s: Session, depth: number)}
  <div class="sess" class:ended={s.status === "ended"} style="--d:{depth}">
    <span class="sdot {s.status}"></span>
    {#if s.kind === "run"}<Zap size={12} />{:else if s.parent}<Layers size={12} />{:else}<Bug size={12} />{/if}
    <span class="ell sname" title={s.error || s.name}>{s.name}</span>
    <span class="tiny st">{statusText(s)}</span>
    {#if s.status !== "ended" && !s.parent}
      <button class="ib" title="Parar" onclick={() => debug.stop({ sid: s.id })}><Square size={10} fill="currentColor" /></button>
    {/if}
  </div>
  {#if s.status !== "ended"}
    {@const main = s.status === "stopped" ? s.threads.filter(t => t.id === s.stopped?.threadId) : s.threads.slice(0, 1)}
    {@const rest = s.threads.filter(t => !main.includes(t))}
    {#each [...main, ...(moreThreads[s.id] ? rest : [])] as t (t.id)}
      {@const key = `${s.id}:${t.id}`}
      {@const isStopped = s.status === "stopped" && (s.stopped?.threadId === t.id || s.stopped?.all !== false)}
      <button class="thr" style="--d:{depth + 1}" onclick={() => toggleThread(s, t.id)}>
        <ChevronRight size={11} class={openThreads[key] ? "rot" : ""} /><span class="ell">{t.name}</span>
        <span class="tiny" class:warn={isStopped && s.stopped?.threadId === t.id}>{isStopped ? (s.stopped?.threadId === t.id ? statusText(s) : "pausado") : "rodando"}</span>
      </button>
      {#if openThreads[key] && isStopped}
        {#each chunks(debug.stackOf(s.id, t.id) || []) as c ("f" in c ? c.f.id : "x" + c.key)}
          {#if "f" in c}
            {@const f = c.f}
            <button class="fr" class:cur={debug.focus.frameId === f.id && debug.focus.sid === s.id} style="--d:{depth + 2}"
              onclick={() => debug.selectFrame(s, t.id, f)} title={f.abs || f.source || ""}>
              <span class="ell fn">{f.name}</span><span class="tiny muted loc">{frameLabel(f)}</span>
            </button>
          {:else if openExt[`${key}:${c.key}`]}
            {#each c.ext as f (f.id)}
              <button class="fr ext" style="--d:{depth + 2}" onclick={() => debug.selectFrame(s, t.id, f)} title={f.abs || f.source || ""}>
                <span class="ell fn">{f.name}</span><span class="tiny muted loc">{frameLabel(f)}</span>
              </button>
            {/each}
          {:else}
            <button class="fr ext" style="--d:{depth + 2}" onclick={() => (openExt = { ...openExt, [`${key}:${c.key}`]: true })} title="Quadros fora do projeto (bibliotecas, framework)">
              <span class="ell fn">[Código externo]</span><span class="tiny muted loc">{c.ext.length}</span>
            </button>
          {/if}
        {/each}
      {/if}
    {/each}
    {#if rest.length}
      <button class="thr more" style="--d:{depth + 1}" onclick={() => (moreThreads = { ...moreThreads, [s.id]: !moreThreads[s.id] })}>
        <ChevronRight size={11} class={moreThreads[s.id] ? "rot" : ""} /><span class="ell">{moreThreads[s.id] ? "Esconder" : "Mais"} {rest.length} thread(s)</span>
      </button>
    {/if}
    {#each kidsOf(s) as c (c.id)}{@render sessionRow(c, depth + 1)}{/each}
  {/if}
{/snippet}

<style>
  .dv { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .hd { display: flex; align-items: center; gap: 2px; height: 34px; padding: 0 6px 0 12px; flex: none; }
  .tt { flex: 1; font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-2); }
  .ib { display: grid; place-items: center; width: 22px; height: 22px; border: 0; border-radius: 5px; background: none; color: var(--muted); cursor: pointer; flex: none; }
  .ib:hover:not(:disabled) { background: var(--surface-3); color: var(--text); }
  .ib:disabled { opacity: 0.4; }
  .ib.alt { color: var(--good); }
  .launch { display: flex; gap: 4px; padding: 0 10px 6px; flex: none; }
  .sel { flex: 1; min-width: 0; height: 28px; font-size: 12px; }
  .go { display: grid; place-items: center; width: 30px; height: 28px; border: 0; border-radius: 7px; background: color-mix(in srgb, var(--good) 18%, transparent); color: var(--good); cursor: pointer; flex: none; }
  .go:hover:not(:disabled) { background: color-mix(in srgb, var(--good) 28%, transparent); }
  .meta { display: flex; flex-wrap: wrap; gap: 4px; padding: 0 10px 8px; flex: none; }
  .chip { padding: 1px 6px; border-radius: 5px; background: var(--surface-2); border: 1px solid var(--line); }
  .need { display: flex; align-items: center; gap: 8px; margin: 0 10px 8px; padding: 8px 10px; border-radius: 8px; background: var(--warn-soft); color: var(--warn); font-size: 12px; flex: none; }
  .need .grow { flex: 1; }
  .secs { flex: 1; min-height: 0; overflow: auto; border-top: 1px solid var(--line); }
  section { border-bottom: 1px solid var(--line); }
  .sh, .shb { display: flex; align-items: center; gap: 5px; width: 100%; height: 26px; padding: 0 6px 0 8px; border: 0; background: none; color: var(--text-2); cursor: pointer;
    font: 650 10.5px/1 var(--font); text-transform: uppercase; letter-spacing: 0.06em; }
  div.sh { padding: 0 6px 0 0; }
  .shb { flex: 1; padding-left: 8px; }
  .sh :global(.rot), .shb :global(.rot), .scope :global(.rot), .thr :global(.rot) { transform: rotate(90deg); }
  .n { margin-left: 4px; padding: 0 5px; border-radius: 8px; background: var(--surface-3); color: var(--text-2); font: 600 10px/16px var(--font); letter-spacing: 0; }
  .none { padding: 4px 12px 10px 24px; color: var(--muted); font-size: 12px; line-height: 1.45; }
  .sess { display: flex; align-items: center; gap: 6px; height: 24px; padding: 0 6px 0 calc(14px + var(--d) * 12px); color: var(--text); font-size: 12px; }
  .sess.ended { color: var(--muted); }
  .sname { flex: 1; min-width: 0; font-weight: 600; }
  .st { color: var(--muted); flex: none; }
  .sdot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); flex: none; }
  .sdot.running { background: var(--good); } .sdot.stopped { background: var(--warn); } .sdot.booting, .sdot.building, .sdot.starting { background: var(--accent); animation: blink 1s infinite; }
  @keyframes blink { 50% { opacity: 0.3; } }
  .thr, .fr, .scope { display: flex; align-items: center; gap: 5px; width: 100%; height: 22px; padding: 0 8px 0 calc(14px + var(--d, 1) * 12px); border: 0; background: none;
    color: var(--text-2); font: 12px var(--font); cursor: pointer; text-align: left; }
  .thr:hover, .fr:hover, .scope:hover { background: var(--surface-2); }
  .thr .ell { flex: 1; }
  .thr .warn { color: var(--warn); }
  .thr.more { color: var(--muted); font-size: 11.5px; }
  .fr .fn { flex: 1; font-family: var(--mono); font-size: 11.5px; }
  .fr.ext { opacity: 0.6; }
  .fr.cur { background: color-mix(in srgb, var(--warn) 14%, transparent); color: var(--text); }
  .loc { flex: none; max-width: 45%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .scope { --d: 0; font-weight: 600; color: var(--text); }
  .w { position: relative; display: flex; align-items: center; }
  .w > :global(.v) { flex: 1; min-width: 0; }
  .wrow { display: flex; align-items: center; gap: 5px; flex: 1; min-width: 0; height: 22px; padding: 0 8px 0 24px; font: 12px var(--mono); color: var(--text-2); white-space: nowrap; overflow: hidden; }
  .wrow .n { margin: 0; padding: 0; background: none; color: #b07cff; font: 12px var(--mono); }
  .wrow .eq { color: var(--faint); }
  .wrow .val { overflow: hidden; text-overflow: ellipsis; color: var(--text); }
  .wrow .val.err { color: var(--muted); font-style: italic; font-family: var(--font); }
  .x { display: grid; place-items: center; width: 20px; height: 20px; margin-right: 4px; border: 0; border-radius: 5px; background: none; color: var(--muted); cursor: pointer; opacity: 0; flex: none; }
  .w:hover .x, .bp:hover .x { opacity: 1; }
  .x:hover { background: var(--surface-3); color: var(--text); }
  .add { display: flex; align-items: center; gap: 6px; padding: 2px 10px 8px 24px; color: var(--muted); }
  .add input { flex: 1; min-width: 0; height: 24px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface-2); color: var(--text); font: 12px var(--mono); padding: 0 7px; }
  .exc { display: flex; align-items: center; gap: 7px; padding: 2px 12px 2px 24px; font-size: 12px; color: var(--text-2); cursor: pointer; }
  .bp { display: flex; align-items: center; gap: 6px; height: 24px; padding-left: 22px; }
  .bp.off { opacity: 0.55; }
  .bp .dot { width: 9px; height: 9px; border-radius: 50%; background: #e51400; flex: none; }
  .bp .dot.pending { background: none; border: 2px solid #e51400; box-sizing: border-box; }
  .bp .dot.cond { border-radius: 2px; transform: rotate(45deg) scale(0.85); }
  .bpm { display: flex; align-items: center; gap: 5px; flex: 1; min-width: 0; height: 22px; border: 0; background: none; color: var(--text-2); font: 12px var(--font); cursor: pointer; text-align: left; padding: 0; }
  .bpm:hover { color: var(--text); }
  .bpm .ln { margin-left: auto; padding: 0 6px; border-radius: 6px; background: var(--surface-3); font: 600 10.5px/16px var(--mono); color: var(--text-2); flex: none; }
  .ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .dt { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; padding: 2px 10px 8px 22px; }
  .pg { height: 22px; padding: 0 7px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface-2); color: var(--text-2); font: 500 11.5px var(--font); cursor: pointer; }
  .pg:hover:not(:disabled) { background: var(--surface-3); color: var(--text); }
  .pg:disabled { opacity: 0.45; cursor: default; }
  .plat { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 2px 10px 6px 24px; font-size: 12px; color: var(--text-2); }
</style>
