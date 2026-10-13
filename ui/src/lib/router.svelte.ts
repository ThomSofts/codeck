import { tick } from "svelte";

// Rotas por hash: #/inbox, #/prs/review, #/repo/<id>, #/settings/github …
export const NAV_ORDER = ["projects", "work", "board", "ai", "inbox", "prs", "builds", "deploys", "issues", "repos", "repo", "automation", "analytics", "history", "settings"];

class Router {
  path = $state(normalize(location.hash));
  get parts() { return this.path.split("/").filter(Boolean); }
  get view() { return this.parts[0] || "inbox"; }
  get param() { return this.parts.slice(1).join("/") ? decodeURIComponent(this.parts.slice(1).join("/")) : ""; }
}

function normalize(hash: string) {
  const p = hash.replace(/^#/, "");
  return p.startsWith("/") ? p : "/inbox";
}

export const router = new Router();

// Sem transição com a janela escondida/minimizada: o navegador pula e rejeita a promessa (era erro solto no app)
const canVT = () => !!(document as any).startViewTransition && document.visibilityState === "visible" && !matchMedia("(prefers-reduced-motion: reduce)").matches;
const quiet = (t: any) => { for (const p of [t?.ready, t?.finished, t?.updateCallbackDone]) p?.catch?.(() => {}); return t; };

/** Troca de tela com View Transition: a tela antiga sai e a nova entra no sentido do menu. */
export function go(path: string, kind?: "down" | "up" | "soft") {
  if (path === router.path) return;
  const next = normalize("#" + path);
  const from = NAV_ORDER.indexOf(router.view), to = NAV_ORDER.indexOf(next.split("/")[1] || "inbox");
  const dir = kind ?? (from === to ? "soft" : to >= from ? "down" : "up");
  const apply = async () => {
    router.path = next;
    history.replaceState(null, "", "#" + next);
    await tick();
  };
  if (!canVT()) { apply(); return; }
  document.documentElement.dataset.vt = dir;
  const t = quiet((document as any).startViewTransition(apply));
  t.finished.finally(() => { if (document.documentElement.dataset.vt === dir) delete document.documentElement.dataset.vt; });
}

/** Mesma tela, conteúdo diferente (filtro, aba): só um crossfade. */
export function soft(update: () => void | Promise<void>) {
  if (!canVT()) { update(); return; }
  document.documentElement.dataset.vt = "soft";
  const t = quiet((document as any).startViewTransition(async () => { await update(); await tick(); }));
  t.finished.finally(() => delete document.documentElement.dataset.vt);
}

window.addEventListener("hashchange", () => {
  const p = normalize(location.hash);
  if (p !== router.path) router.path = p;
});
