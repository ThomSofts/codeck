// Autoteste do EXPLORADOR no app de desktop (SCRIPT=tests/desktop/selftest-explorer.js scripts/test-desktop.sh): novo
// arquivo/pasta, renomear (F2 e menu), copiar/recortar/colar com as teclas reais (⌘C/⌘X/⌘V — Ctrl no Windows),
// duplicar, arrastar para mover (e com ⌥/Ctrl copiar), soltar arquivo "de fora", excluir (Lixeira) e as abas acompanhando.
// Roda dentro da janela real (WKWebView no macOS, WebView2 no Windows); teclas são eventos REAIS do sistema.
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
  const txt = el => (el?.innerText || el?.textContent || "").replace(/ /g, " ").trim();
  const byText = (sel, t, root = document) => $$(sel, root).find(e => txt(e).toLowerCase().includes(t.toLowerCase()));
  async function waitFor(fn, ms = 8000, step = 100) {
    const end = Date.now() + ms;
    while (Date.now() < end) { const v = typeof fn === "string" ? $(fn) : fn(); if (v) return v; await sleep(step); }
    throw new Error("não apareceu: " + (typeof fn === "string" ? fn : fn.toString().slice(0, 90)));
  }
  function click(el, mods = {}) {
    if (!el) throw new Error("elemento não encontrado para clicar");
    const r = el.getBoundingClientRect(), o = { bubbles: true, cancelable: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2, button: 0, view: window, ...mods };
    el.dispatchEvent(new PointerEvent("pointerdown", o)); el.dispatchEvent(new MouseEvent("mousedown", o));
    // o clique de verdade foca o que tem tabindex (a lista do explorador)
    el.closest("[tabindex]")?.focus({ preventScroll: true });
    el.dispatchEvent(new PointerEvent("pointerup", o)); el.dispatchEvent(new MouseEvent("mouseup", o));
    el.dispatchEvent(new MouseEvent("click", o));
  }
  function rightClick(el) {
    const r = el.getBoundingClientRect();
    el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 2, clientX: r.x + 20, clientY: r.y + r.height / 2, view: window }));
    el.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: r.x + 20, clientY: r.y + r.height / 2, button: 2, view: window }));
  }
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
  const MK = { a: 0, s: 1, d: 2, f: 3, h: 4, g: 5, z: 6, x: 7, c: 8, v: 9, b: 11, q: 12, w: 13, e: 14, r: 15, y: 16, t: 17, o: 31, u: 32, i: 34, p: 35, l: 37,
    j: 38, k: 40, n: 45, m: 46, ".": 47, " ": 49, "-": 27, "1": 18, "2": 19, "3": 20 };
  const SPECIAL = MAC
    ? { Enter: { c: "\r", k: 36 }, Escape: { c: "\u001b", k: 53 }, Backspace: { c: "\u007f", k: 51 }, Delete: { c: "", k: 117 }, F2: { c: "", k: 120 },
        ArrowUp: { c: "", k: 126 }, ArrowDown: { c: "", k: 125 } }
    : { Enter: { c: "\r", k: 13 }, Escape: { c: "\u001b", k: 27 }, Backspace: { c: "\b", k: 8 }, Delete: { c: "", k: 46 }, F2: { c: "", k: 113 },
        ArrowUp: { c: "", k: 38 }, ArrowDown: { c: "", k: 40 } };
  function keyOf(ch, mods = "") {
    if (SPECIAL[ch]) return { ...SPECIAL[ch], i: SPECIAL[ch].c, m: mods, n: ch };
    if (!MAC) { const up = ch.toUpperCase(); return { c: ch, k: /^[A-Z0-9]$/.test(up) ? up.charCodeAt(0) : 0, m: mods, n: ch }; }
    const low = ch.toLowerCase();
    return { c: ch, i: low, k: MK[low] ?? 0, m: (ch !== low ? "shift," : "") + mods };
  }
  // a janela do autoteste pode ficar sem foco/oculta (o sistema não entrega teclas reais nem roda requestAnimationFrame):
  // SYNTH=1 no contexto, ou sem foco, as teclas viram eventos do DOM no elemento em foco (testa a lógica da tela)
  const CODES = { Enter: "Enter", Escape: "Escape", Backspace: "Backspace", Delete: "Delete", F2: "F2", ArrowUp: "ArrowUp", ArrowDown: "ArrowDown" };
  const synth = () => CTX.synth || !document.hasFocus();
  function domKey(name, mods = "") {
    const t = document.activeElement || document.body;
    const o = { key: name, code: CODES[name] || (/^[a-z]$/i.test(name) ? "Key" + name.toUpperCase() : ""), bubbles: true, cancelable: true,
      metaKey: mods.includes("cmd"), ctrlKey: mods.includes("ctrl"), shiftKey: mods.includes("shift"), altKey: mods.includes("alt") };
    const down = new KeyboardEvent("keydown", o);
    t.dispatchEvent(down);
    t.dispatchEvent(new KeyboardEvent("keyup", o));
    return down;
  }
  const type = async (text) => {
    if (!synth()) return native("selftest-keys", { keys: [...text].map(c => keyOf(c)) });
    const el = document.activeElement;
    if (!el || el.tagName !== "INPUT") throw new Error("digitar: nada em foco para receber o texto (" + el?.tagName + ")");
    const v = el.value.slice(0, el.selectionStart ?? el.value.length) + text + el.value.slice(el.selectionEnd ?? el.value.length);
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, v);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const press = async (name, mods = "") => { if (!synth()) return native("selftest-keys", { keys: [keyOf(name, mods)] }); domKey(name, mods); };
  const shot = (name) => native("selftest-shot", { name });
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
    for (let i = 0; i < 2; i++) { if ($("[role=alertdialog]") || $(".items[role=menu]")) await press("Escape"); }
  }

  await native("selftest-focus");
  await sleep(800);
  const fx = CTX.fixture;
  let repo = null;
  const row = (p) => $(`.ft .n[data-p="${CSS.escape(p)}"]`);
  const rowW = (p, ms = 6000) => waitFor(() => row(p), ms);
  const exists = async (p) => { try { await api("ws/file?repoId=" + repo.id + "&path=" + encodeURIComponent(p)); return true; } catch { return false; } };
  const listing = async () => (await api("ws/files?repoId=" + repo.id)).files;
  const menuItem = (label) => waitFor(() => $$(".items[role=menu] .it").find(b => txt(b.querySelector(".lbl")) === label), 3000);
  const ren = () => $(".ft input.ren");
  async function confirmDialog() {
    const d = await waitFor("[role=alertdialog]", 4000);
    const btns = $$("button", d);
    click(btns[btns.length - 1]); await sleep(900);
  }

  await step("Abrir o projeto de teste", async () => {
    repo = await api("repos/add", { path: fx + "/demo-api" });
    await api("ws/open", { repoId: repo.id }).catch(() => api("ws/open", { id: repo.id }));
    await go("#/work/" + repo.id, 2500);
    await rowW("a.txt", 10000);
  });

  await step("Novo arquivo pelo botão (digitando de verdade + Enter)", async () => {
    click($(".ft .bar button[title='Novo arquivo']"));
    const i = await waitFor(ren, 3000); await sleep(300);
    if (document.activeElement !== i) throw new Error("o campo de nome não ficou em foco: " + document.activeElement?.tagName + "." + document.activeElement?.className + " · " + document.visibilityState);
    await type("novo.txt"); await press("Enter"); await sleep(1500);
    if (!(await exists("novo.txt"))) throw new Error("novo.txt não foi criado");
    await rowW("novo.txt");
    return "criado";
  });

  await step("Nova pasta pelo botão", async () => {
    click(row("a.txt"));
    click($(".ft .bar button[title='Nova pasta']"));
    await waitFor(ren, 3000); await sleep(300);
    await type("pasta"); await press("Enter"); await sleep(1500);
    await rowW("pasta/");
  });

  await step("Renomear com F2 (teclas reais)", async () => {
    click(await rowW("novo.txt")); await sleep(300);
    await press("F2"); const i = await waitFor(ren, 3000); await sleep(300);
    if (document.activeElement !== i) throw new Error("F2: campo sem foco");
    await type("renomeado"); await press("Enter"); await sleep(1500);
    if (!(await exists("renomeado.txt"))) throw new Error("não renomeou: " + (await listing()).join(","));
    await rowW("renomeado.txt");
  });

  await step("Renomear pelo menu de contexto", async () => {
    rightClick(await rowW("renomeado.txt")); await sleep(300);
    click(await menuItem("Renomear…")); await sleep(500);
    const i = await waitFor(ren, 3000); await sleep(300);
    if (document.activeElement !== i) throw new Error("menu: campo sem foco (" + document.activeElement?.tagName + "." + document.activeElement?.className + ")");
    await type("pelo-menu"); await press("Enter"); await sleep(1500);
    if (!(await exists("pelo-menu.txt"))) throw new Error("não renomeou pelo menu: " + (await listing()).join(","));
  });

  await step("Copiar e colar com ⌘C/⌘V (teclas reais) — vira 'copy'", async () => {
    click(await rowW("a.txt")); await sleep(200);
    await press("c", MOD); await sleep(300);
    await press("v", MOD); await sleep(1500);
    if (!(await exists("a copy.txt"))) throw new Error("não colou: " + (await listing()).join(","));
  });

  await step("Recortar e colar numa pasta com ⌘X/⌘V", async () => {
    click(await rowW("a copy.txt")); await sleep(200);
    await press("x", MOD); await sleep(300);
    click(await rowW("pasta/")); await sleep(300);
    await press("v", MOD); await sleep(1500);
    if (!(await exists("pasta/a copy.txt")) || (await exists("a copy.txt"))) throw new Error("não moveu: " + (await listing()).join(","));
  });

  await step("Copiar pelo menu e colar com a tecla", async () => {
    rightClick(await rowW("pelo-menu.txt")); await sleep(300);
    click(await menuItem("Copiar")); await sleep(300);
    await press("v", MOD); await sleep(1500);
    if (!(await exists("pelo-menu copy.txt"))) throw new Error("⌘V depois do menu não colou (foco: " + document.activeElement?.tagName + "." + document.activeElement?.className + ")");
  });

  await step("Duplicar pelo menu", async () => {
    rightClick(await rowW("util.ts")); await sleep(300);
    click(await menuItem("Duplicar")); await sleep(1500);
    if (!(await exists("util copy.ts"))) throw new Error("não duplicou");
  });

  await step("Arrastar para mover para a pasta (aba aberta acompanha)", async () => {
    const r = await rowW("util copy.ts");
    click(r); r.dispatchEvent(new MouseEvent("dblclick", { bubbles: true })); await sleep(1200);
    const dt = new DataTransfer();
    const target = await rowW("pasta/");
    r.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer: dt }));
    await sleep(50);
    const abs = dt.getData("application/x-codeck-paths");
    for (let i = 0; i < 3; i++) { target.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer: dt })); await sleep(60); }
    target.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt }));
    r.dispatchEvent(new DragEvent("dragend", { bubbles: true, dataTransfer: dt }));
    await sleep(1800);
    if (!(await exists("pasta/util copy.ts"))) throw new Error("não moveu arrastando: " + (await listing()).join(","));
    const tab = byText(".tab", "util copy.ts");
    if (!tab) throw new Error("a aba fechou em vez de acompanhar");
    if (!/^\[".*util copy\.ts"\]$/.test(abs) || !abs.includes("/")) throw new Error("dados do arrasto sem caminho absoluto: " + abs);
    return "aba seguiu · " + abs;
  });

  await step("Soltar arquivo de fora (Finder/Explorer) na pasta", async () => {
    const dt = new DataTransfer();
    dt.items.add(new File([new Uint8Array(3 * 1024 * 1024).fill(65)], "grande.bin"));
    const target = await rowW("pasta/");
    for (let i = 0; i < 2; i++) { target.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer: dt })); await sleep(60); }
    const dz = target.classList.contains("dz") || $(".ft .list.dz") ? "destaque ok" : "SEM destaque";
    let entry = "?"; try { entry = String(dt.items[0].webkitGetAsEntry?.()); } catch (e) { entry = "erro " + e.message; }
    target.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt }));
    window.__dbg = dz + " · entry " + entry;
    const end = Date.now() + 10000; let ok = false;
    while (Date.now() < end) { if ((await listing()).includes("pasta/grande.bin")) { ok = true; break; } await sleep(300); }
    if (!ok) throw new Error("o arquivo de fora não chegou · avisos: " + $$("[class*=toast]").map(txt).join(" | ") + " · tipos: " + [...dt.types].join(",") + " · " + window.__dbg + " · " + window.__ftdbg);
  });

  await step("Excluir com a tecla (vai para a Lixeira) e a aba fecha", async () => {
    const r = await rowW("pelo-menu.txt");
    click(r); r.dispatchEvent(new MouseEvent("dblclick", { bubbles: true })); await sleep(1000);
    click(await rowW("pelo-menu.txt")); await sleep(200);
    if (MAC) await press("Backspace", MOD); else await press("Delete");
    await confirmDialog();
    if (await exists("pelo-menu.txt")) throw new Error("não excluiu");
    if (byText(".tab", "pelo-menu.txt")) throw new Error("a aba do arquivo excluído ficou aberta");
  });

  await step("Seleção múltipla (⇧-clique) e recortar/colar as duas na pasta, depois ⌘Z desfaz", async () => {
    click(await rowW("main.ts"));
    click(await rowW("package.json"), { shiftKey: true }); await sleep(200);
    const n = $$(".ft .n.sel").length;
    if (n < 2) throw new Error("⇧-clique não selecionou: " + n);
    await press("x", MOD); await sleep(200);
    click(await rowW("pasta/")); await sleep(200);
    await press("v", MOD); await sleep(1800);
    if (!(await exists("pasta/main.ts")) || !(await exists("pasta/package.json"))) throw new Error("não moveu os selecionados: " + (await listing()).join(","));
    await press("z", MOD); await sleep(1800);
    if (!(await exists("main.ts")) || !(await exists("package.json"))) throw new Error("⌘Z não desfez: " + (await listing()).join(","));
    return n + " selecionados, movidos e de volta";
  });

  await step("Copiar caminho relativo pelo menu", async () => {
    rightClick(await rowW("a.txt")); await sleep(300);
    click(await menuItem("Copiar caminho relativo")); await sleep(500);
    const t = $$(".toast").map(txt).join(" | ");
    if (!/Caminho relativo copiado/.test(t)) throw new Error("não copiou: " + t);
    return t;
  });

  await shot("explorador");
  results.push({ name: "modo das teclas", ok: true, ms: 0, detail: synth() ? "eventos do DOM (janela sem foco)" : "teclas reais do sistema" });
  const ok = results.filter(r => r.ok).length;
  await native("selftest-done", { result: JSON.stringify({ platform: window.CODECK_PLATFORM, ok, total: results.length, results, jsErrors }, null, 1) });
})();
