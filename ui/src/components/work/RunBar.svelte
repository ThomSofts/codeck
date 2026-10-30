<script lang="ts">
  // A barra de executar/depurar (como a do Visual Studio): ▶ o alvo escolhido (F5 depura, Ctrl+F5 sem depurar), a lista
  // do que dá para iniciar — detectado no projeto, do launch.json do VS Code e as salvas no app —, o dispositivo do
  // Flutter (os desligados ligam ao executar) e, enquanto depura, continuar/pausar, passo a passo, reiniciar, parar,
  // o hot reload e as ferramentas do Flutter (DevTools e as chaves do app: debug paint, overlay de performance…).
  import { ArrowDownToLine, ArrowRightToLine, ArrowUpFromLine, Bug, ChevronDown, ExternalLink, Flame, Gauge, Layers, ListTree, Loader2, Monitor, Pause,
    Play, Power, RefreshCw, RotateCcw, Settings2, Smartphone, Square, StepForward, Zap } from "@lucide/svelte";
  import { untrack } from "svelte";
  import { debug, KIND_LABEL, type Device, type LaunchCfg, type Session } from "../../lib/debug.svelte";
  import { darkOf, DEVTOOLS_PAGES, DUMPS, flipBrightness, flipPlatform, has, isOn, openInBrowser, platformOf, toggle, TOGGLES, dump } from "../../lib/flutter";
  import { kbd } from "../../lib/keys";
  import { kb } from "../../lib/keybindings.svelte";
  import { router } from "../../lib/router.svelte";
  import { ui } from "../../lib/ui.svelte";

  let { repoId, taskId = null, onconfigs }: { repoId: string; taskId?: string | null; onconfigs?: () => void } = $props();
  const k = $derived(debug.key(repoId, taskId));
  $effect(() => { const kk = k; untrack(() => { if (debug.lists[kk] === undefined) debug.load(repoId, taskId); }); });
  const list = $derived(debug.lists[k]?.configs || []);
  const sel = $derived(debug.selected(repoId, taskId));
  const live = $derived(debug.live(repoId, taskId));
  const act = $derived(debug.active(repoId, taskId));
  const dbgLive = $derived(live.filter(s => s.kind === "debug"));
  const stopped = $derived(act?.status === "stopped" || debug.sessions.some(s => s.group === act?.group && s.status === "stopped"));
  const building = $derived(live.some(s => s.status === "building"));
  const starting = $derived(live.some(s => s.status === "starting"));
  const booting = $derived(live.find(s => s.status === "booting") || null);
  const hot = $derived(live.find(s => s.adapter === "dart" && s.status !== "building" && s.status !== "booting") || null);
  const selRunning = $derived(sel ? debug.runningOf(repoId, taskId, sel.id) : []);
  const dev = $derived(debug.device(repoId));
  const devInfo = $derived(debug.deviceInfo(repoId));
  const devName = $derived(devInfo?.name || (dev ? dev.replace(/^avd:/, "").replace(/_/g, " ") : "Dispositivo"));
  const flutter = $derived(debug.flutterSession(repoId, taskId));
  $effect(() => { if (sel?.device && !debug.devices.length && !debug.devicesLoading) untrack(() => debug.loadDevices()); });

  const status = $derived.by(() => {
    if (booting) return `Ligando ${booting.boot || "o emulador"}…`;
    if (building) return "Compilando…";
    if (starting) return "Iniciando…";
    if (stopped) { const r = (act?.stopped?.reason || debug.sessions.find(s => s.group === act?.group && s.stopped)?.stopped?.reason); return r === "exception" ? "Parado · exceção" : r === "breakpoint" ? "Parado · breakpoint" : r === "step" ? "Parado · passo" : "Pausado"; }
    if (dbgLive.length) return "Depurando";
    if (live.length) return "Executando";
    return "";
  });

  function icon(c: LaunchCfg) {
    return c.type === "compound" ? Layers : c.kind === "flutter" || c.kind === "dart" ? Smartphone : c.browser ? Monitor : c.debug ? Play : Zap;
  }
  const pick = $derived.by(() => {
    const items: any[] = [];
    let g = "";
    for (const c of list) {
      if (c.group !== g) { items.push({ heading: c.group }); g = c.group; }
      const on = c.id === sel?.id;
      const run = debug.runningOf(repoId, taskId, c.id).length;
      items.push({ label: `${on ? "● " : ""}${c.name}`, icon: icon(c), hint: run ? "rodando" : !c.debug ? "sem depurador" : c.detail || undefined,
        onclick: () => debug.select(repoId, c.id) });
    }
    if (!list.length) items.push({ label: debug.loadingList[k] ? "Procurando…" : "Nada detectado — crie uma configuração", disabled: true });
    return [...items, { separator: true },
      { label: "Iniciar sem depurar", icon: Zap, kbd: kb.label("workbench.action.debug.run"), disabled: !sel, onclick: () => go(true) },
      { label: "Configurações de execução…", icon: Settings2, onclick: () => onconfigs?.() },
      { label: "Detectar de novo", icon: RefreshCw, onclick: () => debug.load(repoId, taskId) }];
  });
  const isSel = (d: Device) => d.id === dev || (!!d.avd && `avd:${d.avd}` === dev);
  const devIcon = (d: Device) => d.platform.startsWith("web") || d.platform === "darwin" || d.platform.startsWith("windows") || d.platform.startsWith("linux") ? Monitor : Smartphone;
  const devItems = $derived([
    { heading: "Dispositivo do Flutter" },
    ...debug.devices.map(d => ({ label: `${isSel(d) ? "● " : ""}${d.name}`, icon: devIcon(d),
      hint: d.emulator ? "emulador" : d.platform, disabled: !d.supported, onclick: () => debug.pickDevice(repoId, d) })),
    ...(debug.devices.length ? [] : [{ label: debug.devicesLoading ? "Procurando dispositivos…" : debug.devicesErr || "Nenhum dispositivo conectado", disabled: true }]),
    ...(debug.offline.length ? [{ heading: "Desligados — liga ao executar" },
      ...debug.offline.map(d => ({ label: `${isSel(d) ? "● " : ""}${d.name}`, icon: Power, hint: d.booting ? "ligando…" : d.sdk || d.platform,
        onclick: () => debug.pickDevice(repoId, d) }))] : []),
    { separator: true },
    { label: "Atualizar a lista", icon: RefreshCw, onclick: () => debug.loadDevices(true) },
  ]);
  // ferramentas do Flutter: DevTools (numa aba do Codeck ou no navegador) e as chaves do app
  const toolItems = $derived.by(() => {
    const s = flutter;
    if (!s) return [];
    const ready = !!s.flutter?.vmUri;
    const items: any[] = [{ heading: "DevTools" },
      { label: "Abrir o DevTools", icon: Gauge, disabled: !ready, hint: ready ? undefined : "esperando o app", onclick: () => debug.devtoolsOpen?.(repoId, taskId, "") },
      ...DEVTOOLS_PAGES.map(p => ({ label: p.label, disabled: !ready, onclick: () => debug.devtoolsOpen?.(repoId, taskId, p.page) })),
      { label: "Abrir no navegador", icon: ExternalLink, disabled: !ready, onclick: () => openInBrowser(s) }];
    const tg = TOGGLES.filter(t => has(s, t.ext));
    if (tg.length) {
      items.push({ heading: "No app" }, ...tg.map(t => ({ label: `${isOn(s, t) ? "● " : ""}${t.label}`, hint: isOn(s, t) ? "ligado" : undefined, onclick: () => toggle(s, t) })));
      if (has(s, "ext.flutter.brightnessOverride")) items.push({ label: `Tema: ${darkOf(s) ? "escuro" : "claro"}`, hint: `trocar para ${darkOf(s) ? "claro" : "escuro"}`, onclick: () => flipBrightness(s) });
      if (has(s, "ext.flutter.platformOverride")) items.push({ label: `Plataforma: ${platformOf(s) || "?"}`, hint: `trocar para ${platformOf(s) === "iOS" ? "Android" : "iOS"}`, onclick: () => flipPlatform(s) });
    }
    const dp = DUMPS.filter(d => has(s, d.ext));
    if (dp.length) items.push({ heading: "Imprimir no console" }, ...dp.map(d => ({ label: d.label, icon: ListTree, onclick: () => dump(s, d.ext) })));
    if (!s.flutter?.tools) items.push({ separator: true }, { label: s.noDebug || s.flutter?.mode === "profile" || s.flutter?.mode === "release" ? "As chaves do app precisam de F5 (depurar, modo debug)" : "As chaves aparecem quando o app terminar de subir", disabled: true });
    return items;
  });

  function go(noDebug = false) {
    if (!sel) return onconfigs?.();
    debug.start(repoId, taskId, sel.id, { noDebug });
  }
  const restartTarget = (): Session | null => act || live[0] || null;

  // F5, ⌃F5, ⇧F5, F10, F11… (lib/keybindings — personalizáveis em Configurações → Atalhos)
  $effect(() => {
    const here = () => router.view === "work" || router.view === "solo";
    const offs = [
      kb.on("workbench.action.debug.start", () => { if (!here()) return false; if (stopped) debug.control(act, "continue"); else go(false); }),
      kb.on("workbench.action.debug.run", () => { if (!here()) return false; go(true); }),
      kb.on("workbench.action.debug.restart", () => { const r = restartTarget(); if (!here() || !r) return false; debug.restart(r.id); }),
      kb.on("workbench.action.debug.stop", () => { if (!here()) return false; debug.stopScope(repoId, taskId); }),
      kb.on("workbench.action.debug.pause", () => { if (!here() || !act || stopped) return false; debug.control(act, "pause"); }),
      kb.on("workbench.action.debug.stepOver", () => { if (!here() || !stopped) return false; debug.control(act, "next"); }),
      kb.on("workbench.action.debug.stepInto", () => { if (!here() || !stopped) return false; debug.control(act, "stepIn"); }),
      kb.on("workbench.action.debug.stepOut", () => { if (!here() || !stopped) return false; debug.control(act, "stepOut"); }),
    ];
    return () => { for (const off of offs) off(); };
  });
