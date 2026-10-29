import { post } from "./api";
import { store } from "./store.svelte";
import type { DeployRule, Rule } from "./types";
import { ui } from "./ui.svelte";

export const esc = (s: unknown) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
const listText = (arr: string[]) => arr.map(x => `<b>${esc(x)}</b>`).join(" ou ");

export const ACTIONS = {
  approve: { icon: "⚡", label: "Aprovar automaticamente", short: "aprovar", verb: "aprovaria", done: "aprovações", cls: "good", desc: "Vota “Aprovado” assim que a PR aparece. Nunca sobrescreve um voto seu." },
  archive: { icon: "🗄", label: "Arquivar", short: "arquivar", verb: "arquivaria", done: "arquivadas", cls: "neutral", desc: "Tira da fila e ignora — bom para bots e PRs que não são com você." },
  notify: { icon: "🔔", label: "Só me notificar", short: "notificar", verb: "notificaria", done: "avisos", cls: "accent", desc: "Notificação quando chegar, sem votar." },
  review: { icon: "🤖", label: "Revisar com IA", short: "revisar com IA", verb: "revisaria", done: "revisões", cls: "accent",
    desc: "A IA lê a PR: tudo certo → aprova; senão → “Aguardando autor” com cada ponto comentado na linha. Nunca recusa." },
} as const;

export const DACTIONS = {
  release: {
    approve: { icon: "⚡", label: "Aprovar automaticamente", desc: "Aprova o deploy assim que ele chega no estágio/environment.", verb: "aprovaria" },
    notify: { icon: "🔔", label: "Só me notificar", desc: "Notificação quando o deploy chegar, sem aprovar.", verb: "notificaria" },
  },
  permission: {
    approve: { icon: "⚡", label: "Liberar automaticamente", desc: "Dá a permissão (Permit) e o run continua sozinho.", verb: "liberaria" },
    notify: { icon: "🔔", label: "Só me notificar", desc: "Notificação quando um pipeline travar pedindo permissão.", verb: "notificaria" },
  },
} as const;

export const TEMPLATES: { label: string; rule: Partial<Rule> }[] = [
  { label: "Aprovar tudo de uma pessoa (menos produção)", rule: { action: "approve" } },
  { label: "Revisar com IA as PRs de uma pessoa (aprova se estiver tudo certo)", rule: { action: "review", aiApprove: true } },
  { label: "Aprovar PRs para develop de qualquer pessoa", rule: { action: "approve", targets: ["develop"] } },
  { label: "Me avisar quando chegar PR para master/main", rule: { action: "notify", targets: ["master", "main"] } },
  { label: "Arquivar PRs de bots (dependabot, build service)", rule: { action: "archive", creators: ["dependabot", "Build Service", "Project Collection"] } },
];
export const DTEMPLATES: { label: string; rule: Partial<DeployRule> }[] = [
  { label: "Aprovar Prod quando eu já aprovei a PR de origem", rule: { kind: "release", action: "approve", stages: ["Prod"], branches: ["master", "main"], requirePrApproved: true } },
  { label: "Aprovar tudo que não é produção (Dev/Homolog)", rule: { kind: "release", action: "approve", stages: ["Dev"] } },
  { label: "Liberar permissões de grupos de variáveis", rule: { kind: "permission", action: "approve" } },
  { label: "Me avisar de deploy para produção", rule: { kind: "release", action: "notify", stages: ["Prod", "production"] } },
];

export const blankRule = (over: Partial<Rule> = {}): Rule => ({ id: "", name: "", enabled: true, action: "approve", orgs: [], creators: [], targets: [], repos: [],
  titleContains: "", requireBuild: false, aiAccount: null, aiApprove: true, aiFocus: "", aiMine: false, ...JSON.parse(JSON.stringify(over)) });
export const blankDRule = (over: Partial<DeployRule> = {}): DeployRule => ({ id: "", name: "", enabled: true, kind: "release", action: "approve", orgs: [],
  pipelines: [], stages: [], branches: [], resources: [], requirePrApproved: false, ...JSON.parse(JSON.stringify(over)) });

export function ruleSentence(r: Rule): string {
  const prot = store.s?.rules.protectedTargets || [];
  const who = r.creators.length ? listText(r.creators) : "<b>qualquer pessoa</b>";
  const where = r.targets.length ? listText(r.targets) : `<b>qualquer branch</b>${prot.length ? ` <span class="muted">(menos ${prot.map(esc).join(", ")})</span>` : ""}`;
  const orgs = r.orgs.length ? ` em ${listText(r.orgs)}` : "";
  const repos = r.repos.length ? `, no repositório ${listText(r.repos)}` : "";
  const title = r.titleContains ? `, com “<b>${esc(r.titleContains)}</b>” no título` : "";
  return `Quando ${who} abrir PR para ${where}${orgs}${repos}${title}`;
}

export function dRuleSentence(r: DeployRule): string {
  const pipes = r.pipelines.length ? listText(r.pipelines) : "<b>qualquer pipeline</b>";
  const orgs = r.orgs.length ? ` em ${listText(r.orgs)}` : "";
  if (r.kind === "permission") return `Quando ${pipes} travar pedindo permissão para ${r.resources.length ? listText(r.resources) : "<b>qualquer recurso</b>"}${orgs}`;
  return `Quando o deploy de ${pipes} chegar em ${r.stages.length ? listText(r.stages) : "<b>qualquer estágio</b>"}`
    + `${r.branches.length ? `, vindo de ${listText(r.branches)}` : ""}${orgs}${r.requirePrApproved ? ", <b>se você já aprovou a PR de origem</b>" : ""}`;
}

export async function saveRules(patch: { rules?: Rule[]; deployRules?: DeployRule[]; protectedTargets?: string[]; settings?: Record<string, boolean> }, msg = "Regras salvas — aplicando agora") {
  const cur = store.s!.rules;
  try {
    await post("rules", { settings: patch.settings ?? cur.settings, protectedTargets: patch.protectedTargets ?? cur.protectedTargets,
      rules: patch.rules ?? cur.rules, deployRules: patch.deployRules ?? cur.deployRules });
    ui.toast(msg);
    await store.load();
    store.refreshSoon(4000);
    return true;
  } catch (e) { ui.error(e); return false; }
}
