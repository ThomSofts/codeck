// Autoteste do EDITOR no app de desktop (SCRIPT=tests/desktop/selftest-editor.js scripts/test-desktop.sh): cores
// semânticas, lâmpada, F2 em vários arquivos, dicas inline, atalho remapeado, abas, C# (com EXTRA_LSP_PATH apontando
// para uma pasta com o csharp-ls) e Issues (com respostas simuladas — nada é escrito no Azure/GitHub).
// Roda dentro da janela real (WKWebView no macOS, WebView2 no Windows).
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
  const fx = CTX.fixture;
  let apiRepo = null;
  const edOf = (name) => M()?.editor.getEditors().find(e => e.getModel()?.uri.path.endsWith(name));
  const color = (word) => { const s = $$(".monaco-editor .view-line span span").find(x => txt(x) === word); return s ? getComputedStyle(s).color : null; };
  const openFile = async (path) => {
    for (const part of path.split("/").slice(0, -1)) { const d = $$(".ft .n:not(.file)").find(e => txt(e) === part); if (d && d.getAttribute("aria-expanded") !== "true") { click(d); await sleep(500); } }
    const row = await waitFor(() => $$(".ft .n.file").find(e => txt(e.querySelector(".nm")) === path.split("/").pop()), 8000);
    click(row); row.dispatchEvent(new MouseEvent("dblclick", { bubbles: true })); await sleep(1200);   // fixa a aba (clique simples é visualização)
  };

  await step("Abrir o projeto de teste", async () => {
    apiRepo = await api("repos/add", { path: fx + "/demo-api" });
    await api("ws/open", { repoId: apiRepo.id }).catch(() => api("ws/open", { id: apiRepo.id }));
    await go("#/work/" + apiRepo.id, 2500);
    await waitFor(() => byText(".ptab.on", "demo-api"), 10000);
    // tema escuro: as cores conferidas abaixo são as do Dark Modern
    await go("#/settings/prefs", 700); click(await waitFor(() => byText("[role=tab]", "Escuro"))); await sleep(500);
    await go("#/work/" + apiRepo.id, 1500);
  });

  await step("Cores semânticas do servidor de linguagem (TypeScript)", async () => {
    if (!CTX.lsp) return "pulado — sem servidor";
    await openFile("util.ts");
    await waitFor(() => $(".lsp.ok"), 30000);
    const c = await waitFor(() => color("soma") === "rgb(220, 220, 170)" && color("soma"), 30000).catch(() => { throw new Error("soma não ficou amarela (função): " + color("soma")); });
    const p = color("a");
    await waitFor(() => byText(".crumbs .sym", "soma"), 8000).catch(() => { throw new Error("breadcrumb sem o símbolo"); });
    await shot("x1-semantico");
    return `função soma ${c}, parâmetro a ${p}, breadcrumb › soma`;
  });

  await step("Lâmpada: correção rápida aplica o import que falta", async () => {
    if (!CTX.lsp) return "pulado — sem servidor";
    await api("ws/file", { repoId: apiRepo.id, path: "fix.ts", text: "const x = soma(1, 2);\nconsole.log(x);\n" });
    await sleep(1500);
    click($(".ft .bar button[title='Recarregar']")); await sleep(1200);
    await openFile("fix.ts");
    await waitFor(() => M().editor.getModelMarkers({}).find(m => m.resource.path.endsWith("fix.ts") && /soma/.test(m.message)), 45000);
    const ed = edOf("fix.ts"); ed.focus(); ed.setPosition({ lineNumber: 1, column: 12 });
    await sleep(500);
    ed.trigger("teste", "editor.action.codeAction", { kind: "quickfix", apply: "first" });
    await waitFor(() => /import \{ soma \} from "\.\/util"/.test(ed.getModel().getValue()), 15000).catch(() => { throw new Error("o import não entrou: " + ed.getModel().getValue().slice(0, 120)); });
    await press("s", MOD); await sleep(1000);
    return ed.getModel().getValue().split("\n")[0];
  });

  await step("F2: renomear o símbolo em todos os arquivos (aberto e fechado)", async () => {
    if (!CTX.lsp) return "pulado — sem servidor";
    click(byText(".tab", "util.ts")); await sleep(1000);
    const ed = edOf("util.ts"); ed.focus(); ed.setPosition({ lineNumber: 1, column: 19 });
    await sleep(400);
    ed.trigger("teste", "editor.action.rename", null); await sleep(1200);   // F2 (o roteiro não tem a tecla F2 no mapa)
    const inp = await waitFor(".rename-box input, .rename-box textarea, input.rename-input", 5000);
    inp.focus(); inp.select?.();
    await type("somar"); await press("Enter"); await sleep(3500);
    if (!/function somar/.test(ed.getModel().getValue())) throw new Error("util.ts não mudou");
    const fixM = edOf("fix.ts")?.getModel() || M().editor.getModels().find(m => m.uri.path.endsWith("fix.ts"));
    if (fixM && !/somar/.test(fixM.getValue())) throw new Error("fix.ts (aberto) não mudou");
    const main = await api("ws/file?repoId=" + apiRepo.id + "&path=main.ts");
    if (!/somar\(1, 2\)/.test(main.text)) throw new Error("main.ts (fechado) não foi gravado: " + main.text.slice(0, 80));
    return "util.ts e fix.ts no editor; main.ts gravado no disco";
  });

  await step("Dicas inline (Configurações → Sempre)", async () => {
    if (!CTX.lsp) return "pulado — sem servidor";
    await go("#/settings/editor", 800);
    const inlayRow = () => $$(".pref").find(r => /Dicas inline/.test(txt(r)));
    click(await waitFor(() => inlayRow() && byText("[role=tab]", "Sempre", inlayRow()), 5000)); await sleep(500);
    await go("#/work/" + apiRepo.id, 1500);
    await openFile("main.ts");
    const ed = edOf("main.ts");
    const hint = await waitFor(() => ed?.getModel()?.getAllDecorations().map(d => d.options.before?.content || d.options.after?.content || "").find(c => /^a:/.test(c.trim())), 30000)
      .catch(() => { const ds = ed?.getModel()?.getAllDecorations().map(d => d.options.before?.content || d.options.after?.content).filter(Boolean) || [];
        throw new Error(`nenhuma dica inline (a:) em main.ts — opção ${JSON.stringify(ed?.getOption(M().editor.EditorOption.inlayHints))}, conteúdos: ${JSON.stringify(ds).slice(0, 200)}`); });
    await shot("x2-inlay");
    await go("#/settings/editor", 600); click(await waitFor(() => inlayRow() && byText("[role=tab]", "Segurando", inlayRow()))); await go("#/work/" + apiRepo.id, 1000);
    return `dica: "${hint.trim()}"`;
  });

  await step("Atalho de comando do editor remapeado (Apagar a linha → ⌘⌥K)", async () => {
    await go("#/settings/shortcuts", 900);
    const s = await waitFor(".kb .flt input"); s.focus(); await type("Apagar a linha"); await sleep(400);
    const row = await waitFor(() => byText(".kb .row", "Apagar a linha"));
    click(row.querySelector(".chip .kbd")); await sleep(300);
    await press("k", MOD + ",alt"); await press("Enter"); await sleep(800);
    await go("#/work/" + apiRepo.id, 1500);
    click(byText(".tab", "a.txt") || byText(".tab", "util.ts")); await sleep(800);
    const ed = M().editor.getEditors().find(e => e.getModel()?.uri.path.endsWith("util.ts"));
    click(byText(".tab", "util.ts")); await sleep(800);
    ed.focus(); ed.setPosition({ lineNumber: 2, column: 1 });
    const before = ed.getModel().getLineCount();
    await press("k", MOD + ",shift"); await sleep(400);
    const mid = ed.getModel().getLineCount();
    await press("k", MOD + ",alt"); await sleep(400);
    const after = ed.getModel().getLineCount();
    ed.trigger("t", "undo"); ed.trigger("t", "undo");
    await go("#/settings/shortcuts", 700);
    click(await waitFor(() => byText(".kb .row", "Apagar a linha")?.querySelector("button[title^='Voltar ao padrão']"), 4000));
    await go("#/work/" + apiRepo.id, 800);
    if (mid !== before) throw new Error("o atalho antigo (⌘⇧K) continuou apagando");
    if (after !== before - 1) throw new Error(`o novo (⌘⌥K) não apagou: ${before} → ${after}`);
    return `⌘⇧K não apaga mais; ⌘⌥K apagou (${before} → ${after})`;
  });

  await step("Abas: arrastar reordena; não salvo mostra o ponto", async () => {
    const tabs = () => $$(".tl .tab").map(t => txt(t.querySelector(".tname")));
    const before = tabs();
    const a = byText(".tl .tab", "main.ts"), b = byText(".tl .tab", "util.ts");
    const dt = new DataTransfer();
    a.dispatchEvent(new DragEvent("dragstart", { bubbles: true, dataTransfer: dt }));
    b.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer: dt }));
    b.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt }));
    a.dispatchEvent(new DragEvent("dragend", { bubbles: true, dataTransfer: dt }));
    await sleep(500);
    const after = tabs();
    if (after.indexOf("main.ts") > after.indexOf("util.ts") === before.indexOf("main.ts") > before.indexOf("util.ts")) throw new Error(`não reordenou: ${before.join(",")} → ${after.join(",")}`);
    click(byText(".tab", "util.ts")); await sleep(500);
    const ed = edOf("util.ts"); ed.focus(); await type(" "); await sleep(400);
    if (!$(".tab.on.isdirty .dirty")) throw new Error("sem o ponto de não salvo");
    ed.trigger("t", "undo");
    return `${before.join(", ")} → ${after.join(", ")}`;
  });

  await step("C#: servidor de linguagem (csharp-ls) com cores semânticas", async () => {
    if (!CTX.cs) return "pulado — sem csharp-ls";
    await openFile("nested-repo/App/Program.cs");
    await waitFor(() => $(".lsp.ok"), 60000);
    const c = await waitFor(() => color("WriteLine") === "rgb(220, 220, 170)" && color("WriteLine"), 120000).catch(() => { throw new Error("WriteLine sem cor de método: " + color("WriteLine") + " · Console " + color("Console")); });
    await shot("x3-csharp");
    return `WriteLine ${c} · Console ${color("Console")}`;
  });

  await step("Issues: Todas / filtro de responsável / gaveta / comentar / implementar", async () => {
    // respostas simuladas da API (nada é escrito no Azure/GitHub)
    const posts = [];
    const of = window.fetch;
    const I = (n, title, who, email, reasons) => ({ key: "Org|wi:" + n, provider: "azure", org: "Org", repo: "Proj", number: n, title, state: "Active", type: "Task",
      updated: new Date().toISOString(), created: new Date().toISOString(), author: who, assignees: who ? [{ login: who, avatar: null, email }] : [], labels: [{ name: "api", color: null }],
      reason: reasons[0] || "other", reasons, comments: 1, url: "https://example.invalid/" + n, account: null });
    const list = [I(1, "Tarefa do Leonardo na Cifal", "Leonardo Thomaz", "leonardo.thomaz@cifal.invalid", ["assigned"]), I(2, "Tarefa do leonardo na Dematec", "leonardo.thomaz", "leonardo.thomaz@dematec.invalid", []),
      I(3, "Tarefa de outra pessoa", "Breno", "breno@x.invalid", []), I(4, "Sem responsável", "", "", ["created"])];
    window.fetch = async (u, o) => {
      const url = String(u);
      const j = (x) => new Response(JSON.stringify(x), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.includes("/api/issues/browse")) return j({ issues: list, errors: {}, at: new Date().toISOString() });
      if (url.includes("/api/issue/comment")) { posts.push(JSON.parse(o.body)); return j({ ok: true }); }
      if (/\/api\/issue\?/.test(url)) return j({ provider: "azure", number: 1, title: "Tarefa do Leonardo na Cifal", state: "Active", type: "Task", project: "Proj", author: "Leonardo Thomaz",
        assignee: "Leonardo Thomaz", created: new Date().toISOString(), updated: new Date().toISOString(), labels: ["api"], sections: [{ label: "Descrição", html: "<p>Fazer o <b>endpoint</b> de frete</p><script>alert(1)</script>" }],
        comments: [{ author: "Breno", created: new Date().toISOString(), html: "<p>Comentário de teste</p>" }], relations: [], url: "https://example.invalid/1" });
      return of(u, o);
    };
    try {
      await go("#/settings/accounts", 900);
      click(await waitFor(() => byText("#people button", "Pessoa"), 5000)); await sleep(500);
      const pin = await waitFor(() => $("#people .person .nm"), 3000);
      setInput(pin, "Leonardo"); await sleep(500);
      const add = await waitFor(() => $("#people .person .add"), 3000);
      for (const n of ["Leonardo Thomaz", "leonardo.thomaz"]) { add.focus(); setInput(add, n); add.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); await sleep(400); }
      const chips = $$("#people .chip").map(txt).join(" | ");
      if (!/Leonardo Thomaz/.test(chips) || !/leonardo\.thomaz/.test(chips)) throw new Error("pessoa não montou: " + chips);
      await go("#/issues", 1200);
      click(await waitFor(() => byText(".seg button", "Todas"), 8000)); await sleep(1500);
      await waitFor(() => $$(".list-row").length === 4, 6000).catch(() => { throw new Error("Todas não trouxe as 4: " + $$(".list-row").length); });
      const sel = $$("select.select").find(s => [...s.options].some(o => o.value === "p:Leonardo"));
      if (!sel) throw new Error("a pessoa Leonardo não apareceu no filtro de responsável");
      sel.value = "p:Leonardo"; sel.dispatchEvent(new Event("change", { bubbles: true })); await sleep(500);
      const shown = $$(".list-row").map(r => txt(r.querySelector(".title")));
      if (shown.length !== 2) throw new Error("filtro Leonardo: " + shown.join(" | "));
      sel.value = "-"; sel.dispatchEvent(new Event("change", { bubbles: true })); await sleep(400);
      if ($$(".list-row").length !== 1) throw new Error("sem responsável: " + $$(".list-row").length);
      sel.value = ""; sel.dispatchEvent(new Event("change", { bubbles: true })); await sleep(400);
      // estado "Todas" (abertas e fechadas): as minhas vêm da leitura sob demanda (a simulada)
      const stSeg = $$(".seg").find(sg => byText("button", "Fechadas", sg));
      click(byText("button", "Todas", stSeg)); await sleep(1200);
      click(byText(".seg button", "Atribuídas")); await sleep(800);
      if ($$(".list-row").length !== 1) throw new Error("atribuídas: " + $$(".list-row").length);
      click(byText(".seg button", "Todas")); await sleep(500);
      click(byText("button", "Abertas", stSeg)); await sleep(800);
      click(byText(".list-row", "Tarefa do Leonardo na Cifal")); await sleep(1200);
      await waitFor(() => byText(".doc", "endpoint de frete"), 6000);
      if ($(".doc script")) throw new Error("o HTML da descrição não foi limpo");
      await waitFor(() => byText(".cm", "Comentário de teste"), 3000);
      const ta = $(".reply textarea"); setInput(ta, "comentário do autoteste"); await sleep(200);
      click(byText(".reply button", "Comentar")); await sleep(1200);
      if (!posts.length || posts[0].text !== "comentário do autoteste") throw new Error("o comentário não foi enviado");
      await shot("x4-issue");
      const impl = byText("button", "Implementar com IA");
      if (!impl || impl.disabled) throw new Error("Implementar com IA indisponível");
      click(impl); await sleep(2000);
      if (!location.hash.startsWith("#/work/")) throw new Error("Implementar não levou ao projeto: " + location.hash);
      return "Todas=4, Leonardo=2 (Cifal + Dematec), sem responsável=1, atribuídas=1; gaveta com HTML limpo; comentário enviado; Implementar abriu o projeto";
    } finally { window.fetch = of; }
  });

  const ok = results.filter(r => r.ok).length;
  const vis1 = await native("selftest-native");
  await native("selftest-done", { result: JSON.stringify({ platform: window.CODECK_PLATFORM, ok, total: results.length, results, jsErrors, focusMisses,
    visible: { start: vis0?.visible, end: vis1?.visible } }, null, 1) });
})();
