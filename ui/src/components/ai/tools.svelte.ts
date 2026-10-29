// Skills e MCPs: os tipos do inventário (backend aitools.py), o nome de cada lugar e as ações de levar/remover —
// com as perguntas certas no caminho (segredo indo para o Git, já existe no destino, remover guarda cópia).
import { post } from "../../lib/api";
import { ui } from "../../lib/ui.svelte";
import { accColor } from "./limits.svelte";

export type LocKind = "project" | "account" | "local";
export interface Loc {
  id: string; kind: LocKind; provider: string; accountId?: string; name?: string; color?: string | null; group?: string | null;
  caps: { skill: boolean; mcp: boolean }; files?: { skill?: string; mcp?: string }; shared?: boolean; error?: string;
}
export interface Entry {
  loc: string; hash: string;
  desc?: string; version?: string | null; path?: string; link?: string | null; files?: number; readonly?: boolean; synced?: boolean; invocable?: boolean;
  transport?: string; command?: string | null; url?: string | null; env?: string[]; headers?: string[]; secrets?: string[]; disabled?: boolean;
}
export interface Item { key: string; type: "skill" | "mcp"; name: string; entries: Entry[]; desc?: string | null; same: boolean; readonly: boolean; transport?: string }
export interface Inv {
  project: { id: string; name: string; path: string; tracked: Record<string, boolean | null> } | null;
  locations: Loc[]; items: Item[];
}

export const PROV: Record<string, string> = { claude: "Claude", codex: "Codex", cursor: "Cursor", gemini: "Gemini" };

export function locLabel(l: Loc | undefined | null): string {
  if (!l) return "?";
  if (l.kind === "project") return l.provider === "claude" ? "Projeto" : `Projeto · ${PROV[l.provider] || l.provider}`;
  const n = l.name && l.name !== "padrão" ? l.name : PROV[l.provider] || l.provider;
  return l.kind === "local" ? `${n} · só neste projeto` : n;
}
export const locColor = (l: Loc | undefined | null) => (!l ? "var(--muted)" : l.kind === "project" ? "var(--accent)" : accColor({ id: l.accountId!, color: l.color }));
export const can = (l: Loc, t: Item["type"]) => (t === "skill" ? l.caps.skill : l.caps.mcp);

/** A melhor origem para levar o item até `dst`: a da mesma família, senão a versão que mais aparece. */
export function bestSource(it: Item, locs: Map<string, Loc>, prefer: string[] = []): Entry {
  for (const id of prefer) { const e = it.entries.find(x => x.loc === id); if (e) return e; }
  const count = new Map<string, number>();
  for (const e of it.entries) count.set(e.hash, (count.get(e.hash) || 0) + 1);
  return [...it.entries].sort((a, b) => (count.get(b.hash)! - count.get(a.hash)!) || (locs.get(a.loc)?.kind === "project" ? -1 : 1))[0];
}

type CopyRes = { ok: boolean; exists?: boolean; error?: string; how?: string; path?: string; vars?: string[] };

/** Leva um item de `src` para `dst`. Pergunta quando o MCP tem segredo e vai para o projeto (Git) e quando já existe. */
export async function copyItem(repoId: string | null, it: Item, src: Entry, dst: Loc, opts: { quiet?: boolean; overwrite?: boolean; projectTracked?: boolean } = {}): Promise<boolean> {
  let envRefs = false;
  if (it.type === "mcp" && dst.kind === "project" && src.secrets?.length) {
    const r = await ui.ask({
      title: `“${it.name}” tem segredo`,
      message: `${dst.files?.mcp || ".mcp.json"} ${opts.projectTracked === false ? "está fora do Git, mas é do projeto" : "vai para o Git"} — quem clonar vê o valor. Melhor gravar como variável de ambiente.`,
      detail: [`Segredos: ${src.secrets.join(", ")}`],
      confirm: "Gravar como ${VARIÁVEL}", alt: "Copiar com os valores", cancel: "Cancelar",
    });
    if (!r) return false;
    envRefs = r !== "alt";
  }
  const body = { repoId, type: it.type, name: it.name, from: src.loc, to: dst.id, overwrite: !!opts.overwrite, envRefs };
  try {
    let res = await post<CopyRes>("ai/tools/copy", body);
    if (res.exists) {
      const ok = opts.overwrite === false ? false : await ui.ask({ title: `Substituir “${it.name}” em ${locLabel(dst)}?`, message: "A versão de lá vai para a lixeira do Codeck (dá para recuperar).", confirm: "Substituir" });
      if (!ok) return false;
      res = await post<CopyRes>("ai/tools/copy", { ...body, overwrite: true });
    }
    if (!opts.quiet) {
      const extra = res.vars?.length ? ` · defina ${res.vars.join(", ")} no ambiente` : res.how === "link" ? " · como link (ficam em sincronia)" : "";
      ui.toast(`${it.type === "skill" ? "Skill" : "MCP"} “${it.name}” em ${locLabel(dst)}${extra}`, res.vars?.length ? "info" : "ok");
    }
    return true;
  } catch (e) { ui.error(e); return false; }
}

export async function removeItem(repoId: string | null, it: Item, l: Loc): Promise<boolean> {
  const ok = await ui.ask({
    title: `Remover “${it.name}” de ${locLabel(l)}?`, danger: true, confirm: "Remover",
    message: it.type === "skill" ? "A pasta da skill vai para a lixeira do Codeck — nada é apagado de vez." : "A configuração do MCP fica guardada na lixeira do Codeck.",
  });
  if (!ok) return false;
  try { await post("ai/tools/remove", { repoId, type: it.type, name: it.name, loc: l.id }); ui.toast(`Removido de ${locLabel(l)}`); return true; }
  catch (e) { ui.error(e); return false; }
}
