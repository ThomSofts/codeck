// Avisos por tipo (PR nova, release/deploy esperando, IA perguntando, IA em espera…): cada um com o aviso do sistema
// (Central de Notificações / Windows) e o som escolhidos em Configurações → Notificações. O backend decide e põe na
// fila (/api/notifications) já com `os` e `sound`; a tela lê a fila e toca o som. Espelha o ALERTS de backend/core.py.
import { get } from "./api";
import { prefs } from "./prefs.svelte";
import { router } from "./router.svelte";
import { play, type SoundId } from "./sounds";

export type AlertKind = "pr.pending" | "pr.mine" | "build.failed" | "deploy.waiting" | "cascade" | "auto"
  | "agent.question" | "agent.standby" | "agent.limit" | "ai.usage";
export type AlertPref = { os?: boolean; sound?: SoundId };

type Def = { kind: AlertKind; label: string; desc: string; sound: SoundId; legacy?: { rule?: string; pref?: string } };
export const ALERT_GROUPS: { label: string; items: Def[] }[] = [
  { label: "IA e agentes", items: [
    { kind: "agent.question", label: "IA fazendo uma pergunta", desc: "Pediu permissão ou abriu uma pergunta para você responder — o agente está parado esperando.", sound: "alerta", legacy: { pref: "notify.agentNeedsYou" } },
    { kind: "agent.standby", label: "IA em espera", desc: "Terminou o que estava fazendo e ficou em stand-by — pronto para revisar ou seguir.", sound: "gota", legacy: { pref: "notify.agentDone" } },
    { kind: "agent.limit", label: "Conta de IA no limite", desc: "O agente parou porque a conta atingiu o limite (dá para continuar em outra conta).", sound: "grave" },
    { kind: "ai.usage", label: "Limite perto do fim", desc: "A conta passou de 80% ou 95% da janela de 5 h ou da semanal.", sound: "none" },
  ] },
  { label: "PRs e revisões", items: [
    { kind: "pr.pending", label: "PR nova para você revisar", desc: "Chegou uma PR esperando o seu voto.", sound: "sino", legacy: { rule: "notifyPending" } },
    { kind: "pr.mine", label: "Problema nas minhas PRs", desc: "Conflito, build vermelho, voto de recusa ou espera nas PRs que você abriu.", sound: "toque", legacy: { rule: "notifyMyPrs" } },
    { kind: "auto", label: "O piloto agiu sozinho", desc: "Uma regra aprovou uma PR ou liberou um deploy.", sound: "none", legacy: { rule: "notifyAuto" } },
  ] },
  { label: "Builds, releases e deploys", items: [
    { kind: "deploy.waiting", label: "Release / deploy esperando você", desc: "Release, environment ou permissão de pipeline aguardando a sua aprovação.", sound: "acorde", legacy: { rule: "notifyDeploys" } },
    { kind: "build.failed", label: "Build falhou", desc: "Em branch protegida ou disparado por você.", sound: "grave", legacy: { rule: "notifyBuildFailures" } },
    { kind: "cascade", label: "PR acompanhada até o deploy", desc: "Cada passo: integrada, build passou ou falhou, deploy aguardando, concluído ou falhou.", sound: "toque", legacy: { rule: "notifyCascade" } },
  ] },
];
export const ALERT_DEFS = ALERT_GROUPS.flatMap(g => g.items);

/** O que vale para um tipo agora (o escolhido, senão o ajuste antigo e o som padrão). `rules` = settings das regras. */
export function alertOf(kind: AlertKind, rules?: Record<string, any> | null): { os: boolean; sound: SoundId } {
  const d = ALERT_DEFS.find(x => x.kind === kind)!;
  const mine = (prefs.get("alerts") as Record<string, AlertPref>)[kind] || {};
  let os = mine.os;
  if (os === undefined) os = d.legacy?.pref ? prefs.get(d.legacy.pref as any) !== false : d.legacy?.rule ? rules?.[d.legacy.rule] !== false : true;
  return { os: !!os, sound: mine.sound || d.sound };
}
export function setAlert(kind: AlertKind, patch: AlertPref) {
  const all = { ...(prefs.get("alerts") as Record<string, AlertPref>) };
  all[kind] = { ...all[kind], ...patch };
  prefs.set("alerts", all);
}

// importância do som quando vários avisos chegam juntos: toca só o mais importante
const RANK: AlertKind[] = ["agent.question", "deploy.waiting", "pr.pending", "agent.limit", "build.failed", "pr.mine", "cascade", "agent.standby", "ai.usage", "auto"];

/** Lê a fila de avisos do backend e toca o som de cada leva (só a janela principal — a de um projeto solto não). */
export function watchAlerts() {
  let seq: number | null = null, timer: ReturnType<typeof setTimeout> | undefined, stop = false;
  const tick = async () => {
    try {
      const r = await get<{ seq: number; items: { seq: number; kind?: AlertKind; sound?: string }[] }>("notifications", { after: seq ?? 1e12 });
      if (seq !== null && router.view !== "solo" && !prefs.get("alerts.mute")) {
        const best = r.items.filter(x => x.sound && x.sound !== "none" && x.sound !== "system")
          .sort((a, b) => rank(a.kind) - rank(b.kind))[0];
        if (best) play(best.sound!, prefs.get("alerts.volume"));
      }
      seq = r.seq;
    } catch { /* backend fora do ar: tenta na próxima */ }
    if (!stop) timer = setTimeout(tick, 2500);
  };
  const rank = (k?: AlertKind) => { const i = RANK.indexOf(k as AlertKind); return i < 0 ? 99 : i; };
  tick();
  return () => { stop = true; clearTimeout(timer); };
}
