// Tema: "system" segue o sistema operacional; "dark"/"light" fixam. O CSS só conhece o tema RESOLVIDO (data-theme no <html>).
// A escolha vive no config.json (preferência); o localStorage é só um espelho para aplicar o tema antes do 1º /api/state.
import { send } from "./native";

export type ThemePref = "system" | "dark" | "light";
const KEY = "codeck.theme";
const mq = window.matchMedia("(prefers-color-scheme: light)");
let pref: ThemePref = "system";

function read(): ThemePref {
  try { const v = localStorage.getItem(KEY); if (v === "dark" || v === "light" || v === "system") return v; } catch { /* armazenamento indisponível */ }
  return "system";
}

/** tema de cores de uma extensão pintando o app: ele decide se é claro ou escuro (ver lib/extensions) */
let forced: "dark" | "light" | null = null;
const resolved = () => forced || (pref === "system" ? (mq.matches ? "light" : "dark") : pref);
export function forceTheme(t: "dark" | "light" | null) {
  if (t === forced) return;
  forced = t;
  paint(true);
}

function paint(animate: boolean) {
  const t = resolved();
  const root = document.documentElement;
  if (root.dataset.theme === t) return;
  const apply = () => { root.dataset.theme = t; };
  // troca com crossfade quando o navegador tem View Transitions (WebKit atual e WebView2); senão, troca direto
  const doc = document as any;
  if (animate && doc.startViewTransition && document.visibilityState === "visible" && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    root.dataset.vt = "theme";
    const t = doc.startViewTransition(apply);
    t.ready?.catch(() => {});
    t.finished.catch(() => {}).finally(() => { if (root.dataset.vt === "theme") delete root.dataset.vt; });
  } else apply();
  send({ type: "theme", mode: t }); // barra de título nativa acompanha
}

export function initTheme() {
  pref = read();
  paint(false);
  mq.addEventListener("change", () => pref === "system" && paint(true));
}

export function setTheme(p: ThemePref, animate = true) {
  if (!p || p === pref) return;
  pref = p;
  try { localStorage.setItem(KEY, p); } catch { /* armazenamento indisponível */ }
  paint(animate);
}

let userAt = 0;
/** Escolha feita na tela agora: vale na hora, mesmo que um /api/state já em voo ainda traga a preferência anterior. */
export function chooseTheme(p: ThemePref) {
  userAt = Date.now();
  setTheme(p);
}
/** Preferência vinda do backend (config.json) — ignorada por alguns segundos depois de uma escolha na tela. */
export function syncTheme(p: ThemePref) {
  if (Date.now() - userAt > 5000) setTheme(p || "system");
}