</script>

<div class="rb" class:dbg={dbgLive.length > 0} class:live={live.length > 0} class:stopped role="toolbar" aria-label="Executar e depurar">
  {#if live.length}
    {#if dbgLive.length}
      {#if stopped}
        <button class="ib go" title={`Continuar (${kb.label("workbench.action.debug.start")})`} onclick={() => debug.control(act, "continue")}><Play size={13} fill="currentColor" /></button>
      {:else}
        <button class="ib" title={`Pausar (${kb.label("workbench.action.debug.pause")})`} disabled={building || starting} onclick={() => debug.control(act, "pause")}><Pause size={13} /></button>
      {/if}
      <!-- passo a passo só parado (antes ficavam desabilitados o tempo todo e a barra crescia à toa) -->
      {#if stopped}
        <button class="ib" title={`Passar por cima (${kb.label("workbench.action.debug.stepOver")})`} onclick={() => debug.control(act, "next")}><StepForward size={14} /></button>
        <button class="ib" title={`Entrar (${kb.label("workbench.action.debug.stepInto")})`} onclick={() => debug.control(act, "stepIn")}><ArrowDownToLine size={14} /></button>
        <button class="ib" title={`Sair (${kb.label("workbench.action.debug.stepOut")})`} onclick={() => debug.control(act, "stepOut")}><ArrowUpFromLine size={14} /></button>
      {/if}
      <span class="sep"></span>
    {/if}
    {#if hot}
      <button class="ib hot" title="Hot reload (salvar um .dart também recarrega)" onclick={() => debug.control(hot, "hotReload")}><Zap size={14} /></button>
      <button class="ib hot" title="Hot restart" onclick={() => debug.control(hot, "hotRestart")}><Flame size={14} /></button>
    {/if}
    {#if flutter}
      <button class="ib tools" title="Ferramentas do Flutter: DevTools, debug paint, overlay de performance…" onclick={(e) => ui.contextMenu(e, toolItems)}><Gauge size={14} /></button>
    {/if}
    <button class="ib" title={`Reiniciar (${kb.label("workbench.action.debug.restart")})`} onclick={() => { const r = restartTarget(); if (r) debug.restart(r.id); }}><RotateCcw size={13} /></button>
    <button class="ib stop" title={`Parar (${kb.label("workbench.action.debug.stop")})`} onclick={() => debug.stopScope(repoId, taskId)}><Square size={11} fill="currentColor" /></button>
    <span class="st" class:warn={stopped} title={live.map(s => s.name).join(", ")}>
      {#if booting || building || starting}<Loader2 size={12} class="spin" />{:else if dbgLive.length}<Bug size={12} />{/if}
      <span class="ell">{status}{live.length > 1 ? ` · ${live.length}` : ""}</span>
    </span>
  {/if}
  {#if sel?.device}
    <button class="dev" title="Dispositivo do Flutter" onclick={(e) => { if (!debug.devices.length) debug.loadDevices(); ui.contextMenu(e, devItems); }}>
      {#if debug.devicesLoading}<Loader2 size={12} class="spin" />{:else}<Smartphone size={12} />{/if}<span class="ell">{devName}</span><ChevronDown size={11} />
    </button>
  {/if}
  <div class="start">
    <button class="gob" disabled={!sel && !list.length} title={sel ? `${sel.debug ? "Depurar" : "Executar"}: ${sel.name} (${kb.label("workbench.action.debug.start")})${sel.why ? " — " + sel.why : ""}` : "Escolha o que executar"} onclick={() => go(false)}>
      {#if selRunning.some(s => s.status === "building" || s.status === "starting")}<Loader2 size={12} class="spin" />{:else}<Play size={12} fill="currentColor" />{/if}
      <span class="ell lbl">{sel ? sel.name : debug.loadingList[k] ? "Procurando…" : "Executar"}</span>
      {#if sel}<span class="kind">{KIND_LABEL[sel.kind] || sel.kind}</span>{/if}
    </button>
    <button class="caret" title="O que iniciar" onclick={(e) => { const r = (e.currentTarget as HTMLElement).parentElement!.getBoundingClientRect(); ui.openMenu({ items: pick, anchor: { left: r.left, right: r.right, top: r.top, bottom: r.bottom }, align: "right", owner: null }); }}><ChevronDown size={12} /></button>
  </div>
  <button class="ib nodbg" title={`Iniciar sem depurar (${kb.label("workbench.action.debug.run")})`} disabled={!sel} onclick={() => go(true)}><ArrowRightToLine size={14} /></button>
</div>

<style>
  /* encolhe com a barra do projeto (o nome do alvo e o estado cortam com reticências) — nunca empurra os botões vizinhos para fora */
  .rb { display: flex; align-items: center; gap: 2px; padding: 2px; border-radius: 9px; background: var(--bg-2); border: 1px solid var(--line); flex: 0 1 auto; min-width: 0; overflow: hidden; }
  .rb.dbg { border-color: color-mix(in srgb, var(--warn) 45%, var(--line)); }
  .ib { display: grid; place-items: center; width: 26px; height: 24px; border: 0; border-radius: 6px; background: none; color: var(--text-2); cursor: pointer; flex: none; }
  .ib:hover:not(:disabled) { background: var(--surface-3); color: var(--text); }
  .ib:disabled { opacity: 0.35; cursor: default; }
  .ib.go { color: var(--good); }
  .ib.stop { color: var(--bad); }
  .ib.hot { color: var(--warn); }
  .ib.tools { color: var(--accent); }
  .ib.nodbg { color: var(--good); }
  .sep { width: 1px; height: 16px; background: var(--line-2); margin: 0 2px; flex: none; }
  .st { display: inline-flex; align-items: center; gap: 5px; max-width: 150px; min-width: 0; height: 22px; padding: 0 8px; margin: 0 2px; border-radius: 6px; flex: 0 1 auto;
    background: var(--accent-soft); color: var(--accent); font: 650 11px var(--font); }
  .st.warn { background: var(--warn-soft); color: var(--warn); }
  .dev { display: inline-flex; align-items: center; gap: 5px; height: 24px; max-width: 160px; min-width: 0; padding: 0 7px; border: 0; border-radius: 6px; background: none;
    color: var(--text-2); font: 600 11.5px var(--font); cursor: pointer; flex: 0 1 auto; }
  .dev:hover { background: var(--surface-3); color: var(--text); }
  .start { display: flex; align-items: center; min-width: 0; flex: 0 1 auto; }
  .gob { display: inline-flex; align-items: center; gap: 6px; height: 24px; max-width: 260px; min-width: 0; padding: 0 9px; border: 0; border-radius: 6px 0 0 6px; cursor: pointer;
    background: color-mix(in srgb, var(--good) 16%, transparent); color: var(--good); font: 650 12px var(--font); transition: background var(--t-fast); }
  .gob:hover:not(:disabled) { background: color-mix(in srgb, var(--good) 26%, transparent); }
  .gob:disabled { opacity: 0.6; cursor: default; }
  .gob .kind { font: 600 10px var(--font); padding: 1px 5px; border-radius: 4px; background: color-mix(in srgb, var(--good) 18%, transparent); flex: none; }
  .caret { display: grid; place-items: center; width: 20px; height: 24px; border: 0; border-radius: 0 6px 6px 0; margin-left: 1px; cursor: pointer;
    background: color-mix(in srgb, var(--good) 16%, transparent); color: var(--good); flex: none; }
  .caret:hover { background: color-mix(in srgb, var(--good) 26%, transparent); }
  .ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  /* rodando, o estado já diz o que está no ar: o alvo fica mais curto */
  .rb.live .gob { max-width: 150px; }
  .rb.live .gob .kind, .rb.live .nodbg { display: none; }
  @container (max-width: 1100px) { .gob { max-width: 180px; } .gob .kind { display: none; } .rb.live .gob .lbl { display: none; } }
  @container (max-width: 900px) { .gob { max-width: 130px; } .st { display: none; } .dev { max-width: 110px; } }
  @container (max-width: 760px) { .gob .lbl { display: none; } .dev span { display: none; } }
</style>
