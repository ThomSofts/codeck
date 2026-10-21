// Autoteste do app de DESKTOP — roda dentro da janela real (WKWebView no macOS, WebView2 no Windows).
// Injetado pelo app nativo quando CODECK_SELFTEST aponta para este arquivo (scripts/test-desktop.sh).
// Cliques são eventos do DOM; teclas são eventos REAIS do sistema operacional (o app nativo os envia à janela),
// então ⌘T, ⌘S, F12 e a digitação no terminal/editor passam pelo mesmo caminho que o usuário usa.
(async () => {
  const CTX = window.SELFTEST || {};
  const results = [];
  const jsErrors = [];
  window.addEventListener("error", e => jsErrors.push(String(e.message || e.error)));
  window.addEventListener("unhandledrejection", e => setTimeout(() => { if (!e.defaultPrevented) jsErrors.push("promise: " + String(e.reason?.message || e.reason)); }, 0));
  const MAC = (window.CODECK_PLATFORM || "macos") === "macos";
  const MOD = MAC ? "cmd" : "ctrl";
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  // o Monaco desenha os espaços como espaço não separável: normaliza para comparar texto
  const txt = el => (el?.innerText || el?.textContent || "").replace(/\u00a0/g, " ").trim();
  // texto visível pode vir em maiúsculas (text-transform no CSS): compara sem diferenciar
  const byText = (sel, t, root = document) => $$(sel, root).find(e => txt(e).toLowerCase().includes(t.toLowerCase()));
  async function waitFor(fn, ms = 8000, step = 100) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const v = typeof fn === "string" ? $(fn) : fn();
      if (v) return v;
      await sleep(step);
    }
    throw new Error("não apareceu: " + (typeof fn === "string" ? fn : fn.toString().slice(0, 90)));
  }
  function click(el) {
    if (!el) throw new Error("elemento não encontrado para clicar");
    const r = el.getBoundingClientRect(), o = { bubbles: true, cancelable: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2, button: 0, view: window };
    el.dispatchEvent(new PointerEvent("pointerdown", o)); el.dispatchEvent(new MouseEvent("mousedown", o));
    el.dispatchEvent(new PointerEvent("pointerup", o)); el.dispatchEvent(new MouseEvent("mouseup", o));
    el.click();
  }
  function rightClick(el) {
    const r = el.getBoundingClientRect();
    el.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: r.x + 20, clientY: r.y + r.height / 2, button: 2, view: window }));
  }
  function setInput(el, value) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // ---- ponte com o app nativo (teclas reais, screenshots, estado das janelas)
  const pending = {};
  window.__selftestResolve = (id, v) => { pending[id]?.(v); delete pending[id]; };
  function native(type, payload = {}) {
    const id = Math.random().toString(36).slice(2);
    return new Promise(res => {
      pending[id] = res;
      const msg = { type, id, ...payload };
      if (window.webkit?.messageHandlers?.codeck) window.webkit.messageHandlers.codeck.postMessage(msg);
      else window.chrome.webview.postMessage(msg);
      setTimeout(() => { if (pending[id]) { delete pending[id]; res(null); } }, 15000);
    });
  }
  // keyCodes do macOS (o WebView deriva o "code"/keyCode do evento a partir deles); no Windows, os virtuais (VK_*)
  const MK = { a: 0, s: 1, d: 2, f: 3, h: 4, g: 5, z: 6, x: 7, c: 8, v: 9, b: 11, q: 12, w: 13, e: 14, r: 15, y: 16, t: 17, "1": 18, "2": 19, "3": 20, "4": 21,
    "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, o: 31, u: 32, "[": 33, i: 34, p: 35, l: 37, j: 38, "'": 39, k: 40, ";": 41,
    "\\": 42, ",": 43, "/": 44, n: 45, m: 46, ".": 47, " ": 49, "`": 50 };
  const SHIFTED = { "!": "1", "@": "2", "#": "3", $: "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0", _: "-", "+": "=", "{": "[", "}": "]",
    ":": ";", '"': "'", "<": ",", ">": ".", "?": "/", "|": "\\", "~": "`" };
  const SPECIAL = MAC
    ? { Enter: { c: "\r", k: 36 }, Escape: { c: "\u001b", k: 53 }, Tab: { c: "\t", k: 48 }, Backspace: { c: "\u007f", k: 51 }, F12: { c: "", k: 111 },
        ArrowUp: { c: "", k: 126 }, ArrowDown: { c: "", k: 125 }, ArrowLeft: { c: "", k: 123 }, ArrowRight: { c: "", k: 124 },
        Home: { c: "", k: 115 }, End: { c: "", k: 119 } }
    : { Enter: { c: "\r", k: 13 }, Escape: { c: "\u001b", k: 27 }, Tab: { c: "\t", k: 9 }, Backspace: { c: "\b", k: 8 }, F12: { c: "", k: 123 },
        ArrowUp: { c: "", k: 38 }, ArrowDown: { c: "", k: 40 }, ArrowLeft: { c: "", k: 37 }, ArrowRight: { c: "", k: 39 }, Home: { c: "", k: 36 }, End: { c: "", k: 35 } };
  function keyOf(ch, mods = "") {
    if (SPECIAL[ch]) return { ...SPECIAL[ch], m: mods, n: ch };   // n = nome da tecla (o WebView2 precisa dele)
    if (!MAC) {
      const up = ch.toUpperCase();
      const vk = /^[A-Z0-9]$/.test(up) ? up.charCodeAt(0) : 0;
      return { c: ch, k: vk, m: mods + (ch !== ch.toLowerCase() ? ",shift" : ""), n: ch };
    }
    const low = ch.toLowerCase();
    if (MK[low] !== undefined) return { c: ch, i: low, k: MK[low], m: (ch !== low ? "shift," : "") + mods };
    if (SHIFTED[ch]) return { c: ch, i: SHIFTED[ch], k: MK[SHIFTED[ch]], m: "shift," + mods };
    return { c: ch, k: 0, m: mods };
  }
  let focusMisses = 0;
  async function ensureFocus() { const ok = await native("selftest-focus"); if (ok === false) focusMisses++; }
  const type = (text, win) => native("selftest-keys", { keys: [...text].map(c => keyOf(c)), window: win });
  // o que o terminal RECEBEU (buffer do xterm) — vale mesmo com a janela coberta, quando o sistema não desenha a tela
  const termText = () => (window.__cdTermText ? window.__cdTermText() : txt($(".xterm-rows")));
  const M = () => window.__cdMonaco;
  const press = (name, mods = "", win) => native("selftest-keys", { keys: [keyOf(name, mods)], window: win });
  const shot = (name, win) => native("selftest-shot", { name, window: win });
  const H = { "X-Codeck-Token": window.CODECK_TOKEN || "", "X-Codeck": "1", "Content-Type": "application/json" };
  const api = async (path, body) => {
    const r = await fetch("/api/" + path, body ? { method: "POST", headers: H, body: JSON.stringify(body) } : { headers: H });
    const j = await r.json(); if (!r.ok) throw new Error(j.error || r.status); return j;
  };
  const go = async (hash, ms = 700) => { location.hash = hash; await sleep(ms); };

  async function step(name, fn) {
    const t0 = Date.now(), before = jsErrors.length;
    try {
      const detail = await fn();
      const errs = jsErrors.slice(before);
      results.push({ name, ok: !errs.length, ms: Date.now() - t0, detail: errs.length ? "erro JS: " + errs.join(" | ").slice(0, 400) : detail || "" });
    } catch (e) {
      results.push({ name, ok: false, ms: Date.now() - t0, detail: String(e?.message || e).slice(0, 400) });
      await shot("falha-" + results.length);
    }
    // nada de diálogo/menu sobrando entre as etapas
    for (let i = 0; i < 2; i++) { if ($("[role=alertdialog]") || $(".items[role=menu]")) await press("Escape"); }
  }

  await native("selftest-focus");
  await sleep(800);
  const vis0 = await native("selftest-native");

  // ============================================================ 1. abertura e navegação
  await step("App abre com a barra lateral e sem erro", async () => {
    await waitFor(".side");
    await shot("01-inicio");
    return `plataforma ${window.CODECK_PLATFORM}`;
  });
  const VIEWS = [["#/inbox", "Fila"], ["#/prs/review", "Pull requests"], ["#/builds", "Builds"], ["#/deploys", "Deploys"], ["#/issues", "Issues"],
    ["#/repos", "Repositórios"], ["#/automation", "Automação"], ["#/analytics", "Análise"], ["#/history", "Histórico"], ["#/ai", "Uso de IA"]];
  for (const [hash, label] of VIEWS) {
    await step(`Tela ${label} abre`, async () => {
      await go(hash, 900);
      const h = await waitFor(() => $("main h1"));
      await waitFor(() => txt($("main h1")).toLowerCase().includes(label.toLowerCase().split(" ")[0]), 4000).catch(() => { throw new Error(`abriu "${txt(h)}" em vez de ${label}`); });
      return txt($("main h1"));
    });
  }
  for (const tab of ["accounts", "github", "ai", "prefs", "about"]) {
    await step(`Configurações → ${tab}`, async () => { await go("#/settings/" + tab, 900); await waitFor(".body"); if (tab === "ai") await shot("02-ia"); });
  }

  // ============================================================ 2. tema e barra de título nativa
  await step("Tema Claro/Escuro/Sistema troca a tela e a janela", async () => {
    await go("#/settings/prefs", 900);
    const tab = l => byText("[role=tab]", l);
    click(await waitFor(() => tab("Claro"))); await sleep(900);
    const n1 = await native("selftest-native");
    if (document.documentElement.dataset.theme !== "light" || !/Aqua$/.test(n1?.appearance || "") || /dark/i.test(n1?.appearance || "")) {
      if (MAC) throw new Error(`claro: tela=${document.documentElement.dataset.theme} janela=${n1?.appearance}`);
    }
    await shot("03-claro");
    click(tab("Escuro")); await sleep(900);
    const n2 = await native("selftest-native");
    if (document.documentElement.dataset.theme !== "dark" || (MAC && !/dark/i.test(n2?.appearance || ""))) throw new Error(`escuro: tela=${document.documentElement.dataset.theme} janela=${n2?.appearance}`);
    click(tab("Sistema")); await sleep(600);
    return `janela: ${n1?.appearance} → ${n2?.appearance}`;
  });

  // ============================================================ 3. repositórios: lista, favorito, tag, clique direito
  const fx = CTX.fixture;
  let apiRepo = null;
  await step("Repositórios locais: registrar e listar", async () => {
    apiRepo = await api("repos/add", { path: fx + "/demo-api" });
    await api("repos/add", { path: fx + "/demo-web" });
    await go("#/repos", 1200);
    await waitFor(() => byText(".list-row.repo", "demo-api"), 10000);
    return `${$$(".list-row.repo").length} repositórios na lista`;
  });
  await step("Clique direito numa linha abre o menu", async () => {
    rightClick(byText(".list-row.repo", "demo-api"));
    const m = await waitFor(".items[role=menu]");
    const items = $$(".items .it").map(txt);
    await press("Escape");
    if (!items.some(i => /Finder|Explorer/.test(i))) throw new Error("menu sem as ações: " + items.join(", "));
    return items.slice(0, 3).join(" · ");
  });
  await step("Favoritar e criar tag pelo seletor", async () => {
    const row = byText(".list-row.repo", "demo-api");
    click($(".star", row)); await sleep(1200);
    const row2 = byText(".list-row.repo", "demo-api");
    click(await waitFor(() => $(".tags .add", row2))); await sleep(300);
    const input = await waitFor(".tags .combo input");
    input.focus();
    await type("Desktop"); await sleep(300); await press("Enter"); await sleep(1200);
    const chips = $$(".chip", byText(".list-row.repo", "demo-api")).map(txt);
    if (!chips.some(c => c.includes("Desktop"))) throw new Error("tag não apareceu: " + chips.join(","));
    return "tag criada por teclado real";
  });

  await step("Repositório: a linha abre o painel dele; o link do repositório abre o projeto na aba Git", async () => {
    await go("#/repos", 1200);
    click(await waitFor(() => byText(".list-row.repo .title", "demo-api")));
    await waitFor(() => byText(".drawer h4", "Pasta local"), 6000);
    await shot("04-painel-repositorio");
    await press("Escape"); await sleep(500);
    await go("#/repo/" + apiRepo.id, 600);
    await waitFor(() => location.hash.startsWith("#/work/"), 6000);
    await waitFor(() => byText(".modes button.on", "Git"), 6000);
    await waitFor(() => $(".repo.embedded") && byText(".repo.embedded *", "inicial"), 10000);
    await shot("04a-git-no-projeto");
    return "aba Git com o grafo (commit inicial)";
  });

  // ============================================================ 4. projetos: abrir, terminal, editor
  await step("Projetos: fechar pela aba (sai de verdade) e reabrir pelo seletor com filtro", async () => {
    // fecha pelo X da aba: ele SAI (antes reabria sozinho), e reabre pelo seletor com filtro
    click($(".x", await waitFor(() => byText(".ptab", "demo-api"))));
    await sleep(3500);
    if (byText(".ptab", "demo-api")) throw new Error("o projeto voltou depois de fechado");
    click(await waitFor(() => $(".pp > button")));
    const f = await waitFor(".pop input"); f.focus();
    // a lista fica inteira dentro da janela (antes subia/cortava dentro da faixa de abas)
    const r = $(".pop").getBoundingClientRect();
    if (r.top < 0 || r.left < 0 || r.bottom > innerHeight + 1 || r.right > innerWidth + 1 || r.height < 120)
      throw new Error(`seletor fora da janela: ${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}×${Math.round(r.height)} (janela ${innerWidth}×${innerHeight})`);
    await type("api");
    await waitFor(() => $$(".pop .it").some(e => txt(e).includes("demo-api")));
    if ($$(".pop .list .it").some(e => txt(e).includes("demo-web"))) throw new Error("o filtro não filtrou");
    await press("Enter");
    await waitFor(() => byText(".ptab.on", "demo-api"), 8000);
    await shot("04-projeto");
  });
  await step("Terminal: ⌘T abre e responde à digitação real", async () => {
    click(await waitFor(() => byText(".sc", "checkout principal")));
    await sleep(300);
    await native("selftest-focus");
    await press("t", MOD); await sleep(2500);
    await waitFor(".xterm");
    click($(".xterm")); $(".xterm-helper-textarea")?.focus(); await sleep(300);
    await type("echo desktop-ok-$((40+2))"); await press("Enter");
    await waitFor(() => termText().includes("desktop-ok-42"), 10000);
    await shot("05-terminal");
    return "saída: desktop-ok-42";
  });
  await step("Terminal: histórico continua depois de trocar de aba", async () => {
    click(await waitFor(() => byText(".ft .n.file", "a.txt"))); await sleep(2500);
    click(byText(".tab", "terminal")); await sleep(1200);
    if (!termText().includes("desktop-ok-42")) throw new Error("histórico sumiu");
  });
  await step("Executar: launch.json e scripts do package.json", async () => {
    // a barra de executar: a seta lista o que dá para iniciar (escolher seleciona); Ctrl+F5 (▷|) executa sem depurar
    click($(".rb .caret"));
    await waitFor(() => byText(".items .it", "Rodar demo"));
    const items = $$(".items .it").map(txt);
    if (!items.some(i => i.includes("ola"))) throw new Error("script do package.json não apareceu: " + items.join(" | "));
    click(byText(".items .it", "Rodar demo"));
    await waitFor(() => txt($(".rb .gob")).includes("Rodar demo"), 3000);
    click($(".rb .nodbg"));
    await waitFor(() => byText(".tab.on", "Rodar demo"), 8000);
    await waitFor(() => termText().includes("launch-ok"), 15000);
    click($(".rb .caret")); click(await waitFor(() => byText(".items .it", "ola")));
    await waitFor(() => txt($(".rb .gob")).includes("ola"), 3000);
    click($(".rb .nodbg"));
    await waitFor(() => termText().includes("script-ok"), 30000);
    if (!txt($(".rb .gob")).includes("ola")) throw new Error("não lembrou a última escolhida");
    await shot("05a-executar");
    return "launch.json (com comentários) e npm run ola executaram";
  });
  await step("Layout: arquivos em cima, tarefas embaixo e painel redimensionável", async () => {
    const left = $(".work .left");
    if (!(left.querySelector(".tree").compareDocumentPosition(left.querySelector(".scopes")) & Node.DOCUMENT_POSITION_FOLLOWING)) throw new Error("tarefas não estão abaixo dos arquivos");
    const w0 = left.getBoundingClientRect().width, h = $(".hsplit.r"), r = h.getBoundingClientRect();
    const dx = w0 < 400 ? 80 : -80;   // a largura é lembrada entre execuções: arrasta para onde há espaço
    h.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, clientX: r.x + 4, clientY: r.y + 50 }));
    window.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, clientX: r.x + 4 + dx, clientY: r.y + 50 }));
    window.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    await sleep(300);
    const w1 = $(".work .left").getBoundingClientRect().width;
    const expected = w0 + dx;
    if (Math.abs(w1 - expected) > 4) throw new Error(`largura ${w0} → ${w1} (esperado ${expected})`);
    const lh = $(".right .lh"); if (lh) { click(lh); await sleep(200); if ($(".right .lim")) throw new Error("limites não recolheram"); click($(".right .lh")); }
    return `painel ${Math.round(w0)} → ${Math.round(w1)} px`;
  });
  await step("Modos Git/PRs mantêm os arquivos; painel de arquivos recolhe e abre", async () => {
    click(byText(".modes button", "PRs")); await sleep(800);
    await waitFor(() => $(".act") || byText(".body *", "sem remoto"), 5000);
    if (!$(".work .left:not(.hidden)")) throw new Error("os arquivos sumiram no modo PRs");
    click(byText(".modes button", "Git")); await sleep(800);
    if (!$(".work .left:not(.hidden)")) throw new Error("os arquivos sumiram no modo Git");
    click($(".lt")); await sleep(300);
    if (!$(".work .left.hidden")) throw new Error("não recolheu");
    click($(".lt")); await sleep(300);
    if ($(".work .left.hidden")) throw new Error("não reabriu");
    click(byText(".modes button", "Código")); await sleep(300);
    return "PRs e Git com arquivos à mostra; recolher/abrir ok";
  });
  await step("Editor: abrir, digitar e salvar com ⌘S", async () => {
    click(byText(".tab", "a.txt")); await sleep(800);
    const ta = await waitFor(".monaco-editor textarea", 10000);
    ta.focus(); await sleep(300);
    if (MAC) await press("ArrowDown", "cmd"); else await press("End", "ctrl");   // fim do arquivo
    await press("End");
    await type("\nlinha digitada no desktop");
    await sleep(400);
    if (!$(".tab.on .dirty")) throw new Error("não marcou como não salvo");
    await press("s", MOD); await sleep(1200);
    const f = await api("ws/file?repoId=" + apiRepo.id + "&path=a.txt");
    if (!f.text.includes("linha digitada no desktop")) throw new Error("arquivo não foi salvo no disco");
    await shot("06-editor");
    return "salvo no disco";
  });
  await step("Explorador e Git: cor do arquivo alterado, diff e ⌘P", async () => {
    // o explorador pinta o arquivo alterado (M) e a barra de atividades conta as alterações
    await waitFor(() => byText(".ft .n.mod", "a.txt"), 12000);
    click(await waitFor(".abar button[title^='Controle']")); await sleep(800);
    click(await waitFor(() => byText(".scm .f", "a.txt"), 8000)); await sleep(2500);
    if (!txt($(".tab.on")).includes("alterações")) throw new Error("não abriu o diff (aba: " + txt($(".tab.on")) + ")");
    await waitFor(".dv .monaco-diff-editor", 8000);
    await shot("06b-diff");
    click($(".abar button[title^='Explorador']")); await sleep(500);
    // ⌘P: abre arquivo pela busca aproximada
    await press("p", MOD);
    const qi = await waitFor(".qo input", 4000);
    qi.focus(); await type("util"); await sleep(600);
    await press("Enter"); await sleep(1500);
    if (!txt($(".tab.on")).includes("util.ts")) throw new Error("⌘P não abriu util.ts (aba: " + txt($(".tab.on")) + ")");
    return "a.txt em M, diff aberto pelo controle de código-fonte, ⌘P abriu util.ts";
  });
  await step("Explorador: mostra os ignorados e o repositório aninhado (e abre)", async () => {
    const ign = await waitFor(() => byText(".ft .n.file.ign", "workspace.local.json"), 8000).catch(() => { throw new Error("workspace.local.json (ignorado) não apareceu apagado"); });
    click(await waitFor(() => $$(".ft .n:not(.file)").find(e => txt(e) === "nested-repo"), 5000));
    click(await waitFor(() => byText(".ft .n.file", "nested.txt"), 5000)); await sleep(1500);
    if (!txt($(".tab.on")).includes("nested.txt")) throw new Error("não abriu o arquivo do repositório aninhado (aba: " + txt($(".tab.on")) + ")");
    await waitFor(() => M()?.editor.getModels().some(m => m.uri.path.endsWith("nested-repo/nested.txt") && m.getValue().includes("aninhado")), 6000);
    // pasta ignorada inteira (bin/) é lida só ao abrir
    click(await waitFor(() => $$(".ft .n:not(.file)").find(e => txt(e) === "bin"), 5000));
    await waitFor(() => byText(".ft .n.file.ign", "out.txt"), 6000).catch(() => { throw new Error("bin/ não listou out.txt ao abrir"); });
    click($$(".ft .n:not(.file)").find(e => txt(e) === "bin")); click($$(".ft .n:not(.file)").find(e => txt(e) === "nested-repo"));
    await shot("06c-ignorados");
    return `${txt(ign)} apagado; nested-repo/nested.txt abriu; bin/ sob demanda`;
  });
  await step("Gerenciador de Soluções: projeto do repositório aninhado, abrir e criar arquivo", async () => {
    click(await waitFor(".abar button[title^='Gerenciador']", 8000)); await sleep(800);
    const proj = await waitFor(() => byText(".sv .proj", "App"), 8000);
    if (!$$(".sv .proj").some(p => p.classList.contains("start") || true)) throw new Error("sem projeto");
    if (!$(".sv .ft .n") ) click(proj);
    const prog = await waitFor(() => byText(".sv .ft .n.file", "Program.cs"), 6000);
    if ($$(".sv .ft .n").some(e => txt(e) === "bin")) throw new Error("bin/ apareceu no projeto (deveria ficar escondido)");
    click(prog); await sleep(1500);
    if (!txt($(".tab.on")).includes("Program.cs")) throw new Error("Program.cs não abriu (aba: " + txt($(".tab.on")) + ")");
    const r = proj.getBoundingClientRect();
    proj.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: r.x + 20, clientY: r.y + 8 }));
    click(await waitFor(() => byText(".items .it", "Novo arquivo"), 3000)); await sleep(400);
    const inp = await waitFor(".sv input.ren", 3000); inp.focus();
    await type("Novo.cs"); await press("Enter"); await sleep(1500);
    const f = await api("ws/file?repoId=" + apiRepo.id + "&path=nested-repo/App/Novo.cs");
    if (typeof f.text !== "string") throw new Error("Novo.cs não foi criado no disco");
    await waitFor(() => byText(".sv .ft .n.file", "Novo.cs"), 5000);
    await shot("06d-solucao");
    click($(".abar button[title^='Explorador']")); await sleep(500);
    return "App (repositório aninhado) com Program.cs aberto; Novo.cs criado pelo clique direito no projeto";
  });
  await step("Atalhos: personalizar (Configurações) e usar; paleta com comandos (⌘⇧P >)", async () => {
    try { return await shortcutsStep(); } finally { if (!location.hash.startsWith("#/work/")) await go("#/work/" + apiRepo.id, 1200); }
  });
  async function shortcutsStep() {
    await go("#/settings/shortcuts", 900);
    const search = await waitFor(".kb .flt input", 5000); search.focus();
    await type("Mostrar as Extens"); await sleep(400);
    const row = await waitFor(() => byText(".kb .row", "Mostrar as Extensões"), 4000);
    click(row.querySelector("button[title='Adicionar um atalho']")); await sleep(300);
    await press("9", MOD + ",alt"); await sleep(300);
    await press("Enter"); await sleep(600);
    if (!/9/.test(txt(byText(".kb .row", "Mostrar as Extensões")))) throw new Error("o atalho novo não apareceu na lista: " + txt(byText(".kb .row", "Mostrar as Extensões")));
    await go("#/work/" + apiRepo.id, 1500);
    document.body.focus();
    await press("9", MOD + ",alt"); await sleep(600);
    if (!$(".abar button.on[title^='Extensões']")) throw new Error("o atalho personalizado não abriu as Extensões");
    click($(".abar button[title^='Explorador']")); await sleep(300);
    await press("p", MOD + ",shift"); await sleep(500);
    const pi = await waitFor(".pal input", 3000); pi.focus();
    await type(">format"); await sleep(500);
    const it = byText(".pal .it", "Formatar") || byText(".pal .it", "format");
    await press("Escape");
    if (!it) throw new Error("a paleta não listou os comandos com >");
    await go("#/settings/shortcuts", 700);
    click(await waitFor(() => byText(".kb .row", "Mostrar as Extensões")?.querySelector("button[title^='Voltar ao padrão']"), 4000));
    await go("#/work/" + apiRepo.id, 1200);
    return "⌘⌥9 → Extensões; paleta com > lista os comandos; padrão restaurado";
  }
  await step("Editor: servidor de linguagem (erro, hover e F12)", async () => {
    if (!CTX.lsp) return "pulado — sem servidor instalado no teste";
    click(byText(".ft .n.file", "main.ts")); await sleep(1000);
    await waitFor(() => $(".lsp.ok"), 20000);
    // o erro de tipo chega como marcação do servidor de linguagem (estado do editor, não pixels)
    const err = await waitFor(() => M()?.editor.getModelMarkers({}).find(m => m.severity === 8 && /string/i.test(m.message)), 45000);
    const ed = M().editor.getEditors().find(e => e.getModel()?.uri.path.endsWith("main.ts"));
    ed.focus(); ed.setPosition({ lineNumber: 3, column: 25 });   // em cima de "soma"
    await press("F12"); await sleep(2500);
    if (!txt($(".tab.on")).includes("util.ts")) {
      // diagnóstico: a tecla não chegou ou a navegação falhou? roda a ação direto e lista os modelos
      const focused = ed.hasTextFocus();
      ed.focus(); ed.setPosition({ lineNumber: 3, column: 25 });
      await ed._commandService.executeCommand("editor.action.revealDefinition").catch(() => {}); await sleep(2500);
      const models = M().editor.getModels().map(m => m.uri.toString().split("/").slice(-1)[0]).join(",");
      throw new Error(`F12 não abriu util.ts (aba: ${txt($(".tab.on"))}; foco=${focused}; modelos: ${models})`);
    }
    await shot("07-lsp");
    return `erro: "${err.message.slice(0, 60)}" + F12 abriu util.ts`;
  });

  // ============================================================ 5. tarefas, revisão, divisão, quadro e comparação
  let taskTitle = "Tarefa do desktop";
  await step("Nova tarefa pelo formulário (worktree real)", async () => {
    click(byText(".sch button", "Nova")); await sleep(600);
    const inp = await waitFor(".form input.input");
    inp.focus(); await type(taskTitle);
    for (const a of $$(".acc.on")) click(a);   // sem agente nesta etapa
    click(byText(".seg button", "Worktree separado")); await sleep(200);   // o padrão agora é o checkout
    click(byText(".btn.primary", "Criar tarefa"));
    await waitFor(() => byText(".sc.task", taskTitle), 20000);
    const st = await api("ws");
    const t = st.projects.find(p => p.name === "demo-api").tasks.find(x => x.title === taskTitle);
    if (!t?.exists) throw new Error("worktree não existe");
    // o modo Git da tarefa é o Git do worktree (branch da tarefa)
    click(byText(".modes button", "Git"));
    await waitFor(() => byText(".repo.embedded .branch-btn", "feature/tarefa-do-desktop"), 10000);
    return t.path.split(/[\\/]/).slice(-3).join("/") + " · Git na branch da tarefa";
  });
  await step("Revisão: diff, comentário e envio", async () => {
    const st = await api("ws");
    const t = st.projects.find(p => p.name === "demo-api").tasks.find(x => x.title === taskTitle);
    await api("ws/file", { repoId: apiRepo.id, taskId: t.id, path: "a.txt", text: "a\nalteração do agente\n" });
    click(byText(".tab", "Revisão")); await sleep(2500);
    click(await waitFor(() => byText(".rv .f", "a.txt"), 8000)); await sleep(2000);
    await waitFor(".monaco-diff-editor", 10000);
    // os dois lados do diff carregados (base × agora) e uma linha selecionada no lado "agora"
    const mod = await waitFor(() => M()?.editor.getEditors().find(e => e.getModel()?.uri.scheme === "review" && e.getModel().getValue().includes("alteração do agente")), 10000);
    const base = M().editor.getModels().find(m => m.uri.scheme === "review-base" && m.uri.path.endsWith("a.txt"));
    if (!base || base.getValue().includes("alteração do agente")) throw new Error("lado base do diff errado");
    mod.focus(); mod.setSelection({ startLineNumber: 2, startColumn: 1, endLineNumber: 2, endColumn: 20 });
    click(byText(".rv .btn", "Comentar"));
    const ta = await waitFor("[role=alertdialog] textarea"); ta.focus();
    await type("Renomear para o termo do domínio");
    click(byText("[role=alertdialog] button", "Adicionar")); await sleep(500);
    if ($$(".rv .c").length < 1) throw new Error("comentário não entrou");
    await shot("08-revisao");
    return "diff + comentário ok";
  });
  await step("Tela dividida (Abrir ao lado)", async () => {
    await native("selftest-focus");
    await press("t", MOD); await sleep(2000);
    rightClick(byText(".tab", "Revisão"));
    click(await waitFor(() => byText(".items .it", "Abrir ao lado"))); await sleep(1500);
    if ($$(".body.split .pane").length !== 2) throw new Error("não dividiu");
    await shot("09-dividido");
    click($(".unsplit")); await sleep(400);
  });
  await step("Quadro e comparação de soluções", async () => {
    for (const s of ["claude", "codex"]) {
      const t = await api("ws/task", { repoId: apiRepo.id, title: `Frete (${s})`, slug: `frete-${s}`, base: "main", group: "frete" });
      await api("ws/file", { repoId: apiRepo.id, taskId: t.id, path: "frete.txt", text: s + "\n" });
    }
    await sleep(3000);
    await go("#/board/agents", 1500);   // o quadro das tarefas dos agentes é uma aba da página Quadro
    const cards = $$(".tcard").length;
    click(byText(".tcard", "Frete (claude)")); await sleep(1500);
    click(await waitFor(".cmp")); await sleep(2500);
    const cols = $$(".cols .col").length;
    await shot("10-comparar");
    await press("Escape");
    if (cards < 3 || cols !== 2) throw new Error(`quadro=${cards} colunas=${cols}`);
    return `${cards} cartões, ${cols} soluções`;
  });
  await step("Hub de projetos e grupo nas abas (recolher/expandir)", async () => {
    await go("#/projects", 1500);
    await waitFor(() => byText(".pc", "demo-api"), 8000);
    const g = await api("ws/groups/save", { name: "Grupo autoteste", repoIds: [apiRepo.id] });
    await go("#/work/" + apiRepo.id, 1500);
    click(await waitFor(() => byText(".gchip", "Grupo autoteste"), 6000)); await sleep(900);
    if (!$(".grp.collapsed")) throw new Error("o grupo não recolheu");
    click(byText(".gchip", "Grupo autoteste")); await sleep(600);
    await shot("10b-grupo");
    await api("ws/groups/delete", { id: g.id });
    return "hub lista o clone; grupo recolhe e expande";
  });
  await step("Quadro: cartão com o projeto vira contexto para a IA", async () => {
    const c = await api("kanban/card", { title: "Cartão do autoteste", description: "- [ ] passo", projects: [apiRepo.id], primary: apiRepo.id });
    await go("#/board", 1500);
    await waitFor(() => byText(".kc", "Cartão do autoteste"), 6000);
    await shot("10c-quadro");
    const ctx = (await api("kanban/context?id=" + c.id)).text;
    await api("kanban/card/delete", { id: c.id });
    if (!ctx.includes("demo-api")) throw new Error("contexto sem o projeto: " + ctx);
    return "cartão no quadro; contexto com o projeto";
  });
  await step("Markdown abre renderizado e a checkbox grava no arquivo", async () => {
    await api("ws/file", { repoId: apiRepo.id, path: "roteiro.md", text: "# Roteiro\n\n- [ ] abrir o app\n- [ ] testar\n" });
    await go("#/work/" + apiRepo.id, 1200);
    click(await waitFor(() => byText(".sc", "checkout principal"))); await sleep(500);
    click(await waitFor(".abar button[title^='Explorador']"));
    click(await waitFor(".ft .bar button[title='Recarregar']")); await sleep(1500);
    click(await waitFor(() => byText(".ft .n", "roteiro.md"), 6000));
    click(await waitFor(() => $(".doc input[type=checkbox]"), 10000)); await sleep(2500);
    const f = await api("ws/file?repoId=" + apiRepo.id + "&path=roteiro.md");
    await shot("10d-markdown");
    if (!f.text.includes("- [x] abrir o app")) throw new Error("a checkbox não gravou: " + f.text);
    return "pré-visualização; checkbox salva no arquivo";
  });
  await step("Acompanhar: desligar e voltar ao padrão da conta", async () => {
    await api("tracking/repo", { key: "github:autoteste/demo", track: false, builds: false });
    const t = await api("tracking");
    if (t.repos["github:autoteste/demo"]?.track !== false) throw new Error(JSON.stringify(t));
    await api("tracking/repo", { key: "github:autoteste/demo", reset: true });
    if ((await api("tracking")).repos["github:autoteste/demo"]) throw new Error("não voltou ao padrão");
    return "grava e volta ao padrão";
  });
  await step("Ajustes do projeto salvam", async () => {
    click(byText(".sc", "checkout principal")); await sleep(300);
    click($(".gear")); const box = await waitFor(".form textarea");
    if (byText(".form h4", "Pasta")) throw new Error("ainda pede pasta");
    if (!byText(".form h4", "Repositórios relacionados")) throw new Error("sem repositórios relacionados");
    box.focus(); await type("echo preparando");
    click(byText(".btn.primary", "Salvar")); await sleep(1000);
    const st = await api("ws");
    if (st.projects.find(p => p.name === "demo-api").settings.setup !== "echo preparando") throw new Error("não salvou");
  });

  // ============================================================ 6. agente de IA de verdade (telemetria)
  await step("Agente Claude: abre, responde e mostra contexto/limites", async () => {
    if (!CTX.trusted) return "pulado — sem pasta confiável no teste";
    const p = await api("ws/open", { path: CTX.trusted });
    await go("#/work/" + p.id, 1500);
    click(byText(".sc", "checkout principal")); await sleep(300);
    const acc = (await api("ai")).accounts.find(a => a.provider === "claude" && a.name === CTX.account && a.installed);
    if (!acc) throw new Error("conta " + CTX.account + " não encontrada");
    const trig = byText(".tact span.btn", "Agente");
    click(trig.closest("button")); click(await waitFor(() => byText(".items .it", CTX.account)));
    await waitFor(() => byText(".tab", "Claude Code"), 10000);
    await sleep(4000);
    const box = await waitFor(".send textarea"); box.focus();
    await type("Responda apenas: OK");
    click(byText(".send .btn", "Enviar"));
    await waitFor(() => byText(".right .pill", "terminou"), 90000);
    // depois da resposta: contexto em % e os limites (5 h / semanal) da conta têm de aparecer no painel
    await waitFor(() => /\d+%/.test(txt(byText(".right .kv", "Contexto"))), 25000).catch(() => { throw new Error("contexto não apareceu: " + txt(byText(".right .kv", "Contexto"))); });
    await waitFor(() => $$(".right .lim .win").length > 0, 25000).catch(() => { throw new Error("limites da conta não apareceram"); });
    const model = txt(byText(".right .kv", "Modelo")), ctxv = txt(byText(".right .kv", "Contexto"));
    await shot("11-agente");
    if (!/Opus|Sonnet|Haiku|Claude/i.test(model)) throw new Error("modelo não apareceu: " + model);
    const lim = $$(".right .lim .win").length;
    return `${model.replace(/\s+/g, " ")} · ${ctxv.replace(/\s+/g, " ")} · ${lim} janela(s) de limite`;
  });

  // ============================================================ 7. janela própria de projeto
  await step("Uso de IA: tempo no projeto e uso do agente por projeto", async () => {
    await api("ws/focus", { repoId: apiRepo.id, seconds: 60 });
    await go("#/ai", 900);
    const row = await waitFor(() => $$("main tbody tr").find(e => txt(e).includes("demo-api")), 6000);
    if (!/1 min/.test(txt(row))) throw new Error(`tempo no projeto não apareceu: ${txt(row)}`);
    let more = "";
    if (CTX.trusted && CTX.account) {   // o agente de verdade rodou antes: sessão e limites da conta aparecem
      await waitFor(() => $$("main .lim .lw").length > 0, 8000).catch(() => { throw new Error("limites da conta não apareceram"); });
      more = ` · ${$$("main .lim .lw").length} janela(s) de limite`;
    }
    await shot("09-uso-ia");
    await go("#/work", 600);
    return txt(row).replace(/\s+/g, " ").slice(0, 90) + more;
  });
  await step("Projeto em janela própria (nativa)", async () => {
    await go("#/work", 1000);
    rightClick(byText(".ptab", "demo-api"));
    click(await waitFor(() => byText(".items .it", "janela própria")));
    await sleep(4000);
    const n = await native("selftest-native");
    if (!n || n.windows < 2) throw new Error("segunda janela não abriu: " + JSON.stringify(n));
    await shot("12-janela-propria", 1);
    return `janelas: ${n.windows} (${n.titles.join(", ")})`;
  });

  // ============================================================ 8. fechar e sair sem travar nem deixar processo
  await step("Fechar em tela cheia esconde sem tela preta e reabre", async () => {
    await api("ws/shell", { repoId: apiRepo.id, title: "processo longo", command: "sleep 4244" });   // conferido depois de sair
    if (!MAC) return "só no macOS (tela cheia nativa)";
    if (await native("selftest-fullscreen") !== true) {
      // o macOS só põe em tela cheia o app que está em primeiro plano (com você usando outra janela, ele recusa)
      const n = await native("selftest-native");
      if (!n?.visible || !n?.keyWindow) return "pulado — a janela não estava em primeiro plano (o macOS não permite tela cheia assim)";
      throw new Error("não entrou em tela cheia");
    }
    const c = await native("selftest-close");
    if (c?.fullScreen || c?.visible) throw new Error("depois de fechar: " + JSON.stringify(c));
    if (await native("selftest-show") !== true) throw new Error("não reabriu");
    return "saiu da tela cheia, escondeu e reabriu";
  });

  // ============================================================ 9. limpeza e fechamento
  await step("Remover tarefas pela tela (confirmação)", async () => {
    await go("#/work/" + apiRepo.id, 1200);
    for (const title of [taskTitle]) {
      click(byText(".sc.task", title)); await sleep(800);
      click(await waitFor(() => $(".right .danger-text")));
      click(await waitFor(() => byText("[role=alertdialog] button", "Remover worktree"))); await sleep(2500);
    }
    const left = (await api("ws")).projects.find(p => p.name === "demo-api").tasks.map(t => t.title);
    if (left.includes(taskTitle)) throw new Error("tarefa continuou");
    return `restantes: ${left.length}`;
  });

  const ok = results.filter(r => r.ok).length;
  const vis1 = await native("selftest-native");
  await native("selftest-done", { result: JSON.stringify({ platform: window.CODECK_PLATFORM, ok, total: results.length, results, jsErrors, focusMisses,
    visible: { start: vis0?.visible, end: vis1?.visible } }, null, 1) });
})();
