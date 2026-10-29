// Sons dos avisos, sintetizados na hora (Web Audio): nada de arquivo de áudio no app, e cada som tem a sua cara —
// do mais discreto (gota, toque) ao que chama atenção (alerta). "system" é o som da própria notificação do sistema.
export type SoundId = "none" | "system" | "gota" | "toque" | "bolha" | "sino" | "acorde" | "alerta" | "grave";

export const SOUNDS: { id: SoundId; label: string; hint: string }[] = [
  { id: "none", label: "Sem som", hint: "mudo" },
  { id: "gota", label: "Gota", hint: "bem discreto" },
  { id: "toque", label: "Toque", hint: "curto e leve" },
  { id: "bolha", label: "Bolha", hint: "subindo, leve" },
  { id: "sino", label: "Sino", hint: "claro, com eco" },
  { id: "acorde", label: "Acorde", hint: "três notas" },
  { id: "alerta", label: "Alerta", hint: "chama atenção" },
  { id: "grave", label: "Grave", hint: "algo deu errado" },
  { id: "system", label: "Som do sistema", hint: "o da notificação" },
];

let ctx: AudioContext | null = null;
function audio() {
  if (!ctx) {
    const C = window.AudioContext || (window as any).webkitAudioContext;
    if (!C) return null;
    ctx = new C();
  }
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx;
}
// o navegador só libera o áudio depois de um gesto: o 1º clique/tecla deixa o contexto pronto para os avisos
if (typeof window !== "undefined") {
  const unlock = () => { audio(); window.removeEventListener("pointerdown", unlock); window.removeEventListener("keydown", unlock); };
  window.addEventListener("pointerdown", unlock);
  window.addEventListener("keydown", unlock);
}

/** Uma nota: frequência (ou deslize de f0 para f1), forma de onda, quando começa e quanto dura, volume relativo. */
function note(a: AudioContext, out: AudioNode, o: { f: number; f1?: number; type?: OscillatorType; at?: number; dur: number; vol?: number; attack?: number }) {
  const t = a.currentTime + (o.at || 0);
  const osc = a.createOscillator(), g = a.createGain();
  osc.type = o.type || "sine";
  osc.frequency.setValueAtTime(o.f, t);
  if (o.f1) osc.frequency.exponentialRampToValueAtTime(o.f1, t + o.dur * 0.6);
  const v = o.vol ?? 1, atk = o.attack ?? 0.006;
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(v, t + atk);
  g.gain.exponentialRampToValueAtTime(0.0001, t + o.dur);
  osc.connect(g).connect(out);
  osc.start(t);
  osc.stop(t + o.dur + 0.02);
}

/** Toca um som (0 ≤ volume ≤ 1). "none"/"system" não tocam nada aqui. */
export function play(id: SoundId | string, volume = 0.6) {
  if (id === "none" || id === "system" || volume <= 0) return;
  const a = audio();
  if (!a) return;
  const out = a.createGain();
  out.gain.value = Math.min(1, volume) * 0.32;   // o volume do app fica abaixo do volume do sistema: aviso, não susto
  out.connect(a.destination);
  switch (id) {
    case "gota": note(a, out, { f: 1320, f1: 620, dur: 0.22, vol: 0.8 }); break;
    case "toque": note(a, out, { f: 880, type: "triangle", dur: 0.14, vol: 0.7 }); note(a, out, { f: 1760, dur: 0.08, vol: 0.15 }); break;
    case "bolha": note(a, out, { f: 320, f1: 960, dur: 0.16, vol: 0.8 }); break;
    case "sino":
      note(a, out, { f: 1046.5, dur: 1.1, vol: 0.7 }); note(a, out, { f: 2093, dur: 0.6, vol: 0.18 }); note(a, out, { f: 1568, at: 0.11, dur: 0.9, vol: 0.4 });
      break;
    case "acorde": [523.25, 659.25, 783.99].forEach((f, i) => note(a, out, { f, at: i * 0.075, dur: 0.75 - i * 0.08, vol: 0.55 })); break;
    case "alerta":
      note(a, out, { f: 740, type: "triangle", dur: 0.16, vol: 0.85 }); note(a, out, { f: 988, type: "triangle", at: 0.17, dur: 0.24, vol: 0.85 });
      note(a, out, { f: 1976, at: 0.17, dur: 0.12, vol: 0.12 });
      break;
    case "grave": note(a, out, { f: 330, f1: 196, type: "triangle", dur: 0.5, vol: 0.8 }); note(a, out, { f: 165, dur: 0.45, vol: 0.4 }); break;
  }
  setTimeout(() => out.disconnect(), 1600);
}
