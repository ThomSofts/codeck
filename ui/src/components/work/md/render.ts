// Markdown → HTML seguro. O conteúdo vem do repositório (não confiável) e a janela guarda a chave da API local:
// tudo passa pelo DOMPurify, sem script, handler, iframe, formulário nem atributo style; de input, só checkbox.
import DOMPurify from "dompurify";
import { Marked } from "marked";

const md = new Marked({ gfm: true, breaks: false });

let hooked = false;
function hook() {
  if (hooked) return;
  hooked = true;
  DOMPurify.addHook("uponSanitizeElement", (node, data) => {
    if (data.tagName === "input" && (node as Element).getAttribute?.("type") !== "checkbox") node.parentNode?.removeChild(node);
  });
  DOMPurify.addHook("afterSanitizeAttributes", node => {
    if (node.tagName === "A") {
      const href = node.getAttribute("href") || "";
      // com esquema, só http(s) e e-mail (file:, smb:, ms-*: e outros abririam programas); sem esquema = link relativo
      const scheme = /^\s*([a-z][a-z0-9+.-]*):/i.exec(href)?.[1].toLowerCase();
      if (scheme && !["http", "https", "mailto"].includes(scheme)) node.removeAttribute("href");
    }
    if (node.tagName === "IMG") node.setAttribute("referrerpolicy", "no-referrer");   // imagem externa não sabe de onde veio
  });
}

export function renderMarkdown(src: string) {
  hook();
  const html = md.parse(src, { async: false }) as string;
  return DOMPurify.sanitize(html, {
    FORBID_TAGS: ["style", "form", "iframe", "object", "embed", "button", "textarea", "select", "option", "frame", "frameset", "base", "link", "meta", "svg", "math"],
    FORBID_ATTR: ["style", "srcset", "action", "formaction", "background", "ping"],
    ALLOW_DATA_ATTR: false,
  });
}

export const slug = (t: string) => t.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").trim()
  .replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s+/g, "-");

/** Itens de lista de tarefas no código: a N-ésima linha daqui é a N-ésima checkbox renderizada.
 *  Ignora blocos cercados (``` e ~~~) e código indentado (4+ espaços fora de uma lista). */
export interface TaskLine { line: number; col: number; done: boolean }
const TASK = /^((?:\s*>)*\s*(?:[-*+]|\d+[.)])\s+)\[( |x|X)\](?=[ \t]+\S)/;
const ITEM = /^(?:\s*>)*\s*(?:[-*+]|\d+[.)])(\s|$)/;
export function scanTasks(src: string): TaskLine[] {
  const out: TaskLine[] = [];
  let fence: string | null = null, inList = false, prevBlank = true;
  const lines = src.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    const f = l.match(/^\s{0,3}(`{3,}|~{3,})/);
    if (fence) { if (f && f[1][0] === fence[0] && f[1].length >= fence.length && !l.trim().slice(f[1].length).trim()) fence = null; continue; }
    if (f) { fence = f[1]; if (!/^\s/.test(l)) inList = false; continue; }
    if (!l.trim()) { prevBlank = true; continue; }
    const indented = /^( {4,}|\t)/.test(l);
    if (indented && !inList && prevBlank) { prevBlank = false; continue; }   // código indentado
    if (ITEM.test(l)) inList = true;
    else if (!indented && prevBlank) inList = false;
    prevBlank = false;
    const m = l.match(TASK);
    if (m) out.push({ line: i + 1, col: m[1].length + 2, done: m[2] !== " " });
  }
  return out;
}

/** HTML de fora (descrição/comentário de work item do Azure) → HTML seguro, com as mesmas regras do Markdown. */
export function safeHtml(html: string) {
  hook();
  return DOMPurify.sanitize(html || "", {
    FORBID_TAGS: ["style", "form", "iframe", "object", "embed", "button", "textarea", "select", "option", "frame", "frameset", "base", "link", "meta", "svg", "math", "input"],
    FORBID_ATTR: ["style", "srcset", "action", "formaction", "background", "ping"],
    ALLOW_DATA_ATTR: false,
  });
}

/** HTML → texto (para mandar a descrição do work item ao agente). */
export function htmlText(html: string) {
  const d = document.createElement("div");
  d.innerHTML = safeHtml(html.replace(/<br\s*\/?>/gi, "\n").replace(/<\/(p|div|li|h\d|tr)>/gi, "$&\n"));
  return (d.textContent || "").replace(/ /g, " ").replace(/\n{3,}/g, "\n\n").trim();
}
