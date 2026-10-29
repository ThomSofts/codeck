// Copiar texto para a área de transferência do sistema. A API da WebView recusa sem foco/gesto do usuário: aí vai pelo
// backend (pbcopy/clip) e, por último, pelo execCommand("copy") de um campo escondido (o mesmo caminho do FileTree).
import { post } from "./api";
import { ui } from "./ui.svelte";

export async function copyText(t: string, msg = "Copiado") {
  try { await navigator.clipboard.writeText(t); ui.toast(msg); return true; } catch { /* tenta o outro jeito */ }
  try { await post("ws/fs/clipboard", { text: t }, { quiet: true }); ui.toast(msg); return true; } catch { /* último recurso */ }
  const ta = document.createElement("textarea");
  ta.value = t; ta.setAttribute("readonly", ""); ta.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
  document.body.appendChild(ta); ta.select();
  const ok = (() => { try { return document.execCommand("copy"); } catch { return false; } })();
  ta.remove();
  if (ok) ui.toast(msg); else ui.toast("Não consegui copiar para a área de transferência", "error");
  return ok;
}

/** PR para colar no chat/e-mail: o título numa linha, o link na outra; várias, separadas por uma linha em branco. */
export const prLink = (p: { title: string; url: string }) => `${p.title}\n${p.url}`;
export const prLinks = (ps: { title: string; url: string }[]) => ps.map(prLink).join("\n\n");
