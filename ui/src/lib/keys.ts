// Atalhos de teclado conforme o sistema: no Mac ⌘ ⇧ ⌥, no Windows Ctrl+Shift+Alt.
// Escreva o atalho uma vez ("mod+shift+f") e mostre com kbd(); compare eventos com matches().
import { platform } from "./native";

export const isMac = () => platform() !== "windows" && !/Windows/i.test(navigator.userAgent);

const MAC: Record<string, string> = { mod: "⌘", shift: "⇧", alt: "⌥", ctrl: "⌃", enter: "↩", esc: "esc", backspace: "⌫", up: "↑", down: "↓", left: "←", right: "→", tab: "⇥" };
const WIN: Record<string, string> = { mod: "Ctrl", shift: "Shift", alt: "Alt", ctrl: "Ctrl", enter: "Enter", esc: "Esc", backspace: "Backspace", up: "↑", down: "↓", left: "←", right: "→", tab: "Tab" };

/** "mod+shift+f" → "⌘⇧F" (Mac) ou "Ctrl+Shift+F" (Windows). */
export function kbd(combo: string) {
  const mac = isMac(), map = mac ? MAC : WIN;
  const parts = combo.split("+").map(p => p.trim().toLowerCase()).map(p => map[p] ?? (p.length === 1 ? p.toUpperCase() : p[0].toUpperCase() + p.slice(1)));
  return mac ? parts.join("") : parts.join("+");
}

/** Nome do modificador principal: "⌘" ou "Ctrl". */
export const modKey = () => (isMac() ? "⌘" : "Ctrl");

/** O evento é o atalho? "mod" = ⌘ no Mac e Ctrl no Windows. */
export function matches(e: KeyboardEvent, combo: string) {
  const parts = combo.toLowerCase().split("+");
  const key = parts[parts.length - 1];
  const want = new Set(parts.slice(0, -1));
  const mod = isMac() ? e.metaKey : e.ctrlKey;
  if (want.has("mod") !== mod) return false;
  if (want.has("shift") !== e.shiftKey) return false;
  if (want.has("alt") !== e.altKey) return false;
  if (isMac() && want.has("ctrl") !== e.ctrlKey) return false;
  const k = e.key.toLowerCase();
  return k === key || (key === "\\" && e.code === "Backslash") || (key.length === 1 && e.code === `Key${key.toUpperCase()}`) || (/^[0-9]$/.test(key) && e.code === `Digit${key}`);
}
