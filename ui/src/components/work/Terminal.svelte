<script lang="ts" module>
  // Instâncias vivas por terminal: trocar de aba/projeto NÃO recria o xterm nem a conexão — só move o elemento.
  import { Terminal as XTerm } from "@xterm/xterm";
  import { FitAddon } from "@xterm/addon-fit";
  import { SearchAddon } from "@xterm/addon-search";
  import { WebLinksAddon } from "@xterm/addon-web-links";
  import "@xterm/xterm/css/xterm.css";
  import { prefs } from "../../lib/prefs.svelte";
  import { setTermSizeHint } from "../../lib/api";
  import { isMac } from "../../lib/keys";
  import { platform } from "../../lib/native";
  import { extTerminal } from "../../lib/exttheme";
  // no Windows o ConPTY já refaz as linhas ao mudar a largura: o xterm refluir de novo por cima embaralhava a tela
  const isWin = () => platform() === "windows";

  // seen = quantos bytes do processo a tela já tem: ao reconectar, pede só o que faltou (antes apagava tudo e reescrevia
  // o histórico inteiro — num agente que redesenha a tela, como o Claude Code, isso embaralhava e cortava as linhas).
  // sent = último tamanho mandado ao PTY: só manda de novo se mudou.
  // pending = bytes entregues ao xterm e ainda não processados; held = conexão largada até ele dar conta (ver connect).
  type Live = { term: XTerm; fit: FitAddon; search: SearchAddon; el: HTMLDivElement; ws: WebSocket | null; exited: boolean; tries: number; dispose: () => void;
    seen: number | null; sent: string; timer: ReturnType<typeof setTimeout> | null; replaying: boolean; pending: number; held: boolean };
  const live = new Map<string, Live>();
  // controle de fluxo: muita saída (flutter run, dotnet, logs) com a janela em segundo plano — onde o navegador quase não
  // deixa o xterm processar — enchia a fila dele sem limite. Passando de 50 MB o xterm JOGA FORA a escrita com erro: no
  // meio de uma reprodução isso deixava a tela apagada (reset) e `replaying` preso (sem aceitar digitação).
  // Acima de HIGH a conexão é largada; abaixo de LOW reconecta e o servidor manda o que faltou (ou o histórico).
  const HIGH = 8_000_000, LOW = 1_000_000;

  function css(name: string) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function theme() {
    const light = document.documentElement.dataset.theme === "light";
    const ext = extTerminal();
    if (ext) return ext;
    return light
      ? { background: "#ffffff", foreground: "#1f2430", cursor: "#4f6ef7", selectionBackground: "#4f6ef733", black: "#1f2430", brightBlack: "#6b7385",
          red: "#d1384f", green: "#0f9f66", yellow: "#a86c12", blue: "#3f5fe0", magenta: "#8b4cd6", cyan: "#0a83b8", white: "#c9ced8" }
      : { background: css("--surface") || "#12151c", foreground: "#d8dce6", cursor: "#8ba3ff", selectionBackground: "#6f8cff40", black: "#1b1f29",
          brightBlack: "#5d667a", red: "#ff6b7d", green: "#3ccf91", yellow: "#f5b84f", blue: "#6f8cff", magenta: "#b07cff", cyan: "#4fc3f7",
          white: "#d8dce6", brightWhite: "#ffffff" };
  }

  function connect(id: string, l: Live) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/term/${id}${l.seen != null ? "?from=" + l.seen : ""}`, ["codeck." + (window.CODECK_TOKEN || "")]);
    ws.binaryType = "arraybuffer";
    let fresh = false, redraw = false;
    ws.onmessage = (e) => {
      if (l.held || l.ws !== ws) return;   // largada: o que ainda chegar não conta (vem de novo ao reconectar)
      if (typeof e.data === "string") {
        const m = JSON.parse(e.data);
        if (m.t === "hello") {
          if (isWin()) l.term.options.windowsPty = { backend: "conpty", buildNumber: 1 };
          fresh = !m.resume;   // sem retomada: o histórico vem inteiro e a tela começa do zero
          redraw = fresh && l.seen != null && m.alive;
          l.seen = m.start ?? l.seen ?? 0;
          if (fresh && m.cols && m.rows) {
            // o histórico foi desenhado no tamanho do PTY: reproduz nesse tamanho e só depois ajusta ao painel
            // (o programa recebe o tamanho novo e redesenha); reproduzir noutra largura quebrava as linhas
            if (l.term.cols !== m.cols || l.term.rows !== m.rows) l.term.resize(m.cols, m.rows);
            l.sent = `${m.cols}x${m.rows}`;
          } else l.sent = "";
          resizeSoon(id, fresh ? 250 : 30);
        } else if (m.t === "exit") { l.exited = true; l.term.write(`\r\n\x1b[90m— processo terminou${m.code != null ? ` (código ${m.code})` : ""} —\x1b[0m\r\n`); }
        return;
      }
      const data = new Uint8Array(e.data);
      const first = fresh;
      if (fresh) { l.term.reset(); fresh = false; l.replaying = true; }
      l.seen = (l.seen || 0) + data.length;
      l.pending += data.length;
      // o histórico traz as PERGUNTAS que o programa fez ao terminal (posição do cursor, recursos…): respondê-las de
      // novo mandaria respostas velhas como se fossem digitação. Enquanto reproduz, as respostas do xterm não saem.
      l.term.write(data, () => {
        l.pending -= data.length;
        if (first) { l.replaying = false; resizeSoon(id, 30); }
        if (l.held && l.pending < LOW) { l.held = false; if (!l.ws) revive(id); }   // ainda fechando: o onclose reconecta
      });
      if (l.pending > HIGH) { l.held = true; ws.close(); }
      // reconectou sem dar para retomar (histórico já descartado): pede ao programa que redesenhe a tela inteira
      if (redraw) { redraw = false; nudge(id); }
    };
    ws.onopen = () => { l.tries = 0; };   // o tamanho vai depois do "hello" (ver acima)
    ws.onclose = () => {
      if (l.ws === ws) l.ws = null;
      // não desiste: depois de 20 tentativas o terminal ficava morto até fechar a aba (sem saída, sem aceitar digitação);
      // segue tentando a cada 15 s (e na hora ao voltar para a janela ou clicar) — fechar a aba (drop) é que encerra
      if (!l.exited && !l.held && live.get(id) === l) setTimeout(() => { if (live.get(id) === l && !l.ws && !l.held) { l.tries++; l.ws = connect(id, l); } }, Math.min(600 * (l.tries + 1), 15000));
    };
    return ws;
  }

  /** Reconecta já um terminal sem conexão (sem esperar a próxima tentativa). */
  function revive(id: string) {
    const l = live.get(id);
    if (!l || l.ws || l.exited || l.held) return;
    l.tries = 0;
    l.ws = connect(id, l);
  }

  /** Tela preta com texto no buffer: o xterm parou de pintar (pausado por um aviso de visibilidade que não veio, medida
   *  da fonte feita com o elemento fora da página…). Se a área visível tem texto e as linhas desenhadas estão vazias,
   *  mede de novo, despausa e redesenha. Usa internos do xterm 5.5 (versão fixa no package.json) — protegido por try. */
  function heal(l: Live) {
    if (!l.el.isConnected || l.el.offsetWidth < 80 || l.el.offsetHeight < 40) return;
    const rows = l.el.querySelector(".xterm-rows");
    if (!rows || rows.textContent?.trim()) return;
    const b = l.term.buffer.active;
    let text = false;
    for (let i = b.viewportY; i < b.viewportY + l.term.rows && !text; i++) text = !!b.getLine(i)?.translateToString(true).trim();
    if (!text) return;
    try {
      const core = (l.term as any)._core;
      core?._charSizeService?.measure();
      core?._renderService?._handleIntersectionChange?.({ isIntersecting: true, intersectionRatio: 1 });
    } catch { /* interno mudou: fica só o refresh */ }
    l.term.refresh(0, l.term.rows - 1);
  }
  setInterval(() => { if (document.visibilityState === "visible") for (const l of live.values()) heal(l); }, 3000);
  // voltou para a janela (depois de dormir, de minimizar): reconecta na hora quem caiu e redesenha
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    for (const [id, l] of live) { revive(id); l.term.refresh(0, l.term.rows - 1); }
  });

  function resize(id: string) {
    const l = live.get(id);
    // escondido ou no meio de uma animação (largura quase zero): não mexe — o tamanho errado chegava ao programa
    if (!l || !l.el.isConnected || l.el.offsetWidth < 80 || l.el.offsetHeight < 40) return;
    try { l.fit.fit(); } catch { return; }
    const size = `${l.term.cols}x${l.term.rows}`;
    if (l.ws?.readyState === 1 && size !== l.sent) {
      l.sent = size;
      l.ws.send(JSON.stringify({ t: "resize", c: l.term.cols, r: l.term.rows }));
    }
  }
  /** Redimensiona só quando o tamanho para de mudar: cada tamanho intermediário (painel abrindo, barra recolhendo)
   *  fazia o agente redesenhar a tela de novo, e as sobras viravam linhas cortadas. */
  function resizeSoon(id: string, ms = 140) {
    const l = live.get(id);
    if (!l) return;
    if (l.timer) clearTimeout(l.timer);
    l.timer = setTimeout(() => { l.timer = null; resize(id); }, ms);
  }
  /** Faz o programa redesenhar a tela inteira (SIGWINCH): uma coluna a menos e de volta. */
  function nudge(id: string) {
    const l = live.get(id);
    if (!l?.ws || l.ws.readyState !== 1) return;
    const { cols, rows } = l.term;
    l.ws.send(JSON.stringify({ t: "resize", c: Math.max(20, cols - 1), r: rows }));
    setTimeout(() => { if (l.ws?.readyState === 1) { l.sent = `${cols}x${rows}`; l.ws.send(JSON.stringify({ t: "resize", c: cols, r: rows })); } }, 120);
  }

  export function ensure(id: string): Live {
    let l = live.get(id);
    if (l) return l;
    const el = document.createElement("div");
    el.className = "xterm-host";
    const term = new XTerm({ fontFamily: '"JetBrains Mono Variable", ui-monospace, "SF Mono", Menlo, Consolas, monospace', fontSize: prefs.get("terminal.fontSize"), lineHeight: 1.25,
      cursorBlink: prefs.get("terminal.cursorBlink"), allowProposedApi: true, scrollback: prefs.get("terminal.scrollback"), macOptionIsMeta: true, theme: theme(), smoothScrollDuration: 80 });
    const fit = new FitAddon(), search = new SearchAddon();
    term.loadAddon(fit); term.loadAddon(search); term.loadAddon(new WebLinksAddon((_e, uri) => window.open(uri, "_blank")));
    term.open(el);
    const sub = term.onData(d => { const x = live.get(id); if (x?.ws?.readyState === 1 && !x.replaying) x.ws.send(JSON.stringify({ t: "in", d })); });
    const bin = term.onBinary(d => { const x = live.get(id), ws = x?.ws; if (ws?.readyState === 1 && !x!.replaying) ws.send(new Uint8Array([...d].map(c => c.charCodeAt(0) & 255))); });
    // ⌘K limpa a tela (como no Terminal do macOS); ⌘F é tratado pela tela
    term.attachCustomKeyEventHandler(e => {
      if (e.type === "keydown" && isMac() && e.metaKey && e.key.toLowerCase() === "k" && !e.shiftKey) { term.clear(); return false; }   // no Windows Ctrl+K é do shell
      return true;
    });
    l = { term, fit, search, el, ws: null, exited: false, tries: 0, dispose: () => { sub.dispose(); bin.dispose(); }, seen: null, sent: "", timer: null, replaying: false, pending: 0, held: false };
    live.set(id, l);
    l.ws = connect(id, l);
    return l;
  }

  export function drop(id: string) {
    const l = live.get(id);
    if (!l) return;
    live.delete(id);
    if (l.timer) clearTimeout(l.timer);
    l.ws?.close();
    l.dispose();
    l.term.dispose();
    l.el.remove();
  }

  /** Escreve no terminal como se fosse digitado (ex.: mandar um prompt para o agente). */
  export function typeInto(id: string, text: string) {
    const ws = live.get(id)?.ws;
    if (ws?.readyState !== 1) return;
    // texto + Enter de uma vez o agente entende como COLAGEM e o Enter vira quebra de linha (o prompt não ia):
    // manda o texto e, um instante depois, o Enter sozinho
    const enter = /\r$/.test(text);
    const body = enter ? text.slice(0, -1) : text;
    if (body) ws.send(JSON.stringify({ t: "in", d: body }));
    if (enter) setTimeout(() => { const w = live.get(id)?.ws; if (w?.readyState === 1) w.send(JSON.stringify({ t: "in", d: "\r" })); }, body ? 250 : 0);
  }

  // autoteste do desktop: lê o que o terminal RECEBEU (buffer), independente de a janela estar sendo desenhada
  if ((window as any).__CD_SELFTEST) (window as any).__cdTermText = () => [...live.values()].map(l => {
    const b = l.term.buffer.active, out: string[] = [];
    for (let i = 0; i < b.length; i++) out.push(b.getLine(i)?.translateToString(true) || "");
    return out.join("\n");
  }).join("\n");

  /** Tamanho (colunas × linhas) que um terminal novo terá no painel central: o de um terminal aberto, ou a conta pela
   *  área do painel. Vai junto ao criar o terminal, para o programa já nascer no tamanho certo. */
  export function paneSize(): { cols: number; rows: number } | null {
    for (const l of live.values()) if (l.el.isConnected && l.el.offsetWidth > 80) return { cols: l.term.cols, rows: l.term.rows };
    const body = document.querySelector<HTMLElement>(".work .center .body") || document.querySelector<HTMLElement>(".work .center");
    if (!body || body.offsetWidth < 100) return null;
    const fs = prefs.get("terminal.fontSize");
    // célula do xterm: largura ≈ 0,6 em (JetBrains Mono); altura = altura da fonte (~1,2 em, arredondada) × lineHeight 1,25
    return { cols: Math.max(20, Math.floor((body.offsetWidth - 22) / (fs * 0.6))), rows: Math.max(5, Math.floor((body.offsetHeight - 12) / (Math.ceil(fs * 1.2) * 1.25 + 0.5))) };
  }

  setTermSizeHint(paneSize);

  /** Configurações → Terminal: fonte, histórico e cursor valem também para os terminais já abertos. */
  export function applyPrefs(o: { fontSize: number; scrollback: number; cursorBlink: boolean }) {
    for (const [id, l] of live) {
      const t = l.term.options;
      if (t.fontSize === o.fontSize && t.scrollback === o.scrollback && t.cursorBlink === o.cursorBlink) continue;
      t.fontSize = o.fontSize; t.scrollback = o.scrollback; t.cursorBlink = o.cursorBlink;
      resizeSoon(id);
    }
  }

  export function retheme() { for (const l of live.values()) l.term.options.theme = theme(); }
  new MutationObserver(retheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-ext-theme"] });
</script>

<script lang="ts">
  import { Paperclip, Pin, Timer, X as XIcon } from "@lucide/svelte";
  import { get as apiGet, post } from "../../lib/api";
  import { ui } from "../../lib/ui.svelte";
  let { id, active = true }: { id: string; active?: boolean } = $props();
  let host: HTMLDivElement | undefined = $state();

  // ------------------------------------------------------------ arquivos de referência soltos no terminal
  // Arrastar arquivos do Finder/Explorer (ou da árvore) para cima do terminal: metade de cima = temporário (apagado ao
  // fechar o terminal), metade de baixo = fixo no projeto (.codeck/refs). O caminho é digitado no prompt, sem Enter.
  type Ref = { name: string; path: string; keep: boolean };
  let dragging = $state<null | "tmp" | "keep">(null);
  let refs = $state<Ref[]>([]);
  const INTERNAL = "application/x-codeck-paths";
  const accepts = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].some(t => t === "Files" || t === INTERNAL);
  const quote = (p: string) => (!/[\s'"()&;$`!*?<>|]/.test(p) ? p : isWin() ? `"${p}"` : `'${p.replace(/'/g, `'\\''`)}'`);
  function zone(e: DragEvent) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    return e.clientY - r.top < r.height / 2 ? "tmp" : "keep";
  }
  function over(e: DragEvent) {
    if (!accepts(e)) return;
    e.preventDefault();
    e.dataTransfer!.dropEffect = "copy";
    dragging = zone(e);
  }
  function leave(e: DragEvent) { if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) dragging = null; }
  const b64 = (f: File) => new Promise<string>((ok, bad) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",", 2)[1] || ""); r.onerror = () => bad(r.error); r.readAsDataURL(f); });
  async function drop(e: DragEvent) {
    if (!accepts(e)) return;
    e.preventDefault();
    const keep = zone(e) === "keep";
    dragging = null;
    const dt = e.dataTransfer!;
    const internal = dt.getData(INTERNAL);
    if (internal) {   // da árvore: o arquivo já está no projeto — só o caminho
      try { typeInto(id, (JSON.parse(internal) as string[]).map(quote).join(" ") + " "); } catch { /* formato estranho: ignora */ }
      live.get(id)?.term.focus();
      return;
    }
    const files = [...dt.files];
    if (!files.length) return;
    const prog = files.length > 1 || files[0].size > 2e6 ? ui.progress(`Anexando ${files.length} arquivo(s)…`) : null;
    try {
      const paths: string[] = [];
      for (const f of files) {
        if (f.size > 50 * 1024 * 1024) { ui.toast(`${f.name}: grande demais para referência (máx. 50 MB)`, "info"); continue; }
        paths.push((await post<{ path: string }>("terms/drop", { id, name: f.name, data: await b64(f), keep })).path);
      }
      if (paths.length) typeInto(id, paths.map(quote).join(" ") + " ");
      prog?.done(keep ? "Fixado em .codeck/refs" : "Anexado — some ao fechar o terminal");
      loadRefs();
    } catch (err) { if (prog) prog.fail(err); else ui.error(err); }
    live.get(id)?.term.focus();
  }
  function loadRefs() { apiGet<{ refs: Ref[] }>("terms/refs", { id }).then(r => (refs = r.refs)).catch(() => {}); }
  $effect(() => { void id; loadRefs(); });
  function refsMenu(e: MouseEvent) {
    ui.contextMenu(e, [
      { heading: "Referências deste terminal" },
      ...refs.map(r => ({ label: r.name, icon: r.keep ? Pin : Timer, hint: r.keep ? "fixo" : "temporário", onclick: () => { typeInto(id, quote(r.path) + " "); live.get(id)?.term.focus(); } })),
      { separator: true },
      ...refs.map(r => ({ label: `Apagar ${r.name}`, icon: XIcon, danger: true, onclick: () => post("terms/refs/remove", { id, path: r.path }).then(loadRefs).catch(err => ui.error(err)) })),
    ]);
  }

  $effect(() => {
    if (!host) return;
    const h = host, l = ensure(id);
    h.appendChild(l.el);
    // reajusta no quadro seguinte: dentro do próprio aviso o resize muda o layout de novo (o WebKit reporta "ResizeObserver loop")
    const ro = new ResizeObserver(() => resizeSoon(id));
    ro.observe(h);
    const poke = () => revive(id);   // clicar num terminal que perdeu a conexão reconecta na hora
    h.addEventListener("pointerdown", poke);
    // redesenha ao voltar para a tela: o que chegou com o elemento fora da página não estava pintado (tela preta)
    requestAnimationFrame(() => { if (live.get(id) !== l) return; resize(id); l.term.refresh(0, l.term.rows - 1); });
    return () => { ro.disconnect(); h.removeEventListener("pointerdown", poke); if (l.el.parentElement === h) l.el.remove(); };
  });
  $effect(() => {
    const o = { fontSize: prefs.get("terminal.fontSize"), scrollback: prefs.get("terminal.scrollback"), cursorBlink: prefs.get("terminal.cursorBlink") };
    requestAnimationFrame(() => applyPrefs(o));
  });
  $effect(() => { if (active) requestAnimationFrame(() => { resizeSoon(id, 30); live.get(id)?.term.focus(); }); });
</script>

<div class="wrap" role="region" aria-label="Terminal" ondragover={over} ondragleave={leave} ondrop={drop}>
  <div class="term" bind:this={host}></div>
  {#if dragging}
    <div class="drop" aria-hidden="true">
      <div class="dz" class:on={dragging === "tmp"}><Timer size={18} /><b>Referência temporária</b><span>apagada ao fechar o terminal</span></div>
      <div class="dz" class:on={dragging === "keep"}><Pin size={18} /><b>Fixar no projeto</b><span>fica em .codeck/refs (fora do Git)</span></div>
    </div>
  {/if}
  {#if refs.length}
    <button class="refs" title="Arquivos de referência deste terminal — clique para inserir o caminho de novo ou apagar" onclick={refsMenu}><Paperclip size={12} /> {refs.length}</button>
  {/if}
</div>

<style>
  .wrap { position: relative; width: 100%; height: 100%; min-height: 0; }
  .drop { position: absolute; inset: 6px; display: grid; grid-template-rows: 1fr 1fr; gap: 6px; pointer-events: none; z-index: 5; animation: fade 0.12s var(--ease-out); }
  .dz { display: grid; place-content: center; justify-items: center; gap: 4px; border: 1.5px dashed var(--line-3); border-radius: var(--r); color: var(--text-2);
    background: color-mix(in srgb, var(--surface) 82%, transparent); backdrop-filter: blur(2px); font-size: 12px; transition: border-color var(--t-fast), background var(--t-fast), color var(--t-fast); }
  .dz b { font-size: 13px; color: var(--text); }
  .dz span { color: var(--muted); }
  .dz.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent-soft) 85%, var(--surface)); color: var(--accent); }
  .refs { position: absolute; right: 14px; bottom: 8px; z-index: 4; display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 8px; border-radius: 99px;
    border: 1px solid var(--line-2); background: var(--surface-2); color: var(--text-2); font: 600 11px var(--font); cursor: pointer; opacity: 0.85; }
  .refs:hover { opacity: 1; color: var(--text); }
  @keyframes fade { from { opacity: 0; } }
  .term { width: 100%; height: 100%; min-height: 0; padding: 8px 4px 4px 10px; background: var(--surface); overflow: hidden; }
  .term :global(.xterm-host) { width: 100%; height: 100%; }
  .term :global(.xterm) { height: 100%; }
  .term :global(.xterm-viewport) { background: transparent !important; }
  .term :global(.xterm-viewport::-webkit-scrollbar) { width: 8px; }
  .term :global(.xterm-viewport::-webkit-scrollbar-thumb) { background: var(--line-2); border-radius: 8px; }
</style>
