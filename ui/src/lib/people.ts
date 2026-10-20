// A mesma pessoa em várias contas (Configurações → Contas → Pessoas): "Leonardo" = "Leonardo Thomaz" na Cifal e
// "leonardo.thomaz" na Dematec. O filtro de responsável junta todos os nomes dela. Compara sem maiúsculas/acentos,
// pelo nome, pelo login e pelo e-mail (inteiro ou só o que vem antes do @).
import { prefs } from "./prefs.svelte";

type Who = { login: string; email?: string };
const norm = (s: string) => (s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").trim().toLowerCase();
const idsOf = (w: Who) => [w.login, w.email || "", (w.email || "").split("@")[0]].map(norm).filter(Boolean);

export const people = (): Record<string, string[]> => (prefs.get("people") as Record<string, string[]>) || {};
/** A pessoa (nome dado em Configurações) a que este responsável pertence, ou null */
export function personOf(w: Who): string | null {
  const ids = idsOf(w);
  for (const [name, aliases] of Object.entries(people())) {
    if (aliases.map(norm).some(a => a && ids.includes(a))) return name;
  }
  return null;
}
/** O filtro de responsável: "" = qualquer um, "-" = sem responsável, "p:<pessoa>" ou "u:<nome>" */
export function matchesAssignee(assignees: Who[] | undefined, f: string) {
  const list = assignees || [];
  if (!f) return true;
  if (f === "-") return !list.length;
  if (f.startsWith("p:")) return list.some(w => personOf(w) === f.slice(2));
  const want = norm(f.slice(2));
  return list.some(w => idsOf(w).includes(want));
}
export function savePeople(next: Record<string, string[]>) {
  const clean = Object.fromEntries(Object.entries(next).map(([k, v]) => [k.trim().slice(0, 60), [...new Set(v.map(x => x.trim()).filter(Boolean))].slice(0, 8)])
    .filter(([k, v]) => k && (v as string[]).length));
  prefs.set("people", clean);
}
