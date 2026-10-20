// Ferramentas do Flutter (como as do Dart/Flutter no VS Code): as páginas do DevTools e as chaves que o app expõe
// por extensões de serviço (debug paint, overlay de performance, animações lentas…). Usadas pela RunBar (menu) e pela
// visão Executar e depurar.
import { debug, type Session } from "./debug.svelte";
import { ui } from "./ui.svelte";

export const DEVTOOLS_PAGES: { page: string; label: string }[] = [
  { page: "inspector", label: "Inspetor de widgets" },
  { page: "performance", label: "Performance" },
  { page: "cpu-profiler", label: "CPU" },
  { page: "memory", label: "Memória" },
  { page: "network", label: "Rede" },
  { page: "logging", label: "Logs" },
  { page: "app-size", label: "Tamanho do app" },
  { page: "deep-links", label: "Deep links" },
  { page: "vm-tools", label: "Ferramentas da VM" },
];

type Toggle = { ext: string; label: string; on: (v: string | undefined) => boolean; set: (on: boolean) => Record<string, string> };
const bool = (ext: string, label: string): Toggle => ({ ext, label, on: v => v === "true", set: on => ({ enabled: String(on) }) });

export const TOGGLES: Toggle[] = [
  bool("ext.flutter.inspector.show", "Selecionar widget no app"),
  bool("ext.flutter.debugPaint", "Debug paint (contornos e espaços)"),
  bool("ext.flutter.debugPaintBaselinesEnabled", "Linhas de base do texto"),
  bool("ext.flutter.repaintRainbow", "Repaint rainbow (o que repinta)"),
  bool("ext.flutter.showPerformanceOverlay", "Overlay de performance"),
  bool("ext.flutter.invertOversizedImages", "Destacar imagens grandes demais"),
  { ext: "ext.flutter.timeDilation", label: "Animações lentas (5×)", on: v => parseFloat(v || "1") > 1, set: on => ({ timeDilation: on ? "5.0" : "1.0" }) },
  bool("ext.flutter.debugAllowBanner", "Faixa DEBUG"),
];

export const DUMPS: { ext: string; label: string }[] = [
  { ext: "ext.flutter.debugDumpApp", label: "Árvore de widgets" },
  { ext: "ext.flutter.debugDumpRenderTree", label: "Árvore de render" },
  { ext: "ext.flutter.debugDumpLayerTree", label: "Árvore de camadas" },
  { ext: "ext.flutter.debugDumpSemanticsTreeInTraversalOrder", label: "Árvore de semântica" },
  { ext: "ext.flutter.debugDumpFocusTree", label: "Árvore de foco" },
];

export const has = (s: Session | null, ext: string) => !!s?.flutter?.tools && s.flutter.exts.includes(ext);
export const isOn = (s: Session, t: Toggle) => t.on(s.flutter?.state[t.ext]);
export function toggle(s: Session, t: Toggle) { return debug.service(s, t.ext, t.set(!isOn(s, t))); }

/** a plataforma que o app finge ser (Android ⇄ iOS) — muda os widgets adaptativos, a rolagem, as transições */
export const platformOf = (s: Session) => s.flutter?.state["ext.flutter.platformOverride"] || null;
export function flipPlatform(s: Session) {
  return debug.service(s, "ext.flutter.platformOverride", { value: platformOf(s) === "iOS" ? "android" : "iOS" });
}

/** o tema que o app está usando (sem forçar, é o do sistema) — trocar força o outro */
export const darkOf = (s: Session) => s.flutter?.state["ext.flutter.brightnessOverride"] === "Brightness.dark";
export function flipBrightness(s: Session) {
  return debug.service(s, "ext.flutter.brightnessOverride", { value: darkOf(s) ? "Brightness.light" : "Brightness.dark" });
}

export async function dump(s: Session, ext: string) {
  const r = await debug.service(s, ext);
  if (r?.data) debug.panelOpen?.(s.repoId);
}

export async function openInBrowser(s: Session, page = "") {
  try { window.open(await debug.devtoolsUrl(s, page), "_blank"); } catch (e) { ui.error(e); }
}
